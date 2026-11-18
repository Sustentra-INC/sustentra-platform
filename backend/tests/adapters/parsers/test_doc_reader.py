"""The Word 97-2003 (.doc) reader: the main text, its paragraphs and tables, and safe on hostile files.

Documents are written by ``_doc_builder`` (nothing among the dependencies writes the format), plus one
written by macOS ``textutil`` from the HTML beside it, to catch a builder and a reader that share a
misreading of the format. Hostile tests change the builder's streams before the compound file is written.
"""

from __future__ import annotations

import random
import struct
import time
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from backend.app.adapters.parsers import doc_reader, xls_parser
from backend.app.adapters.parsers.doc_reader import DocError, read_doc
from backend.app.adapters.parsers.ole import OleFile
from backend.tests.adapters.parsers._doc_builder import (
    CB_FCLCB_AT,
    CCP_TEXT_AT,
    CLX_AT,
    CSW_AT,
    FC_COMPRESSED,
    FKP_SIZE,
    PLC_BTE_PAPX_AT,
    TEXT_START,
    Table,
    doc_bytes,
    doc_streams,
    field,
)
from backend.tests.adapters.parsers._ole_builder import Tree, ole_tree
from backend.tests.adapters.parsers._timing import budget
from backend.tests.adapters.parsers._xls_builder import xls_bytes

FIXTURE = Path(__file__).parent / "data" / "textutil_bill.doc"
BILL = ["Acme Gas Company", "Account Number: 12-345", "Service: Natural Gas", "See your bill online.",
        "Month\tTherms", "January\t120", "\t5", "Total Usage: 125 therms – café"]
BODY: list[str | Table] = ["Acme Gas", "Account Number: 12-345\x0bService: Natural Gas",
                           Table([["Month", "Therms"], ["January", "120"], ["", "5"], ["Two\rparas", "x"]]),
                           "Total"]
LINES = ["Acme Gas", "Account Number: 12-345", "Service: Natural Gas", "Month\tTherms", "January\t120", "\t5",
         "Two paras\tx", "Total"]


def _lines(body: list[str | Table], **options: Any) -> list[str]:
    return read_doc(doc_bytes(body, **options)).text.split("\n")


def _refused(data: bytes) -> DocError:
    with pytest.raises(DocError) as caught:
        read_doc(data)
    return caught.value


def _damaged(data: bytes) -> None:
    refusal = _refused(data)
    assert (refusal.code, refusal.message) == ("doc_load_failed", doc_reader.DAMAGED_DOCUMENT)
    # A guard in the reader refused it: the catch-all in read_doc would have chained what it caught.
    assert refusal.__cause__ is None, repr(refusal.__cause__)


def _bytes(tree: Tree, stream: str) -> bytes:
    content = tree[stream]
    assert isinstance(content, bytes)
    return content


def _poke(tree: Tree, stream: str, offset: int, layout: str, *values: int) -> Tree:
    data = bytearray(_bytes(tree, stream))
    struct.pack_into(layout, data, offset, *values)
    tree[stream] = bytes(data)
    return tree


# --- reading what Word writes -------------------------------------------------------------------
def test_a_document_word_wrote_reads_as_word_shows_it() -> None:
    document = read_doc(FIXTURE.read_bytes())

    assert document.text.split("\n") == BILL
    assert document.notes == []


def test_paragraphs_line_breaks_and_tables() -> None:
    assert _lines(BODY) == LINES


def test_a_fast_saved_document_is_read_in_piece_order() -> None:
    body = [*BODY, "Café – ‘quoted’ 5 m³"]

    assert _lines(body, pieces=5, shuffle=True, compressed="mixed") == [*LINES, "Café – ‘quoted’ 5 m³"]


def test_pieces_in_either_encoding_decode_alike() -> None:
    body: list[str | Table] = ["Ωmega ≥ 5 – ‘x’", Table([["é", "€"]]), "ɐ"]
    expected = ["Ωmega ≥ 5 – ‘x’", "é\t€", "ɐ"]

    for options in ({}, {"compressed": True}, {"compressed": "mixed", "pieces": 4}, {"pieces": 6, "shuffle": True}):
        assert _lines(body, **options) == expected, options


def test_prc_entries_before_the_piece_table_are_skipped() -> None:
    assert _lines(BODY, prcs=3, pieces=2) == LINES


