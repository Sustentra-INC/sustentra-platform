"""Excel workbook parser adapter.

Normalizes ``.xlsx`` workbooks into a ``parser_output`` object using ``openpyxl``.
Every non-empty cell becomes a traceable text block plus source reference, and
each worksheet with content produces a table. No business-field inference is
performed here.

``parser_output_from_sheets`` builds that output from any reader's sheets, so the
Excel 97-2003 reader (``xls_parser``) gives exactly the same shape: the same block
ids, ``excel_cell`` source references and tables.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, time
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

PARSER_NAME = "openpyxl"

# One cell as a reader hands it over: its coordinate ("D2") and its coerced value. An
# empty cell needs no coordinate (openpyxl's read-only rows pad with cells that have
# none), but it still takes its place in the table row.
SheetCell = tuple[str | None, Any]
# One worksheet: its name, then its rows from the top.
Sheet = tuple[str, Iterable[Sequence[SheetCell]]]


def _coerce_cell_value(value: Any) -> str | int | float | bool | None:
    """Coerce a workbook cell value into a JSON/table-safe scalar."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def parser_output_from_sheets(
    sheets: Iterable[Sheet],
    *,
    parser_name: str,
    document_id: str,
    processing_run_id: str,
    warnings: list[dict[str, str]] | None = None,
    max_sheets: int | None = None,
    max_rows_per_sheet: int | None = None,
    max_cells: int | None = None,
    max_table_slots: int | None = None,
) -> dict:
    """Build a workbook's ``parser_output`` from its sheets.

    Every non-empty cell becomes a text block ``<parser>-<sheet>-<coordinate>`` with an
    ``excel_cell`` source reference (sheet name and coordinate), and each sheet with
    content becomes one table of its rows. With a limit on sheets, rows per sheet, filled
    cells or table slots (every cell a table row holds, empty padding included), reading
    stops there and the output is ``partial``, with a ``workbook_truncated`` warning saying where.
    """

    warnings = list(warnings or [])
    text_blocks: list[dict] = []
    source_references: list[dict] = []
    tables: list[dict] = []
    cell_counter = 0
    slots_used = 0
    stopped: list[str] = []

    for sheet_index, (sheet_name, rows) in enumerate(sheets, start=1):
        if max_sheets is not None and sheet_index > max_sheets:
            stopped.append(f"after {max_sheets} sheets")
            break
        table_rows: list[list[Any]] = []
        sheet_has_content = False
        cell_limit_reached = False
        slot_limit_reached = False

        for row_index, row in enumerate(rows):
            if max_rows_per_sheet is not None and row_index >= max_rows_per_sheet:
                stopped.append(f"after row {max_rows_per_sheet} of sheet '{sheet_name}'")
                break
            if max_table_slots is not None:
                slots_used += len(row)
                if slots_used > max_table_slots:
                    slot_limit_reached = True
                    break
            table_row: list[Any] = []
            for coordinate, value in row:
                if coordinate is None or _is_blank(value):
                    table_row.append(value)
                    continue
                if max_cells is not None and cell_counter >= max_cells:
                    cell_limit_reached = True
                    break
                table_row.append(value)

                sheet_has_content = True
                cell_counter += 1
                block_id = f"{parser_name}-{sheet_name}-{coordinate}"
                source_reference_id = f"SRC-{parser_name}-c{cell_counter}"
                cell_text = str(value)
                source_references.append(
                    build_source_reference(
                        source_reference_id,
                        document_id,
                        sheet_name=sheet_name,
                        cell_or_range=coordinate,
                        text_snippet=snippet(cell_text),
                        parser_block_ids=[block_id],
                        source_kind="excel_cell",
                    )
                )
                text_blocks.append(
                    build_text_block(
                        block_id,
                        cell_text,
                        source_reference_id=source_reference_id,
                    )
                )

            table_rows.append(table_row)
            if cell_limit_reached:
                break

        if sheet_has_content:
            tables.append(
                {
                    "table_id": f"{parser_name}-{sheet_name}-t{sheet_index}",
                    "page_number": None,
                    "sheet_name": sheet_name,
                    "rows": table_rows,
                    "confidence": None,
                    "bounding_box": None,
                    "source_reference_id": None,
                }
            )
        if cell_limit_reached:
            stopped.append(f"after {max_cells} filled cells, in sheet '{sheet_name}'")
            break
        if slot_limit_reached:
            stopped.append(f"after {max_table_slots} table cells, in sheet '{sheet_name}'")
            break

    if stopped:
        warnings.append(
            build_warning(
                "workbook_truncated",
                "The workbook is larger than can be read here. Reading stopped " + "; ".join(stopped) + ".",
            )
        )

    if not text_blocks:
        warnings.append(
            build_warning(
                "empty_document",
                "Workbook contained no non-empty cells.",
                severity="info",
            )
        )
        return build_empty_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=parser_name,
            warnings=warnings,
        )

    return build_parser_output(
        document_id=document_id,
        processing_run_id=processing_run_id,
        parser_name=parser_name,
        status="partial" if stopped else "parsed",
        text_blocks=text_blocks,
        tables=tables,
        source_references=source_references,
        warnings=warnings,
    )


def read_only_workbook(path: Path) -> Any:
    """openpyxl's read-only, values-only workbook, opened from the file's bytes. The caller
    closes it.

    openpyxl refuses a file *name* without an Excel extension (an .xlsx saved as .xls, an
    upload with no extension that its media type routed here); given the bytes, it goes by
    the contents.
    """

    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(path.read_bytes()), data_only=True, read_only=True)


def _openpyxl_sheets(workbook: Any) -> Iterator[Sheet]:
    for worksheet in workbook.worksheets:
        yield worksheet.title, (_openpyxl_row(row) for row in worksheet.iter_rows())


def _openpyxl_row(row: Iterable[Any]) -> list[SheetCell]:
    cells: list[SheetCell] = []
    for cell in row:
        value = _coerce_cell_value(cell.value)
        cells.append((None if _is_blank(value) else cell.coordinate, value))
    return cells


class ExcelParser:
    """Adapter that normalizes ``.xlsx`` workbooks into ``parser_output`` dicts."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)

        try:
            import openpyxl  # noqa: F401
        except ImportError:
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[
                    build_warning(
                        "missing_dependency",
                        "openpyxl is not installed; cannot parse Excel workbook.",
                        severity="error",
                    )
                ],
            )

        try:
            workbook = read_only_workbook(path)
        except Exception as exc:  # noqa: BLE001 - normalize any load failure
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[
                    build_warning(
                        "workbook_load_failed",
                        f"Could not open workbook: {type(exc).__name__}.",
                        severity="error",
                    )
                ],
            )

        try:
            return parser_output_from_sheets(
                _openpyxl_sheets(workbook),
                parser_name=self.parser_name,
                document_id=document_id,
                processing_run_id=processing_run_id,
            )
        finally:
            workbook.close()
