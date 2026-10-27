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

- an OLE2 compound file goes to xlrd, after a structural check (below);
- a zip is an ``.xlsx`` saved with the wrong name and goes to ``openpyxl``;
- a bare BIFF2-4 stream (Excel 2.x to 4.0) goes to xlrd;
- anything else (a web page, XML or text export named ``.xls``) is refused with what to do.

An encrypted workbook (a FILEPASS record, or an encrypted ``.xlsx`` in its OLE wrapper)
is refused as ``password_protected``. The work is bounded: the file size, the sheets read,
the rows read per sheet and the cells read are capped, a sheet is loaded only when it is
read and dropped after, and xlrd's diagnostics are discarded rather than buffered.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_failed_parser_output,
    build_warning,
)
from backend.app.adapters.parsers.excel_parser import (
    ExcelParser,
    Sheet,
    _coerce_cell_value,
    _is_blank,
    parser_output_from_sheets,
)

PARSER_NAME = "xlrd"

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP_SIGNATURE = b"PK\x03\x04"
# The BOF record that opens a bare BIFF2, 3, 4 or 5-8 stream.
_BIFF_BOF_RECORDS = {b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08"}

MAX_XLS_BYTES = 32 * 1024 * 1024  # above the 25 MB upload limit; a larger file is not opened
MAX_XLS_SHEETS = 100
MAX_XLS_ROWS_PER_SHEET = 50_000  # BIFF8 itself stops at 65,536
MAX_XLS_CELLS = 250_000  # non-empty cells read from the whole workbook

# OLE storage and stream names (compared lowercased).
_VBA_NAMES = {"_vba_project_cur", "_vba_project"}  # Excel keeps its VBA project in _VBA_PROJECT_CUR
_ENCRYPTED_PACKAGE_NAMES = {"encryptedpackage", "encryptioninfo"}  # a password-protected .xlsx

# xlrd's cell types (xlrd.XL_CELL_*) and error codes (xlrd.error_text_from_code), here so
# reading a value does not import xlrd.
_TEXT, _NUMBER, _DATE, _BOOLEAN, _ERROR = 1, 2, 3, 4, 5
_ERROR_TEXT = {0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!", 0x17: "#REF!", 0x1D: "#NAME?",
               0x24: "#NUM!", 0x2A: "#N/A"}

NOT_A_LEGACY_WORKBOOK = (
    "This .xls is not an Excel 97-2003 workbook (it looks like a web page or text export). "
    "Open it in Excel and save it as .xlsx, or export it as CSV."
)
PASSWORD_PROTECTED = (
    "This workbook is password-protected, so it could not be read. "
    "Ask for a copy without a password."
)
CONTAINS_MACROS = "The workbook contains macros. They were not run."


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
    return book, notes


def _check_ole(data: bytes) -> bool:
    """Check the OLE2 container before xlrd reads the workbook stream; return whether it
    holds a VBA project.

    xlrd follows a small stream's chain through the mini-stream allocation table without
    checking for a loop, so a chain that loops would never end. That chain is walked here
    first, with a bound. An encrypted ``.xlsx`` (an OLE file holding ``EncryptedPackage``)
    is password-protected rather than damaged.
    """

    from xlrd import compdoc

    try:
        document = compdoc.CompDoc(data, logfile=_Discard())
    except Exception as exc:  # noqa: BLE001 - CompDocError, or asserts/recursion on a damaged directory
        raise XlsError("workbook_load_failed", f"Could not open workbook: {type(exc).__name__}.") from exc

    names = {str(node.name).lower() for node in document.dirlist}
    if names & _ENCRYPTED_PACKAGE_NAMES:
        raise XlsError("password_protected", PASSWORD_PROTECTED)

    top_level = [document.dirlist[index] for index in document.dirlist[0].children]
    for wanted in ("workbook", "book"):  # the streams xlrd looks for, in its order
        stream = next((node for node in top_level if str(node.name).lower() == wanted), None)
        if stream is None:
            continue
        if stream.etype == 2 and 0 < stream.tot_size < document.min_size_std_stream:
            mini_table = document.SSAT
            sector, steps = stream.first_SID, 0
            while sector >= 0:
                steps += 1
                if sector >= len(mini_table) or steps > len(mini_table):
                    raise XlsError("workbook_load_failed", "Could not open workbook: its sector chain is damaged.")
                sector = mini_table[sector]
        break
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


def xls_worksheets(book: Any) -> Iterator[tuple[str, Iterator[list[Any]]]]:
    """Each worksheet's name and its rows of values (list index = column). A sheet is
    loaded when its rows are first read and unloaded when they are done."""

    for index, name in enumerate(book.sheet_names()):
        yield str(name), _worksheet_rows(book, index)


def _worksheet_rows(book: Any, index: int) -> Iterator[list[Any]]:
    sheet = book.sheet_by_index(index)
    try:
        for row in range(sheet.nrows):
            yield [
                xls_cell_value(cell_type, value, book.datemode)
                for cell_type, value in zip(sheet.row_types(row), sheet.row_values(row))
            ]
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


def _with_coordinates(worksheets: Iterator[tuple[str, Iterator[list[Any]]]]) -> Iterator[Sheet]:
    for name, rows in worksheets:
        yield name, (
            [(None if _is_blank(value) else f"{column_letter(column)}{row + 1}", value)
             for column, value in enumerate(values)]
            for row, values in enumerate(rows)
        )


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

        try:
            output = parser_output_from_sheets(
                _with_coordinates(xls_worksheets(book)),
                parser_name=self.parser_name,
                document_id=document_id,
                processing_run_id=processing_run_id,
                warnings=notes,
                max_sheets=MAX_XLS_SHEETS,
                max_rows_per_sheet=MAX_XLS_ROWS_PER_SHEET,
                max_cells=MAX_XLS_CELLS,
            )
        except Exception as exc:  # noqa: BLE001 - a damaged sheet stream
            return self._failed("workbook_load_failed", f"Could not read workbook: {type(exc).__name__}.",
                                document_id, processing_run_id)
        finally:
            book.release_resources()
        return output

    def _failed(self, code: str, message: str, document_id: str, processing_run_id: str) -> dict:
        return build_failed_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            warnings=[build_warning(code, message, severity="error")],
        )