def test_field_results_are_read_and_codes_are_not() -> None:
    assert _lines(["Page " + field("PAGE", "1") + " of " + field("NUMPAGES", "3")]) == ["Page 1 of 3"]
    assert _lines(["See " + field('HYPERLINK "https://x.example"', "the portal")]) == ["See the portal"]
    assert _lines([field('XE "gas"', None) + "Indexed"]) == ["Indexed"]
    nested = "Total " + field("=SUM(ABOVE)", field("MERGEFIELD Usage", "120") + " therms")
    assert _lines([nested]) == ["Total 120 therms"]
    assert _lines(["a\x15b\x14c"]) == ["abc"]


def test_an_unclosed_field_hides_only_what_follows_it_and_an_extra_end_hides_nothing() -> None:
    assert _lines(["shown \x13hidden", "also hidden"]) == ["shown ", ""]
    assert _lines(["a\x15\x15b", "c"]) == ["ab", "c"]


def test_special_characters() -> None:
    assert _lines(["co\x1eop re\x1fad\xa0now\x01\x08"]) == ["co-op read now"]
    assert _lines(["page one\x0cpage two"]) == ["page one", "page two"]
    assert _lines(["col\x0eumn"]) == ["col", "umn"]
    assert _lines(["a\tb"]) == ["a\tb"]
    assert _lines([Table([["x\x0by", "z"]])]) == ["x y\tz"]


def test_characters_beyond_the_basic_plane_do_not_shift_the_table() -> None:
    # Each emoji is two UTF-16 code units. If the text were counted in characters, the cell marks after
    # these ten would be looked up two bytes early each, outside the table's paragraphs, and the cell
    # that holds two paragraphs would break apart.
    body: list[str | Table] = ["😀" * 10, Table([["one\rtwo", "x😀"]]), "end"]

    assert _lines(body) == ["😀" * 10, "one two\tx😀", "end"]
    assert _lines(body, pieces=3, shuffle=True) == ["😀" * 10, "one two\tx😀", "end"]


def test_a_lone_surrogate_becomes_a_replacement_character() -> None:
    assert _lines(["a\ud800b", "c\udc00"]) == ["a�b", "c�"]


# --- refusals ------------------------------------------------------------------------------------
def test_a_password_protected_document_is_refused() -> None:
    refusal = _refused(doc_bytes(BODY, encrypted=True))

    assert (refusal.code, refusal.message) == ("password_protected", xls_parser.PASSWORD_PROTECTED)
    assert refusal.__cause__ is None


def test_an_encrypted_docx_in_its_ole_wrapper_is_password_protected() -> None:
    data = ole_tree({"EncryptionInfo": b"\x04\x00\x04\x00" + bytes(200), "EncryptedPackage": bytes(5000)})

    refusal = _refused(data)

    assert (refusal.code, refusal.message) == ("password_protected", xls_parser.PASSWORD_PROTECTED)


@pytest.mark.parametrize("nfib", [0x0068, 0x0065])
def test_word_95_and_earlier_are_refused_plainly(nfib: int) -> None:
    refusal = _refused(doc_bytes(BODY, nfib=nfib))

    assert (refusal.code, refusal.message) == ("old_word_document", doc_reader.OLD_WORD_DOCUMENT)


def test_an_ole_file_that_is_not_word_is_refused() -> None:
    refusal = _refused(xls_bytes({"S": [["a"]]}))

    assert (refusal.code, refusal.message) == ("not_a_word_document", doc_reader.NOT_A_WORD_DOCUMENT)


@pytest.mark.parametrize("data", [b"", b"just text", b"PK\x03\x04" + bytes(600)])
def test_bytes_that_are_not_a_compound_file_are_not_a_word_document(data: bytes) -> None:
    refusal = _refused(data)

    assert (refusal.code, refusal.message) == ("not_a_word_document", doc_reader.NOT_A_WORD_DOCUMENT)


def test_a_stream_that_does_not_start_like_word_is_not_a_word_document() -> None:
    tree = _poke(doc_streams(BODY), "WordDocument", 0, "<H", 0x1234)

    assert _refused(ole_tree(tree)).code == "not_a_word_document"


def test_a_document_missing_its_table_stream_is_damaged() -> None:
    tree = doc_streams(BODY)  # its FIB names 1Table
    tree["0Table"] = tree.pop("1Table")

    _damaged(ole_tree(tree))


def test_the_table_stream_is_the_one_the_fib_names() -> None:
    assert _lines(BODY, table_stream="0Table") == LINES


def test_a_compound_file_cut_short_is_damaged() -> None:
    _damaged(doc_bytes(BODY)[:700])


