"""Small Excel 97-2003 (.xls) workbooks, written by the tests themselves.

Nothing among the dependencies writes .xls (xlrd only reads it), and a binary fixture
says nothing about what it holds, so the tests write the format: a BIFF8 workbook stream
in an OLE2 compound file, with the records Excel saves (shared strings, RK and NUMBER
numbers, date-formatted numbers, booleans, error cells, formulas with a cached result) and
the hostile cases the reader must refuse or survive (encryption, a VBA project, a looping
sector chain, an encrypted .xlsx in its OLE wrapper).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT, ENDOFCHAIN, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
SECTOR, MINI_SECTOR, MINI_CUTOFF = 512, 64, 4096


@dataclass(frozen=True)
class ErrorCell:
    code: int  # 0x07 is #DIV/0!


@dataclass(frozen=True)
class FormulaCell:
    cached: float  # the result Excel saved; the formula itself is never evaluated


# --- BIFF8 workbook stream -------------------------------------------------------------------
def _record(record_id: int, data: bytes = b"") -> bytes:
    assert len(data) <= 8224, "a BIFF8 record holds at most 8224 bytes"
    return struct.pack("<HH", record_id, len(data)) + data


def _bof(substream: int) -> bytes:  # 0x0005 workbook globals, 0x0010 worksheet
    return _record(0x0809, struct.pack("<HHHHII", 0x0600, substream, 0x0DBB, 0x07CC, 0, 0x06))


def _xf(format_index: int) -> bytes:
    return _record(0x00E0, struct.pack("<HHHBBBBIiH", 0, format_index, 0x0001, 0x20, 0, 0, 0, 0, 0, 0x20C0))


def _utf16(text: str, length_bytes: int) -> bytes:
    encoded = text.encode("utf-16-le")
    prefix = struct.pack("<B" if length_bytes == 1 else "<H", len(encoded) // 2)
    return prefix + b"\x01" + encoded  # option flags: 16-bit characters


def _serial(value: date | datetime | time, datemode: int) -> float:
    from openpyxl.utils.datetime import MAC_EPOCH, WINDOWS_EPOCH, to_excel

    return float(to_excel(value, MAC_EPOCH if datemode else WINDOWS_EPOCH))


def _cell(row: int, column: int, value: Any, strings: list[str], datemode: int) -> bytes:
    if value is None:
        return b""
    if isinstance(value, ErrorCell):
        return _record(0x0205, struct.pack("<HHHBB", row, column, 0, value.code, 1))
    if isinstance(value, bool):
        return _record(0x0205, struct.pack("<HHHBB", row, column, 0, int(value), 0))
    if isinstance(value, FormulaCell):  # =1 with a cached (stale) result
        tokens = b"\x1e" + struct.pack("<H", 1)  # tInt 1
        return _record(0x0006, struct.pack("<HHHdHI", row, column, 0, value.cached, 0, 0)
                       + struct.pack("<H", len(tokens)) + tokens)
    if isinstance(value, (date, datetime, time)):  # XF 1: a date format
        return _record(0x0203, struct.pack("<HHHd", row, column, 1, _serial(value, datemode)))
    if isinstance(value, int) and -(2**29) <= value < 2**29:
        return _record(0x027E, struct.pack("<HHHi", row, column, 0, (value << 2) | 2))  # RK integer
    if isinstance(value, (int, float)):
        return _record(0x0203, struct.pack("<HHHd", row, column, 0, float(value)))
    if value == "":
        return _record(0x0201, struct.pack("<HHH", row, column, 0))  # BLANK: formatted, no value
    if str(value) not in strings:
        strings.append(str(value))
    return _record(0x00FD, struct.pack("<HHHI", row, column, 0, strings.index(str(value))))


def biff_workbook(sheets: dict[str, list[Any]], *, encrypted: bool = False, datemode: int = 0,
                  pad_to: int = MINI_CUTOFF, shared_sheets: int = 0, overlap_step: int | None = None) -> bytes:
    """A BIFF8 workbook stream: the globals, then one substream per sheet. ``shared_sheets``
    adds that many more sheets whose BOUNDSHEET records point at the first sheet's data: all
    at the same offset, or, with ``overlap_step``, at distinct offsets ``first + k*step`` that
    still fall inside the first sheet's records (distinct but overlapping spans)."""

    strings: list[str] = []
    bodies: list[bytes] = []
    for rows in sheets.values():
        # A row is a list of values, or (for sparse sheets) a {column: value} dict.
        cells = b"".join(_cell(r, c, value, strings, datemode) for r, row in enumerate(rows)
                         for c, value in (row.items() if isinstance(row, dict) else enumerate(row)))
        width = max((max(row, default=-1) + 1 if isinstance(row, dict) else len(row) for row in rows), default=0)
        dimensions = _record(0x0200, struct.pack("<IIHHH", 0, len(rows), 0, width, 0))
        bodies.append(_bof(0x0010) + dimensions + cells + _record(0x000A))

    head = _bof(0x0005)
    if encrypted:  # FILEPASS, RC4: the records after it would be encrypted
        head += _record(0x002F, struct.pack("<HHH", 1, 1, 1) + bytes(48))
    head += _record(0x0042, struct.pack("<H", 1200))  # CODEPAGE: UTF-16
    head += _record(0x0022, struct.pack("<H", datemode))  # DATEMODE: 0 = 1900, 1 = 1904
    head += _xf(0) + _xf(14)  # XF 0 General, XF 1 the built-in date format m/d/yyyy
    sst = _record(0x00FC, struct.pack("<II", len(strings), len(strings))
                  + b"".join(_utf16(text, 2) for text in strings))
    shared = [f"Copy {n}" for n in range(1, shared_sheets + 1)]
    sheet_records_size = sum(len(_record(0x0085, bytes(6) + _utf16(name, 1))) for name in [*sheets, *shared])
    offset = len(head) + sheet_records_size + len(sst) + len(_record(0x000A))
    first = offset
    for name, body in zip(sheets, bodies):
        head += _record(0x0085, struct.pack("<IBB", offset, 0, 0) + _utf16(name, 1))  # BOUNDSHEET
        offset += len(body)
    for k, name in enumerate(shared, start=1):
        at = first + k * overlap_step if overlap_step else first
        head += _record(0x0085, struct.pack("<IBB", at, 0, 0) + _utf16(name, 1))
    stream = head + sst + _record(0x000A) + b"".join(bodies)
    return stream.ljust(pad_to, b"\x00")


