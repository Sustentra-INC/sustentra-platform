"""Word 97-2003 (``.doc``) documents: the main text, its paragraphs and its tables, read from bytes
that may be hostile.

A ``.doc`` is an OLE2 compound file (``ole.OleFile``) whose ``WordDocument`` stream starts with the
File Information Block ([MS-DOC] Fib, FibBase) and holds the text. Everything else this reader needs
lives in the table stream (``1Table`` or ``0Table``, chosen by a FIB flag):

- the Clx ([MS-DOC] Clx, PlcPcd) says where each run of the text lies in ``WordDocument`` and how it
  is stored (cp1252 bytes, or UTF-16LE). A fast-saved file keeps its pieces out of order; the piece
  table already describes that, so there is no special path for it;
- the PlcBtePapx and its PapxFkp pages ([MS-DOC] PlcBtePapx, PapxFkp) say which paragraphs are in a
  table and where a row ends.

Streams are read in a fixed order, ``WordDocument`` first and the table stream second. In a damaged
file whose sector chains cross, the stream read second is the one ``OleFile`` refuses (its sectors are
already claimed), so the file is reported as damaged, never read twice.

Every number read from the file is checked against the stream it indexes before it is used, so a
crafted file can only produce a ``DocError`` or text. Work and memory are bounded by module caps
(``MAX_DOC_PIECES``, ``MAX_DOC_CHARS``, ``MAX_DOC_FKP_PAGES``) and by one rule: nothing walks the text
one character at a time. Text is cut at its marks (paragraph and cell ends, field marks) with a
regular expression and handled in slices; a mark's formatting is found by bisecting arrays that are
never expanded into Python ints.

A chunk of text is ``(text, fc_start, bytes_per_char)``: ``fc_start`` is the offset in ``WordDocument``
of its first character, so a mark at index ``i`` lies at ``fc_start + i * bytes_per_char``. Chunks are
split, never compacted: a character taken out of the visible text is taken out of the slice that is
rendered, not out of the chunk the offsets are measured in.
"""

from __future__ import annotations

import re
import struct
import sys
from array import array
from bisect import bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from backend.app.adapters.parsers.ole import SIGNATURE, STORAGE, STREAM, OleEntry, OleError, OleFile
from backend.app.adapters.parsers.xls_parser import PASSWORD_PROTECTED

MAX_DOC_PIECES = 100_000  # pieces in the Clx (and Prc entries before it)
MAX_DOC_CHARS = 1_000_000  # characters read from the text; the rest is cut
MAX_DOC_FKP_PAGES = 8_192  # distinct paragraph formatting pages parsed

NOT_A_WORD_DOCUMENT = "This .doc is not a Word 97-2003 document. Open it in Word and save it as .docx or PDF."
OLD_WORD_DOCUMENT = (
    "This .doc was saved by Word 95 or earlier, which can't be read here. "
    "Open it in Word and save it as .docx or PDF."
)
DAMAGED_DOCUMENT = (
    "The Word document could not be read; it may be damaged. Ask the client for the file again, or for a PDF."
)
CONTAINS_MACROS = "The document contains macros. They were not run."
DOCUMENT_TRUNCATED = "The document is very long; only its beginning was read."

_FAILED = "doc_load_failed"

_WORD_IDENT = 0xA5EC  # [MS-DOC] FibBase.wIdent
_WORD_97 = 0x00C1  # [MS-DOC] FibBase.nFib of Word 97; earlier versions use another layout
_FLAG_ENCRYPTED = 0x0100  # [MS-DOC] FibBase.fEncrypted
_FLAG_1TABLE = 0x0200  # [MS-DOC] FibBase.fWhichTblStm
_MIN_LW = 11  # FibRgLw97 values up to ccpHdrTxbx (index 10)
_MIN_FCLCB = 0x5D  # FibRgFcLcb97 pairs
_PAPX_PAIR, _CLX_PAIR = 13, 33  # [MS-DOC] FibRgFcLcb97 pair indexes: fcPlcfBtePapx, fcClx

