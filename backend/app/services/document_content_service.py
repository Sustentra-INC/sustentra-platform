"""The content of an uploaded spreadsheet, CSV, Word/text file or email, for the source pane.

A PDF or image is shown as a page picture with the value outlined on it. These files have
no page, so the pane draws their content instead: a grid for a workbook or CSV, lines for
Word, text and emails. The numbering is the parsers' own, so an extracted value's source reference
points at the right spot:

- Excel: sheet name and cell ("D2"), as ``openpyxl`` reports them (the ``.xls`` reader
  numbers cells the same way).
- CSV: the row number in the file, counting blank rows (the CSV parser's ``r<N>``).
- Word / text / email: the n-th non-empty line (the text parser's block ``b<N>``); an email's
  lines are the email parser's own rendering (headers, message text, attachment names).

The work and the response are bounded whatever the file holds: one budget for all cells
and characters, a cap on rows scanned (empty ones included) and on line length, and Word
files whose text parts are too large are not drawn. A cut file says so (``truncated``).
"""

from __future__ import annotations

import csv
import zipfile
from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.docx_parser import DocxError, docx_text
from backend.app.adapters.parsers.email_parser import email_text, read_email_file
from backend.app.adapters.parsers.email_reader import EmailError
from backend.app.adapters.parsers.excel_parser import _coerce_cell_value, _is_blank, read_only_workbook
from backend.app.adapters.parsers.xls_parser import XlsError, is_zip, open_xls, xls_worksheets
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


# A sheet as the pane reads it: its name, then every row scanned (empty ones included) as
# the row's number in the workbook and its non-empty values by 0-based column.
PaneSheet = tuple[str, Iterator[tuple[int | None, dict[int, Any]]]]


def _sheets(sheets: Iterable[PaneSheet], sheet_count: int, budget: _Budget) -> dict[str, Any]:
    drawn: list[dict[str, Any]] = []
    truncated = sheet_count > MAX_SHEETS
    for name, scanned_rows in islice(sheets, MAX_SHEETS):
        rows: list[dict[str, Any]] = []
        width = 0
        for scanned, (number, values) in enumerate(scanned_rows, start=1):
            if scanned > MAX_SCANNED_ROWS:
                truncated = True
                break
            # Placed by the cell's own column, as its "D2" reference says.
            placed = {column: text for column, value in values.items() if (text := _cell(value)) is not None}
            if not placed:
                continue
            cells = [placed.get(i) for i in range(max(placed) + 1)]
            if not budget.take(cells):
                truncated = True
                break
            width = max(width, len(cells))
            rows.append({"number": number, "cells": cells})
        if rows:
            drawn.append({"name": name, "columns": width, "rows": rows})
        if truncated and budget.cells <= 0:
            break
    return {"kind": "sheets", "sheets": drawn, "truncated": truncated}


def _workbook(path: Path, budget: _Budget) -> dict[str, Any]:
    try:
        workbook = read_only_workbook(path)
    except Exception as exc:  # noqa: BLE001 - any load failure is "unreadable"
        raise UnreadableContent("The workbook could not be opened.") from exc
    try:
        sheets = ((worksheet.title, _openpyxl_rows(worksheet)) for worksheet in workbook.worksheets)
        return _sheets(sheets, len(workbook.worksheets), budget)
    finally:
        workbook.close()


def _openpyxl_rows(worksheet: Any) -> Iterator[tuple[int | None, dict[int, Any]]]:
    # Read only the cells the sheet holds, not its declared (possibly huge) dimension.
    worksheet.reset_dimensions()
    for row in worksheet.iter_rows(max_col=MAX_COLUMNS):
        number: int | None = None
        values: dict[int, Any] = {}
        for cell in row:
            value = _coerce_cell_value(cell.value)
            column = getattr(cell, "column", None)
            if _is_blank(value) or not isinstance(column, int):
                continue
            number = number or getattr(cell, "row", None)
            values[column - 1] = value
        yield number, values


def _xls_workbook(path: Path, budget: _Budget) -> dict[str, Any]:
    """An Excel 97-2003 workbook, through the parser's own reader. An .xlsx saved with an
    .xls name is read as an .xlsx, as the parser does."""

    if is_zip(path):
        return _workbook(path, budget)
    try:
        book, _notes = open_xls(path)
    except XlsError as exc:
        raise UnreadableContent(exc.message) from exc
    try:
        sheets = ((name, _xls_rows(rows)) for name, rows in xls_worksheets(book))
        return _sheets(sheets, book.nsheets, budget)
    except Exception as exc:  # noqa: BLE001 - a damaged sheet stream
        raise UnreadableContent("The workbook could not be opened.") from exc
    finally:
        book.release_resources()


def _xls_rows(rows: Iterator[list[Any]]) -> Iterator[tuple[int | None, dict[int, Any]]]:
    for number, values in enumerate(rows, start=1):
        yield number, {column: value for column, value in enumerate(values[:MAX_COLUMNS]) if not _is_blank(value)}


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
    """The file's content as sheets (Excel, CSV) or lines (Word, text, email)."""

    kind = ParserService.parser_kind(path, mime_type)
    budget = _Budget()
    if kind == "excel":
        return _workbook(path, budget)
    if kind == "xls":
        return _xls_workbook(path, budget)
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
    if kind == "email":
        try:
            return _lines(email_text(read_email_file(path)), budget)
        except EmailError as exc:
            raise UnreadableContent(exc.message) from exc
    raise UnsupportedContent("This file is shown as pages, not as content.")
