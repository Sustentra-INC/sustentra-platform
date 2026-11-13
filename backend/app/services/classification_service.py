from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..reference.vocabulary_loader import (
    VocabularyLibrary,
    VocabularyVariant,
    load_default_vocabulary_library,
    load_vocabulary_library,
)


# --- content cues -----------------------------------------------------------------------
# The vocabulary library's filename globs and header terms miss ordinary documents: a gas
# bill is "Usage (CCF)" with no "gas bill" in its file name, a vehicle log is headed "Miles"
# and "Gallons", a refrigerant invoice lists "R-134a" in a line item. Cues read units and
# product names in the text itself and credit the canonical type that unit belongs to.
GAS_UNIT_RE = re.compile(r"\b(?:therms?|ccf|hcf|mcf|dekatherms?|dth)\b")
GAS_QUANTITY_RE = re.compile(
    r"\d[\d,.]*\s*(?:therms?|ccf|hcf|mcf|dekatherms?|dth)\b|\((?:therms?|ccf|hcf|mcf|dth)\)"
)
CHARGE_RE = re.compile(r"\$\s?\d|amount due|total due|pay by|pay this amount|\bamount\b|\bcharges?\b|\binvoice\b")
ELECTRICITY_RE = re.compile(r"\bk?wh\b|\bmwh\b|kilowatt|megawatt|electric")
DISTANCE_RE = re.compile(r"\bmiles?\b|\bodometer\b|\bmileage\b|\bkilomet(?:er|re)s?\b|\bkm\b")
FUEL_VOLUME_RE = re.compile(r"\bgallons?\b|\bgal\b|\blit(?:er|re)s?\b")
VEHICLE_RE = re.compile(r"\bvehicles?\b|\btrucks?\b|\bvans?\b|\bpickup\b|\bfleet\b|\bdriver\b|\btractor\b")
REFRIGERANT_RE = re.compile(
    r"\br-?(?:11|12|22|32|123|125|134a|143a|152a|290|401a|402a|404a|407a|407c|407f|408a|410a|417a|422b|422d|427a|"
    r"438a|448a|449a|452a|454b|507a?|508b|600a?|717|744)\b|\bhfc-?\d{3}|\bhcfc-?\d{2,3}|\brefrigerants?\b"
)
MASS_RE = re.compile(r"\d\s*(?:lbs?|pounds?|kg|kilograms?)\b|\bcylinders?\b|\blbs?\b")
CUE_BONUS = 0.3
SUMMARY_PREFIX = "CT-GHG-"
STATIONARY_TYPE = "CT-S1-FUELQTY"
MOBILE_TYPE = "CT-S1-MOBFUEL"
REFRIGERANT_TYPE = "CT-S1-REFRSVC"
ELECTRICITY_TYPE = "CT-S2-ELEC"
DISTANCE_TYPE = "CT-S1-TRANSACT"


