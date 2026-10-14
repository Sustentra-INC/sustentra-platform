"""The content of an uploaded spreadsheet, CSV or Word/text file, for the source pane.

A PDF or image is shown as a page picture with the value outlined on it. These files have
no page, so the pane draws their content instead: a grid for a workbook or CSV, lines for
Word and text. The numbering is the parsers' own, so an extracted value's source reference
points at the right spot:

- Excel: sheet name and cell ("D2"), as ``openpyxl`` reports them.
- CSV: the row number in the file, counting blank rows (the CSV parser's ``r<N>``).
- Word / text: the n-th non-empty line (the text parser's block ``b<N>``).

The work and the response are bounded whatever the file holds: one budget for all cells
and characters, a cap on rows scanned (empty ones included) and on line length, and Word
files whose text parts are too large are not drawn. A cut file says so (``truncated``).
"""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.docx_parser import DocxError, docx_text
from backend.app.adapters.parsers.excel_parser import _coerce_cell_value
from backend.app.services.parser_service import ParserService

MAX_SHEETS = 30
MAX_COLUMNS = 60
MAX_SCANNED_ROWS = 20_000  # per sheet, empty rows included
MAX_CELLS = 50_000  # in the whole response
MAX_CHARS = 2_000_000  # in the whole response
MAX_CELL_CHARS = 500
MAX_LINE_CHARS = 2_000
MAX_DOCX_TEXT_BYTES = 10 * 1024 * 1024  # uncompressed body, header and footer parts


class UnsupportedContent(ValueError):
    """The file is shown as pages (PDF, image), or cannot be shown at all."""


class UnreadableContent(ValueError):
    """The file could not be opened, or is too large to draw."""


class _Budget:
    """Cells and characters left for the response."""

    def __init__(self) -> None:
        self.cells = MAX_CELLS
        self.chars = MAX_CHARS

    def take(self, texts: list[str | None]) -> bool:
        used = sum(len(t) for t in texts if t)
        filled = sum(1 for t in texts if t)
        if filled > self.cells or used > self.chars:
            return False
        self.cells -= filled
        self.chars -= used
        return True


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return _clip(text, MAX_CELL_CHARS) if text.strip() else None


def _workbook(path: Path, budget: _Budget) -> dict[str, Any]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 - any load failure is "unreadable"
        raise UnreadableContent("The workbook could not be opened.") from exc
    sheets: list[dict[str, Any]] = []
    truncated = len(workbook.worksheets) > MAX_SHEETS
    try:
        for worksheet in workbook.worksheets[:MAX_SHEETS]:
            # Read only the cells the sheet holds, not its declared (possibly huge) dimension.
            worksheet.reset_dimensions()
            rows: list[dict[str, Any]] = []
            width = 0
            for scanned, row in enumerate(worksheet.iter_rows(max_col=MAX_COLUMNS), start=1):
                if scanned > MAX_SCANNED_ROWS:
                    truncated = True
                    break
                placed: dict[int, str] = {}
                number: int | None = None
                for cell in row:  # placed by the cell's own column, as its "D2" reference says
                    text = _cell(_coerce_cell_value(cell.value))
                    column = getattr(cell, "column", None)
                    if text is None or not isinstance(column, int):
                        continue
                    number = number or getattr(cell, "row", None)
                    placed[column - 1] = text
                if not placed:
                    continue
                cells = [placed.get(i) for i in range(max(placed) + 1)]
                if not budget.take(cells):
                    truncated = True
                    break
                width = max(width, len(cells))
                rows.append({"number": number, "cells": cells})
            if rows:
                sheets.append({"name": worksheet.title, "columns": width, "rows": rows})
            if truncated and budget.cells <= 0:
                break
    finally:
        workbook.close()
    return {"kind": "sheets", "sheets": sheets, "truncated": truncated}


def _decoded(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _csv(path: Path, budget: _Budget) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    width = 0
    truncated = False
    for number, values in enumerate(csv.reader(_decoded(path).splitlines()), start=1):
        if number > MAX_SCANNED_ROWS:
            truncated = True
            break
        if not any(str(v).strip() for v in values):
            continue
        truncated = truncated or len(values) > MAX_COLUMNS
        cells = [_cell(v) for v in values[:MAX_COLUMNS]]
        if not budget.take(cells):
            truncated = True
            break
        width = max(width, len(cells))
        rows.append({"number": number, "cells": cells})
    return {"kind": "sheets", "sheets": [{"name": None, "columns": width, "rows": rows}] if rows else [],
            "truncated": truncated}


def _lines(text: str, budget: _Budget) -> dict[str, Any]:
    lines: list[str] = []
    truncated = False
    for line in (line for line in text.splitlines() if line.strip()):
        clipped = _clip(line, MAX_LINE_CHARS)
        if not budget.take([clipped]):
            truncated = True
            break
        truncated = truncated or clipped != line
        lines.append(clipped)
    return {"kind": "lines", "lines": lines, "truncated": truncated}


def _docx_text_size(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(info.file_size for info in archive.infolist()
                       if info.filename == "word/document.xml"
                       or (info.filename.startswith(("word/header", "word/footer")) and info.filename.endswith(".xml")))
    except zipfile.BadZipFile as exc:
        raise UnreadableContent("The file is not a valid .docx (it could not be opened).") from exc


def document_content(path: Path, mime_type: str | None = None) -> dict[str, Any]:
    """The file's content as sheets (Excel, CSV) or lines (Word, text)."""

    kind = ParserService.parser_kind(path, mime_type)
    budget = _Budget()
    if kind == "excel":
        return _workbook(path, budget)
    if kind == "csv":
        return _csv(path, budget)
    if kind == "docx":
        if _docx_text_size(path) > MAX_DOCX_TEXT_BYTES:
            raise UnreadableContent("This Word document is too large to show here. Download it to check the value.")
        try:
            return _lines(docx_text(path), budget)
        except DocxError as exc:
            raise UnreadableContent(str(exc)) from exc
    if kind == "text":
        return _lines(_decoded(path), budget)
    raise UnsupportedContent("This file is shown as pages, not as content.")
