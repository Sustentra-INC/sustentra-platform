"""Excel 97-2003 (``.xls``) workbook parser adapter.

Reads a BIFF workbook's cell values with ``xlrd`` (pure Python, BSD licence) and builds
the same ``parser_output`` as the ``.xlsx`` reader (``excel_parser.parser_output_from_sheets``):
one text block and ``excel_cell`` source reference per non-empty cell, coordinates like
"D2", one table per sheet. Values are converted to what ``openpyxl`` gives for the same
cell of an ``.xlsx``: a whole number is an int (28100, not 28100.0), a date is ISO 8601,
an error cell is its text ("#DIV/0!").

Nothing in the file is ever run. xlrd reads the values Excel last saved: a formula is
its cached result, and macros (VBA or Excel 4.0 sheets) are never read or evaluated. A
workbook that carries a VBA project gets a ``contains_macros`` note.

Legacy file names often lie, so the first bytes decide:

- an OLE2 compound file goes to xlrd, after its container is checked (``ole.py``: a
  directory shaped to make xlrd recurse 2^N times, or a sector chain that loops, is refused);
- a zip is an ``.xlsx`` saved with the wrong name and goes to ``openpyxl``;
- a bare BIFF2-4 stream (Excel 2.x to 4.0) goes to xlrd;
- anything else (a web page, XML or text export named ``.xls``) is refused with what to do.

An encrypted workbook (a FILEPASS record, or an encrypted ``.xlsx`` in its OLE wrapper)
is refused as ``password_protected``.

The work is bounded whatever the file holds. xlrd builds a whole sheet when it loads one
(every row up to the last one used, each as wide as its last cell), so before a sheet is
loaded the rows already loaded are counted against ``MAX_XLS_LOADED_ROWS``; sheets whose
records share or overlap the same data are refused; only filled cells are converted; and
the parser output's cells, rows, sheets and table slots (padding included) are capped. A
sheet is dropped once read, and xlrd's diagnostics are discarded rather than buffered.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from pathlib import Path
from struct import unpack
from typing import Any

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_failed_parser_output,
    build_warning,
)
from backend.app.adapters.parsers.excel_parser import (
    ExcelParser,
    Sheet,
    SheetCell,
    _coerce_cell_value,
    _is_blank,
    parser_output_from_sheets,
)
from backend.app.adapters.parsers.ole import OleError, read_directory

PARSER_NAME = "xlrd"

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_SIGNATURE = b"PK\x03\x04"
# The BOF record that opens a bare BIFF2, 3, 4 or 5-8 stream.
_BIFF_BOF_RECORDS = {b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08"}
_XL_EOF = 0x000A  # the BIFF record that ends a substream

MAX_XLS_BYTES = 32 * 1024 * 1024  # above the 25 MB upload limit; a larger file is not opened
MAX_XLS_SHEETS = 100
MAX_XLS_ROWS_PER_SHEET = 50_000  # BIFF8 itself stops at 65,536
MAX_XLS_LOADED_ROWS = 200_000  # rows xlrd builds, empty ones included, in the whole workbook
MAX_XLS_TABLE_SLOTS = 2_000_000  # table cells kept, empty padding included
MAX_XLS_CELLS = 100_000  # non-empty cells read from the whole workbook

# OLE storage and stream names (compared lowercased).
_VBA_NAMES = {"_vba_project_cur", "_vba_project"}  # Excel keeps its VBA project in _VBA_PROJECT_CUR
_ENCRYPTED_PACKAGE_NAMES = {"encryptedpackage", "encryptioninfo"}  # a password-protected .xlsx
_WORKBOOK_STREAMS = {"workbook", "book"}  # the streams xlrd reads, either of which it may fall back to

# xlrd's cell types (xlrd.XL_CELL_*) and error codes (xlrd.error_text_from_code), here so
# reading a value does not import xlrd.
_TEXT, _NUMBER, _DATE, _BOOLEAN, _ERROR, _BLANK = 1, 2, 3, 4, 5, 6
_ERROR_TEXT = {0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!", 0x17: "#REF!", 0x1D: "#NAME?",
               0x24: "#NUM!", 0x2A: "#N/A"}
_FILLED = re.compile(rb"[^\x00\x06]")  # a cell whose type is neither empty nor blank

NOT_A_LEGACY_WORKBOOK = (
    "This .xls is not an Excel 97-2003 workbook (it looks like a web page or text export). "
    "Open it in Excel and save it as .xlsx, or export it as CSV."
)
PASSWORD_PROTECTED = (
    "This workbook is password-protected, so it could not be read. "
    "Ask for a copy without a password."
)
CONTAINS_MACROS = "The workbook contains macros. They were not run."
DAMAGED_SHEETS = "Could not read workbook: its sheets share or overlap the same data, so it is damaged."


class XlsError(ValueError):
    """The workbook cannot be read; ``code`` is the parser warning code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Discard(io.TextIOBase):
    """xlrd writes diagnostics to a log file (stdout by default). Drop them: a hostile file
    could make it write one per record."""

    def write(self, text: str) -> int:
        return len(text)


