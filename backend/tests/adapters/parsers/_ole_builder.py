"""OLE2 compound files with a storage tree, written byte by byte by the tests themselves.

``_xls_builder.ole_file`` writes the flat files the .xls tests need. The .doc and .msg
readers need more: nested storages, version 4 files (4096-byte sectors) and hostile shapes
that only exist around streams (two entries sharing a start sector, a chain that loops
inside its own length). ``ole_tree`` writes those, to [MS-CFB] (the Compound File Binary
format); the constants are literal values with the section that defines them.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

Tree = dict[str, "bytes | Tree"]  # bytes = a stream, dict = a storage

SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")  # [MS-CFB] 2.2 header signature
FREESECT, ENDOFCHAIN, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD  # [MS-CFB] 2.1 special sector numbers
NOSTREAM = 0xFFFFFFFF  # [MS-CFB] 2.6.1 "no sibling" / "no child"
STORAGE, STREAM, ROOT = 0x01, 0x02, 0x05  # [MS-CFB] 2.6.1 object types
MINI_SECTOR, MINI_CUTOFF = 64, 4096  # [MS-CFB] 2.2 mini sector shift 6, mini stream cutoff 0x00001000
MAX_HEADER_FAT_SECTORS = 109  # [MS-CFB] 2.2 DIFAT array in the header


@dataclass(eq=False)  # nodes are compared by identity: a directory can hold thousands
class _Node:
    name: str
    path: str
    data: bytes | None  # None: a storage
    children: list[_Node] = field(default_factory=list)
    index: int = 0  # the directory entry's index
    right: int = NOSTREAM  # the next entry in its storage's chain of siblings

    @property
    def is_big(self) -> bool:
        return self.data is not None and len(self.data) >= MINI_CUTOFF

    @property
    def is_small(self) -> bool:
        return self.data is not None and 0 < len(self.data) < MINI_CUTOFF


def _nodes(tree: Tree, prefix: str = "") -> list[_Node]:
    result = []
    for name, content in tree.items():
        assert 0 < len(name) <= 31, "a name is at most 31 UTF-16 characters"  # [MS-CFB] 2.6.1
        path = f"{prefix}{name}"
        if isinstance(content, dict):
            result.append(_Node(name, path, None, _nodes(content, path + "/")))
        else:
            result.append(_Node(name, path, content))
    return result


def _dir_entry(name: str, kind: int, start: int, size: int, *, left: int = NOSTREAM, right: int = NOSTREAM,
               child: int = NOSTREAM) -> bytes:
    """One 128-byte directory entry [MS-CFB] 2.6.1."""

    encoded = (name.encode("utf-16-le") + b"\x00\x00") if name else b""
    colour = 1 if name else 0  # black; an unused entry is all zero
    return (encoded.ljust(64, b"\x00") + struct.pack("<HBBIII", len(encoded), kind, colour, left, right, child)
            + bytes(16 + 4 + 8 + 8)  # CLSID, state bits, creation and modified times
            + struct.pack("<IQ", start, size))


def ole_tree(tree: Tree, *, sector_shift: int = 9, dag: bool = False, loop: str | None = None,
             share: tuple[str, str] | None = None, mini_loop: str | None = None) -> bytes:
    """A compound file holding ``tree``: streams (``bytes``) and storages (``dict``), nested.

    ``sector_shift`` 9 writes a version 3 file (512-byte sectors), 12 a version 4 file (4096-byte
    sectors, the header padded to a whole sector). A stream under 4096 bytes lives in the mini
    stream, as Office writes it. There is no DIFAT: the allocation table must fit the header's
    109 entries (about 7 MB with 512-byte sectors, about 450 MB with 4096-byte ones, so large
    hostile files use ``sector_shift=12``).

    Each storage's children are a chain of right siblings, the storage's ``child`` pointing at
    the first. Hostile shapes, with paths as ``"/"``-joined names:

    - ``dag``: every entry in a chain is also the *left* sibling of the one before it, so the
      next entry is reachable twice (a chain of at least two entries is needed).
    - ``loop``: a stream of 3 sectors or more whose second sector points back to its first.
      A reader that takes exactly the sectors the size needs meets the loop inside that length.
    - ``mini_loop``: the same in the mini FAT, for a stream of 3 mini sectors (129 bytes) or more.
    - ``share=(a, b)``: stream ``b``'s directory entry gets the start sector of stream ``a``
      (both big, or both small). ``b``'s own sectors stay in the file, unreferenced.
    """

    assert sector_shift in (9, 12), "sector shift 9 is version 3, 12 is version 4"
    sector_size = 1 << sector_shift
    per_fat = sector_size // 4
    root = _Node("Root Entry", "", None, _nodes(tree))

    # The directory: breadth first, so the children of a storage are consecutive entries.
    ordered = [root]
    for storage in ordered:
        for child in storage.children:
            child.index = len(ordered)
            ordered.append(child)
        for before, after in zip(storage.children, storage.children[1:]):
            before.right = after.index
    by_path = {node.path: node for node in ordered}
    streams = [node for node in ordered if node.data is not None]

    # The mini stream: every small stream, in directory order, in 64-byte sectors.
    mini_fat: list[int] = []
    mini_data: list[bytes] = []
    mini_start: dict[str, int] = {}
    for node in streams:
        if node.is_small:
            assert node.data is not None
            count = math.ceil(len(node.data) / MINI_SECTOR)
            first = len(mini_fat)
            mini_start[node.path] = first
            mini_fat += list(range(first + 1, first + count)) + [ENDOFCHAIN]
            mini_data.append(node.data.ljust(count * MINI_SECTOR, b"\x00"))
            if node.path == mini_loop:
                assert count >= 3, "a mini loop needs a stream of 3 mini sectors or more"
                mini_fat[first + 1] = first  # the second mini sector points back to the first
    assert mini_loop is None or mini_loop in mini_start, "mini_loop must name a small stream"
    mini_stream = b"".join(mini_data)

    # Sector counts, then the number of allocation table sectors that can hold them all.
    dir_sectors = math.ceil(len(ordered) / (sector_size // 128))
    mini_fat_sectors = math.ceil(len(mini_fat) / per_fat)
    mini_stream_sectors = math.ceil(len(mini_stream) / sector_size)
    big = {node.path: math.ceil(len(node.data) / sector_size) for node in streams if node.data and node.is_big}
    rest = dir_sectors + mini_fat_sectors + mini_stream_sectors + sum(big.values())
    fat_sectors = 1
    while fat_sectors * per_fat < fat_sectors + rest:
        fat_sectors += 1
    assert fat_sectors <= MAX_HEADER_FAT_SECTORS, "no DIFAT sectors: use sector_shift=12 for large files"

    fat: list[int] = [FATSECT] * fat_sectors

    def chain(count: int) -> int:
        first = len(fat)
        fat.extend(list(range(first + 1, first + count)) + [ENDOFCHAIN])
        return first

    dir_start = chain(dir_sectors)
    mini_fat_start = chain(mini_fat_sectors) if mini_fat_sectors else ENDOFCHAIN
    mini_stream_start = chain(mini_stream_sectors) if mini_stream_sectors else ENDOFCHAIN
    big_start: dict[str, int] = {}
    for node in streams:
        if node.path in big:
            big_start[node.path] = chain(big[node.path])
            if node.path == loop:
                assert big[node.path] >= 3, "a loop needs a stream of 3 sectors or more"
                fat[big_start[node.path] + 1] = big_start[node.path]  # the second sector points back to the first
    assert loop is None or loop in big_start, "loop must name a big stream"

    start: dict[str, int] = {**big_start, **mini_start}
    if share:
        donor, taker = (by_path[path] for path in share)
        assert donor.is_big == taker.is_big and donor.is_small == taker.is_small and donor.data and taker.data, (
            "share needs two streams of the same size class")
        start[taker.path] = start[donor.path]

    # The directory entries.
    entries: list[bytes] = []
    for node in ordered:
        right = node.right
        left = right if dag else NOSTREAM
        child = node.children[0].index if node.children else NOSTREAM
        if node is root:
            entries.append(_dir_entry(node.name, ROOT, mini_stream_start, len(mini_stream), child=child))
        elif node.data is None:
            entries.append(_dir_entry(node.name, STORAGE, 0, 0, left=left, right=right, child=child))
        else:
            entries.append(_dir_entry(node.name, STREAM, start.get(node.path, ENDOFCHAIN), len(node.data),
                                      left=left, right=right))
    unused = _dir_entry("", 0, 0, 0)
    entries += [unused] * (dir_sectors * (sector_size // 128) - len(entries))

    version = 3 if sector_shift == 9 else 4
    header = (SIGNATURE + bytes(16)  # [MS-CFB] 2.2: signature, CLSID
              + struct.pack("<HHHHH", 0x003E, version, 0xFFFE, sector_shift, 6) + bytes(6)
              + struct.pack("<IIIIIIIII", dir_sectors if version == 4 else 0, fat_sectors, dir_start, 0,
                            MINI_CUTOFF, mini_fat_start, mini_fat_sectors, ENDOFCHAIN, 0)
              + struct.pack("<109I", *(list(range(fat_sectors)) + [FREESECT] * (109 - fat_sectors))))
    fat += [FREESECT] * (fat_sectors * per_fat - len(fat))
    parts = [header.ljust(sector_size, b"\x00"), struct.pack(f"<{len(fat)}I", *fat), b"".join(entries)]
    if mini_fat_sectors:
        padded = mini_fat + [FREESECT] * (mini_fat_sectors * per_fat - len(mini_fat))
        parts.append(struct.pack(f"<{len(padded)}I", *padded))
    parts.append(mini_stream.ljust(mini_stream_sectors * sector_size, b"\x00"))
    for node in streams:
        if node.path in big and node.data is not None:
            parts.append(node.data.ljust(big[node.path] * sector_size, b"\x00"))
    return b"".join(parts)
