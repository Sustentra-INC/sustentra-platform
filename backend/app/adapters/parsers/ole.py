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

``OleFile`` reads the streams of a compound file for the readers that do not go through xlrd
(Word 97-2003 ``.doc``, Outlook ``.msg``). It addresses sectors as MS-CFB does (``cfb=True``:
sector N at ``(N + 1) * size``, which is what 4096-byte-sector files need) and claims every
sector it reads: a sector belongs to one stream, or to the FAT, DIFAT, directory or mini FAT,
so streams that overlap, chains that loop and directories that share children cannot make a
reader do the same work twice. ``.xls`` keeps ``read_directory(data)`` with xlrd's addressing.
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
    root: OleEntry | None = None  # the root entry (raw[0]), whose chain is the mini stream
    parents: dict[int, int] = field(default_factory=dict, repr=False)  # entry index -> its storage's index (0 = root)
    reserved: frozenset[int] = frozenset()  # sectors of the FAT, DIFAT, directory and mini FAT chains
    base: int = 512  # file offset of sector 0
    sector_count: int = 0
    mini_sector_size: int = 64

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


def read_directory(data: bytes, *, cfb: bool = False) -> OleDirectory:
    """Read and check an OLE2 file's directory. Raises ``OleError``.

    ``cfb=False`` addresses sector N at ``512 + N * size``, as xlrd does (what the ``.xls``
    reader needs: the same container xlrd then reads). ``cfb=True`` addresses it as MS-CFB
    does, at ``(N + 1) * size``: the same for 512-byte sectors, and correct for version 4
    files (4096-byte sectors, a header padded to a whole sector), which xlrd misreads."""

    if len(data) < 512 or data[:8] != SIGNATURE or data[28:30] != b"\xfe\xff":
        raise OleError("Not an OLE2 compound file.")
    shift, mini_shift = struct.unpack("<HH", data[30:34])
    # Real files use a sector shift of 9 (512 bytes) or 12 (4096), and a mini shift of 6.
    # A shift under 7 gives a sector too small to hold even one 4-byte entry (shift 0 and 1
    # give per_sector 0, which would make struct.unpack raise); a huge one is absurd.
    if not 7 <= shift <= 20 or not 2 <= mini_shift <= shift:
        raise OleError("The compound file header has an invalid sector size.")
    sector_size = 1 << shift
    base = sector_size if cfb else 512
    (_fat_count, dir_start, _unused, mini_cutoff, mini_fat_start, mini_fat_count, difat_start,
     difat_count) = struct.unpack("<8i", data[44:76])
    sectors = -(-(len(data) - base) // sector_size)
    per_sector = sector_size // 4

    def sector(index: int) -> tuple[int, ...]:
        chunk = data[base + index * sector_size: base + (index + 1) * sector_size]
        if len(chunk) < sector_size:
            raise OleError("The file is truncated.")
        return struct.unpack(f"<{per_sector}i", chunk)

    # The sectors holding the allocation table: 109 in the header, then the DIFAT chain.
    fat_sectors = list(struct.unpack("<109i", data[76:512]))
    difat_chain: set[int] = set()
    if not (difat_count == 0 and difat_start in (_END, _FREE, 0)):
        index = difat_start
        while index not in (_END, _FREE, _MSAT_SECTOR):
            if not 0 <= index < sectors or index in difat_chain:
                raise OleError("The allocation table's chain is damaged.")
            difat_chain.add(index)
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

    directory_chain = _walk(fat, dir_start, sectors, "directory")
    directory = b"".join(data[base + s * sector_size: base + (s + 1) * sector_size] for s in directory_chain)
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
    parents: dict[int, int] = {}
    pending = [(0, raw[0].child)]
    while pending:
        parent, index = pending.pop()
        if index < 0:
            continue
        if index >= len(raw) or index in visited:
            raise OleError("The directory tree is damaged (an entry is reached twice).")
        visited.add(index)
        parents[index] = parent
        entry = raw[index]
        reached.append(entry)
        if parent == 0:
            top_level.append(entry)
        pending += [(parent, entry.left), (parent, entry.right)]
        if entry.kind == STORAGE:
            pending.append((index, entry.child))

    mini_fat: list[int] = []
    mini_fat_chain: set[int] = set()
    root = raw[0]
    if root.size > 0 and root.start >= 0:  # as xlrd: no mini stream, no mini table
        _walk(fat, root.start, sectors, "mini stream")
        index, count = mini_fat_start, mini_fat_count
        while index >= 0 and count > 0:
            if index >= sectors or index >= len(fat) or index in mini_fat_chain:
                raise OleError("The mini allocation table's chain is damaged.")
            mini_fat_chain.add(index)
            mini_fat += sector(index)
            index, count = fat[index], count - 1
    return OleDirectory(
        reached, top_level, sector_size, mini_cutoff, fat, mini_fat, root=root, parents=parents,
        reserved=frozenset(used | difat_chain | set(directory_chain) | mini_fat_chain), base=base,
        sector_count=sectors, mini_sector_size=1 << mini_shift)


_SHARED = "Two streams share the same sectors."


class OleFile:
    """A compound file's streams; every sector is read at most once.

    Each sector a read touches is claimed: the FAT, DIFAT, directory and mini FAT chains start
    out claimed (``OleDirectory.reserved``), and a stream may only walk sectors nobody has
    claimed, so streams that overlap, chains that loop and entries that share a start cannot
    make the work grow faster than the file. A stream is walked for exactly the sectors its
    size needs (never to the end of its chain), claiming as it goes, so a refused stream still
    leaves its sectors claimed and a second attempt (or a second entry sharing them) is refused
    at once. A stream read twice is served from a cache and claims nothing more.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._view = memoryview(data)
        self.directory = read_directory(data, cfb=True)
        self._claimed: set[int] = set(self.directory.reserved)  # FAT sectors
        self._mini_claimed: set[int] = set()  # mini sectors
        self._streams: dict[int, bytes] = {}
        self._refused: dict[int, str] = {}
        self._mini_stream: bytes | None = None  # the container of the small streams, read once
        self._mini_refusal: str | None = None
        self._kids: dict[int, list[OleEntry]] | None = None
        self._by_name: dict[int, dict[str, OleEntry]] = {}

    # --- the storage tree --------------------------------------------------------------------
    def _tree(self) -> dict[int, list[OleEntry]]:
        if self._kids is None:
            kids: dict[int, list[OleEntry]] = {}
            for entry in self.directory.entries:
                kids.setdefault(self.directory.parents[entry.index], []).append(entry)
            for index, group in kids.items():
                group.sort(key=lambda entry: (entry.name.upper(), entry.index))
                names: dict[str, OleEntry] = {}
                for entry in group:
                    names.setdefault(entry.name.upper(), entry)  # sorted by index within a name: the lowest wins
                self._by_name[index] = names
            self._kids = kids
        return self._kids

    def children(self, storage: OleEntry) -> list[OleEntry]:
        """The entries directly inside a storage (or the root), by upper-cased name, then index."""

        if storage.kind not in (STORAGE, ROOT):
            return []
        return list(self._tree().get(storage.index, ()))

    def child(self, storage: OleEntry, name: str) -> OleEntry | None:
        """The entry inside ``storage`` called ``name`` (case-insensitive); the lowest index if
        several have the same name."""

        if storage.kind not in (STORAGE, ROOT):
            return None
        self._tree()
        return self._by_name.get(storage.index, {}).get(name.upper())

    # --- streams -------------------------------------------------------------------------------
    def read(self, entry: OleEntry) -> bytes:
        """A stream's bytes. Raises ``OleError`` for a storage, an impossible size, a chain that
        is cut short, loops or leaves the file, or sectors another stream (or the file's own
        tables) already claimed."""

        cached = self._streams.get(entry.index)
        if cached is not None:
            return cached
        if entry.index in self._refused:
            raise OleError(self._refused[entry.index])
        try:
            content = self._read(entry)
        except OleError as exc:
            self._refused[entry.index] = str(exc)
            raise
        self._streams[entry.index] = content
        return content

    def _read(self, entry: OleEntry) -> bytes:
        if entry.kind != STREAM:
            raise OleError("This entry is not a stream.")
        if not 0 <= entry.size <= len(self._data):
            raise OleError("A stream's size does not fit the file.")
        if entry.size == 0:
            return b""
        if entry.size >= self.directory.mini_cutoff:
            return self._read_sectors(entry.start, entry.size)
        return self._read_mini_sectors(entry.start, entry.size)

    def _read_sectors(self, start: int, size: int) -> bytes:
        """``size`` bytes from the FAT chain at ``start``: exactly the sectors they need."""

        directory = self.directory
        sector_size, fat, count = directory.sector_size, directory.fat, -(-size // directory.sector_size)
        walked: list[int] = []
        seen: set[int] = set()
        sector = start
        while True:
            if sector < 0:
                raise OleError("A stream's sector chain is truncated.")
            if sector >= directory.sector_count:
                raise OleError("A stream's sector chain leaves the file.")
            if sector in seen:
                raise OleError("A stream's sector chain loops.")
            if sector in self._claimed:
                raise OleError(_SHARED)
            seen.add(sector)
            self._claimed.add(sector)
            walked.append(sector)
            if len(walked) == count:
                break
            if sector >= len(fat):
                raise OleError("A stream's sector chain leaves the allocation table.")
            sector = fat[sector]
        base = directory.base
        content = b"".join(self._view[base + s * sector_size: base + (s + 1) * sector_size] for s in walked)
        if len(content) < size:  # the file ends inside the stream's last sector
            raise OleError("A stream's sector chain is truncated.")
        return content[:size]

    def _container(self) -> bytes:
        """The mini stream (the root's FAT chain, cut to the root's size), read once."""

        if self._mini_refusal is not None:
            raise OleError(self._mini_refusal)
        if self._mini_stream is None:
            root = self.directory.root
            try:
                if root is None or not 0 <= root.size <= len(self._data):
                    raise OleError("The mini stream's size does not fit the file.")
                self._mini_stream = self._read_sectors(root.start, root.size) if root.size else b""
            except OleError as exc:
                self._mini_refusal = str(exc)
                raise
        return self._mini_stream

    def _read_mini_sectors(self, start: int, size: int) -> bytes:
        """``size`` bytes from the mini FAT chain at ``start``, each mini sector wholly inside
        the mini stream."""

        container = self._container()
        step, mini_fat = self.directory.mini_sector_size, self.directory.mini_fat
        count = -(-size // step)
        walked: list[int] = []
        seen: set[int] = set()
        sector = start
        while True:
            if sector < 0:
                raise OleError("A stream's sector chain is truncated.")
            if (sector + 1) * step > len(container):
                raise OleError("A stream's sector chain leaves the mini stream.")
            if sector in seen:
                raise OleError("A stream's sector chain loops.")
            if sector in self._mini_claimed:
                raise OleError(_SHARED)
            seen.add(sector)
            self._mini_claimed.add(sector)
            walked.append(sector)
            if len(walked) == count:
                break
            if sector >= len(mini_fat):
                raise OleError("A stream's sector chain leaves the allocation table.")
            sector = mini_fat[sector]
        return b"".join(container[s * step:(s + 1) * step] for s in walked)[:size]
