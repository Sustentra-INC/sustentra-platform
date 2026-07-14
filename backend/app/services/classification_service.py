from __future__ import annotations

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


class ClassificationService:
    """Deterministic S1 document classifier driven by the vocabulary library."""

    SIGNAL_WEIGHTS = {
        "filename_patterns": 0.35,
        "header_terms": 0.25,
        "key_phrases": 0.25,
        "layout_features": 0.15,
    }

    def __init__(
        self,
        vocabulary_library: VocabularyLibrary | None = None,
        workbook_path: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._vocabulary_library = vocabulary_library
        self._workbook_path = Path(workbook_path) if workbook_path is not None else None
        self._repo_root = Path(repo_root) if repo_root is not None else None
        self._classifier_version = "classification-v0"

    def classify(self, payload: dict) -> dict:
        document_id = str(payload.get("document_id") or "")
        engagement_id = str(payload.get("engagement_id") or "")
        processing_run_id = payload.get("processing_run_id")
        created_at = self._utc_now_iso()

        base_result = {
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
            scored_candidates = self._score_candidates(vocabulary_library, search_text)

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

    def _score_candidates(self, vocabulary_library: VocabularyLibrary, search_text: str) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for variant in vocabulary_library.variants:
            matched_signals = {
                "filename_patterns": self._matched_terms(variant.filename_patterns, search_text),
                "layout_features": self._matched_terms(variant.layout_features, search_text),
                "header_terms": self._matched_terms(variant.header_terms, search_text),
                "key_phrases": self._matched_terms(variant.key_phrases, search_text),
            }

            confidence = self._compute_confidence(matched_signals)
            if confidence <= 0:
                continue

            candidate = {
                "canonical_type_id": variant.canonical_type_id,
                "variant_id": variant.variant_id,
                "confidence": round(confidence, 4),
                "threshold": variant.confidence_threshold_default,
                "matched_signals": matched_signals,
                "reason": self._build_reason(matched_signals),
                "review_required": confidence < variant.confidence_threshold_default,
            }
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                -item["confidence"],
                item["canonical_type_id"],
                item.get("variant_id") or "",
            )
        )
        return candidates

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

    def _compute_confidence(self, matched_signals: dict[str, list[str]]) -> float:
        confidence = 0.0
        for signal_name, weight in self.SIGNAL_WEIGHTS.items():
            if matched_signals.get(signal_name):
                confidence += weight
        return confidence

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