_PAPX_FKP_SIZE = 512
_MAX_PARAGRAPHS_PER_PAGE = 29  # [MS-DOC] PapxFkp.cpara
_PAGE_SCAN_BUDGET = 512  # grpprl bytes scanned per page: a page's own entries never add up to more

# [MS-DOC] sprmPFInTable, sprmPFTtp (paragraph sprms with a one-byte operand), sprmTDefTable and
# sprmPChgTabs (the two sprms whose operand size is not "first byte = size")
_SPRM_IN_TABLE, _SPRM_TTP, _SPRM_TDEF_TABLE, _SPRM_CHG_TABS = 0x2416, 0x2417, 0xD608, 0xC615
_FIXED_OPERAND = (1, 1, 2, 4, 2, 2, 0, 3)  # operand size by spra (the top three bits of the opcode); 6 = variable

_IN_TABLE, _ROW_END = 1, 2  # what a paragraph's sprms say

_U16, _U32, _I16, _PAIR, _CCP = (struct.Struct(f) for f in ("<H", "<I", "<h", "<II", "<8i"))
_UINT = "I" if array("I").itemsize == 4 else "L"

_MARKS = re.compile("[\r\x07]|\x13+|\x14+|\x15+")
# Visible text: line breaks, hyphens and spaces as Word shows them; every other C0 control (object and
# note anchors included) goes. Tab stays. Marks never reach this: the regular expression cuts them out.
_PLAIN: dict[int, str | None] = {code: None for code in range(0x20) if code != 0x09}
_PLAIN.update({0x0B: "\n", 0x0C: "\n", 0x0E: "\n", 0x1E: "-", 0xA0: " "})

Chunk = tuple[str, int, int]  # (text, fc_start, bytes_per_char)