class XlsBudget:
    """What reading one workbook may still load. ``stopped`` says where loading stopped."""

    def __init__(self) -> None:
        self.rows_left = MAX_XLS_LOADED_ROWS
        self.stopped: str | None = None


def is_zip(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(ZIP_SIGNATURE)) == ZIP_SIGNATURE


def open_xls(path: Path) -> tuple[Any, list[dict[str, str]]]:
    """Open a BIFF workbook with xlrd, sheets loaded on demand; also return its notes
    (``contains_macros``). The caller must ``release_resources()`` the book.

    Raises ``XlsError`` when the file is too large, not a BIFF workbook, encrypted or damaged.
    """

    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - xlrd is a pinned dependency
        raise XlsError("missing_dependency", "xlrd is not installed; cannot parse Excel 97-2003 workbook.") from exc

    if path.stat().st_size > MAX_XLS_BYTES:
        raise XlsError("file_too_large", f"The workbook is larger than {MAX_XLS_BYTES // (1024 * 1024)} MB.")
    data = path.read_bytes()
    notes: list[dict[str, str]] = []
    if data.startswith(OLE_SIGNATURE):
        if _check_ole(data):
            notes.append(build_warning("contains_macros", CONTAINS_MACROS, severity="info"))
    elif data[:2] not in _BIFF_BOF_RECORDS:
        raise XlsError("not_a_legacy_workbook", NOT_A_LEGACY_WORKBOOK)

    try:
        book = xlrd.open_workbook(
            file_contents=data,
            logfile=_Discard(),
            on_demand=True,  # one sheet in memory at a time
            ragged_rows=True,  # rows are not padded to the widest row
            formatting_info=False,
        )
    except xlrd.XLRDError as exc:
        if "encrypted" in str(exc).lower():
            raise XlsError("password_protected", PASSWORD_PROTECTED) from exc
        raise XlsError("workbook_load_failed", f"Could not open workbook: {type(exc).__name__}.") from exc
    except Exception as exc:  # noqa: BLE001 - xlrd asserts and indexes freely on damaged files
        raise XlsError("workbook_load_failed", f"Could not open workbook: {type(exc).__name__}.") from exc
    try:
        _check_sheet_spans(book)
    except XlsError:
        book.release_resources()
        raise
    return book, notes


