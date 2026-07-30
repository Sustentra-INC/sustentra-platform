"""Extraction candidate service (PR6).

Combines a normalized ``parser_output`` with extraction targets to produce
``extraction_candidate``-shaped dictionaries conforming to
``contracts/extraction_candidate.schema.json``.

Scope for v0:
    * deterministic extraction methods: key_value_pair, regex, anchor_text,
      table_lookup, excel_cell
    * basic value normalization (numbers with commas, simple dates, units)
    * source_reference attachment (resolved or inline)
    * flagged low-confidence candidates for missing / unsupported cases

Out of scope: LLM/manual extraction, review decisions, approved evidence,
persistence, and any external calls. This service never mutates its inputs.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

SUPPORTED_METHODS = ("key_value_pair", "regex", "anchor_text", "table_lookup", "excel_cell")

_METHOD_BASE_CONFIDENCE = {
    "key_value_pair": 0.90,
    "regex": 0.85,
    "anchor_text": 0.80,
    "table_lookup": 0.75,
    "excel_cell": 0.70,
}

_MISSING_CONFIDENCE = 0.20
_UNSUPPORTED_CONFIDENCE = 0.10

_NUMERIC_VALUE_TYPES = {"number", "integer", "quantity", "currency", "percentage"}
_DATE_VALUE_TYPES = {"date", "date_range"}

_MAX_SNIPPET = 240
_CELL_COORD_PATTERN = re.compile(r"^([A-Za-z]+)(\d+)$")

_SHORT_ANCHOR_MAX_LEN = 4
_LABEL_VALUE_DELIMITERS = " \t:-\u2013\u2014=|"

_QUANTITY_ANCHOR_KEYWORDS = (
    "usage",
    "total usage",
    "consumption",
    "fuel consumption",
    "fuel deliveries",
    "gallons delivered",
    "quantity",
    "delivered",
    "volume",
)

_UNIT_CONTEXT_KEYS = (
    "usage unit",
    "unit",
    "uom",
    "units",
    "measurement unit",
)

_NO_ACTIVITY_PATTERNS = (
    "annual emissions activity: no activity",
    "no activity",
    "no consumption",
    "fuel consumption recorded: 0",
    "fuel deliveries recorded: 0",
    "combustion hours recorded: 0",
    "no deliveries",
    "standby statement",
)

_ID_CONTEXT_LABELS = (
    "document id",
    "bill number",
    "account number",
    "invoice",
    "ticket no",
    "ticket",
)

_ROW_ID_KEYS = (
    "record_id",
    "record_identifier",
    "record_id_value",
    "row_identifier",
    "row_context",
)

_TABLE_QUANTITY_HEADER_HINTS = (
    "gallons delivered",
    "quantity",
    "delivered",
    "usage",
    "consumption",
    "total",
)


@dataclass(frozen=True)
class _MethodHit:
    method: str
    raw_value: Any
    method_confidence: float
    parser_confidence: float | None
    source_reference: dict
    context: dict[str, Any] | None = None


class ExtractionCandidateService:
    """Generates extraction candidates from parser output and targets."""

    def generate_candidates(
        self,
        parser_output: dict,
        extraction_targets: Sequence[dict],
        evidence_id: str,
    ) -> list[dict]:
        document_id = parser_output.get("document_id")
        if not document_id:
            raise ValueError("parser_output must include a non-empty 'document_id'.")

        return [
            self._generate_for_target(parser_output, target, evidence_id, str(document_id))
            for target in extraction_targets
        ]

    # ------------------------------------------------------------------
    # Per-target orchestration
    # ------------------------------------------------------------------
    def _generate_for_target(
        self,
        parser_output: dict,
        target: dict,
        evidence_id: str,
        document_id: str,
    ) -> dict:
        field_id = str(target.get("field_id") or "")
        display_label = str(target.get("field_label") or field_id)
        required_status = target.get("required_status")
        methods = tuple(target.get("extraction_methods") or ())

        supported = [method for method in methods if method in SUPPORTED_METHODS]

        if not supported:
            return self._build_candidate(
                evidence_id=evidence_id,
                document_id=document_id,
                field_id=field_id,
                display_label=display_label,
                raw_value=None,
                normalized_value=None,
                unit=None,
                confidence=_UNSUPPORTED_CONFIDENCE,
                source_reference=self._missing_source_reference(document_id, field_id),
                validation_flags=["unsupported_extraction_method"],
            )

        if self._should_suppress_activity_quantity(parser_output, target):
            flags: list[str] = []
            if required_status in {"core", "conditional"}:
                flags.append("field_not_found")
            return self._build_candidate(
                evidence_id=evidence_id,
                document_id=document_id,
                field_id=field_id,
                display_label=display_label,
                raw_value=None,
                normalized_value=None,
                unit=None,
                confidence=_MISSING_CONFIDENCE,
                source_reference=self._missing_source_reference(document_id, field_id),
                validation_flags=flags,
            )

        ordered = sorted(
            supported,
            key=lambda method: -self._method_priority(method, target),
        )
        hit: _MethodHit | None = None
        for method in ordered:
            candidate_hit = self._dispatch(method, parser_output, target, document_id)
            if candidate_hit is not None and self._has_value(candidate_hit.raw_value):
                hit = candidate_hit
                break

        if hit is None:
            flags: list[str] = []
            if required_status in {"core", "conditional"}:
                flags.append("field_not_found")
            return self._build_candidate(
                evidence_id=evidence_id,
                document_id=document_id,
                field_id=field_id,
                display_label=display_label,
                raw_value=None,
                normalized_value=None,
                unit=None,
                confidence=_MISSING_CONFIDENCE,
                source_reference=self._missing_source_reference(document_id, field_id),
                validation_flags=flags,
            )

        normalized_value, unit, flags = self._normalize(hit.raw_value, target)
        inferred_unit = self._infer_unit_from_context(
            parser_output=parser_output,
            target=target,
            hit=hit,
            current_unit=unit,
        )
        if inferred_unit is not None:
            unit = inferred_unit
            flags = [flag for flag in flags if flag != "unit_missing"]
        confidence = self._combine_confidence(hit.method_confidence, hit.parser_confidence)
        return self._build_candidate(
            evidence_id=evidence_id,
            document_id=document_id,
            field_id=field_id,
            display_label=display_label,
            raw_value=self._coerce_raw(hit.raw_value),
            normalized_value=normalized_value,
            unit=unit,
            confidence=confidence,
            source_reference=hit.source_reference,
            validation_flags=flags,
        )

    def _method_priority(self, method: str, target: dict) -> float:
        base = _METHOD_BASE_CONFIDENCE[method]
        if self._target_record_id(target) and method == "table_lookup":
            return base + 0.3
        return base

    def _dispatch(
        self, method: str, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        if method == "key_value_pair":
            return self._extract_key_value_pair(parser_output, target, document_id)
        if method == "regex":
            return self._extract_regex(parser_output, target, document_id)
        if method == "anchor_text":
            return self._extract_anchor_text(parser_output, target, document_id)
        if method == "table_lookup":
            return self._extract_table_lookup(parser_output, target, document_id)
        if method == "excel_cell":
            return self._extract_excel_cell(parser_output, target, document_id)
        return None

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------
    def _extract_key_value_pair(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        anchors = self._lower_anchors(target)
        if not anchors:
            return None
        for pair in parser_output.get("key_value_pairs", []) or []:
            if not isinstance(pair, dict):
                continue
            key = str(pair.get("key") or "")
            matched_anchor = self._best_key_anchor_match(key, anchors)
            if matched_anchor is None:
                continue
            raw_value = pair.get("value")
            if str(target.get("value_type") or "") in _NUMERIC_VALUE_TYPES:
                if not re.search(r"\d", str(raw_value or "")):
                    continue
            reference_id = pair.get("value_source_reference_id") or pair.get(
                "key_source_reference_id"
            )
            source_reference = self._resolve_source_reference(parser_output, reference_id)
            if source_reference is None:
                source_reference = self._inline_from_pair(pair, document_id)
            return _MethodHit(
                method="key_value_pair",
                raw_value=raw_value,
                method_confidence=_METHOD_BASE_CONFIDENCE["key_value_pair"],
                parser_confidence=self._as_confidence(pair.get("confidence")),
                source_reference=source_reference,
                context={
                    "page_number": pair.get("page_number"),
                    "sheet_name": pair.get("sheet_name"),
                    "pair_key": key,
                    "pair_value": raw_value,
                    "matched_anchor": matched_anchor,
                },
            )
        return None

    def _extract_regex(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        if self._is_activity_quantity_target(target) and self._target_record_id(target):
            record_hit = self._extract_row_bound_quantity(
                parser_output=parser_output,
                target=target,
                document_id=document_id,
            )
            if record_hit is not None:
                return record_hit

        patterns = self._compiled_patterns(target)
        if not patterns:
            return None

        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            for line in self._split_search_lines(text):
                for pattern in patterns:
                    for match in pattern.finditer(line):
                        if self._is_likely_bad_quantity_match(match.group(0), line, target):
                            continue
                        source_reference = self._source_reference_for_block(
                            parser_output, block, document_id
                        )
                        return _MethodHit(
                            method="regex",
                            raw_value=match.group(0),
                            method_confidence=_METHOD_BASE_CONFIDENCE["regex"],
                            parser_confidence=self._as_confidence(block.get("confidence")),
                            source_reference=source_reference,
                            context={
                                "page_number": block.get("page_number"),
                                "sheet_name": None,
                                "surrounding_text": line,
                            },
                        )

        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            for line in self._split_search_lines(str(page.get("text") or "")):
                for pattern in patterns:
                    for match in pattern.finditer(line):
                        if self._is_likely_bad_quantity_match(match.group(0), line, target):
                            continue
                        return _MethodHit(
                            method="regex",
                            raw_value=match.group(0),
                            method_confidence=_METHOD_BASE_CONFIDENCE["regex"],
                            parser_confidence=None,
                            source_reference=self._inline_from_page(page, document_id),
                            context={
                                "page_number": page.get("page_number"),
                                "sheet_name": None,
                                "surrounding_text": line,
                            },
                        )
        return None

    def _extract_anchor_text(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        if self._is_activity_quantity_target(target):
            record_hit = self._extract_row_bound_quantity(
                parser_output=parser_output,
                target=target,
                document_id=document_id,
            )
            if record_hit is not None:
                return record_hit

        anchors = self._lower_anchors(target)
        if not anchors:
            return None

        patterns = self._compiled_patterns(target)

        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            result = self._value_after_anchor(text, anchors, patterns, target)
            if result:
                value, matched_anchor = result
                source_reference = self._source_reference_for_block(
                    parser_output, block, document_id
                )
                return _MethodHit(
                    method="anchor_text",
                    raw_value=value,
                    method_confidence=_METHOD_BASE_CONFIDENCE["anchor_text"],
                    parser_confidence=self._as_confidence(block.get("confidence")),
                    source_reference=source_reference,
                    context={
                        "page_number": block.get("page_number"),
                        "sheet_name": None,
                        "surrounding_text": text,
                        "matched_anchor": matched_anchor,
                    },
                )

        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            for line in str(page.get("text") or "").splitlines():
                result = self._value_after_anchor(line, anchors, patterns, target)
                if result:
                    value, matched_anchor = result
                    return _MethodHit(
                        method="anchor_text",
                        raw_value=value,
                        method_confidence=_METHOD_BASE_CONFIDENCE["anchor_text"],
                        parser_confidence=None,
                        source_reference=self._inline_from_page(page, document_id),
                        context={
                            "page_number": page.get("page_number"),
                            "sheet_name": None,
                            "surrounding_text": line,
                            "matched_anchor": matched_anchor,
                        },
                    )
        return None

    def _extract_table_lookup(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        if self._is_activity_quantity_target(target):
            record_hit = self._extract_row_bound_quantity(
                parser_output=parser_output,
                target=target,
                document_id=document_id,
            )
            if record_hit is not None:
                return record_hit

        anchors = self._lower_anchors(target)
        if not anchors:
            return None

        for table in parser_output.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            rows = table.get("rows") or []
            for row in rows:
                if not isinstance(row, (list, tuple)):
                    continue
                for index, cell in enumerate(row):
                    if cell is None:
                        continue
                    if not self._contains_anchor(str(cell), anchors):
                        continue
                    value = self._adjacent_value(row, index)
                    if value is None:
                        continue
                    source_reference = self._source_reference_for_table(
                        parser_output, table, document_id
                    )
                    return _MethodHit(
                        method="table_lookup",
                        raw_value=value,
                        method_confidence=_METHOD_BASE_CONFIDENCE["table_lookup"],
                        parser_confidence=self._as_confidence(table.get("confidence")),
                        source_reference=source_reference,
                        context={
                            "page_number": table.get("page_number"),
                            "sheet_name": table.get("sheet_name"),
                            "row_text": self._row_to_text(row),
                            "table_id": table.get("table_id"),
                        },
                    )
        return None

    def _extract_excel_cell(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        anchors = self._lower_anchors(target)
        if not anchors:
            return None
        sheet_hints = {str(hint).lower() for hint in (target.get("sheet_hints") or ())}

        excel_refs = [
            ref
            for ref in parser_output.get("source_references", []) or []
            if isinstance(ref, dict)
            and ref.get("source_kind") == "excel_cell"
            and ref.get("cell_or_range")
        ]
        by_sheet_cell: dict[tuple[str, str], dict] = {}
        for ref in excel_refs:
            sheet = str(ref.get("sheet_name") or "")
            coord = str(ref.get("cell_or_range") or "")
            by_sheet_cell[(sheet, coord)] = ref

        for ref in excel_refs:
            sheet = str(ref.get("sheet_name") or "")
            if sheet_hints and sheet.lower() not in sheet_hints:
                continue
            snippet = str(ref.get("text_snippet") or "")
            if not self._contains_anchor(snippet, anchors):
                continue
            neighbor_coord = self._next_column(str(ref.get("cell_or_range") or ""))
            if neighbor_coord is None:
                continue
            neighbor = by_sheet_cell.get((sheet, neighbor_coord))
            if neighbor is None:
                continue
            value = neighbor.get("text_snippet")
            if not self._has_value(value):
                continue
            return _MethodHit(
                method="excel_cell",
                raw_value=value,
                method_confidence=_METHOD_BASE_CONFIDENCE["excel_cell"],
                parser_confidence=None,
                source_reference=copy.deepcopy(neighbor),
                context={
                    "page_number": None,
                    "sheet_name": sheet,
                    "cell_or_range": neighbor_coord,
                },
            )
        return None

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------
    def _normalize(self, raw_value: Any, target: dict) -> tuple[Any, str | None, list[str]]:
        flags: list[str] = []
        if raw_value is None:
            return None, None, flags

        value_type = target.get("value_type")
        expected_units = tuple(target.get("expected_units") or ())
        unit_patterns = tuple(target.get("unit_patterns") or ())
        normalization = target.get("normalization") or {}
        target_unit = normalization.get("target_unit")

        raw_str = raw_value if isinstance(raw_value, str) else str(raw_value)
        unit: str | None = None

        if value_type in _NUMERIC_VALUE_TYPES:
            if unit_patterns:
                unit = self._detect_unit(raw_str, unit_patterns)
            number = self._parse_number(raw_str)
            if expected_units and unit is None:
                flags.append("unit_missing")
            if unit and target_unit and unit.lower() != str(target_unit).lower():
                flags.append("unit_conversion_not_implemented")
            return number, unit, flags

        if value_type in _DATE_VALUE_TYPES:
            iso = self._parse_date(raw_str)
            return (iso if iso is not None else raw_str.strip()), None, flags

        if value_type == "boolean":
            low = raw_str.strip().lower()
            if low in {"true", "yes", "1"}:
                return True, None, flags
            if low in {"false", "no", "0"}:
                return False, None, flags
            return raw_str.strip(), None, flags

        # string / object / array default
        if unit_patterns:
            unit = self._detect_unit(raw_str, unit_patterns)
        normalized = raw_str.strip() if isinstance(raw_value, str) else raw_value
        return normalized, unit, flags

    @staticmethod
    def _detect_unit(raw_str: str, unit_patterns: Sequence[str]) -> str | None:
        for pattern in unit_patterns:
            try:
                search_pattern = pattern
                # Guard short symbolic alpha patterns (e.g., "L") with boundaries.
                if re.fullmatch(r"[A-Za-z]{1,2}", pattern):
                    search_pattern = rf"\b{pattern}\b"
                match = re.search(search_pattern, raw_str, re.IGNORECASE)
            except re.error:
                continue
            if match:
                return match.group(0)
        return None

    @staticmethod
    def _parse_number(raw_str: str) -> int | float | None:
        cleaned = raw_str.replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        token = match.group(0)
        if "." in token:
            return float(token)
        return int(token)

    @staticmethod
    def _parse_date(raw_str: str) -> str | None:
        text = raw_str.strip()
        iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if iso_match:
            year, month, day = iso_match.groups()
            try:
                return date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                return None
        slash_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
        if slash_match:
            month, day, year = slash_match.groups()
            if len(year) == 2:
                year = f"20{year}"
            try:
                return date(int(year), int(month), int(day)).isoformat()
            except ValueError:
                return None
        return None

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------
    @staticmethod
    def _combine_confidence(method_confidence: float, parser_confidence: float | None) -> float:
        if parser_confidence is None:
            value = method_confidence
        else:
            value = min(method_confidence, parser_confidence)
        return round(max(0.0, min(1.0, value)), 4)

    # ------------------------------------------------------------------
    # Source references
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_source_reference(parser_output: dict, reference_id: Any) -> dict | None:
        if not reference_id:
            return None
        for reference in parser_output.get("source_references", []) or []:
            if isinstance(reference, dict) and reference.get("source_reference_id") == reference_id:
                return copy.deepcopy(reference)
        return None

    def _source_reference_for_block(
        self, parser_output: dict, block: dict, document_id: str
    ) -> dict:
        resolved = self._resolve_source_reference(parser_output, block.get("source_reference_id"))
        if resolved is not None:
            return resolved
        return self._inline_from_block(block, document_id)

    def _source_reference_for_table(
        self, parser_output: dict, table: dict, document_id: str
    ) -> dict:
        resolved = self._resolve_source_reference(parser_output, table.get("source_reference_id"))
        if resolved is not None:
            return resolved
        return self._inline_from_table(table, document_id)

    def _inline_from_block(self, block: dict, document_id: str) -> dict:
        block_id = block.get("block_id")
        return {
            "source_reference_id": f"inline::{document_id}::{block_id}",
            "document_id": document_id,
            "page_number": block.get("page_number"),
            "sheet_name": None,
            "cell_or_range": None,
            "text_snippet": self._snippet(block.get("text")),
            "bounding_box": None,
            "parser_block_ids": [block_id] if block_id else [],
        }

    def _inline_from_page(self, page: dict, document_id: str) -> dict:
        page_number = page.get("page_number")
        return {
            "source_reference_id": f"inline::{document_id}::page-{page_number}",
            "document_id": document_id,
            "page_number": page_number,
            "sheet_name": None,
            "cell_or_range": None,
            "text_snippet": self._snippet(page.get("text")),
            "bounding_box": None,
            "parser_block_ids": [],
        }

    def _inline_from_pair(self, pair: dict, document_id: str) -> dict:
        pair_id = pair.get("pair_id")
        key = pair.get("key")
        value = pair.get("value")
        return {
            "source_reference_id": f"inline::{document_id}::kv-{pair_id}",
            "document_id": document_id,
            "page_number": pair.get("page_number"),
            "sheet_name": pair.get("sheet_name"),
            "cell_or_range": None,
            "text_snippet": self._snippet(f"{key}: {value}"),
            "bounding_box": None,
            "parser_block_ids": [],
        }

    def _inline_from_table(self, table: dict, document_id: str) -> dict:
        table_id = table.get("table_id")
        return {
            "source_reference_id": f"inline::{document_id}::table-{table_id}",
            "document_id": document_id,
            "page_number": table.get("page_number"),
            "sheet_name": table.get("sheet_name"),
            "cell_or_range": None,
            "text_snippet": None,
            "bounding_box": None,
            "parser_block_ids": [],
        }

    @staticmethod
    def _missing_source_reference(document_id: str, field_id: str) -> dict:
        return {
            "source_reference_id": f"missing::{document_id}::{field_id}",
            "document_id": document_id,
            "page_number": None,
            "sheet_name": None,
            "cell_or_range": None,
            "text_snippet": None,
            "bounding_box": None,
            "parser_block_ids": [],
        }

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_candidate(
        *,
        evidence_id: str,
        document_id: str,
        field_id: str,
        display_label: str,
        raw_value: Any,
        normalized_value: Any,
        unit: str | None,
        confidence: float,
        source_reference: dict,
        validation_flags: list[str],
    ) -> dict:
        return {
            "candidate_id": f"candidate::{evidence_id}::{document_id}::{field_id}",
            "evidence_id": evidence_id,
            "document_id": document_id,
            "field_name": field_id,
            "display_label": display_label,
            "raw_value": raw_value,
            "normalized_value": normalized_value,
            "unit": unit,
            "confidence": confidence,
            "source_reference": source_reference,
            "validation_flags": validation_flags,
        }

    @staticmethod
    def _lower_anchors(target: dict) -> list[str]:
        return [str(label).strip() for label in (target.get("anchor_labels") or ()) if str(label).strip()]

    def _contains_anchor(self, text: str, anchors: Sequence[str]) -> bool:
        for anchor in anchors:
            if self._label_match_span(text, anchor) is not None:
                return True

            # Keep long-label fallback lenient for legacy behavior.
            if len(anchor.strip()) > _SHORT_ANCHOR_MAX_LEN and anchor.lower() in text.lower():
                return True
        return False

    def _best_key_anchor_match(self, key: str, anchors: Sequence[str]) -> str | None:
        for anchor in anchors:
            if self._key_matches_anchor(key, anchor):
                return anchor
        return None

    def _key_matches_anchor(self, key: str, anchor: str) -> bool:
        key_text = str(key).strip()
        anchor_text = str(anchor).strip()
        if not key_text or not anchor_text:
            return False

        key_norm = self._normalize_label(key_text)
        anchor_norm = self._normalize_label(anchor_text)
        if key_norm == anchor_norm:
            return True

        if key_text.lower().startswith(anchor_text.lower()):
            remainder = key_text[len(anchor_text) :]
            if not remainder:
                return True
            if remainder[0] in _LABEL_VALUE_DELIMITERS:
                return True

        span = self._label_match_span(key_text, anchor_text)
        return span is not None and span[0] == 0

    @staticmethod
    def _normalize_label(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    @staticmethod
    def _label_match_span(text: str, anchor: str) -> tuple[int, int] | None:
        text_value = str(text)
        anchor_value = str(anchor).strip()
        if not text_value or not anchor_value:
            return None

        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(anchor_value)}(?=(?:\s*[:=|\-\u2013\u2014]|\s|$))",
            re.IGNORECASE,
        )
        match = pattern.search(text_value)
        if match is not None:
            return match.span()

        if len(anchor_value) <= _SHORT_ANCHOR_MAX_LEN:
            return None

        index = text_value.lower().find(anchor_value.lower())
        if index == -1:
            return None
        return (index, index + len(anchor_value))

    def _first_anchor_span(
        self,
        text: str,
        anchors: Sequence[str],
    ) -> tuple[int, int, str] | None:
        best: tuple[int, int, str] | None = None
        for anchor in anchors:
            span = self._label_match_span(text, anchor)
            if span is None:
                continue
            candidate = (span[0], span[1], anchor)
            if best is None:
                best = candidate
                continue
            if candidate[0] < best[0]:
                best = candidate
                continue
            if candidate[0] == best[0] and (candidate[1] - candidate[0]) > (best[1] - best[0]):
                best = candidate
        return best

    def _compiled_patterns(self, target: dict) -> list[re.Pattern[str]]:
        compiled: list[re.Pattern[str]] = []
        for pattern in target.get("value_patterns") or ():
            try:
                compiled.append(re.compile(pattern))
            except re.error:
                continue
        return compiled

    def _value_after_anchor(
        self,
        text: str,
        anchors: Sequence[str],
        patterns: Sequence[re.Pattern[str]],
        target: dict,
    ) -> tuple[str, str] | None:
        anchor_span = self._first_anchor_span(text, anchors)
        if anchor_span is None:
            return None
        _, anchor_end, matched_anchor = anchor_span

        remainder = text[anchor_end:]
        remainder = remainder.lstrip(_LABEL_VALUE_DELIMITERS)

        if patterns:
            for pattern in patterns:
                for corpus in (remainder, text):
                    for match in pattern.finditer(corpus):
                        value = match.group(0)
                        if self._is_likely_bad_quantity_match(value, corpus, target):
                            continue
                        return value, matched_anchor

        cleaned = remainder.strip()
        if not cleaned:
            return None
        if self._is_likely_bad_quantity_match(cleaned, text, target):
            return None
        return cleaned, matched_anchor

    @staticmethod
    def _split_search_lines(text: str) -> list[str]:
        lines = [line for line in str(text).splitlines() if line.strip()]
        if lines:
            return lines
        return [str(text)] if str(text).strip() else []

    def _infer_unit_from_context(
        self,
        parser_output: dict,
        target: dict,
        hit: _MethodHit,
        current_unit: str | None,
    ) -> str | None:
        if current_unit is not None:
            return current_unit

        value_type = str(target.get("value_type") or "")
        expected_units = tuple(target.get("expected_units") or ())
        unit_patterns = tuple(target.get("unit_patterns") or ())
        if value_type not in _NUMERIC_VALUE_TYPES:
            return None
        if not expected_units and not unit_patterns:
            return None

        units_found: list[str] = []

        direct = self._detect_unit_candidate(str(hit.raw_value or ""), target)
        if direct:
            units_found.append(direct)

        context = hit.context or {}
        if isinstance(context.get("inferred_unit"), str):
            inferred = self._detect_unit_candidate(str(context.get("inferred_unit") or ""), target)
            if inferred:
                units_found.append(inferred)

        page_number = context.get("page_number")
        for pair in parser_output.get("key_value_pairs", []) or []:
            if not isinstance(pair, dict):
                continue
            if page_number is not None and pair.get("page_number") != page_number:
                continue

            key_text = str(pair.get("key") or "")
            key_lower = key_text.lower().strip()
            if not any(
                key_lower == unit_key or key_lower.startswith(f"{unit_key} ")
                for unit_key in _UNIT_CONTEXT_KEYS
            ):
                continue

            candidate_text = str(pair.get("value") or "")
            detected = self._detect_unit_candidate(candidate_text, target)
            if detected:
                units_found.append(detected)

        for line in self._context_lines(parser_output, page_number):
            lower = line.lower()
            if not any(keyword in lower for keyword in _QUANTITY_ANCHOR_KEYWORDS + _UNIT_CONTEXT_KEYS):
                continue
            detected = self._detect_unit_candidate(line, target)
            if detected:
                units_found.append(detected)

        for context_key in ("row_text", "header_text", "surrounding_text", "pair_key", "pair_value"):
            value = context.get(context_key)
            if not value:
                continue
            detected = self._detect_unit_candidate(str(value), target)
            if detected:
                units_found.append(detected)

        return self._resolve_single_inferred_unit(units_found)

    @staticmethod
    def _resolve_single_inferred_unit(units: Sequence[str]) -> str | None:
        normalized: dict[str, str] = {}
        for unit in units:
            text = str(unit).strip()
            if not text:
                continue
            key = text.lower().rstrip("s")
            normalized.setdefault(key, text)
        if len(normalized) == 1:
            return next(iter(normalized.values()))
        return None

    def _detect_unit_candidate(self, text: str, target: dict) -> str | None:
        source_text = str(text)
        if not source_text.strip():
            return None

        unit_patterns = tuple(target.get("unit_patterns") or ())
        expected_units = tuple(target.get("expected_units") or ())

        if unit_patterns:
            detected = self._detect_unit(source_text, unit_patterns)
            if detected:
                return self._align_unit_to_expected(detected, expected_units)

        for expected in expected_units:
            expected_text = str(expected).strip()
            if not expected_text:
                continue
            pattern = re.compile(rf"\b{re.escape(expected_text)}s?\b", re.IGNORECASE)
            match = pattern.search(source_text)
            if match:
                return self._align_unit_to_expected(match.group(0), expected_units)
        return None

    @staticmethod
    def _align_unit_to_expected(detected: str, expected_units: Sequence[str]) -> str:
        detected_text = str(detected).strip()
        detected_low = detected_text.lower()
        if not expected_units:
            return detected_text

        for expected in expected_units:
            expected_text = str(expected).strip()
            if not expected_text:
                continue
            expected_low = expected_text.lower()

            if detected_low == expected_low:
                return expected_text

            if detected_low == f"{expected_low}s":
                if expected_text.isupper():
                    return expected_text
                return f"{expected_low}s"

        return detected_text

    def _context_lines(self, parser_output: dict, page_number: Any | None) -> list[str]:
        lines: list[str] = []

        for pair in parser_output.get("key_value_pairs", []) or []:
            if not isinstance(pair, dict):
                continue
            if page_number is not None and pair.get("page_number") != page_number:
                continue
            key = pair.get("key")
            value = pair.get("value")
            lines.append(f"{key}: {value}")

        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            if page_number is not None and block.get("page_number") != page_number:
                continue
            lines.extend(self._split_search_lines(str(block.get("text") or "")))

        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            if page_number is not None and page.get("page_number") != page_number:
                continue
            lines.extend(self._split_search_lines(str(page.get("text") or "")))

        return lines

    def _should_suppress_activity_quantity(self, parser_output: dict, target: dict) -> bool:
        if not self._is_activity_quantity_target(target):
            return False

        corpus = self._parser_text_corpus(parser_output).lower()
        has_negative_signal = any(pattern in corpus for pattern in _NO_ACTIVITY_PATTERNS)
        if not has_negative_signal:
            return False

        return not self._has_positive_activity_quantity_signal(parser_output)

    def _parser_text_corpus(self, parser_output: dict) -> str:
        parts: list[str] = []

        for page in parser_output.get("pages", []) or []:
            if isinstance(page, dict):
                parts.append(str(page.get("text") or ""))

        for block in parser_output.get("text_blocks", []) or []:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))

        for pair in parser_output.get("key_value_pairs", []) or []:
            if isinstance(pair, dict):
                parts.append(f"{pair.get('key')}: {pair.get('value')}")

        for table in parser_output.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            for row in table.get("rows") or []:
                if isinstance(row, (list, tuple)):
                    parts.append(self._row_to_text(row))

        return "\n".join(parts)

    def _has_positive_activity_quantity_signal(self, parser_output: dict) -> bool:
        for pair in parser_output.get("key_value_pairs", []) or []:
            if not isinstance(pair, dict):
                continue
            key = str(pair.get("key") or "").lower()
            if not any(keyword in key for keyword in _QUANTITY_ANCHOR_KEYWORDS):
                continue
            number = self._parse_number(str(pair.get("value") or ""))
            if number is not None and number > 0:
                return True

        for line in self._context_lines(parser_output, page_number=None):
            lowered = line.lower()
            if not any(keyword in lowered for keyword in _QUANTITY_ANCHOR_KEYWORDS):
                continue
            for match in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", line):
                token = match.group(0)
                if self._is_likely_bad_quantity_match(
                    token,
                    line,
                    {"field_id": "activity_quantity", "value_type": "quantity"},
                ):
                    continue
                number = self._parse_number(token)
                if number is not None and number > 0:
                    return True
        return False

    def _is_likely_bad_quantity_match(
        self,
        match_text: str,
        surrounding_text: str,
        target: dict,
    ) -> bool:
        value_type = str(target.get("value_type") or "")
        if value_type not in _NUMERIC_VALUE_TYPES:
            return False

        field_id = str(target.get("field_id") or "")
        if field_id != "activity_quantity":
            return False

        token = str(match_text or "").strip()
        if not re.fullmatch(r"\d[\d,]*(?:\.\d+)?", token):
            return False

        cleaned = token.replace(",", "")
        low_surrounding = str(surrounding_text or "").lower()

        if re.fullmatch(r"\d{4}", cleaned):
            year = int(cleaned)
            if 1900 <= year <= 2100:
                return True

        for date_match in re.finditer(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", surrounding_text or ""):
            date_parts = date_match.group(0).split("/")
            if cleaned in {part.lstrip("0") or "0" for part in date_parts}:
                return True
            if cleaned in date_parts:
                return True

        for label in _ID_CONTEXT_LABELS:
            if label in low_surrounding and not any(
                keyword in low_surrounding for keyword in _QUANTITY_ANCHOR_KEYWORDS
            ):
                return True

        for token_like in re.findall(r"[A-Za-z0-9-]+", surrounding_text or ""):
            if cleaned not in token_like:
                continue
            if token_like == cleaned:
                continue
            if any(ch.isalpha() for ch in token_like) or "-" in token_like:
                return True

        return False

    @staticmethod
    def _is_activity_quantity_target(target: dict) -> bool:
        return str(target.get("field_id") or "") == "activity_quantity"

    def _target_record_id(self, target: dict) -> str | None:
        for key in _ROW_ID_KEYS:
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        normalization = target.get("normalization")
        if isinstance(normalization, dict):
            for key in _ROW_ID_KEYS:
                value = normalization.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        for hint in (target.get("validation_hints") or ()):
            parsed = self._record_id_from_hint(hint)
            if parsed:
                return parsed

        for hint in (target.get("table_hints") or ()):
            parsed = self._record_id_from_hint(hint)
            if parsed:
                return parsed

        return None

    @staticmethod
    def _record_id_from_hint(hint: Any) -> str | None:
        text = str(hint or "").strip()
        if not text:
            return None
        lowered = text.lower()
        for key in _ROW_ID_KEYS:
            prefix = f"{key}:"
            if lowered.startswith(prefix):
                value = text.split(":", 1)[1].strip()
                return value or None
        return None

    def _extract_row_bound_quantity(
        self,
        parser_output: dict,
        target: dict,
        document_id: str,
    ) -> _MethodHit | None:
        if not self._is_activity_quantity_target(target):
            return None

        record_id = self._target_record_id(target)
        if not record_id:
            return None

        table_hit = self._extract_row_bound_quantity_from_tables(
            parser_output=parser_output,
            target=target,
            document_id=document_id,
            record_id=record_id,
        )
        if table_hit is not None:
            return table_hit

        return self._extract_row_bound_quantity_from_lines(
            parser_output=parser_output,
            target=target,
            document_id=document_id,
            record_id=record_id,
        )

    def _extract_row_bound_quantity_from_tables(
        self,
        parser_output: dict,
        target: dict,
        document_id: str,
        record_id: str,
    ) -> _MethodHit | None:
        for table in parser_output.get("tables", []) or []:
            if not isinstance(table, dict):
                continue
            rows = [row for row in (table.get("rows") or []) if isinstance(row, (list, tuple))]
            if not rows:
                continue

            header_index = self._header_row_index(rows)
            header_row = rows[header_index] if header_index is not None else None
            quantity_indexes = self._quantity_column_indexes(header_row)
            header_text = self._row_to_text(header_row) if header_row is not None else ""

            for index, row in enumerate(rows):
                if header_index is not None and index == header_index:
                    continue
                row_text = self._row_to_text(row)
                if record_id.lower() not in row_text.lower():
                    continue

                quantity_value = self._extract_quantity_from_row(
                    row=row,
                    quantity_indexes=quantity_indexes,
                    surrounding_text=row_text,
                    target=target,
                )
                if quantity_value is None:
                    continue

                inferred_unit = self._detect_unit_candidate(header_text, target) or self._detect_unit_candidate(
                    row_text, target
                )
                source_reference = self._source_reference_for_table(
                    parser_output,
                    table,
                    document_id,
                )
                source_reference["text_snippet"] = self._snippet(row_text)

                return _MethodHit(
                    method="table_lookup",
                    raw_value=quantity_value,
                    method_confidence=_METHOD_BASE_CONFIDENCE["table_lookup"],
                    parser_confidence=self._as_confidence(table.get("confidence")),
                    source_reference=source_reference,
                    context={
                        "page_number": table.get("page_number"),
                        "sheet_name": table.get("sheet_name"),
                        "row_text": row_text,
                        "header_text": header_text,
                        "record_id": record_id,
                        "inferred_unit": inferred_unit,
                    },
                )
        return None

    def _extract_row_bound_quantity_from_lines(
        self,
        parser_output: dict,
        target: dict,
        document_id: str,
        record_id: str,
    ) -> _MethodHit | None:
        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            lines = [line for line in str(page.get("text") or "").splitlines() if line.strip()]
            for line_index, line in enumerate(lines):
                if record_id.lower() not in line.lower():
                    continue

                header_line = lines[line_index - 1] if line_index > 0 else ""
                row_parts = [part.strip() for part in line.split("|")]
                header_parts = [part.strip() for part in header_line.split("|")] if "|" in header_line else []
                quantity_indexes = self._quantity_column_indexes(header_parts)

                quantity_value = None
                if quantity_indexes and len(row_parts) > max(quantity_indexes):
                    for idx in quantity_indexes:
                        if idx >= len(row_parts):
                            continue
                        quantity_value = self._extract_quantity_token(
                            row_parts[idx],
                            line,
                            target,
                        )
                        if quantity_value is not None:
                            break
                if quantity_value is None:
                    quantity_value = self._extract_quantity_token(line, line, target)
                if quantity_value is None:
                    continue

                inferred_unit = self._detect_unit_candidate(header_line, target) or self._detect_unit_candidate(
                    line, target
                )
                source_reference = self._inline_from_page(page, document_id)
                source_reference["text_snippet"] = self._snippet(line)

                return _MethodHit(
                    method="table_lookup",
                    raw_value=quantity_value,
                    method_confidence=_METHOD_BASE_CONFIDENCE["table_lookup"],
                    parser_confidence=None,
                    source_reference=source_reference,
                    context={
                        "page_number": page.get("page_number"),
                        "sheet_name": None,
                        "row_text": line,
                        "header_text": header_line,
                        "record_id": record_id,
                        "inferred_unit": inferred_unit,
                    },
                )
        return None

    def _header_row_index(self, rows: Sequence[Sequence[Any]]) -> int | None:
        for index, row in enumerate(rows[:3]):
            lowered_cells = [str(cell).lower() for cell in row if cell is not None]
            if any("ticket" in cell for cell in lowered_cells):
                return index
            if any(any(hint in cell for hint in _TABLE_QUANTITY_HEADER_HINTS) for cell in lowered_cells):
                return index
        return 0 if rows else None

    def _quantity_column_indexes(self, header_row: Sequence[Any] | None) -> list[int]:
        if not header_row:
            return []
        indexes: list[int] = []
        lowered = [str(cell).lower() if cell is not None else "" for cell in header_row]
        for hint in _TABLE_QUANTITY_HEADER_HINTS:
            for index, text in enumerate(lowered):
                if hint in text and index not in indexes:
                    indexes.append(index)
        return indexes

    def _extract_quantity_from_row(
        self,
        row: Sequence[Any],
        quantity_indexes: Sequence[int],
        surrounding_text: str,
        target: dict,
    ) -> str | None:
        search_indexes = list(quantity_indexes) if quantity_indexes else list(range(len(row)))
        for index in search_indexes:
            if index >= len(row):
                continue
            token = self._extract_quantity_token(row[index], surrounding_text, target)
            if token is not None:
                return token
        return None

    def _extract_quantity_token(self, cell_value: Any, surrounding_text: str, target: dict) -> str | None:
        text = str(cell_value or "")
        for match in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
            token = match.group(0)
            if self._is_likely_bad_quantity_match(token, surrounding_text, target):
                continue
            number = self._parse_number(token)
            if number is None:
                continue
            return token
        return None

    @staticmethod
    def _row_to_text(row: Sequence[Any] | None) -> str:
        if not row:
            return ""
        return " | ".join(str(cell or "").strip() for cell in row)

    @staticmethod
    def _adjacent_value(row: Sequence[Any], index: int) -> Any:
        for cell in row[index + 1 :]:
            if cell is not None and str(cell).strip():
                return cell
        return None

    @staticmethod
    def _next_column(coord: str) -> str | None:
        match = _CELL_COORD_PATTERN.match(coord)
        if not match:
            return None
        letters, digits = match.group(1).upper(), match.group(2)
        number = 0
        for char in letters:
            number = number * 26 + (ord(char) - ord("A") + 1)
        number += 1
        next_letters = ""
        while number > 0:
            number, remainder = divmod(number - 1, 26)
            next_letters = chr(ord("A") + remainder) + next_letters
        return f"{next_letters}{digits}"

    @staticmethod
    def _has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    @staticmethod
    def _coerce_raw(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _as_confidence(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _snippet(text: Any, max_length: int = _MAX_SNIPPET) -> str | None:
        if text is None:
            return None
        collapsed = " ".join(str(text).split())
        if not collapsed:
            return ""
        if len(collapsed) <= max_length:
            return collapsed
        return collapsed[: max_length - 1].rstrip() + "\u2026"
