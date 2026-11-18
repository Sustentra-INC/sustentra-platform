"""Word 97-2003 (.doc) documents, written byte by byte by the tests themselves.

Nothing among the dependencies writes .doc, and a binary fixture says nothing about what it holds, so
the tests write the format, to [MS-DOC] (Word Binary File Format): a ``WordDocument`` stream (the File
Information Block, the text, the paragraph formatting pages) and a table stream (the Clx and the
PlcBtePapx), in a compound file written by ``_ole_builder.ole_tree``. The constants are literal values
with the structure that defines them, never imported from the reader: a reader and a builder that share
a misreading would agree with each other, which is why one test also reads a document macOS wrote.

``doc_streams`` returns the streams as a tree so the hostile tests can change bytes before the
compound file is written.
"""

from __future__ import annotations

import math
import struct
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any

from backend.tests.adapters.parsers._ole_builder import Tree, ole_tree

WORD_IDENT = 0xA5EC  # [MS-DOC] 2.5.2 FibBase.wIdent
F_COMPLEX, F_ENCRYPTED, F_WHICH_TABLE = 0x0004, 0x0100, 0x0200  # [MS-DOC] 2.5.2 FibBase flags (offset 0x0A)
TEXT_START = 0x600  # where Word starts the text in WordDocument
FKP_SIZE = 512  # [MS-DOC] PapxFkp is one 512-byte page
MAX_RUNS = 29  # [MS-DOC] PapxFkp.cpara is at most 0x1D
FIB_CSW, FIB_CSLW, FIB_CB_FCLCB = 14, 22, 0x5D  # [MS-DOC] 2.5.1 Fib counts for nFib 0x00C1
CSW_AT, CSLW_AT, FIB_RG_LW, CB_FCLCB_AT, FIB_RG_FCLCB = 0x20, 0x3E, 0x40, 0x98, 0x9A  # with the counts above
PLC_BTE_PAPX_AT, CLX_AT = 0x102, 0x1A2  # FibRgFcLcb97 pairs 13 and 33 (fc, lcb)
CCP_TEXT_AT = FIB_RG_LW + 3 * 4  # FibRgLw97.ccpText; cbMac is the first value
SPRM_P_F_IN_TABLE, SPRM_P_F_TTP, SPRM_T_DEF_TABLE = 0x2416, 0x2417, 0xD608  # [MS-DOC] 2.6.2, 2.6.3
FC_COMPRESSED = 0x40000000  # [MS-DOC] FcCompressed.fCompressed (bit 30)
TARGET_SIZE = 4096  # Word never writes a smaller WordDocument (so it is a big stream, not a mini one)

MARKS = ("\r", "\x07")


@dataclass
class Table:
    rows: list[list[str]]  # cell text; "\r" inside a cell = two paragraphs


def field(code: str, result: str | None) -> str:
    """A field: begin mark, code, separator and result (when given), end mark."""

    return "\x13" + code + ("\x14" + result if result is not None else "") + "\x15"


# --- the text and the kind of each mark ---------------------------------------------------------
def _text(body: list[str | Table]) -> tuple[str, list[tuple[str, int]]]:
    """The whole text, and the kind of each ``\\r`` and ``\\x07`` in it, in order: ("body", 0) for a
    paragraph, ("cell", 0) for a paragraph of a cell, ("row", columns) for a row end."""

    parts: list[str] = []
    kinds: list[tuple[str, int]] = []
    for item in body:
        if isinstance(item, Table):
            for row in item.rows:
                for cell in row:
                    assert "\x07" not in cell
                    parts.append(cell + "\x07")
                    kinds += [("cell", 0)] * (cell.count("\r") + 1)
                parts.append("\x07")
                kinds.append(("row", len(row)))
        else:
            assert "\x07" not in item
            parts.append(item + "\r")
            kinds += [("body", 0)] * (item.count("\r") + 1)
    return "".join(parts), kinds


def _store(part: list[int], squeeze: bool) -> tuple[bytes, int]:
    """A piece's bytes and their width: cp1252 when asked for and every character has a byte there."""

    if squeeze:
        try:
            return "".join(map(chr, part)).encode("cp1252"), 1
        except UnicodeEncodeError:
            pass
    return struct.pack(f"<{len(part)}H", *part), 2