class DocError(ValueError):
    """The document cannot be read; ``code`` is the parser warning code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class WordDocument:
    text: str  # lines joined by "\n"; the parser and the source pane share it
    notes: list[tuple[str, str]] = field(default_factory=list)  # (code, sentence), severity info


def _damaged() -> DocError:
    return DocError(_FAILED, DAMAGED_DOCUMENT)


def read_doc(data: bytes) -> WordDocument:
    """The text of a Word 97-2003 document. Raises ``DocError`` and nothing else: a refusal raises
    it directly (no cause); anything unforeseen in the bytes is reported as damage."""

    try:
        return _read(data)
    except DocError:
        raise
    except Exception as exc:
        raise DocError(_FAILED, DAMAGED_DOCUMENT) from exc


def _read(data: bytes) -> WordDocument:
    if data[:8] != SIGNATURE:
        raise DocError("not_a_word_document", NOT_A_WORD_DOCUMENT)
    try:
        ole = OleFile(data)
    except OleError:
        raise _damaged() from None
    root = ole.directory.root
    if root is None:
        raise _damaged()
    if ole.child(root, "EncryptedPackage") is not None or ole.child(root, "EncryptionInfo") is not None:
        raise DocError("password_protected", PASSWORD_PROTECTED)
    entry = ole.child(root, "WordDocument")
    if entry is None or entry.kind != STREAM:
        raise DocError("not_a_word_document", NOT_A_WORD_DOCUMENT)
    notes: list[tuple[str, str]] = []
    macros = ole.child(root, "Macros")
    if macros is not None and macros.kind == STORAGE:
        notes.append(("contains_macros", CONTAINS_MACROS))

    word = _stream(ole, entry)  # first
    fib = _fib(word)
    table_entry = ole.child(root, "1Table" if fib.second_table else "0Table")
    if table_entry is None or table_entry.kind != STREAM:
        raise _damaged()
    table = _stream(ole, table_entry)  # second

    pieces = _pieces(table, len(word), *fib.clx)
    papx = _Papx.load(table, word, *fib.papx)

    end = min(fib.ccp_text, pieces.cps[len(pieces.offsets)])
    if end > MAX_DOC_CHARS:
        end = MAX_DOC_CHARS
        notes.append(("document_truncated", DOCUMENT_TRUNCATED))
    lines = _render(_chunks(pieces, word, 0, end), papx)
    # Text was kept one character per UTF-16 code unit; join the surrogate pairs, replace the lone ones.
    text = "\n".join(lines).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return WordDocument(text, notes)


def _stream(ole: OleFile, entry: OleEntry) -> bytes:
    try:
        return ole.read(entry)
    except OleError:
        raise _damaged() from None


# --- the File Information Block ----------------------------------------------------------------
@dataclass(frozen=True)
class _Fib:
    second_table: bool  # the table stream is 1Table
    ccp_text: int  # characters in the main document
    papx: tuple[int, int]  # (fc, lcb) of the PlcBtePapx in the table stream
    clx: tuple[int, int]  # (fc, lcb) of the Clx in the table stream


def _unpack(layout: struct.Struct, buffer: bytes, offset: int) -> tuple[int, ...]:
    """``struct.unpack_from`` that cannot raise ``struct.error``: it checks the room first."""

    if offset < 0 or offset + layout.size > len(buffer):
        raise _damaged()
    return layout.unpack_from(buffer, offset)


def _fib(word: bytes) -> _Fib:
    if len(word) < 2 or _U16.unpack_from(word, 0)[0] != _WORD_IDENT:
        raise DocError("not_a_word_document", NOT_A_WORD_DOCUMENT)
    if len(word) < 0x20:  # the FibBase
        raise _damaged()
    (nfib,) = _U16.unpack_from(word, 0x02)
    (flags,) = _U16.unpack_from(word, 0x0A)
    if nfib < _WORD_97:
        raise DocError("old_word_document", OLD_WORD_DOCUMENT)
    if flags & _FLAG_ENCRYPTED:
        raise DocError("password_protected", PASSWORD_PROTECTED)
    # csw, fibRgW, cslw, fibRgLw, cbRgFcLcb, rgFcLcb: each count sits after the array before it.
    (csw,) = _unpack(_U16, word, 0x20)
    (cslw,) = _unpack(_U16, word, 0x22 + csw * 2)
    lw = 0x24 + csw * 2
    if cslw < _MIN_LW:
        raise _damaged()
    (count,) = _unpack(_U16, word, lw + cslw * 4)
    pairs = lw + cslw * 4 + 2
    if count < _MIN_FCLCB or pairs + count * 8 > len(word):
        raise _damaged()
    ccp = _unpack(_CCP, word, lw + 3 * 4)  # ccpText .. ccpHdrTxbx
    if min(ccp) < 0:
        raise _damaged()
    papx = _unpack(_PAIR, word, pairs + _PAPX_PAIR * 8)
    clx = _unpack(_PAIR, word, pairs + _CLX_PAIR * 8)
    return _Fib(bool(flags & _FLAG_1TABLE), ccp[0], (papx[0], papx[1]), (clx[0], clx[1]))


# --- the piece table ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Pieces:
    cps: array[int]  # n + 1 character positions, from 0, strictly increasing
    offsets: list[int]  # byte offset of each piece's first character in WordDocument
    widths: list[int]  # 1 (cp1252 bytes) or 2 (UTF-16LE) bytes per character


def _u32s(buffer: bytes, offset: int, count: int) -> array[int]:
    """``count`` little-endian u32 values as a C array (bisectable without one Python int each)."""

    if offset < 0 or count < 0 or offset + 4 * count > len(buffer):
        raise _damaged()
    values = array(_UINT)
    values.frombytes(buffer[offset:offset + 4 * count])
    if sys.byteorder == "big":
        values.byteswap()
    return values


def _pieces(table: bytes, word_size: int, fc: int, lcb: int) -> _Pieces:
    end = fc + lcb
    if end > len(table):
        raise _damaged()
    pos = fc
    # Zero or more Prc ([MS-DOC] Prc: 0x01, i16 cbGrpprl, grpprl), then the Pcdt (0x02, u32 lcb, PlcPcd).
    for _ in range(MAX_DOC_PIECES + 1):
        if pos >= end:
            raise _damaged()
        kind = table[pos]
        if kind == 1:
            if pos + 3 > end:
                raise _damaged()
            (size,) = _I16.unpack_from(table, pos + 1)
            if size < 0 or pos + 3 + size > end:
                raise _damaged()
            pos += 3 + size
        elif kind == 2:
            if pos + 5 > end:
                raise _damaged()
            (size,) = _U32.unpack_from(table, pos + 1)
            pos += 5
            if pos + size > end:
                raise _damaged()
            break
        else:
            raise _damaged()
    else:
        raise _damaged()
    # PlcPcd: n + 1 CPs, then n 8-byte Pcd, so size = 4 + 12 n.
    if size < 4 or (size - 4) % 12:
        raise _damaged()
    count = (size - 4) // 12
    if count > MAX_DOC_PIECES:
        raise _damaged()
    cps = _u32s(table, pos, count + 1)
    if cps[0] != 0 or any(before >= after for before, after in zip(cps, cps[1:])):
        raise _damaged()
    offsets: list[int] = []
    widths: list[int] = []
    pcd = pos + 4 * (count + 1)
    for index in range(count):
        (raw,) = _U32.unpack_from(table, pcd + 8 * index + 2)  # Pcd.fc, [MS-DOC] FcCompressed
        compressed = bool(raw & 0x40000000)
        raw &= 0x3FFFFFFF
        width = 1 if compressed else 2
        offset = raw // 2 if compressed else raw
        if offset + (cps[index + 1] - cps[index]) * width > word_size:
            raise _damaged()
        offsets.append(offset)
        widths.append(width)
    return _Pieces(cps, offsets, widths)


def _decode(raw: bytes, width: int) -> str:
    """The characters of a piece, one Python character per stored character (so a UTF-16 surrogate
    is one character each, and offsets stay ``index * width``)."""

    if width == 1:
        return raw.decode("cp1252", "replace")
    wide = bytearray(2 * len(raw))  # each u16 widened to a u32, which decodes without pairing
    wide[0::4] = raw[0::2]
    wide[1::4] = raw[1::2]
    return wide.decode("utf-32-le", "surrogatepass")


def _chunks(pieces: _Pieces, word: bytes, start: int, end: int) -> Iterator[Chunk]:
    """The text of CPs ``[start, end)`` as chunks, one per piece touched, decoded only as far as read."""

    cps = pieces.cps
    index = bisect_right(cps, start) - 1
    cp = start
    while cp < end and 0 <= index < len(pieces.offsets):
        take = min(cps[index + 1], end) - cp
        width = pieces.widths[index]
        offset = pieces.offsets[index] + (cp - cps[index]) * width
        yield _decode(word[offset:offset + take * width], width), offset, width
        cp += take
        index += 1


# --- paragraph properties ----------------------------------------------------------------------
def _sprm_flags(page: bytes, pos: int, end: int) -> int:
    """Whether a grpprl puts its paragraph in a table and ends a row. A sprm that runs past ``end``
    ends the scan (what was found before it stands); nothing here can raise."""

    flags = 0
    while pos + 2 <= end:
        opcode = page[pos] | page[pos + 1] << 8
        spra = opcode >> 13
        if spra != 6:
            size = 2 + _FIXED_OPERAND[spra]
        elif opcode == _SPRM_TDEF_TABLE:  # u16 cb, then cb - 1 more bytes
            if pos + 4 > end:
                break
            size = 2 + (page[pos + 2] | page[pos + 3] << 8) + 1
        elif pos + 3 > end:
            break
        elif opcode == _SPRM_CHG_TABS and page[pos + 2] == 255:
            # 255: itbdDelMax, two u16 arrays of that many, itbdAddMax, a u16 and a byte array of that many
            cursor = pos + 3
            if cursor >= end:
                break
            cursor += 1 + 4 * page[cursor]
            if cursor >= end:
                break
            size = cursor + 1 + 3 * page[cursor] - pos
        else:
            size = 3 + page[pos + 2]
        if pos + size > end:
            break
        if opcode == _SPRM_IN_TABLE:
            flags = flags | _IN_TABLE if page[pos + 2] == 1 else flags & ~_IN_TABLE
        elif opcode == _SPRM_TTP:
            flags = flags | _ROW_END if page[pos + 2] == 1 else flags & ~_ROW_END
        pos += size
    return flags


class _Page:
    """One PapxFkp page: its run boundaries, and the flags of each distinct grpprl, found once."""

    __slots__ = ("data", "fcs", "runs", "budget", "flags")

    def __init__(self, data: bytes, fcs: array[int], runs: int) -> None:
        self.data = data
        self.fcs = fcs
        self.runs = runs
        self.budget = _PAGE_SCAN_BUDGET
        self.flags: dict[int, int | None] = {}

    def flags_of(self, run: int) -> int | None:
        offset = self.data[(self.runs + 1) * 4 + 13 * run]  # BxPap.bOffset
        if offset in self.flags:
            return self.flags[offset]
        self.flags[offset] = result = self._scan(offset * 2) if offset else None
        return result

    def _scan(self, at: int) -> int | None:
        data = self.data
        count = data[at]  # PapxInFkp.cb; ``at`` is a byte times two, so at most 510
        if count:
            start, size = at + 1, 2 * count - 1
        else:
            if at + 1 >= _PAPX_FKP_SIZE - 1:  # the next byte would be cpara
                return None
            start, size = at + 2, 2 * data[at + 1]
        end = start + size
        if size < 2 or end > _PAPX_FKP_SIZE - 1 or size > self.budget:
            return None  # no istd, runs off the page, or this page's scanning is spent
        self.budget -= size
        return _sprm_flags(data, start + 2, end)  # after the istd


class _Papx:
    """The paragraph properties of the main document: PlcBtePapx -> PapxFkp page -> run -> grpprl."""

    def __init__(self, word: bytes, fcs: array[int], pages: array[int]) -> None:
        self._word = word
        self._fcs = fcs
        self._pages_of = pages
        self._pages: dict[int, _Page | None] = {}
        self._lo = self._hi = 0  # the last run found: [lo, hi) has these flags
        self._flags: int | None = None

    @classmethod
    def load(cls, table: bytes, word: bytes, fc: int, lcb: int) -> _Papx | None:
        """None when the file has no usable PlcBtePapx: tables then fall back to cell marks."""

        if lcb < 12 or (lcb - 4) % 8 or fc + lcb > len(table):
            return None
        count = (lcb - 4) // 8
        return cls(word, _u32s(table, fc, count + 1), _u32s(table, fc + 4 * (count + 1), count))

    def flags_at(self, fc: int) -> int | None:
        """The flags of the paragraph whose mark is at ``fc``; None when it has no properties."""

        if self._lo <= fc < self._hi:
            return self._flags
        fcs = self._fcs
        slot = bisect_right(fcs, fc) - 1
        if not 0 <= slot < len(self._pages_of) or not fcs[slot] <= fc < fcs[slot + 1]:
            return None  # (the check also keeps an array that is out of order from naming a wrong run)
        number = self._pages_of[slot] & 0x3FFFFF
        page = self._page(number)
        if page is None:
            return None
        run = bisect_right(page.fcs, fc) - 1
        if not 0 <= run < page.runs or not page.fcs[run] <= fc < page.fcs[run + 1]:
            return None
        self._lo = max(fcs[slot], page.fcs[run])
        self._hi = min(fcs[slot + 1], page.fcs[run + 1])
        self._flags = page.flags_of(run)
        return self._flags

    def _page(self, number: int) -> _Page | None:
        if number in self._pages:
            return self._pages[number]
        if len(self._pages) >= MAX_DOC_FKP_PAGES:
            raise _damaged()
        page: _Page | None = None
        start = number * _PAPX_FKP_SIZE
        if start + _PAPX_FKP_SIZE <= len(self._word):
            data = self._word[start:start + _PAPX_FKP_SIZE]
            runs = data[_PAPX_FKP_SIZE - 1]  # PapxFkp.cpara
            if 1 <= runs <= _MAX_PARAGRAPHS_PER_PAGE:
                page = _Page(data, _u32s(data, 0, runs + 1), runs)
        self._pages[number] = page
        return page


# --- text to lines -----------------------------------------------------------------------------
def _render(chunks: Iterable[Chunk], papx: _Papx | None) -> list[str]:
    """Lines of text from chunks: paragraphs (split at their line breaks), and each table row as its
    cells joined by tabs. Field codes are hidden and field results shown.

    Marks are found with a regular expression and the text between them is handled in slices. A
    paragraph or cell mark is looked up in ``papx`` by its offset; with no properties for it a
    ``\\x07`` ends a cell, or the row when it directly follows a cell end."""

    lines: list[str] = []
    row: list[str] = []  # finished cells of the row being read
    cell: list[str] = []  # finished paragraphs of the cell being read
    para: list[str] = []  # visible text of the paragraph being read
    fields = bytearray()  # one byte per open field: 0 while in its code, 1 once in its result
    hidden = 0  # open fields still in their code
    bare = False  # the last thing read was a cell end

    def end_cell(tail: str) -> None:
        cell.append(tail.replace("\n", " ").strip())
        row.append(" ".join(part for part in cell if part))
        cell.clear()

    def end_row() -> None:
        if any(row):
            lines.append("\t".join(row))
        row.clear()

    def flush_table() -> None:  # a table whose last row has no row-end mark
        if cell:
            end_cell("")
        end_row()

    for text, fc_start, width in chunks:
        at = 0
        for found in _MARKS.finditer(text):
            start, stop = found.span()
            if start > at:
                bare = False
                if not hidden:
                    para.append(text[at:start].translate(_PLAIN))
            at = stop
            mark = text[start]
            if mark == "\x13":
                fields.extend(bytes(stop - start))
                hidden += stop - start
                bare = False
            elif mark == "\x14":
                if fields and not fields[-1]:
                    fields[-1] = 1
                    hidden -= 1
                bare = False
            elif mark == "\x15":
                closing = min(stop - start, len(fields))
                if closing:
                    hidden -= fields[-closing:].count(0)
                    del fields[-closing:]
                bare = False
            else:  # a paragraph end (\r) or a cell or row end (\x07)
                flags = papx.flags_at(fc_start + start * width) if papx is not None else None
                body = "".join(para)
                para.clear()
                if mark == "\r":
                    bare = False
                    if flags is not None and flags & _IN_TABLE:
                        cell.append(body.replace("\n", " ").strip())
                    else:
                        flush_table()
                        lines.extend(body.split("\n"))
                elif flags is not None and flags & _ROW_END:
                    if cell or body.strip():
                        end_cell(body)
                    end_row()
                    bare = False
                elif flags is None and bare:
                    end_row()
                    bare = False
                else:
                    end_cell(body)
                    bare = True
        if at < len(text):
            bare = False
            if not hidden:
                para.append(text[at:].translate(_PLAIN))
    body = "".join(para)
    if body:
        if row or cell:
            end_cell(body)
        else:
            lines.extend(body.split("\n"))
    flush_table()
    return lines