def test_an_unforeseen_error_is_reported_as_damage_and_keeps_its_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(word: bytes) -> None:
        raise RecursionError

    monkeypatch.setattr(doc_reader, "_fib", explode)

    refusal = _refused(doc_bytes(BODY))

    assert (refusal.code, refusal.message) == ("doc_load_failed", doc_reader.DAMAGED_DOCUMENT)
    assert isinstance(refusal.__cause__, RecursionError)
    assert "Recursion" not in refusal.message


def test_macros_are_noted_not_run() -> None:
    document = read_doc(doc_bytes(BODY, macros=True))

    assert document.notes == [("contains_macros", doc_reader.CONTAINS_MACROS)]
    assert document.text.split("\n") == LINES


def test_the_word_document_stream_is_read_before_the_table_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    # In a file whose chains cross, the stream read second is the one OleFile refuses.
    read: list[str] = []
    real = OleFile.read

    def recording(self: OleFile, entry: Any) -> bytes:
        read.append(entry.name)
        return real(self, entry)

    monkeypatch.setattr(OleFile, "read", recording)

    read_doc(doc_bytes(BODY))

    assert read == ["WordDocument", "1Table"]


# --- tables --------------------------------------------------------------------------------------
def test_tables_without_paragraph_properties_fall_back_to_cell_marks() -> None:
    assert _lines([Table([["a", "b"], ["c", "d"]])], papx=False) == ["a\tb", "c\td"]
    assert _lines(["before", Table([["", "5"], ["x", ""]]), "after"], papx=False) == ["before", "\t5", "x", "after"]


def test_a_table_with_no_row_end_mark_is_flushed_at_the_next_paragraph() -> None:
    document = doc_streams(["Before", Table([["a", "b"]]), "After"])
    # Turn the row-end mark (the last \x07 of the table) into an object anchor: no mark ends the row.
    word = bytearray(_bytes(document, "WordDocument"))
    at = bytes(word).index("Before\ra\x07b\x07\x07After\r".encode("utf-16-le")) + 2 * len("Before\ra\x07b\x07")
    word[at:at + 2] = b"\x01\x00"
    document["WordDocument"] = bytes(word)

    assert read_doc(ole_tree(document)).text.split("\n") == ["Before", "a\tb", "After"]


def test_a_table_cut_off_by_the_character_count_is_flushed_at_the_end() -> None:
    tree = doc_streams(["Before", Table([["a", "b"], ["c", "d"]])])
    cut = len("Before\ra\x07b\x07\x07c\x07")  # inside the second row

    _poke(tree, "WordDocument", CCP_TEXT_AT, "<i", cut)

    assert read_doc(ole_tree(tree)).text.split("\n") == ["Before", "a\tb", "c"]


def test_the_text_of_a_cell_with_paragraphs_and_a_line_break_is_one_line() -> None:
    assert _lines([Table([["a\x0bb\rc", "d"]])]) == ["a b c\td"]


def test_a_row_of_empty_cells_is_not_a_line() -> None:
    assert _lines([Table([["", ""], ["x", ""]])]) == ["x\t"]


