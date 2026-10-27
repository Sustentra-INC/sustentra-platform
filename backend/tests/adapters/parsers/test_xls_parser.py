"""The Excel 97-2003 (.xls) reader: the same output as the .xlsx reader, and safe on hostile files.

The .xls files are written by ``_xls_builder`` (nothing among the dependencies writes the
format): a BIFF8 workbook in an OLE2 file, the records Excel saves.
"""

from __future__ import annotations

import struct
import time
from datetime import datetime
from datetime import time as clock
from pathlib import Path
from typing import Any

import pytest

openpyxl = pytest.importorskip("openpyxl")
pytest.importorskip("xlrd")

from backend.app.adapters.parsers import xls_parser  # noqa: E402
from backend.app.adapters.parsers.excel_parser import ExcelParser  # noqa: E402
from backend.app.adapters.parsers.xls_parser import XlsParser, column_letter, xls_worksheets  # noqa: E402
from backend.tests.adapters.parsers._parser_output_asserts import assert_parser_output_shape  # noqa: E402
from backend.tests.adapters.parsers._xls_builder import (  # noqa: E402
    ErrorCell,
    FormulaCell,
    biff_workbook,
    ole_file,
    xls_bytes,
)

REPO = Path(__file__).resolve().parents[4]
RELIABILITY_WORKBOOKS = sorted((REPO / "parser_reliability_test_set" / "raw_documents" / "excel").glob("*.xlsx"))


def _xls(tmp_path: Path, sheets: dict[str, list[list[Any]]], name: str = "log.xls", **options: Any) -> Path:
    path = tmp_path / name
    path.write_bytes(xls_bytes(sheets, **options))
    return path


def _xlsx(tmp_path: Path, sheets: dict[str, list[list[Any]]], name: str = "log.xlsx") -> Path:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                if isinstance(value, ErrorCell):  # openpyxl stores "#DIV/0!" as an error cell
                    value = xls_parser._ERROR_TEXT[value.code]
                if value is not None and value != "":
                    sheet.cell(row=r, column=c, value=value)
    path = tmp_path / name
    book.save(path)
    return path


def _sheets_of(xlsx: Path) -> dict[str, list[list[Any]]]:
    book = openpyxl.load_workbook(xlsx, data_only=True)
    return {sheet.title: [list(row) for row in sheet.iter_rows(min_row=1, min_col=1, values_only=True)]
            for sheet in book.worksheets}


def _cells(output: dict) -> list[tuple[str, str, str, str]]:
    """What a reviewer and the extractors see of each cell: sheet, cell, text, snippet."""

    texts = {block["block_id"]: block["text"] for block in output["text_blocks"]}
    return [(ref["sheet_name"], ref["cell_or_range"], texts[ref["parser_block_ids"][0]], ref["text_snippet"])
            for ref in output["source_references"]]


def _tables(output: dict) -> list[tuple[str, list[list[Any]]]]:
    """Tables without trailing empty cells and rows: openpyxl pads rows to the sheet's width."""

    def trimmed(row: list[Any]) -> list[Any]:
        while row and row[-1] is None:
            row = row[:-1]
        return row

    tables = []
    for table in output["tables"]:
        rows = [trimmed(row) for row in table["rows"]]
        while rows and not rows[-1]:
            rows.pop()
        tables.append((table["sheet_name"], rows))
    return tables