# --- paragraph formatting ------------------------------------------------------------------------
def _grpprl(kind: tuple[str, int]) -> bytes:
    """The sprms of a paragraph: a cell's paragraphs are in a table; a row end is too, ends the row,
    and carries a sprmTDefTable (a variable-size sprm: u16 cb, then cb - 1 bytes)."""

    name, columns = kind
    if name == "body":
        return b""
    in_table = struct.pack("<HB", SPRM_P_F_IN_TABLE, 1)
    if name == "cell":
        return in_table
    definition = bytes([columns]) + struct.pack(f"<{columns + 1}h", *range(0, 1000 * (columns + 1), 1000))
    definition += bytes(20 * columns)  # one TC80 per column
    return (in_table + struct.pack("<HB", SPRM_P_F_TTP, 1)
            + struct.pack("<HH", SPRM_T_DEF_TABLE, len(definition) + 1) + definition)


def _papx_in_fkp(grpprl: bytes, kind: tuple[str, int]) -> bytes:
    """A PapxInFkp. Cell paragraphs use the form with cb != 0 (GrpPrlAndIstd is 2 * cb - 1 bytes), row
    ends the form with cb == 0 (a byte follows, GrpPrlAndIstd is twice that)."""

    istd_and_sprms = struct.pack("<H", 0) + grpprl
    if kind[0] == "row":
        padded = istd_and_sprms + bytes(len(istd_and_sprms) % 2)
        assert len(padded) // 2 <= 255, "a row this wide needs more than one PapxInFkp"
        return bytes([0, len(padded) // 2]) + padded
    padded = istd_and_sprms + bytes(1 - len(istd_and_sprms) % 2)
    return bytes([(len(padded) + 1) // 2]) + padded


def _fkp_pages(boundaries: list[int], kinds: list[tuple[str, int]]) -> list[tuple[list[int], bytes]]:
    """PapxFkp pages for runs ``[boundaries[i], boundaries[i + 1])`` of kind ``kinds[i]``: each page
    as (its run boundaries, its 512 bytes). A page takes runs until it has 29 or no room is left; runs
    of the same kind in a page share one PapxInFkp."""

    pages: list[tuple[list[int], bytes]] = []
    first = 0
    while first < len(kinds):
        entries: dict[tuple[str, int], bytes] = {}
        count = 0
        while first + count < len(kinds) and count < MAX_RUNS:
            kind = kinds[first + count]
            wanted = dict(entries)
            if kind[0] != "body" and kind not in wanted:
                wanted[kind] = _papx_in_fkp(_grpprl(kind), kind)
            header = 4 * (count + 2) + 13 * (count + 1)
            if header + sum(len(entry) for entry in wanted.values()) > FKP_SIZE - 2:
                break
            entries, count = wanted, count + 1
        assert count, "a single run must fit in a page"
        page = bytearray(FKP_SIZE)
        page[FKP_SIZE - 1] = count
        end = FKP_SIZE - 2  # entries are placed from the end of the page, at even offsets
        offsets: dict[tuple[str, int], int] = {}
        for kind, entry in entries.items():
            end -= len(entry)
            page[end:end + len(entry)] = entry
            offsets[kind] = end
        run_boundaries = boundaries[first:first + count + 1]
        struct.pack_into(f"<{count + 1}I", page, 0, *run_boundaries)
        for index in range(count):
            kind = kinds[first + index]
            page[4 * (count + 1) + 13 * index] = offsets[kind] // 2 if kind in offsets else 0  # BxPap.bOffset
        pages.append((run_boundaries, bytes(page)))
        first += count
    return pages


# --- the document --------------------------------------------------------------------------------
def doc_streams(body: list[str | Table], *, compressed: bool | str = False, pieces: int = 1,
                shuffle: bool = False, encrypted: bool = False, nfib: int = 0x00C1,
                table_stream: str = "1Table", papx: bool = True, macros: bool = False,
                prcs: int = 0) -> Tree:
    """The streams of a Word 97-2003 document holding ``body``: strings are paragraphs, a ``Table`` is
    a table. ``pieces`` splits the text at fixed character positions; ``shuffle`` stores the pieces
    in reverse order in the file (as a fast-saved file does) and sets fComplex. ``compressed`` stores
    cp1252 pieces (``"mixed"``: every other piece); a piece with a character cp1252 lacks is UTF-16.
    ``papx=False`` leaves out the paragraph formatting, ``prcs`` puts that many Prc entries before the
    piece table in the Clx."""

    text, kinds = _text(body)
    data = text.encode("utf-16-le", "surrogatepass")  # a lone surrogate is a legal code unit here
    units = list(struct.unpack(f"<{len(data) // 2}H", data))  # the characters, as UTF-16 code units
    assert units, "a document needs some text"
    marks = [i for i, unit in enumerate(units) if unit in (0x0D, 0x07)]
    assert len(marks) == len(kinds)

    # The pieces: where each starts in the text (a character position) and in the file, and how it is stored.
    count = min(pieces, len(units))
    cps = [len(units) * i // count for i in range(count + 1)]
    stored: list[tuple[bytes, int]] = []
    for index in range(count):
        part = units[cps[index]:cps[index + 1]]
        squeeze = compressed is True or (compressed == "mixed" and index % 2 == 0)
        stored.append(_store(part, squeeze))
    place: dict[int, int] = {}
    position = TEXT_START
    for index in (reversed(range(count)) if shuffle else range(count)):
        place[index] = position
        position += len(stored[index][0])
    text_end = position

    def file_offset(unit: int) -> tuple[int, int]:  # (offset in WordDocument, bytes per character)
        piece = bisect_right(cps, unit) - 1
        width = stored[piece][1]
        return place[piece] + (unit - cps[piece]) * width, width

    # The paragraph runs, in file order: each ends just after its mark.
    pages: list[tuple[list[int], bytes]] = []
    pages_start = math.ceil(text_end / FKP_SIZE) * FKP_SIZE
    plc_bte = b""
    if papx:
        located = sorted(zip((file_offset(m) for m in marks), kinds))
        boundaries = [TEXT_START] + [offset + width for (offset, width), _ in located]
        pages = _fkp_pages(boundaries, [kind for _, kind in located])
        numbers = [pages_start // FKP_SIZE + i for i in range(len(pages))]
        plc_bte = (struct.pack(f"<{len(pages) + 1}I", *(run[0] for run, _ in pages), boundaries[-1])
                   + struct.pack(f"<{len(pages)}I", *numbers))

    word = bytearray(max(TARGET_SIZE, pages_start + FKP_SIZE * len(pages)))
    for index, (part, _) in enumerate(stored):
        word[place[index]:place[index] + len(part)] = part
    for index, (_, page) in enumerate(pages):
        word[pages_start + index * FKP_SIZE:pages_start + (index + 1) * FKP_SIZE] = page

    # The table stream: the Clx, then the PlcBtePapx.
    prc_bytes = b"".join(b"\x01" + struct.pack("<h", 3) + struct.pack("<HB", SPRM_P_F_IN_TABLE, 0)
                         for _ in range(prcs))
    pcds = b"".join(struct.pack("<HIH", 0, (place[i] * 2 | FC_COMPRESSED) if stored[i][1] == 1 else place[i], 0)
                    for i in range(count))
    plc_pcd = struct.pack(f"<{count + 1}I", *cps) + pcds
    clx = prc_bytes + b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd
    plc_at = math.ceil(len(clx) / 4) * 4
    table = bytearray(clx.ljust(plc_at, b"\x00") + plc_bte)

    # The File Information Block.
    flags = (F_COMPLEX if shuffle else 0) | (F_ENCRYPTED if encrypted else 0)
    flags |= F_WHICH_TABLE if table_stream == "1Table" else 0
    struct.pack_into("<HH", word, 0, WORD_IDENT, nfib)
    struct.pack_into("<H", word, 0x0A, flags)
    struct.pack_into("<H", word, CSW_AT, FIB_CSW)
    struct.pack_into("<H", word, CSLW_AT, FIB_CSLW)
    struct.pack_into("<I", word, FIB_RG_LW, len(word))  # cbMac
    struct.pack_into("<i", word, CCP_TEXT_AT, len(units))
    struct.pack_into("<H", word, CB_FCLCB_AT, FIB_CB_FCLCB)
    if papx:
        struct.pack_into("<II", word, PLC_BTE_PAPX_AT, plc_at, len(plc_bte))
    struct.pack_into("<II", word, CLX_AT, 0, len(clx))

    tree: Tree = {"WordDocument": bytes(word), table_stream: bytes(table)}
    if macros:
        tree["Macros"] = {"PROJECT": b"ID={00000000-0000-0000-0000-000000000000}"}
    return tree


def doc_bytes(body: list[str | Table], **options: Any) -> bytes:
    return ole_tree(doc_streams(body, **options))
