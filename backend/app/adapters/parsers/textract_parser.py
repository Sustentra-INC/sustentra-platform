"""Textract output normalizer adapter.

Parser runtime v0 does **not** make live AWS Textract calls. This adapter only
normalizes already-saved Textract JSON (a dict or a local JSON file) into a
``parser_output`` object. ``LINE`` blocks become text blocks, ``KEY_VALUE_SET``
pairs become key/value pairs, and ``TABLE`` blocks become tables, each traced
back to Textract block ids. If no usable JSON is provided it returns a
``failed`` output with a warning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_empty_parser_output,
    build_failed_parser_output,
    build_parser_output,
    build_source_reference,
    build_text_block,
    build_warning,
    snippet,
)

PARSER_NAME = "textract"


class TextractParser:
    """Normalizes saved Textract JSON; never calls AWS."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def parse(
        self,
        textract_source: dict[str, Any] | str | Path,
        document_id: str,
        processing_run_id: str,
    ) -> dict:
        payload, load_warning = self._load_payload(textract_source)
        if load_warning is not None:
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[load_warning],
            )

        blocks = payload.get("Blocks") if isinstance(payload, dict) else None
        if not blocks:
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[
                    build_warning(
                        "empty_document",
                        "Textract payload contained no Blocks.",
                        severity="info",
                    )
                ],
            )

        block_map = {block.get("Id"): block for block in blocks if block.get("Id")}

        pages: dict[int, str] = {}
        text_blocks: list[dict] = []
        key_value_pairs: list[dict] = []
        source_references: list[dict] = []
        warnings: list[dict] = []

        # LINE blocks -> text blocks + page text accumulation.
        for block in blocks:
            if block.get("BlockType") != "LINE":
                continue
            text = block.get("Text", "") or ""
            page_number = int(block.get("Page", 1) or 1)
            block_id = block.get("Id")
            pages.setdefault(page_number, "")
            pages[page_number] = (pages[page_number] + "\n" + text).strip() if pages[page_number] else text

            source_reference_id = f"SRC-{self.parser_name}-{block_id}"
            source_references.append(
                build_source_reference(
                    source_reference_id,
                    document_id,
                    page_number=page_number,
                    text_snippet=snippet(text),
                    parser_block_ids=[block_id],
                    source_kind="page_text",
                )
            )
            text_blocks.append(
                build_text_block(
                    block_id,
                    text,
                    page_number=page_number,
                    confidence=self._normalize_confidence(block.get("Confidence")),
                    source_reference_id=source_reference_id,
                )
            )

        # KEY_VALUE_SET (KEY entities) -> key/value pairs.
        for block in blocks:
            if block.get("BlockType") != "KEY_VALUE_SET":
                continue
            if "KEY" not in (block.get("EntityTypes") or []):
                continue
            key_text = self._collect_child_text(block, block_map)
            value_block = self._resolve_value_block(block, block_map)
            value_text = self._collect_child_text(value_block, block_map) if value_block else None
            page_number = int(block.get("Page", 1) or 1)
            pair_id = f"KV-{self.parser_name}-{block.get('Id')}"
            key_value_pairs.append(
                {
                    "pair_id": pair_id,
                    "page_number": page_number,
                    "sheet_name": None,
                    "key": key_text,
                    "value": value_text,
                    "confidence": self._normalize_confidence(block.get("Confidence")),
                    "key_source_reference_id": None,
                    "value_source_reference_id": None,
                }
            )

        # TABLE blocks -> normalized tables.
        tables = self._build_tables(blocks, block_map)

        if not (text_blocks or key_value_pairs or tables):
            warnings.append(
                build_warning(
                    "no_supported_blocks",
                    "Textract payload had no LINE, KEY_VALUE_SET, or TABLE blocks.",
                    severity="info",
                )
            )
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=warnings,
            )

        page_list = [
            {"page_number": number, "text": pages[number]}
            for number in sorted(pages)
        ]

        return build_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            status="parsed",
            pages=page_list,
            text_blocks=text_blocks,
            tables=tables,
            key_value_pairs=key_value_pairs,
            source_references=source_references,
            warnings=warnings,
        )

    def _load_payload(
        self, textract_source: dict[str, Any] | str | Path
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        if isinstance(textract_source, dict):
            return textract_source, None

        path = Path(textract_source)
        if not path.exists() or not path.is_file():
            return None, build_warning(
                "textract_json_not_found",
                "Textract JSON artifact was not found at the provided path.",
                severity="error",
            )
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle), None
        except (json.JSONDecodeError, OSError) as exc:
            return None, build_warning(
                "textract_json_invalid",
                f"Could not read Textract JSON: {type(exc).__name__}.",
                severity="error",
            )

    @staticmethod
    def _normalize_confidence(raw: Any) -> float | None:
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        # Textract confidence is 0-100; normalize to 0-1 for the contract.
        if value > 1:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    @staticmethod
    def _collect_child_text(block: dict[str, Any] | None, block_map: dict[str, Any]) -> str:
        if not block:
            return ""
        words: list[str] = []
        for relationship in block.get("Relationships", []) or []:
            if relationship.get("Type") != "CHILD":
                continue
            for child_id in relationship.get("Ids", []) or []:
                child = block_map.get(child_id)
                if not child:
                    continue
                if child.get("BlockType") == "WORD":
                    words.append(child.get("Text", ""))
                elif child.get("BlockType") == "SELECTION_ELEMENT":
                    if child.get("SelectionStatus") == "SELECTED":
                        words.append("[X]")
        return " ".join(word for word in words if word)

    @staticmethod
    def _resolve_value_block(
        key_block: dict[str, Any], block_map: dict[str, Any]
    ) -> dict[str, Any] | None:
        for relationship in key_block.get("Relationships", []) or []:
            if relationship.get("Type") != "VALUE":
                continue
            for value_id in relationship.get("Ids", []) or []:
                value_block = block_map.get(value_id)
                if value_block:
                    return value_block
        return None

    def _build_tables(
        self, blocks: list[dict[str, Any]], block_map: dict[str, Any]
    ) -> list[dict]:
        tables: list[dict] = []
        for table_index, block in enumerate(blocks, start=1):
            if block.get("BlockType") != "TABLE":
                continue
            cells: list[dict[str, Any]] = []
            for relationship in block.get("Relationships", []) or []:
                if relationship.get("Type") != "CHILD":
                    continue
                for cell_id in relationship.get("Ids", []) or []:
                    cell = block_map.get(cell_id)
                    if cell and cell.get("BlockType") == "CELL":
                        cells.append(cell)

            if not cells:
                continue

            max_row = max(int(cell.get("RowIndex", 1) or 1) for cell in cells)
            max_col = max(int(cell.get("ColumnIndex", 1) or 1) for cell in cells)
            grid: list[list[Any]] = [[None] * max_col for _ in range(max_row)]
            for cell in cells:
                row_idx = int(cell.get("RowIndex", 1) or 1) - 1
                col_idx = int(cell.get("ColumnIndex", 1) or 1) - 1
                grid[row_idx][col_idx] = self._collect_child_text(cell, block_map) or None

            tables.append(
                {
                    "table_id": f"{self.parser_name}-table-{block.get('Id', table_index)}",
                    "page_number": int(block.get("Page", 1) or 1),
                    "sheet_name": None,
                    "rows": grid,
                    "confidence": self._normalize_confidence(block.get("Confidence")),
                    "bounding_box": None,
                    "source_reference_id": None,
                }
            )
        return tables
