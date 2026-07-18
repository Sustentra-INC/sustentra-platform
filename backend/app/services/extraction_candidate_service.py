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


@dataclass(frozen=True)
class _MethodHit:
    method: str
    raw_value: Any
    method_confidence: float
    parser_confidence: float | None
    source_reference: dict


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

        ordered = sorted(supported, key=lambda method: -_METHOD_BASE_CONFIDENCE[method])
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
            if not self._contains_anchor(key, anchors):
                continue
            raw_value = pair.get("value")
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
            )
        return None

    def _extract_regex(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        patterns = self._compiled_patterns(target)
        if not patterns:
            return None

        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    source_reference = self._source_reference_for_block(
                        parser_output, block, document_id
                    )
                    return _MethodHit(
                        method="regex",
                        raw_value=match.group(0),
                        method_confidence=_METHOD_BASE_CONFIDENCE["regex"],
                        parser_confidence=self._as_confidence(block.get("confidence")),
                        source_reference=source_reference,
                    )

        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            text = str(page.get("text") or "")
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    return _MethodHit(
                        method="regex",
                        raw_value=match.group(0),
                        method_confidence=_METHOD_BASE_CONFIDENCE["regex"],
                        parser_confidence=None,
                        source_reference=self._inline_from_page(page, document_id),
                    )
        return None

    def _extract_anchor_text(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
        anchors = self._lower_anchors(target)
        if not anchors:
            return None
        patterns = self._compiled_patterns(target)

        for block in parser_output.get("text_blocks", []) or []:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "")
            value = self._value_after_anchor(text, anchors, patterns)
            if value:
                source_reference = self._source_reference_for_block(
                    parser_output, block, document_id
                )
                return _MethodHit(
                    method="anchor_text",
                    raw_value=value,
                    method_confidence=_METHOD_BASE_CONFIDENCE["anchor_text"],
                    parser_confidence=self._as_confidence(block.get("confidence")),
                    source_reference=source_reference,
                )

        for page in parser_output.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            for line in str(page.get("text") or "").splitlines():
                value = self._value_after_anchor(line, anchors, patterns)
                if value:
                    return _MethodHit(
                        method="anchor_text",
                        raw_value=value,
                        method_confidence=_METHOD_BASE_CONFIDENCE["anchor_text"],
                        parser_confidence=None,
                        source_reference=self._inline_from_page(page, document_id),
                    )
        return None

    def _extract_table_lookup(
        self, parser_output: dict, target: dict, document_id: str
    ) -> _MethodHit | None:
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
                match = re.search(pattern, raw_str, re.IGNORECASE)
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
        return [str(label).lower() for label in (target.get("anchor_labels") or ()) if str(label).strip()]

    @staticmethod
    def _contains_anchor(text: str, anchors: Sequence[str]) -> bool:
        lowered = text.lower()
        return any(anchor in lowered for anchor in anchors)

    def _compiled_patterns(self, target: dict) -> list[re.Pattern[str]]:
        compiled: list[re.Pattern[str]] = []
        for pattern in target.get("value_patterns") or ():
            try:
                compiled.append(re.compile(pattern))
            except re.error:
                continue
        return compiled

    def _value_after_anchor(
        self, text: str, anchors: Sequence[str], patterns: Sequence[re.Pattern[str]]
    ) -> str | None:
        lowered = text.lower()
        best_index = -1
        best_anchor_len = 0
        for anchor in anchors:
            position = lowered.find(anchor)
            if position != -1 and (best_index == -1 or position < best_index):
                best_index = position
                best_anchor_len = len(anchor)
        if best_index == -1:
            return None

        remainder = text[best_index + best_anchor_len :]
        remainder = remainder.lstrip(" \t:-\u2013\u2014=|")

        if patterns:
            for pattern in patterns:
                match = pattern.search(remainder) or pattern.search(text)
                if match:
                    return match.group(0)

        cleaned = remainder.strip()
        return cleaned or None

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
