"""OLE2 compound files (the container of Excel 97-2003 workbooks): checked before a reader
walks them.

xlrd's own container reader (``xlrd.compdoc``) trusts the file in two places a crafted
file can turn into a hang:

- it builds the directory tree by recursion with no visited set, so a directory shaped as
  a DAG (entries sharing children) makes it call itself 2^N times;
- it follows a small stream's chain through the mini allocation table with no loop check.

``read_directory`` reads the header, the allocation tables and the directory itself, the
way xlrd reads them (same sector addressing, same links), but walks every chain and the
directory tree once with a visited set and an entry cap. Anything reached twice, or
pointing outside the file, is refused, so xlrd is only ever handed a container it can walk
in time proportional to the file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_ENTRIES = 10_000  # directory entries (128 bytes each)
_END = -2  # end of a sector chain (xlrd's EOCSID)
_FREE = -1
_MSAT_SECTOR = -4

STORAGE, STREAM, ROOT = 1, 2, 5


class OleError(ValueError):
    """The container is damaged or crafted: something in it is reached twice or points
    outside the file."""


@dataclass(frozen=True)
class OleEntry:
    index: int
    name: str
    kind: int  # 1 storage, 2 stream, 5 root
    left: int
    right: int
    child: int
    start: int
    size: int


@dataclass
class OleDirectory:
    entries: list[OleEntry]  # every entry reachable from the root
    top_level: list[OleEntry]  # the root storage's own children
    sector_size: int
    mini_cutoff: int
    fat: list[int] = field(repr=False)
    mini_fat: list[int] = field(repr=False)

    def names(self) -> set[str]:
        return {entry.name.lower() for entry in self.entries}

    def check_chain(self, entry: OleEntry) -> None:
        """Refuse a stream whose sector chain loops or leaves its table. A stream under the
        cutoff (an empty one included) lives in the mini stream, as xlrd reads it."""

        table = self.fat if entry.size >= self.mini_cutoff else self.mini_fat
        _walk(table, entry.start, len(table), f"stream {entry.name!r}")


def _walk(table: list[int], start: int, limit: int, what: str) -> list[int]:
    """The sectors of a chain, each at most once and all inside ``limit``."""

    sectors: list[int] = []
    seen: set[int] = set()
    sector = start
    while sector >= 0:
        if sector >= limit or sector >= len(table) or sector in seen:
            raise OleError(f"The {what} chain is damaged.")
        seen.add(sector)
        sectors.append(sector)
        sector = table[sector]
    return sectors


def read_directory(data: bytes) -> OleDirectory:
    """Read and check an OLE2 file's directory. Raises ``OleError``."""

    if len(data) < 512 or data[:8] != SIGNATURE or data[28:30] != b"\xfe\xff":
        raise OleError("Not an OLE2 compound file.")
    shift, mini_shift = struct.unpack("<HH", data[30:34])
    if shift > 20:  # as xlrd: a preposterous sector size is read as 512
        shift = 9
    sector_size = 1 << shift
    (_fat_count, dir_start, _unused, mini_cutoff, mini_fat_start, mini_fat_count, difat_start,
     difat_count) = struct.unpack("<8i", data[44:76])
    sectors = -(-(len(data) - 512) // sector_size)
    per_sector = sector_size // 4

    def sector(index: int) -> tuple[int, ...]:
        chunk = data[512 + index * sector_size: 512 + (index + 1) * sector_size]
        if len(chunk) < sector_size:
            raise OleError("The file is truncated.")
        return struct.unpack(f"<{per_sector}i", chunk)

    # The sectors holding the allocation table: 109 in the header, then the DIFAT chain.
    fat_sectors = list(struct.unpack("<109i", data[76:512]))
    if not (difat_count == 0 and difat_start in (_END, _FREE, 0)):
        seen: set[int] = set()
        index = difat_start
        while index not in (_END, _FREE, _MSAT_SECTOR):
            if not 0 <= index < sectors or index in seen:
                raise OleError("The allocation table's chain is damaged.")
            seen.add(index)
            *more, index = sector(index)
            fat_sectors += more
    fat: list[int] = []
    used: set[int] = set()
    for index in fat_sectors:
        if index in (_FREE, _END) or index >= sectors:  # xlrd skips these too
            continue
        if index < -2 or index in used:
            raise OleError("The allocation table is damaged.")
        used.add(index)
        fat += sector(index)

    directory = b"".join(data[512 + s * sector_size: 512 + (s + 1) * sector_size]
                         for s in _walk(fat, dir_start, sectors, "directory"))
    if len(directory) // 128 > MAX_ENTRIES:
        raise OleError("The directory has too many entries.")
    raw: list[OleEntry] = []
    for offset in range(0, len(directory) - 127, 128):
        record = directory[offset:offset + 128]
        name_size, kind, _colour, left, right, child = struct.unpack("<HBBiii", record[64:80])
        start, size = struct.unpack("<ii", record[116:124])
        name = record[:max(0, min(name_size, 64) - 2)].decode("utf-16-le", errors="replace")
        raw.append(OleEntry(len(raw), name, kind, left, right, child, start, size))
    if not raw or raw[0].kind != ROOT:
        raise OleError("The directory has no root entry.")

    # The tree, along the links xlrd follows (siblings, and a storage's children), once each.
    reached: list[OleEntry] = []
    top_level: list[OleEntry] = []
    visited = {0}
    pending = [(0, raw[0].child)]
    while pending:
        parent, index = pending.pop()
        if index < 0:
            continue
        if index >= len(raw) or index in visited:
            raise OleError("The directory tree is damaged (an entry is reached twice).")
        visited.add(index)
        entry = raw[index]
        reached.append(entry)
        if parent == 0:
            top_level.append(entry)
        pending += [(parent, entry.left), (parent, entry.right)]
        if entry.kind == STORAGE:
            pending.append((index, entry.child))

    mini_fat: list[int] = []
    root = raw[0]
    if root.size > 0 and root.start >= 0:  # as xlrd: no mini stream, no mini table
        _walk(fat, root.start, sectors, "mini stream")
        index, count, seen = mini_fat_start, mini_fat_count, set()
        while index >= 0 and count > 0:
            if index >= sectors or index >= len(fat) or index in seen:
                raise OleError("The mini allocation table's chain is damaged.")
            seen.add(index)
            mini_fat += sector(index)
            index, count = fat[index], count - 1
    return OleDirectory(reached, top_level, sector_size, mini_cutoff, fat, mini_fat)