# --- OLE2 compound file --------------------------------------------------------------------
def _dir_entry(name: str, kind: int, start: int, size: int, *, child: int = NOSTREAM, right: int = NOSTREAM,
               left: int = NOSTREAM) -> bytes:
    encoded = (name.encode("utf-16-le") + b"\x00\x00") if name else b""
    return (encoded.ljust(64, b"\x00") + struct.pack("<HBBIII", len(encoded), kind, 1, left, right, child)
            + bytes(16 + 4 + 8 + 8) + struct.pack("<IQ", start, size))


def ole_file(streams: dict[str, bytes], storages: tuple[str, ...] = (), *, loop_mini_chain: str | None = None,
             dag: bool = False) -> bytes:
    """An OLE2 (version 3, 512-byte sectors) file holding ``streams`` and empty ``storages``
    at the top level. Streams under 4096 bytes live in the mini stream, as Office writes them.

    Hostile shapes: ``loop_mini_chain`` names a small stream whose mini-sector chain points
    back to its start; ``dag`` links every directory entry to the next one as both its left
    and its right sibling, so a reader without a visited set walks 2^N paths.
    """

    big = {name: data for name, data in streams.items() if len(data) >= MINI_CUTOFF}
    small = {name: data for name, data in streams.items() if len(data) < MINI_CUTOFF}

    mini_fat: list[int] = []
    mini_data = b""
    mini_start: dict[str, int] = {}
    for name, data in small.items():
        count = max(1, math.ceil(len(data) / MINI_SECTOR))
        first = len(mini_fat)
        mini_start[name] = first
        mini_fat += list(range(first + 1, first + count)) + [ENDOFCHAIN]
        mini_data += data.ljust(count * MINI_SECTOR, b"\x00")
        if name == loop_mini_chain:
            mini_fat[-1] = first  # the chain's last sector points back to its first

    names = list(streams) + list(storages)
    dir_sectors = math.ceil((1 + len(names)) / 4)
    mini_fat_sectors = math.ceil(len(mini_fat) * 4 / SECTOR)
    mini_stream_sectors = math.ceil(len(mini_data) / SECTOR)
    big_sectors = {name: math.ceil(len(data) / SECTOR) for name, data in big.items()}
    rest = dir_sectors + mini_fat_sectors + mini_stream_sectors + sum(big_sectors.values())
    fat_sectors = 1
    while fat_sectors * (SECTOR // 4) < fat_sectors + rest:
        fat_sectors += 1
    assert fat_sectors <= 109, "no DIFAT sectors in these small files"

    fat: list[int] = [FATSECT] * fat_sectors
    next_sector = fat_sectors

    def chain(count: int) -> int:
        nonlocal next_sector
        first = next_sector
        fat.extend(list(range(first + 1, first + count)) + [ENDOFCHAIN])
        next_sector += count
        return first

    dir_start = chain(dir_sectors)
    mini_fat_start = chain(mini_fat_sectors) if mini_fat_sectors else ENDOFCHAIN
    mini_stream_start = chain(mini_stream_sectors) if mini_stream_sectors else ENDOFCHAIN
    big_start = {name: chain(count) for name, count in big_sectors.items()}

    entries = [_dir_entry("Root Entry", 5, mini_stream_start, len(mini_data), child=1 if names else NOSTREAM)]
    for index, name in enumerate(names, start=1):
        right = index + 1 if index < len(names) else NOSTREAM
        left = right if dag else NOSTREAM
        if name in big:
            entries.append(_dir_entry(name, 2, big_start[name], len(big[name]), right=right, left=left))
        elif name in small:
            entries.append(_dir_entry(name, 2, mini_start[name], len(small[name]), right=right, left=left))
        else:
            entries.append(_dir_entry(name, 1, 0, 0, right=right, left=left))
    while len(entries) % 4:
        entries.append(_dir_entry("", 0, 0, 0))

    header = (OLE_SIGNATURE + bytes(16) + struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6) + bytes(6)
              + struct.pack("<IIIIIIIII", 0, fat_sectors, dir_start, 0, MINI_CUTOFF, mini_fat_start,
                            mini_fat_sectors, ENDOFCHAIN, 0)
              + struct.pack("<109I", *(list(range(fat_sectors)) + [FREESECT] * (109 - fat_sectors))))
    fat += [FREESECT] * (fat_sectors * (SECTOR // 4) - len(fat))
    body = struct.pack(f"<{len(fat)}I", *fat)
    body += b"".join(entries)
    if mini_fat_sectors:
        padded = mini_fat + [FREESECT] * (mini_fat_sectors * (SECTOR // 4) - len(mini_fat))
        body += struct.pack(f"<{len(padded)}I", *padded)
    body += mini_data.ljust(mini_stream_sectors * SECTOR, b"\x00")
    for name in big:
        body += big[name].ljust(big_sectors[name] * SECTOR, b"\x00")
    return header + body


def embedded_block_xls(*, overlap: bool) -> bytes:
    """A two-sheet workbook whose first sheet holds an embedded chart block (BOF...EOF).

    The parser must read past that inner EOF to the sheet's real EOF, as xlrd does. With
    ``overlap=True`` the second sheet's BOUNDSHEET points inside the first sheet's records,
    after the embedded block's inner EOF but before its real EOF -- a span a reader that
    stopped at the first EOF would miss. With ``overlap=False`` the second sheet follows the
    first cleanly (a legitimate embedded chart)."""

    def cell(row: int, value: float) -> bytes:
        return _record(0x0203, struct.pack("<HHHd", row, 0, 0, value))

    eof = _record(0x000A)
    embedded = _bof(0x20) + cell(0, 1.0) + eof  # an embedded chart block: BOF(chart) ... EOF
    own_bof = _bof(0x0010)
    tail = b"".join(cell(r, 100.0 + r) for r in range(200))
    sheet_a = own_bof + embedded + tail + eof
    sheet_b = _bof(0x0010) + cell(0, 450.0) + eof

    globals_head = _bof(0x0005) + _record(0x0042, struct.pack("<H", 1200)) + _xf(0) + _xf(14)
    one_boundsheet = len(_record(0x0085, struct.pack("<IBB", 0, 0, 0) + _utf16("S", 1)))
    globals_size = len(globals_head) + 2 * one_boundsheet + len(eof)

    a_start = globals_size
    if overlap:  # just after the embedded block's inner EOF, at a real record boundary in the tail
        b_start = a_start + len(own_bof) + len(embedded)
    else:
        b_start = a_start + len(sheet_a)
    head = globals_head
    for name, offset in (("A", a_start), ("B", b_start)):
        head += _record(0x0085, struct.pack("<IBB", offset, 0, 0) + _utf16(name, 1))
    return ole_file({"Workbook": head + eof + sheet_a + sheet_b})


def past_the_stream_xls(shape: str, *, sheets: int = 100, rows_after: int = 1000) -> bytes:
    """A workbook whose sheets lead xlrd past the end of its Workbook stream.

    The Workbook stream is a standard stream (over the 4096-byte cutoff) stored in one piece,
    so xlrd reads it in place inside the whole file, and its record reads do not stop at the
    stream's end. What follows the stream in the file is records the stream does not hold:
    ``rows_after`` cells, then an EOF.

    - ``identical``: ``sheets`` more BOUNDSHEETs all point 2 bytes before the stream's end,
      whose last 2 bytes are a BOF opcode; the BOF's length and body, and the sheet's records,
      lie after the stream. xlrd reads those records once per sheet.
    - ``adjacent``: the extra sheets point at the stream's last 1, 2 and 3 bytes in turn.
    - ``no_eof``: one sheet whose records run to the stream's end with no EOF; xlrd reads
      the cells after the stream as that sheet's.
    """

    def number(row: int, value: float) -> bytes:
        return _record(0x0203, struct.pack("<HHHd", row, 0, 0, value))

    eof = _record(0x000A)
    filler = _record(0x00EF, bytes(4200))  # keeps the stream over the mini-stream cutoff
    cells_after = b"".join(number(row, 1000.0 + row) for row in range(1, rows_after + 1)) + eof
    names = ["S"] if shape == "no_eof" else ["S", *(f"T{k}" for k in range(1, sheets + 1))]
    head = _bof(0x0005) + _record(0x0042, struct.pack("<H", 1200)) + _xf(0) + _xf(14)
    first = len(head) + sum(len(_record(0x0085, bytes(6) + _utf16(name, 1))) for name in names) + len(eof)
    if shape == "no_eof":
        sheet, tail = _bof(0x0010) + number(0, 450.0) + filler, b""  # the stream ends with no EOF
        offsets = [first]
        after = cells_after
    else:
        sheet = _bof(0x0010) + number(0, 450.0) + filler + eof
        tail = b"\x09\x08" if shape == "identical" else b"\x00\x09\x08"  # 0x0809, a BOF opcode
        end = first + len(sheet) + len(tail)
        extra = [end - 2] * sheets if shape == "identical" else [end - 1 - k % 3 for k in range(sheets)]
        offsets = [first, *extra]
        # The BOF's length (16) and body (a worksheet), then the sheet's records.
        after = struct.pack("<HHHHHII", 16, 0x0600, 0x0010, 0x0DBB, 0x07CC, 0, 0x06) + cells_after
    for name, offset in zip(names, offsets):
        head += _record(0x0085, struct.pack("<IBB", offset, 0, 0) + _utf16(name, 1))
    stream = head + eof + sheet + tail
    data = ole_file({"Workbook": stream})
    stream_end = data.index(stream) + len(stream)
    data = data[:stream_end] + after
    return data + bytes(-(len(data) - 512) % 512)  # whole sectors


def xls_bytes(sheets: dict[str, list[Any]], *, encrypted: bool = False, macros: bool = False,
              datemode: int = 0, shared_sheets: int = 0, overlap_step: int | None = None) -> bytes:
    """A whole .xls file, as Excel saves one (the Workbook stream at least 4096 bytes)."""

    storages = ("_VBA_PROJECT_CUR",) if macros else ()
    stream = biff_workbook(sheets, encrypted=encrypted, datemode=datemode, shared_sheets=shared_sheets,
                           overlap_step=overlap_step)
    return ole_file({"Workbook": stream}, storages)
