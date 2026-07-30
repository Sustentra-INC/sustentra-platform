"""CSV parser adapter.

Normalizes ``.csv`` files into parser_output with both text blocks and one
structured table. It performs no business-field inference.
"""

from __future__ import annotations

import csv
from pathlib import Path

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_empty_parser_output,
    build_parser_output,
    build_source_reference,
    build_text_block,
    build_warning,
    snippet,
)

PARSER_NAME = "csv_parser"


class CsvParser:
    """Adapter that normalizes CSV files into ``parser_output`` dicts."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)
        warnings: list[dict[str, str]] = []

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            warnings.append(
                build_warning(
                    "non_utf8_content",
                    "File was not valid UTF-8; undecodable bytes were replaced.",
                )
            )

        rows = list(csv.reader(raw_text.splitlines()))
        non_empty_rows = [
            (row_number, row)
            for row_number, row in enumerate(rows, start=1)
            if any(str(cell).strip() for cell in row)
        ]

        if not non_empty_rows:
            warnings.append(
                build_warning(
                    "empty_document",
                    "CSV file contained no non-empty rows.",
                    severity="info",
                )
            )
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=warnings,
                pages=[{"page_number": 1, "text": raw_text}],
            )

        text_blocks: list[dict] = []
        source_references: list[dict] = []

        for position, (row_number, row_values) in enumerate(non_empty_rows, start=1):
            row_text = " | ".join(str(cell).strip() for cell in row_values)
            block_id = f"{self.parser_name}-r{row_number}-b{position}"
            source_reference_id = f"SRC-{self.parser_name}-r{row_number}"
            source_references.append(
                build_source_reference(
                    source_reference_id,
                    document_id,
                    page_number=1,
                    cell_or_range=f"row {row_number}",
                    text_snippet=snippet(row_text),
                    parser_block_ids=[block_id],
                    source_kind="page_text",
                )
            )
            text_blocks.append(
                build_text_block(
                    block_id,
                    row_text,
                    page_number=1,
                    source_reference_id=source_reference_id,
                )
            )

        table_rows = [[cell for cell in row_values] for _, row_values in non_empty_rows]
        tables = [
            {
                "table_id": f"{self.parser_name}-table-1",
                "page_number": 1,
                "sheet_name": None,
                "rows": table_rows,
                "confidence": None,
                "bounding_box": None,
                "source_reference_id": None,
            }
        ]

        return build_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            status="parsed",
            pages=[{"page_number": 1, "text": raw_text}],
            text_blocks=text_blocks,
            tables=tables,
            source_references=source_references,
            warnings=warnings,
        )