def _papx_page(tree: Tree) -> int:
    """The offset in WordDocument of the first PapxFkp page."""

    plc_at, plc_size = struct.unpack_from("<II", _bytes(tree, "WordDocument"), PLC_BTE_PAPX_AT)
    (number,) = struct.unpack_from("<I", _bytes(tree, "1Table"), plc_at + 4 * ((plc_size - 4) // 8 + 1))
    return number * FKP_SIZE


def _row_end_document(grpprl: bytes, after: bytes = b"") -> bytes:
    """Two one-cell rows whose row-end PapxInFkp is replaced by ``grpprl`` (after its istd), with
    ``after`` written in the page right behind it."""

    tree = doc_streams([Table([["a"], ["b"]])])
    word = bytearray(_bytes(tree, "WordDocument"))
    page = _papx_page(tree)
    runs = word[page + FKP_SIZE - 1]
    bx = page + 4 * (runs + 1)  # the BxPap table; the first byte of each is the bOffset
    row_end = word[bx + 13 * 1]  # run 1 is the first row end
    data = struct.pack("<H", 0) + grpprl  # istd, then the sprms
    data += bytes(len(data) % 2)
    free = 200  # the page's free space lies between the BxPap table and the entries at its end
    assert bx - page + 13 * runs <= free and free + 2 + len(data) <= FKP_SIZE - 80
    word[page + free:page + free + 2 + len(data)] = bytes([0, len(data) // 2]) + data
    word[page + free + 2 + len(data):page + free + 2 + len(data) + len(after)] = after
    for run in range(runs):
        if word[bx + 13 * run] == row_end:
            word[bx + 13 * run] = free // 2
    tree["WordDocument"] = bytes(word)
    return ole_tree(tree)


IN_TABLE, TTP = struct.pack("<HB", 0x2416, 1), struct.pack("<HB", 0x2417, 1)


def test_variable_size_sprms_never_overrun() -> None:
    cases = {
        "a table definition claiming 65535 bytes": IN_TABLE + TTP + struct.pack("<HH", 0xD608, 0xFFFF),
        "tab changes with size 255 and garbage counts": IN_TABLE + TTP + struct.pack("<HB", 0xC615, 255) + b"\xff" * 5,
        "a sprm cut off after its opcode": IN_TABLE + TTP + struct.pack("<H", 0x2416),
        "an operand-size byte past the end": IN_TABLE + TTP + struct.pack("<H", 0xC60D),
        "a table definition cut off in its size": IN_TABLE + TTP + b"\x08\xd6\x01",
        "a table definition with nothing after its opcode": IN_TABLE + TTP + b"\x08\xd6",
        "tab changes with size 255 and no counts": IN_TABLE + TTP + struct.pack("<HB", 0xC615, 255) + b"\x00",
        "tab changes ending at their size byte": (IN_TABLE + struct.pack("<HB", 0x2461, 0) + TTP
                                                  + struct.pack("<HB", 0xC615, 255)),
    }

    for what, grpprl in cases.items():
        assert read_doc(_row_end_document(grpprl)).text.split("\n") == ["a", "b"], what  # the Ttp before them is found


def test_a_sprm_cut_off_by_the_end_of_its_grpprl_is_not_read() -> None:
    # sprmPFTtp's opcode is the last thing in the grpprl; its operand byte would be the next byte in the
    # page, which belongs to something else (here a 1). A cut-off sprm is not honoured, so no row ends.
    grpprl = IN_TABLE + struct.pack("<HB", 0x2461, 0) + struct.pack("<H", 0x2417)

    assert read_doc(_row_end_document(grpprl, after=b"\x01")).text.split("\n") == ["a\t\tb\t"]
    assert read_doc(_row_end_document(grpprl + b"\x01\x00")).text.split("\n") == ["a", "b"]  # whole: the same sprm honoured


def test_a_grpprl_offset_at_the_end_of_the_page_has_no_properties() -> None:
    # bOffset 255 puts the PapxInFkp at byte 510; with a zero there its size byte would be the page's
    # cpara. The marks then have no properties, so cells fall back to cell marks.
    tree = doc_streams([Table([["a"], ["b"]])])
    word = bytearray(_bytes(tree, "WordDocument"))
    page = _papx_page(tree)
    runs = word[page + FKP_SIZE - 1]
    for run in range(runs):
        word[page + 4 * (runs + 1) + 13 * run] = 255
    word[page + 510] = 0
    tree["WordDocument"] = bytes(word)

    assert read_doc(ole_tree(tree)).text.split("\n") == ["a", "b"]


def test_a_formatting_page_with_no_valid_run_count_has_no_properties() -> None:
    # With properties the two paragraphs of the first cell are one line; without them (a page whose
    # cpara is 0 or above 29) the cell can only fall back to cell marks and the paragraphs split.
    body: list[str | Table] = [Table([["one\rtwo", "x"]])]
    assert _lines(body) == ["one two\tx"]
    for cpara in (0, 30, 255):
        tree = doc_streams(body)
        word = bytearray(_bytes(tree, "WordDocument"))
        word[_papx_page(tree) + FKP_SIZE - 1] = cpara
        tree["WordDocument"] = bytes(word)

        assert read_doc(ole_tree(tree)).text.split("\n") == ["one", "two\tx"], cpara


def test_hidden_text_at_the_end_of_the_text_is_not_shown() -> None:
    tree = _poke(doc_streams(["a\x13hidden code"]), "WordDocument", CCP_TEXT_AT, "<i", len("a\x13hid"))

    assert read_doc(ole_tree(tree)).text == "a"


def test_every_sprm_size_is_skipped_exactly() -> None:
    sizes = b"".join([
        struct.pack("<HB", 0x0800, 1),  # spra 0: one byte
        struct.pack("<HB", 0x2461, 1),  # 1: one byte
        struct.pack("<HH", 0x4455, 1),  # 2: two bytes
        struct.pack("<HI", 0x6649, 1),  # 3: four bytes
        struct.pack("<HH", 0x845E, 1),  # 4: two bytes
        struct.pack("<HH", 0xA461, 1),  # 5: two bytes
        struct.pack("<HB", 0xC60D, 3) + b"abc",  # 6: a size byte, then that many
        struct.pack("<H", 0xE000) + b"abc",  # 7: three bytes
        # tab changes, size 255: 1 deleted tab (two u16 arrays of 1), 1 added (a u16 and a byte)
        struct.pack("<HB", 0xC615, 255) + b"\x01" + b"\x00\x00" + b"\x00\x00" + b"\x01" + b"\x00\x00" + b"\x00",
        struct.pack("<HHB", 0xD608, 4, 7) + b"\x00\x00",  # a table definition: cb 4, so 5 bytes with the cb itself
    ])

    assert read_doc(_row_end_document(sizes + IN_TABLE + TTP)).text.split("\n") == ["a", "b"]


# --- hostile files -------------------------------------------------------------------------------
def _timed(data: bytes, seconds: float) -> Any:
    started = time.perf_counter()
    try:
        return read_doc(data)
    finally:
        assert time.perf_counter() - started < budget(seconds)


def test_too_many_pieces_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc_reader, "MAX_DOC_PIECES", 3)

    refusal = _refused(doc_bytes(BODY, pieces=5))

    assert (refusal.code, refusal.message) == ("doc_load_failed", doc_reader.DAMAGED_DOCUMENT)


def test_unsorted_cps_or_pieces_outside_the_stream_are_refused() -> None:
    # The Clx opens the table stream: 0x02, u32 lcb, then the CPs (4 pieces: 5 of them), then the Pcds.
    decreasing = _poke(doc_streams(BODY, pieces=4), "1Table", 5 + 2 * 4, "<I", 1)
    equal = _poke(doc_streams(BODY, pieces=4), "1Table", 5 + 4, "<I", 0)
    off_the_end = _poke(doc_streams(BODY, pieces=4), "1Table", 5 + 5 * 4 + 8 + 2, "<I", 0x3FFFFFF0)
    compressed_off_the_end = _poke(doc_streams(BODY, pieces=4), "1Table", 5 + 5 * 4 + 2, "<I",
                                   0x3FFFFFF0 | FC_COMPRESSED)
    starts_late = _poke(doc_streams(BODY, pieces=4), "1Table", 5, "<I", 3)

    for tree in (decreasing, equal, off_the_end, compressed_off_the_end, starts_late):
        _damaged(ole_tree(tree))


def _overlapping_pieces(pieces: int, characters: int) -> Tree:
    """``pieces`` pieces of ``characters`` each, all stored in the same 100,000-byte region."""

    tree = doc_streams(["x"])
    word = bytearray(_bytes(tree, "WordDocument"))
    word = word.ljust(TEXT_START + 100_000, b"\x00")
    word[TEXT_START:TEXT_START + 100_000] = b"a" * 100_000
    tree["WordDocument"] = bytes(word)
    plc = struct.pack(f"<{pieces + 1}I", *(characters * i for i in range(pieces + 1)))
    plc += struct.pack("<HIH", 0, (TEXT_START * 2) | FC_COMPRESSED, 0) * pieces
    clx = b"\x02" + struct.pack("<I", len(plc)) + plc
    tree["1Table"] = clx
    _poke(tree, "WordDocument", CLX_AT, "<II", 0, len(clx))
    _poke(tree, "WordDocument", PLC_BTE_PAPX_AT, "<II", 0, 0)
    _poke(tree, "WordDocument", CCP_TEXT_AT, "<i", pieces * characters)
    return tree


def test_overlapping_pieces_stop_at_the_character_cap() -> None:
    data = ole_tree(_overlapping_pieces(40, 100_000))  # 4,000,000 characters from 100,000 bytes

    document = _timed(data, 2)
    tracemalloc.start()
    read_doc(data)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(document.text) == 1_000_000
    assert document.notes == [("document_truncated", doc_reader.DOCUMENT_TRUNCATED)]
    assert peak < 30_000_000, peak


def test_the_character_cap_is_the_module_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc_reader, "MAX_DOC_CHARS", 10)

    document = read_doc(doc_bytes(["0123456789abcdef"]))

    assert document.text == "0123456789"
    assert document.notes == [("document_truncated", doc_reader.DOCUMENT_TRUNCATED)]


def test_a_document_of_exactly_the_cap_is_not_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc_reader, "MAX_DOC_CHARS", 17)

    assert read_doc(doc_bytes(["0123456789abcdef"])).notes == []  # 16 characters and the paragraph mark


def test_a_character_count_beyond_the_piece_table_reads_what_is_there() -> None:
    tree = _poke(doc_streams(BODY), "WordDocument", CCP_TEXT_AT, "<i", 2**31 - 1)

    assert read_doc(ole_tree(tree)).text.split("\n") == LINES


def test_a_character_count_shorter_than_the_text_cuts_the_text() -> None:
    tree = _poke(doc_streams(["abcdef"]), "WordDocument", CCP_TEXT_AT, "<i", 3)

    assert read_doc(ole_tree(tree)).text == "abc"


def test_a_negative_character_count_is_damaged() -> None:
    for index in range(3, 11):  # ccpText .. ccpHdrTxbx
        _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", 0x40 + 4 * index, "<i", -1)))


def test_a_clx_outside_the_table_stream_is_refused() -> None:
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", CLX_AT, "<II", 10**9, 100)))
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", CLX_AT, "<II", 0xFFFFFFFF, 0xFFFFFFFF)))

    def with_prc(size: int) -> Tree:
        tree = doc_streams(BODY)
        clx = _bytes(tree, "1Table")
        lcb = struct.unpack_from("<I", clx, 1)[0] + 5
        prc = b"\x01" + struct.pack("<h", size)
        tree["1Table"] = prc + clx
        return _poke(tree, "WordDocument", CLX_AT, "<II", 0, len(prc) + lcb)

    _damaged(ole_tree(with_prc(-5)))
    _damaged(ole_tree(with_prc(32000)))  # a Prc running past lcbClx


def test_a_clx_that_is_not_made_of_prcs_and_a_piece_table_is_damaged() -> None:
    for first in (0x00, 0x03, 0xFF):
        tree = doc_streams(BODY)
        tree["1Table"] = bytes([first]) + _bytes(tree, "1Table")[1:]
        _damaged(ole_tree(tree))
    for clx in (b"\x01\x00", b"\x01\x00\x00", b"\x02\x00\x00", b"\x01\x00\x00\x02"):  # cut off in a header
        tree = doc_streams(BODY)
        tree["1Table"] = clx
        _poke(tree, "WordDocument", CLX_AT, "<II", 0, len(clx))
        _damaged(ole_tree(tree))
    for size in (3, 5, 4 + 12 * 4 + 1):  # a piece table that is not 4 + 12 n bytes
        tree = doc_streams(BODY)
        _poke(tree, "1Table", 1, "<I", size)
        _damaged(ole_tree(tree))


def test_an_array_that_does_not_fit_is_damaged_and_is_read_little_endian(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DocError):
        doc_reader._u32s(b"\x01\x00\x00", 0, 1)
    assert list(doc_reader._u32s(b"\x00\x01\x00\x00\x00", 1, 1)) == [1]

    monkeypatch.setattr(doc_reader.sys, "byteorder", "big")  # a big-endian host swaps what it read
    assert list(doc_reader._u32s(b"\x01\x00\x00\x00", 0, 1)) == [1 << 24]


def test_a_clx_made_only_of_prcs_is_damaged_and_fast() -> None:
    prcs = b"\x01\x00\x00" * 200_000  # 600,000 bytes of empty Prcs, and no piece table
    tree = doc_streams(BODY)
    tree["1Table"] = prcs
    _poke(tree, "WordDocument", CLX_AT, "<II", 0, len(prcs))

    started = time.perf_counter()
    _damaged(ole_tree(tree))
    assert time.perf_counter() - started < budget(1)


def test_a_short_fib_is_refused() -> None:
    tree = doc_streams(BODY)
    tree["WordDocument"] = _bytes(tree, "WordDocument")[:100]
    _damaged(ole_tree(tree))

    tree = doc_streams(BODY)
    tree["WordDocument"] = _bytes(tree, "WordDocument")[:0x20]
    _damaged(ole_tree(tree))

    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", CB_FCLCB_AT, "<H", 10)))


def test_a_stream_that_ends_inside_the_fib_base_is_damaged() -> None:
    tree = doc_streams(BODY)
    tree["WordDocument"] = _bytes(tree, "WordDocument")[:0x1F]

    _damaged(ole_tree(tree))


def test_counts_in_the_fib_that_run_past_the_stream_are_refused() -> None:
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", CSW_AT, "<H", 0xFFFF)))
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", CB_FCLCB_AT, "<H", 0xFFFF)))
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", 0x3E, "<H", 5)))  # cslw too small
    _damaged(ole_tree(_poke(doc_streams(BODY), "WordDocument", 0x3E, "<H", 0xFFFF)))


def test_formatting_pages_beyond_the_cap_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doc_reader, "MAX_DOC_FKP_PAGES", 2)

    _damaged(doc_bytes([Table([[f"r{n}", "x"] for n in range(200)])]))