# --- the same output as the .xlsx reader --------------------------------------------------------
@pytest.mark.parametrize("workbook", RELIABILITY_WORKBOOKS, ids=lambda path: path.name)
def test_an_xls_reads_like_the_same_workbook_saved_as_xlsx(tmp_path: Path, workbook: Path) -> None:
    xls = _xls(tmp_path, _sheets_of(workbook))

    expected = ExcelParser().parse(workbook, document_id="DOC-1", processing_run_id="RUN-1")
    output = XlsParser().parse(xls, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == expected["status"] == "parsed"
    assert output["parser_name"] == "xlrd"
    assert _cells(output) == _cells(expected)
    assert _tables(output) == _tables(expected)
    assert [block["block_id"].replace("xlrd-", "openpyxl-", 1) for block in output["text_blocks"]] == [
        block["block_id"] for block in expected["text_blocks"]
    ]
    assert all(ref["source_kind"] == "excel_cell" for ref in output["source_references"])


def test_values_come_out_as_openpyxl_gives_them(tmp_path: Path) -> None:
    rows = [
        ["Delivered", "Gallons", "Price", "Metered", "Check", "Large", "Start", "Note"],
        [datetime(2025, 2, 10), 28100, 3.25, True, ErrorCell(0x07), 2**40, clock(8, 30), "Ünïcødé ✓"],
        [datetime(2025, 3, 1, 14, 5), -12, 0.1, False, ErrorCell(0x2A), 1e20, None, "  "],
    ]
    expected = ExcelParser().parse(_xlsx(tmp_path, {"Deliveries": rows}), "DOC-1", "RUN-1")
    output = XlsParser().parse(_xls(tmp_path, {"Deliveries": rows}), "DOC-1", "RUN-1")

    assert _cells(output) == _cells(expected)
    by_cell = {cell: text for _, cell, text, _ in _cells(output)}
    assert by_cell["A2"] == "2025-02-10T00:00:00" and by_cell["A3"] == "2025-03-01T14:05:00"
    assert by_cell["B2"] == "28100" and by_cell["C2"] == "3.25" and by_cell["F2"] == "1099511627776"
    assert by_cell["D2"] == "True" and by_cell["E2"] == "#DIV/0!" and by_cell["E3"] == "#N/A"
    assert by_cell["G2"] == "08:30:00" and "H3" not in by_cell  # a blank string is no cell
    assert output["tables"][0]["rows"][1][:3] == ["2025-02-10T00:00:00", 28100, 3.25]


def test_a_whitespace_only_cell_stays_in_the_table_row_like_xlsx(tmp_path: Path) -> None:
    # A whitespace-only cell is kept in the table row (so the grid lines up), with the same
    # value openpyxl keeps, but it is not a traceable block (no coordinate).
    rows = [["Gallons", "   ", 450]]  # the whitespace sits between two filled cells
    expected = ExcelParser().parse(_xlsx(tmp_path, {"S": rows}), "DOC-1", "RUN-1")
    output = XlsParser().parse(_xls(tmp_path, {"S": rows}), "DOC-1", "RUN-1")

    assert output["tables"][0]["rows"] == expected["tables"][0]["rows"] == [["Gallons", "   ", 450]]
    # The whitespace cell is in neither reader's blocks.
    assert [b["text"] for b in output["text_blocks"]] == [b["text"] for b in expected["text_blocks"]] == [
        "Gallons", "450"]


def test_a_workbook_in_the_1904_date_system_gives_the_same_dates(tmp_path: Path) -> None:
    # Old Excel for Mac counted days from 1 Jan 1904: the same date is a smaller serial number.
    for datemode in (0, 1):
        path = _xls(tmp_path, {"S": [[datetime(2025, 2, 10, 9, 15)]]}, name=f"dates{datemode}.xls", datemode=datemode)
        assert XlsParser().parse(path, "D", "R")["text_blocks"][0]["text"] == "2025-02-10T09:15:00"


def test_a_formula_is_its_saved_result_and_is_never_evaluated(tmp_path: Path) -> None:
    # The cell holds =1 with a saved result of 12.5: the reader gives what Excel saved.
    output = XlsParser().parse(_xls(tmp_path, {"S": [["Total", FormulaCell(12.5)]]}), "D", "R")
    assert [block["text"] for block in output["text_blocks"]] == ["Total", "12.5"]


def test_several_sheets_keep_their_names_and_order(tmp_path: Path) -> None:
    output = XlsParser().parse(_xls(tmp_path, {"2025 log": [["Gallons", 450]], "Notes": [[None, "Generator only"]]}),
                               "D", "R")
    assert [(sheet, cell) for sheet, cell, _, _ in _cells(output)] == [
        ("2025 log", "A1"), ("2025 log", "B1"), ("Notes", "B1")]
    assert [table["table_id"] for table in output["tables"]] == ["xlrd-2025 log-t1", "xlrd-Notes-t2"]


def test_an_empty_workbook_is_empty(tmp_path: Path) -> None:
    output = XlsParser().parse(_xls(tmp_path, {"Sheet1": [[None, ""]]}), "D", "R")
    assert_parser_output_shape(output)
    assert output["status"] == "empty"
    assert any(w["code"] == "empty_document" for w in output["warnings"])


def test_a_workbook_in_the_mini_stream_and_a_bare_biff_stream_are_read(tmp_path: Path) -> None:
    small = tmp_path / "small.xls"
    small.write_bytes(ole_file({"Workbook": biff_workbook({"S": [["Gallons", 450]]}, pad_to=0)}))
    assert [b["text"] for b in XlsParser().parse(small, "D", "R")["text_blocks"]] == ["Gallons", "450"]
    bare = tmp_path / "bare.xls"  # Excel 2-4 wrote the workbook stream with no OLE container
    bare.write_bytes(biff_workbook({"S": [["Gallons", 450]]}, pad_to=0))
    assert [b["text"] for b in XlsParser().parse(bare, "D", "R")["text_blocks"]] == ["Gallons", "450"]


def test_column_letters_are_openpyxl_s() -> None:
    from openpyxl.utils import get_column_letter

    assert [column_letter(i) for i in (0, 25, 26, 51, 255)] == ["A", "Z", "AA", "AZ", "IV"]
    assert all(column_letter(i) == get_column_letter(i + 1) for i in range(800))


# --- the name says .xls, the bytes say otherwise --------------------------------------------------
def test_an_xlsx_saved_with_an_xls_name_is_read_as_xlsx(tmp_path: Path) -> None:
    renamed = tmp_path / "renamed.xls"
    renamed.write_bytes(_xlsx(tmp_path, {"S": [["Gallons", 450]]}).read_bytes())
    output = XlsParser().parse(renamed, "D", "R")
    assert output["status"] == "parsed" and output["parser_name"] == "openpyxl"


@pytest.mark.parametrize("body", [
    b"<html><body><table><tr><td>Gallons</td><td>450</td></tr></table></body></html>",
    b'<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>',
    b"Gallons\t450\n",
    b"",
])
def test_a_web_page_or_text_export_named_xls_says_what_to_do(tmp_path: Path, body: bytes) -> None:
    path = tmp_path / "portal-export.xls"
    path.write_bytes(body)
    output = XlsParser().parse(path, "D", "R")
    assert_parser_output_shape(output)
    assert output["status"] == "failed"
    assert output["warnings"] == [{"code": "not_a_legacy_workbook", "severity": "error",
                                   "message": xls_parser.NOT_A_LEGACY_WORKBOOK}]


# --- hostile and damaged files --------------------------------------------------------------
def test_an_encrypted_workbook_is_refused_as_password_protected(tmp_path: Path) -> None:
    output = XlsParser().parse(_xls(tmp_path, {"S": [["Gallons", 450]]}, encrypted=True), "D", "R")
    assert output["status"] == "failed"
    assert [(w["code"], w["message"]) for w in output["warnings"]] == [
        ("password_protected", "This workbook is password-protected, so it could not be read. "
                               "Ask for a copy without a password.")]


def test_an_encrypted_xlsx_in_its_ole_wrapper_is_password_protected(tmp_path: Path) -> None:
    # Office saves a password-protected .xlsx as an OLE file holding the encrypted package.
    path = tmp_path / "locked.xls"
    path.write_bytes(ole_file({"EncryptionInfo": b"\x04\x00\x04\x00" + bytes(200), "EncryptedPackage": bytes(5000)}))
    output = XlsParser().parse(path, "D", "R")
    assert [w["code"] for w in output["warnings"]] == ["password_protected"]


def test_macros_are_noted_and_never_run(tmp_path: Path) -> None:
    output = XlsParser().parse(_xls(tmp_path, {"S": [["Gallons", 450]]}, macros=True), "D", "R")
    assert output["status"] == "parsed"
    assert {"code": "contains_macros", "severity": "info",
            "message": "The workbook contains macros. They were not run."} in output["warnings"]
    plain = XlsParser().parse(_xls(tmp_path, {"S": [["Gallons", 450]]}, name="plain.xls"), "D", "R")
    assert plain["warnings"] == []


@pytest.mark.parametrize("streams, looping", [
    ({"Workbook": "small"}, "Workbook"),
    ({"Workbook": "empty"}, "Workbook"),  # an empty stream's chain is followed too
    ({"Workbook": "empty", "Book": "small"}, "Book"),  # xlrd falls back from an empty Workbook to Book
], ids=["small_workbook", "empty_workbook", "book_after_empty_workbook"])
def test_a_looping_sector_chain_is_refused_before_xlrd_follows_it(tmp_path: Path, monkeypatch, streams: dict,
                                                                  looping: str) -> None:
    # xlrd follows a small stream's mini-sector chain without a loop check: it would never end.
    import xlrd

    def never(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("xlrd must not read a workbook whose sector chain loops")

    monkeypatch.setattr(xlrd, "open_workbook", never)
    body = {"small": biff_workbook({"S": [["a"] * 40]}, pad_to=0), "empty": b""}
    path = tmp_path / "loop.xls"
    path.write_bytes(ole_file({name: body[kind] for name, kind in streams.items()}, loop_mini_chain=looping))
    started = time.perf_counter()
    output = XlsParser().parse(path, "D", "R")
    assert time.perf_counter() - started < 1
    assert output["status"] == "failed"
    assert output["warnings"][0]["code"] == "workbook_load_failed"


@pytest.mark.parametrize("entries", [24, 40])
def test_a_directory_shaped_as_a_dag_is_refused_in_time(tmp_path: Path, entries: int) -> None:
    # Every entry is both siblings of the one before: xlrd's recursive tree builder, which
    # has no visited set, would make 2^N calls (24 entries took 10 s, 40 never finished).
    from backend.app.services.document_content_service import UnreadableContent, document_content

    path = tmp_path / "dag.xls"
    path.write_bytes(ole_file({"Workbook": biff_workbook({"S": [["Gallons", 450]]})},
                              tuple(f"S{n}" for n in range(entries)), dag=True))
    started = time.perf_counter()
    output = XlsParser().parse(path, "D", "R")
    assert output["status"] == "failed"
    assert output["warnings"][0]["code"] == "workbook_load_failed"
    assert "reached twice" in output["warnings"][0]["message"]
    with pytest.raises(UnreadableContent):  # the source pane is refused just as fast
        document_content(path)
    assert time.perf_counter() - started < 1


@pytest.mark.parametrize("damage", ["truncated", "garbage", "no_workbook_stream"])
def test_a_damaged_workbook_fails_cleanly(tmp_path: Path, damage: str) -> None:
    good = xls_bytes({"S": [["Gallons", 450]]})
    body = {
        "truncated": good[:700],
        "garbage": good[:8] + bytes(range(256)) * 8,
        "no_workbook_stream": ole_file({"Something else": bytes(5000)}),
    }[damage]
    path = tmp_path / "damaged.xls"
    path.write_bytes(body)
    output = XlsParser().parse(path, "D", "R")
    assert_parser_output_shape(output)
    assert output["status"] == "failed"
    assert output["warnings"][0]["code"] == "workbook_load_failed"


def test_a_sheet_that_cannot_be_read_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    def broken(book: Any):
        yield "S", iter([[1]])
        raise ValueError("bad sheet stream")

    monkeypatch.setattr(xls_parser, "xls_worksheets", broken)
    output = XlsParser().parse(_xls(tmp_path, {"S": [[1]], "T": [[2]]}), "D", "R")
    assert output["status"] == "failed"
    assert output["warnings"][0]["code"] == "workbook_load_failed"


def test_reading_is_bounded(tmp_path: Path, monkeypatch) -> None:
    sheets = {"A": [["a1", "b1"], ["a2", "b2"], ["a3", "b3"]], "B": [["x"]], "C": [["y"]]}
    path = _xls(tmp_path, sheets)

    monkeypatch.setattr(xls_parser, "MAX_XLS_CELLS", 3)
    output = XlsParser().parse(path, "D", "R")
    assert output["status"] == "partial"
    assert [text for _, _, text, _ in _cells(output)] == ["a1", "b1", "a2"]
    assert [w["code"] for w in output["warnings"]] == ["workbook_truncated"]
    assert "after 3 filled cells, in sheet 'A'" in output["warnings"][0]["message"]

    monkeypatch.setattr(xls_parser, "MAX_XLS_CELLS", 100)
    monkeypatch.setattr(xls_parser, "MAX_XLS_ROWS_PER_SHEET", 1)
    monkeypatch.setattr(xls_parser, "MAX_XLS_SHEETS", 2)
    output = XlsParser().parse(path, "D", "R")
    assert output["status"] == "partial"
    assert [(sheet, text) for sheet, _, text, _ in _cells(output)] == [("A", "a1"), ("A", "b1"), ("B", "x")]
    assert "after row 1 of sheet 'A'" in output["warnings"][0]["message"]
    assert "after 2 sheets" in output["warnings"][0]["message"]

    monkeypatch.setattr(xls_parser, "MAX_XLS_BYTES", 100)
    output = XlsParser().parse(path, "D", "R")
    assert output["status"] == "failed" and output["warnings"][0]["code"] == "file_too_large"


def test_each_sheet_is_dropped_once_read(tmp_path: Path) -> None:
    book, notes = xls_parser.open_xls(_xls(tmp_path, {"A": [["a", None, "  ", 2]], "B": [[], [None, "b"]]}))
    try:
        assert notes == []
        sheets = xls_worksheets(book, xls_parser.XlsBudget())
        name, rows = next(sheets)
        assert not book.sheet_loaded(0)  # nothing is loaded until its rows are read
        # Every cell whose type is not empty, by column: an empty cell is left out, but a
        # whitespace-only text cell is kept (as openpyxl keeps it in a table row).
        assert (name, list(rows)) == ("A", [[(0, "a"), (2, "  "), (3, 2)]])
        assert not book.sheet_loaded(0)
        assert [(name, list(rows)) for name, rows in sheets] == [("B", [[], [(1, "b")]])]
    finally:
        book.release_resources()


def _wide_rows(count: int) -> list[Any]:
    return [{255: 1.5} for _ in range(count)]  # one number per row, in the last column (IV)


def test_wide_sparse_sheets_are_read_in_bounded_time_and_size(tmp_path: Path) -> None:
    # One number per row in column IV makes every row 256 cells wide: 3 sheets of 20,000 such
    # rows used to be converted and stored in full (5 x 50,000 took 15 s and 915 MB).
    path = _xls(tmp_path, {f"S{n}": _wide_rows(20_000) for n in range(3)})
    started = time.perf_counter()
    output = XlsParser().parse(path, "D", "R")
    elapsed = time.perf_counter() - started
    assert elapsed < 3, elapsed
    assert output["status"] == "partial"
    assert sum(len(row) for table in output["tables"] for row in table["rows"]) <= xls_parser.MAX_XLS_TABLE_SLOTS
    assert "table cells" in output["warnings"][-1]["message"]
    # The pane looks at its 60 columns only, so it finds these rows empty, and fast.
    from backend.app.services.document_content_service import document_content

    started = time.perf_counter()
    assert document_content(path)["sheets"] == []
    assert time.perf_counter() - started < 3


@pytest.mark.parametrize("overlap_step", [None, 4], ids=["identical_offsets", "distinct_offsets"])
def test_sheets_that_point_at_the_same_records_are_refused(tmp_path: Path, overlap_step) -> None:
    # 100 BOUNDSHEET records into one 10,000-row sheet, at the same offset or distinct offsets
    # a few bytes apart, made xlrd read that sheet's records once per sheet (up to 100 times).
    # The span walk refuses them before any sheet is loaded, whatever the offsets.
    path = _xls(tmp_path, {"S": _wide_rows(10_000)}, shared_sheets=99, overlap_step=overlap_step)
    started = time.perf_counter()
    output = XlsParser().parse(path, "D", "R")
    assert time.perf_counter() - started < 2
    assert (output["status"], output["warnings"][0]["code"]) == ("failed", "workbook_load_failed")
    assert output["warnings"][0]["message"] == xls_parser.DAMAGED_SHEETS

    from backend.app.services.document_content_service import UnreadableContent, document_content

    with pytest.raises(UnreadableContent):
        document_content(path)


@pytest.mark.parametrize("shift", [0, 1])
def test_a_file_with_an_invalid_sector_size_fails_cleanly(tmp_path: Path, shift: int) -> None:
    # Sector shift 0 or 1 made ole.read_directory raise struct.error, which escaped _check_ole
    # and open_xls as a 500. It is now a clean workbook_load_failed.
    data = bytearray(_xls(tmp_path, {"S": [["Gallons", 450]]}).read_bytes())
    data[30:32] = struct.pack("<H", shift)
    path = tmp_path / "bad_sector.xls"
    path.write_bytes(data)
    output = XlsParser().parse(path, "D", "R")
    assert_parser_output_shape(output)
    assert (output["status"], output["warnings"][0]["code"]) == ("failed", "workbook_load_failed")


class _FakeBook:
    """Just the four attributes the span guard reads (xlrd 2.0.2 sets these once)."""

    def __init__(self, records_by_start: dict[int, bytes], base: int = 100, stream_len: int | None = None) -> None:
        self.base = base
        parts = {start: data for start, data in records_by_start.items()}
        end = max((start + len(data) for start, data in parts.items()), default=base)
        buffer = bytearray(end)
        for start, data in parts.items():
            buffer[start:start + len(data)] = data
        self.mem = bytes(buffer)
        self.stream_len = end - base if stream_len is None else stream_len
        self._sh_abs_posn = sorted(parts)


def _records(*records: tuple[int, bytes]) -> bytes:
    return b"".join(struct.pack("<HH", code, len(body)) + body for code, body in records)


_EOF = _records((0x000A, b""))
_SHEET = _records((0x0809, b"\x00" * 16), (0x0203, b"\x00" * 14)) + _EOF  # BOF, a cell, EOF


def test_the_span_guard_accepts_sound_sheets_and_refuses_damaged_ones() -> None:
    from backend.app.adapters.parsers.xls_parser import _check_sheet_spans

    sound = _FakeBook({100: _SHEET, 100 + len(_SHEET): _SHEET})
    _check_sheet_spans(sound)  # adjacent, non-overlapping: fine

    overlapping = _FakeBook({100: _SHEET, 104: _SHEET})  # second starts inside the first
    with pytest.raises(xls_parser.XlsError, match="damaged"):
        _check_sheet_spans(overlapping)

    # A record whose length reaches past the stream end (stream_len shorter than the records).
    runs_past = _FakeBook({100: _records((0x0809, b"\x00" * 16), (0x0203, b"\x00" * 200))}, stream_len=30)
    with pytest.raises(xls_parser.XlsError, match="damaged"):
        _check_sheet_spans(runs_past)

    out_of_range = _FakeBook({100: _SHEET})
    out_of_range._sh_abs_posn = [100, 99_999]
    with pytest.raises(xls_parser.XlsError, match="damaged"):
        _check_sheet_spans(out_of_range)


def test_loading_stops_once_enough_rows_are_loaded(tmp_path: Path, monkeypatch) -> None:
    # xlrd builds every row up to a sheet's last one when it loads it, empty or not.
    monkeypatch.setattr(xls_parser, "MAX_XLS_LOADED_ROWS", 3)
    rows: list[Any] = [[], [], ["a"]]
    output = XlsParser().parse(_xls(tmp_path, {"A": rows, "B": [["b"]], "C": [["c"]]}), "D", "R")
    assert output["status"] == "partial"
    assert [(sheet, text) for sheet, _, text, _ in _cells(output)] == [("A", "a")]
    assert output["warnings"][-1]["message"] == (
        "The workbook is larger than can be read here. Reading stopped before sheet 'B' (3 rows already loaded).")


def test_xlrd_writes_nothing_to_stdout(tmp_path: Path, capsys) -> None:
    XlsParser().parse(_xls(tmp_path, {"S": [["Gallons", 450]]}), "D", "R")
    XlsParser().parse(_xls(tmp_path, {"S": [["a"]]}, name="locked.xls", encrypted=True), "D", "R")
    assert capsys.readouterr().out == ""