class ClassificationService:
    """Deterministic S1 document classifier driven by the vocabulary library."""

    SIGNAL_WEIGHTS = {
        "filename_patterns": 0.35,
        "header_terms": 0.25,
        "key_phrases": 0.25,
        "layout_features": 0.15,
    }

    # Extra credit for matching MANY header/key-phrase terms (per term beyond the
    # first), capped. A real fuel bill matches several headers even when its
    # filename and the library's exact key-phrases do not, so content strength
    # must be able to raise confidence past a single-term match.
    STRENGTH_BONUS_PER_TERM = 0.08
    STRENGTH_BONUS_CAP = 0.25

    # The library ships provisional 0.80 thresholds (uncalibrated). Cap the
    # effective threshold so strong CONTENT matches can classify without a
    # matching filename (uploads are rarely named "*gas*bill*.pdf"). Thresholds
    # already below the cap (e.g. test fixtures at 0.35/0.50) are left untouched.
    CALIBRATED_THRESHOLD_CAP = 0.55

    def __init__(
        self,
        vocabulary_library: VocabularyLibrary | None = None,
        workbook_path: Path | None = None,
        repo_root: Path | None = None,
        threshold_cap: float | None = None,
    ) -> None:
        self._vocabulary_library = vocabulary_library
        self._workbook_path = Path(workbook_path) if workbook_path is not None else None
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._threshold_cap = threshold_cap if threshold_cap is not None else self.CALIBRATED_THRESHOLD_CAP
        self._classifier_version = "classification-v1"

    def classify(self, payload: dict) -> dict:
        document_id = str(payload.get("document_id") or "")
        engagement_id = str(payload.get("engagement_id") or "")
        processing_run_id = payload.get("processing_run_id")
        created_at = self._utc_now_iso()

        base_result: dict[str, Any] = {
            "classification_result_id": self._new_classification_result_id(),
            "document_id": document_id,
            "engagement_id": engagement_id,
            "processing_run_id": processing_run_id,
            "status": "unclassified",
            "primary_canonical_type_id": None,
            "primary_variant_id": None,
            "confidence": None,
            "threshold": None,
            "candidate_matches": [],
            "matched_signals": self._empty_matched_signals(),
            "review_required": True,
            "classifier_version": self._classifier_version,
            "notes": None,
            "review_decision": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": created_at,
        }

        try:
            vocabulary_library = self._get_vocabulary_library()
            search_text = self._build_search_text(payload)
            raw_file_name = payload.get("file_name")
            file_name = raw_file_name if isinstance(raw_file_name, str) else ""
            scored_candidates = self._score_candidates(vocabulary_library, search_text, file_name)

            if not scored_candidates:
                base_result["status"] = "unclassified"
                base_result["notes"] = "No vocabulary signals matched the provided document context."
                return base_result

            passing_candidates = [
                candidate
                for candidate in scored_candidates
                if candidate["threshold"] is not None and candidate["confidence"] >= candidate["threshold"]
            ]

            selected_candidates = scored_candidates
            status = "low_confidence"
            review_required = True
            notes: str | None = None

            if not passing_candidates:
                status = "low_confidence"
                notes = "Best candidate confidence did not meet variant threshold."
            else:
                selected_candidates = passing_candidates
                passing_canonical_ids = {
                    candidate["canonical_type_id"]
                    for candidate in passing_candidates
                }
                has_multi_type_variant = any(
                    self._variant_is_multi_type(vocabulary_library, candidate.get("variant_id"))
                    for candidate in passing_candidates
                )

                if len(passing_canonical_ids) > 1 and has_multi_type_variant:
                    status = "multi_type_candidate"
                    review_required = True
                    notes = "Multiple canonical types met threshold with multi_type-enabled variant(s)."
                elif len(passing_canonical_ids) > 1:
                    status = "low_confidence"
                    review_required = True
                    notes = "Multiple canonical types met threshold without multi_type support."
                else:
                    status = "classified"
                    review_required = False

            primary = selected_candidates[0]

            base_result.update(
                {
                    "status": status,
                    "primary_canonical_type_id": primary["canonical_type_id"],
                    "primary_variant_id": primary.get("variant_id"),
                    "confidence": primary["confidence"],
                    "threshold": primary["threshold"],
                    "candidate_matches": selected_candidates,
                    "matched_signals": primary["matched_signals"],
                    "review_required": review_required,
                    "notes": notes,
                }
            )
            return base_result
        except Exception as exc:
            base_result.update(
                {
                    "status": "failed",
                    "review_required": True,
                    "notes": f"Classification failed: {exc}",
                }
            )
            return base_result

    def _get_vocabulary_library(self) -> VocabularyLibrary:
        if self._vocabulary_library is not None:
            return self._vocabulary_library

        if self._workbook_path is not None:
            self._vocabulary_library = load_vocabulary_library(self._workbook_path)
        else:
            self._vocabulary_library = load_default_vocabulary_library(repo_root=self._repo_root)

        return self._vocabulary_library

    def _score_candidates(
        self,
        vocabulary_library: VocabularyLibrary,
        search_text: str,
        file_name: str = "",
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for variant in vocabulary_library.variants:
            matched_signals = {
                "filename_patterns": self._matched_filename_patterns(variant.filename_patterns, file_name, search_text),
                "layout_features": self._matched_terms(variant.layout_features, search_text),
                "header_terms": self._matched_terms(variant.header_terms, search_text),
                "key_phrases": self._matched_terms(variant.key_phrases, search_text),
            }

            confidence = self._compute_confidence(matched_signals)
            if confidence <= 0:
                continue

            effective_threshold = min(variant.confidence_threshold_default, self._threshold_cap)
            if variant.canonical_type_id.startswith(SUMMARY_PREFIX):
                # A company-prepared summary is a claim about the whole document. A file name glob plus
                # one generic header ("Fuel type") is not enough to make it one: a log of fuel
                # deliveries is activity data. Without two content terms, stay below threshold.
                content_terms = len(matched_signals["header_terms"]) + len(matched_signals["key_phrases"])
                if content_terms < 2:
                    confidence = min(confidence, effective_threshold - 0.01)
            candidate = {
                "canonical_type_id": variant.canonical_type_id,
                "variant_id": variant.variant_id,
                "confidence": round(confidence, 4),
                "threshold": effective_threshold,
                "matched_signals": matched_signals,
                "reason": self._build_reason(matched_signals),
                "review_required": confidence < effective_threshold,
            }
            candidates.append(candidate)

        candidates = self._apply_content_cues(vocabulary_library, search_text, candidates)
        candidates.sort(
            key=lambda item: (
                -item["confidence"],
                item["canonical_type_id"],
                item.get("variant_id") or "",
            )
        )
        return candidates

    def _apply_content_cues(
        self,
        vocabulary_library: VocabularyLibrary,
        search_text: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Credit the type a unit or product name belongs to; drop types the text contradicts."""

        credits: dict[str, str] = {}
        has_gas_quantity = bool(GAS_QUANTITY_RE.search(search_text)) or (
            bool(GAS_UNIT_RE.search(search_text)) and "natural gas" in search_text
        )
        if has_gas_quantity and CHARGE_RE.search(search_text):
            credits[STATIONARY_TYPE] = "cue: gas quantity (therms/CCF) with charges"
        if DISTANCE_RE.search(search_text) and FUEL_VOLUME_RE.search(search_text) and VEHICLE_RE.search(search_text):
            credits[MOBILE_TYPE] = "cue: vehicle distance and fuel volume"
        if REFRIGERANT_RE.search(search_text) and MASS_RE.search(search_text):
            credits[REFRIGERANT_TYPE] = "cue: refrigerant name with a mass or cylinders"

        for type_id, label in credits.items():
            of_type = [c for c in candidates if c["canonical_type_id"] == type_id]
            if of_type:
                target = max(of_type, key=lambda c: c["confidence"])
            else:
                variants = [v for v in vocabulary_library.variants if v.canonical_type_id == type_id]
                if not variants:
                    continue
                target = {
                    "canonical_type_id": type_id,
                    "variant_id": variants[0].variant_id,
                    "confidence": 0.0,
                    "threshold": min(variants[0].confidence_threshold_default, self._threshold_cap),
                    "matched_signals": self._empty_matched_signals(),
                    "reason": "",
                    "review_required": True,
                }
                candidates.append(target)
            target["matched_signals"]["key_phrases"].append(label)
            target["confidence"] = round(min(target["confidence"] + CUE_BONUS, 1.0), 4)
            target["reason"] = self._build_reason(target["matched_signals"])
            target["review_required"] = target["confidence"] < target["threshold"]

        kept: list[dict[str, Any]] = []
        electricity_named = bool(ELECTRICITY_RE.search(search_text))
        for candidate in candidates:
            type_id = candidate["canonical_type_id"]
            if type_id == ELECTRICITY_TYPE and not electricity_named and STATIONARY_TYPE in credits:
                continue  # gas units and no kWh: not an electricity bill
            if type_id == DISTANCE_TYPE and MOBILE_TYPE in credits:
                # A log with fuel volume next to the distance is fuel activity (mobile combustion):
                # the distance-only type no longer outranks it.
                candidate["confidence"] = round(min(candidate["confidence"], candidate["threshold"] - 0.01), 4)
                candidate["review_required"] = True
            kept.append(candidate)
        return kept

    def _build_search_text(self, payload: dict[str, Any]) -> str:
        text_parts: list[str] = []

        file_name = payload.get("file_name")
        if isinstance(file_name, str):
            text_parts.append(file_name)

        extracted_text = payload.get("extracted_text")
        if isinstance(extracted_text, str):
            text_parts.append(extracted_text)

        parser_output = payload.get("parser_output")
        if isinstance(parser_output, dict):
            text_parts.extend(self._extract_text_from_parser_output(parser_output))

        normalized = "\n".join(text_parts).lower()
        return " ".join(normalized.split())

    def _extract_text_from_parser_output(self, parser_output: dict[str, Any]) -> list[str]:
        extracted: list[str] = []

        pages = parser_output.get("pages", [])
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict):
                    page_text = page.get("text")
                    if isinstance(page_text, str):
                        extracted.append(page_text)

        text_blocks = parser_output.get("text_blocks", [])
        if isinstance(text_blocks, list):
            for block in text_blocks:
                if isinstance(block, dict):
                    block_text = block.get("text")
                    if isinstance(block_text, str):
                        extracted.append(block_text)

        tables = parser_output.get("tables", [])
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, dict):
                    continue
                rows = table.get("rows", [])
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, list):
                        continue
                    row_text = " ".join(str(cell) for cell in row if cell is not None)
                    if row_text:
                        extracted.append(row_text)

        key_value_pairs = parser_output.get("key_value_pairs", [])
        if isinstance(key_value_pairs, list):
            for pair in key_value_pairs:
                if not isinstance(pair, dict):
                    continue
                key = pair.get("key")
                value = pair.get("value")
                if key is not None:
                    extracted.append(str(key))
                if value is not None:
                    extracted.append(str(value))

        return extracted

    def _matched_terms(self, terms: tuple[str, ...], search_text: str) -> list[str]:
        matched: list[str] = []
        for term in terms:
            normalized_term = term.strip().lower()
            if not normalized_term:
                continue
            if normalized_term in search_text:
                matched.append(term)
        return matched

    def _matched_filename_patterns(self, patterns: tuple[str, ...], file_name: str, search_text: str) -> list[str]:
        """Vocabulary filename patterns are globs (``*gas*bill*``); plain terms are substrings.

        Globs are matched against the file name only, with spaces/dashes treated as
        underscores so "Gas Bill - Jan.pdf" matches ``*gas*bill*``.
        """

        normalized_name = re.sub(r"[\s\-.]+", "_", file_name.strip().lower())
        matched: list[str] = []
        for pattern in patterns:
            term = pattern.strip().lower()
            if not term:
                continue
            if any(ch in term for ch in "*?["):
                if normalized_name and fnmatch.fnmatchcase(normalized_name, re.sub(r"[\s\-]+", "_", term)):
                    matched.append(pattern)
            elif term in search_text:
                matched.append(pattern)
        return matched

    def _compute_confidence(self, matched_signals: dict[str, list[str]]) -> float:
        confidence = 0.0
        for signal_name, weight in self.SIGNAL_WEIGHTS.items():
            if matched_signals.get(signal_name):
                confidence += weight
        # Strength bonus: additional header/key-phrase matches beyond the first
        # raise confidence, so a document that matches several content terms
        # outranks one that matches a single term (and can clear threshold even
        # when its filename does not match any variant glob).
        extra_terms = 0
        for signal_name in ("header_terms", "key_phrases"):
            extra_terms += max(len(matched_signals.get(signal_name) or []) - 1, 0)
        confidence += min(extra_terms * self.STRENGTH_BONUS_PER_TERM, self.STRENGTH_BONUS_CAP)
        return min(confidence, 1.0)

    def _build_reason(self, matched_signals: dict[str, list[str]]) -> str:
        groups = [
            name
            for name in ["filename_patterns", "layout_features", "header_terms", "key_phrases"]
            if matched_signals.get(name)
        ]
        if not groups:
            return "No signal groups matched."
        return "Matched signal groups: " + ", ".join(groups)

    def _variant_is_multi_type(
        self,
        vocabulary_library: VocabularyLibrary,
        variant_id: str | None,
    ) -> bool:
        if variant_id is None:
            return False
        variant: VocabularyVariant | None = vocabulary_library.variant_by_id.get(variant_id)
        return bool(variant and variant.multi_type)

    def _empty_matched_signals(self) -> dict[str, list[str]]:
        return {
            "filename_patterns": [],
            "layout_features": [],
            "header_terms": [],
            "key_phrases": [],
        }

    def _new_classification_result_id(self) -> str:
        return f"CLS-{uuid4().hex[:12].upper()}"

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