def test_a_plc_bte_papx_that_does_not_fit_is_ignored_not_refused() -> None:
    table = Table([["a", "b"], ["c", "d"]])
    for lcb in (7, 13, 10**9):  # not 4 + 8 m, or past the table stream
        tree = doc_streams([table])
        _poke(tree, "WordDocument", PLC_BTE_PAPX_AT + 4, "<I", lcb)
        assert read_doc(ole_tree(tree)).text.split("\n") == ["a\tb", "c\td"], lcb
    tree = doc_streams([table])
    _poke(tree, "WordDocument", PLC_BTE_PAPX_AT, "<I", 10**9)
    assert read_doc(ole_tree(tree)).text.split("\n") == ["a\tb", "c\td"]


def test_formatting_pages_outside_the_stream_are_ignored_not_refused() -> None:
    tree = doc_streams([Table([["a", "b"], ["c", "d"]])])
    table = bytearray(_bytes(tree, "1Table"))
    plc_at, plc_size = struct.unpack_from("<II", _bytes(tree, "WordDocument"), PLC_BTE_PAPX_AT)
    struct.pack_into("<I", table, plc_at + 4 * ((plc_size - 4) // 8 + 1), 0x3FFFFF)  # page 4,194,303
    tree["1Table"] = bytes(table)

    assert read_doc(ole_tree(tree)).text.split("\n") == ["a\tb", "c\td"]


def test_unsorted_formatting_boundaries_never_raise() -> None:
    tree = doc_streams([Table([[f"c{n}", "x"] for n in range(40)])])
    table = bytearray(_bytes(tree, "1Table"))
    plc_at, plc_size = struct.unpack_from("<II", _bytes(tree, "WordDocument"), PLC_BTE_PAPX_AT)
    for slot in range((plc_size - 4) // 8 + 1):
        struct.pack_into("<I", table, plc_at + 4 * slot, 0xFFFFFFFF - slot)
    tree["1Table"] = bytes(table)

    # A mark whose run cannot be named is a mark with no properties: the cells fall back to cell marks.
    assert read_doc(ole_tree(tree)).text.split("\n") == [f"c{n}\tx" for n in range(40)]


def test_many_formatting_pages_are_read_in_time() -> None:
    paragraphs = 8_000 * 29
    tree = doc_streams(["x"] * paragraphs)
    word = bytearray(_bytes(tree, "WordDocument"))
    plc_at, plc_size = struct.unpack_from("<II", word, PLC_BTE_PAPX_AT)
    pages = (plc_size - 4) // 8
    assert pages == 8_000
    first = struct.unpack_from("<I", _bytes(tree, "1Table"), plc_at + 4 * (pages + 1))[0]
    # Every run of every page points at one grpprl that fills the rest of its page with 1-byte-operand sprms.
    grpprl_at = 498  # the first even offset after the 29 runs' tables (4 * 30 + 13 * 29 = 497)
    entry = bytes([5]) + struct.pack("<H", 0) + struct.pack("<HB", 0x2461, 1) + struct.pack("<HB", 0x2461, 2) + b"\x00"
    for number in range(first, first + pages):
        page = number * FKP_SIZE
        assert word[page + FKP_SIZE - 1] == 29
        word[page + grpprl_at:page + grpprl_at + len(entry)] = entry
        for run in range(29):
            word[page + 4 * 30 + 13 * run] = grpprl_at // 2
    tree["WordDocument"] = bytes(word)
    data = ole_tree(tree)

    document = _timed(data, 2)

    assert document.text.count("\n") == paragraphs - 1


def test_formatting_that_costs_scanning_on_every_run_is_bounded_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # 29 runs per page, each pointing at its own offset of one string of 4-byte-operand sprms whose
    # size byte claims 199 bytes: scanned in full that is 29 scans of 199 bytes per page. A page's own
    # entries never add up to more than 512 bytes, so that is all one page may cost.
    pages_made = 2_000
    paragraphs = pages_made * 29
    tree = doc_streams(["x"] * paragraphs)
    word = bytearray(_bytes(tree, "WordDocument"))
    plc_at, plc_size = struct.unpack_from("<II", word, PLC_BTE_PAPX_AT)
    pages = (plc_size - 4) // 8
    assert pages == pages_made
    first = struct.unpack_from("<I", _bytes(tree, "1Table"), plc_at + 4 * (pages + 1))[0]
    for number in range(first, first + pages):
        page = number * FKP_SIZE
        word[page + 120:page + 510] = b"\x64" * 390  # cb 100: GrpPrlAndIstd of 199 bytes; sprms 0x6464 (4-byte operand)
        for run in range(29):
            word[page + 4 * 30 + 13 * run] = 62 + run  # entries at 124, 126, ...: all inside the string
    tree["WordDocument"] = bytes(word)
    scanned: list[int] = []
    real = doc_reader._sprm_flags

    def counting(page: bytes, pos: int, end: int) -> int:
        scanned.append(end - pos)
        return real(page, pos, end)

    monkeypatch.setattr(doc_reader, "_sprm_flags", counting)
    data = ole_tree(tree)

    document = _timed(data, 1)

    assert document.text.count("\n") == paragraphs - 1
    assert sum(scanned) <= 512 * pages_made
    assert len(scanned) >= pages_made  # and each page did get its entries read


def test_deeply_nested_fields_take_linear_time() -> None:
    data = doc_bytes(["\x13" * 300_000 + "x" + "\x15" * 300_000])

    document = _timed(data, 1)

    assert document.text.strip() == ""


def test_alternating_field_marks_take_linear_time() -> None:
    data = doc_bytes(["\x13\x14\x15" * 150_000 + "shown"])

    document = _timed(data, 1)

    assert document.text == "shown"


def test_a_page_of_nothing_but_paragraph_marks_is_read_in_time() -> None:
    data = doc_bytes(["\r" * 100_000 + "end"])

    document = _timed(data, 1)

    assert document.text.endswith("end")


def test_a_million_marks_with_no_formatting_are_read_in_time() -> None:
    # The character cap is also the cap on marks: 990,000 of them, looked up for nothing.
    data = ole_tree(doc_streams(["\r" * 990_000], papx=False), sector_shift=12)

    document = _timed(data, 2)

    assert document.text.count("\n") == 990_000


def test_crafted_containers_are_damaged() -> None:
    _damaged(ole_tree(doc_streams(BODY), dag=True))
    _damaged(ole_tree(doc_streams(BODY), loop="WordDocument"))

    tree = doc_streams(BODY)
    tree["1Table"] = _bytes(tree, "1Table").ljust(5000, b"\x00")
    _damaged(ole_tree(tree, share=("WordDocument", "1Table")))
    _damaged(ole_tree(tree, dag=True, loop="WordDocument", share=("WordDocument", "1Table")))


def _fuzzed(original: bytes, rng: random.Random, rounds: int) -> list[bytes]:
    copies = []
    for _ in range(rounds):
        data = bytearray(original)
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        copies.append(bytes(data))
    copies += [original[:rng.randrange(len(original))] for _ in range(rounds // 6)]
    return copies


def _never_another_error(copies: list[bytes]) -> None:
    for data in copies:
        try:
            read_doc(data)
        except DocError as refusal:
            # Refused on purpose, in the reader's own words: the catch-all in read_doc would have
            # chained the unforeseen error it caught as the cause.
            assert refusal.__cause__ is None, repr(refusal.__cause__)
            assert refusal.code in {"doc_load_failed", "not_a_word_document", "old_word_document",
                                    "password_protected"}


def test_random_damage_never_escapes_as_another_error() -> None:
    rng = random.Random(20261028)
    copies = (_fuzzed(doc_bytes(BODY, pieces=3, compressed="mixed"), rng, 300)
              + _fuzzed(FIXTURE.read_bytes(), rng, 300))

    started = time.perf_counter()
    _never_another_error(copies)

    assert time.perf_counter() - started < budget(5)


def test_random_damage_inside_the_streams_never_escapes_as_another_error() -> None:
    # The same, aimed at what the reader parses: the FIB, the Clx and the paragraph formatting.
    rng = random.Random(20261029)
    tree = doc_streams(BODY, pieces=3, compressed="mixed")
    word, table = _bytes(tree, "WordDocument"), _bytes(tree, "1Table")
    plc_at, plc_size = struct.unpack_from("<II", word, PLC_BTE_PAPX_AT)
    pages_at = struct.unpack_from("<I", table, plc_at + 4 * ((plc_size - 4) // 8 + 1))[0] * FKP_SIZE
    copies = []
    for _ in range(1500):
        damaged_word, damaged_table = bytearray(word), bytearray(table)
        for _ in range(rng.randint(1, 6)):
            where = rng.choice(("fib", "table", "table", "pages"))
            if where == "fib":
                damaged_word[rng.randrange(0x1B0)] = rng.randrange(256)
            elif where == "table":
                damaged_table[rng.randrange(len(damaged_table))] = rng.randrange(256)
            else:
                damaged_word[rng.randrange(pages_at, len(damaged_word))] = rng.randrange(256)
        copies.append(ole_tree({"WordDocument": bytes(damaged_word), "1Table": bytes(damaged_table)}))

    started = time.perf_counter()
    _never_another_error(copies)

    assert time.perf_counter() - started < budget(5)