def _check_sheet_spans(book: Any) -> None:
    """Refuse sheets whose record spans overlap, so xlrd cannot be made to read the same
    records once per sheet. Each sheet's records are walked here, header only (4 bytes, body
    skipped), from its BOUNDSHEET offset to its EOF. The spans partition the workbook stream
    when the file is sound, so the total bytes walked are bounded by the stream; a span that
    overlaps another, or runs past the stream, is damaged.

    This reads only ``mem``, ``base``, ``stream_len`` and ``_sh_abs_posn`` -- set once when the
    globals are parsed and never reset by a sheet load (unlike ``_position``)."""

    mem = getattr(book, "mem", None)
    starts = getattr(book, "_sh_abs_posn", None)
    base = getattr(book, "base", None)
    stream_len = getattr(book, "stream_len", None)
    if mem is None or not starts or not isinstance(base, int) or not isinstance(stream_len, int):
        return  # not the xlrd 2.0.2 layout: leave the row-count cap as the only bound
    end_bound = min(base + stream_len, len(mem))
    budget = stream_len + 4 * (len(starts) + 1)  # bytes we may walk: the stream, plus one header per sheet
    spans: list[tuple[int, int]] = []
    for start in starts:
        if not base <= start < end_bound:
            raise XlsError("workbook_load_failed", DAMAGED_SHEETS)
        pos = start
        while pos + 4 <= end_bound:
            code, length = unpack("<HH", mem[pos:pos + 4])
            pos += 4 + length
            budget -= 4 + length
            if budget < 0 or pos > end_bound:
                raise XlsError("workbook_load_failed", DAMAGED_SHEETS)
            if code == _XL_EOF:
                break
        spans.append((start, pos))
    reach = base
    for start, stop in sorted(spans):
        if start < reach:  # this sheet begins inside an earlier sheet's records
            raise XlsError("workbook_load_failed", DAMAGED_SHEETS)
        reach = stop


def _check_ole(data: bytes) -> bool:
    """Check the OLE2 container before xlrd reads it (``ole.read_directory``: the directory
    tree and every chain walked once); return whether it holds a VBA project.

    The workbook streams' chains are checked too: xlrd follows a small stream's chain (an
    empty one included) through the mini allocation table without a loop check, and falls
    back from an empty ``Workbook`` to ``Book``. An encrypted ``.xlsx`` (an OLE file holding
    ``EncryptedPackage``) is password-protected rather than damaged.
    """

    try:
        directory = read_directory(data)
        names = directory.names()
        if names & _ENCRYPTED_PACKAGE_NAMES:
            raise XlsError("password_protected", PASSWORD_PROTECTED)
        for entry in directory.top_level:
            if entry.kind == 2 and entry.name.lower() in _WORKBOOK_STREAMS:
                directory.check_chain(entry)
    except XlsError:
        raise
    except OleError as exc:
        raise XlsError("workbook_load_failed", f"Could not open workbook: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - a crafted header can still trip struct/index before a check
        raise XlsError("workbook_load_failed", f"Could not open workbook: {type(exc).__name__}.") from exc
    return bool(names & _VBA_NAMES)


def xls_cell_value(cell_type: int, value: Any, datemode: int) -> str | int | float | bool | None:
    """An xlrd cell as ``openpyxl`` gives the same cell of an ``.xlsx``, then coerced the
    same way (``excel_parser._coerce_cell_value``)."""

    if cell_type == _TEXT:
        return str(value)
    if cell_type == _NUMBER:
        return _number(value)
    if cell_type == _DATE:
        from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, from_excel

        try:
            return _coerce_cell_value(from_excel(value, MAC_EPOCH if datemode else WINDOWS_EPOCH))
        except (OverflowError, ValueError, TypeError):
            return _number(value)
    if cell_type == _BOOLEAN:
        return bool(value)
    if cell_type == _ERROR:
        return _ERROR_TEXT.get(value, "#N/A")
    return None  # empty or blank


def _number(value: Any) -> int | float:
    # BIFF stores every number as a float; an .xlsx stores 28100 as an integer.
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    return value


# A row as the readers take it: its filled cells, as (0-based column, value), left to right.
FilledCells = list[tuple[int, Any]]


def xls_worksheets(book: Any, budget: XlsBudget, *, max_columns: int | None = None
                   ) -> Iterator[tuple[str, Iterator[FilledCells]]]:
    """Each worksheet's name and its rows, every row (empty ones too) as its filled cells,
    only the first ``max_columns`` looked at. A sheet is loaded when its rows are first
    read and unloaded when they are done; once ``budget`` has no rows left, no further
    sheet is loaded."""

    for index, name in enumerate(book.sheet_names()):
        yield str(name), _worksheet_rows(book, index, str(name), budget, max_columns)


def _worksheet_rows(book: Any, index: int, name: str, budget: XlsBudget, max_columns: int | None
                    ) -> Iterator[FilledCells]:
    if budget.rows_left <= 0:
        budget.stopped = budget.stopped or f"before sheet '{name}' ({MAX_XLS_LOADED_ROWS} rows already loaded)"
        return
    sheet = book.sheet_by_index(index)
    try:
        budget.rows_left -= sheet.nrows
        for row in range(sheet.nrows):
            types = sheet.row_types(row, 0, max_columns).tobytes()
            if not _FILLED.search(types):
                yield []
                continue
            values = sheet.row_values(row, 0, max_columns)
            cells: FilledCells = []
            for match in _FILLED.finditer(types):
                column = match.start()
                value = xls_cell_value(types[column], values[column], book.datemode)
                # A whitespace-only text cell is kept in the table row (``openpyxl`` keeps "  "),
                # but ``_positional`` gives it no coordinate, so it is not a block.
                cells.append((column, value))
            yield cells
    finally:
        book.unload_sheet(index)


def column_letter(index: int) -> str:
    """0 -> "A", 25 -> "Z", 26 -> "AA", as openpyxl names columns."""

    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


_NO_CELL: SheetCell = (None, None)


def _positional(row: int, cells: FilledCells) -> list[SheetCell]:
    """A row for the shared builder: list index = column, up to its last filled cell."""

    if not cells:
        return []
    slots = [_NO_CELL] * (cells[-1][0] + 1)
    for column, value in cells:
        coordinate = None if _is_blank(value) else f"{column_letter(column)}{row + 1}"
        slots[column] = (coordinate, value)
    return slots


def _with_coordinates(worksheets: Iterator[tuple[str, Iterator[FilledCells]]]) -> Iterator[Sheet]:
    for name, rows in worksheets:
        yield name, (_positional(row, cells) for row, cells in enumerate(rows))


class XlsParser:
    """Adapter that normalizes ``.xls`` workbooks into ``parser_output`` dicts."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def __init__(self, excel_parser: ExcelParser | None = None) -> None:
        self._excel_parser = excel_parser or ExcelParser()

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)
        if is_zip(path):  # an .xlsx saved with an .xls name
            return self._excel_parser.parse(path, document_id, processing_run_id)

        try:
            book, notes = open_xls(path)
        except XlsError as exc:
            return self._failed(exc.code, exc.message, document_id, processing_run_id)

        budget = XlsBudget()
        try:
            output = parser_output_from_sheets(
                _with_coordinates(xls_worksheets(book, budget)),
                parser_name=self.parser_name,
                document_id=document_id,
                processing_run_id=processing_run_id,
                warnings=notes,
                max_sheets=MAX_XLS_SHEETS,
                max_rows_per_sheet=MAX_XLS_ROWS_PER_SHEET,
                max_cells=MAX_XLS_CELLS,
                max_table_slots=MAX_XLS_TABLE_SLOTS,
            )
        except XlsError as exc:
            return self._failed(exc.code, exc.message, document_id, processing_run_id)
        except Exception as exc:  # noqa: BLE001 - a damaged sheet stream
            return self._failed("workbook_load_failed", f"Could not read workbook: {type(exc).__name__}.",
                                document_id, processing_run_id)
        finally:
            book.release_resources()
        if budget.stopped:
            output["warnings"].append(build_warning(
                "workbook_truncated",
                f"The workbook is larger than can be read here. Reading stopped {budget.stopped}.",
            ))
            if output["status"] == "parsed":
                output["status"] = "partial"
        return output

    def _failed(self, code: str, message: str, document_id: str, processing_run_id: str) -> dict:
        return build_failed_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            warnings=[build_warning(code, message, severity="error")],
        )
