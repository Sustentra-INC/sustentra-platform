"""The OLE2 stream reader the .doc and .msg readers share: both sector layouts, the storage
tree, and "every sector is read at most once", so overlapping streams, looping chains and
directories shaped as DAGs cannot multiply the work.

Files are written by ``_ole_builder.ole_tree``. ``test_ole.py`` and ``test_ole_xls_pin.py``
cover ``read_directory(data)``, the call the .xls reader makes.
"""

from __future__ import annotations

import struct
import time
import tracemalloc
from collections.abc import Iterable
from typing import Any

import pytest

from backend.app.adapters.parsers import ole
from backend.app.adapters.parsers.ole import OleEntry, OleError, OleFile, read_directory
from backend.tests.adapters.parsers._ole_builder import ole_tree
from backend.tests.adapters.parsers._timing import budget
from backend.tests.adapters.parsers._xls_builder import xls_bytes

TREE: dict[str, Any] = {"Big": b"B" * 5000, "Small": b"s" * 100,
                        "Store": {"Inner": b"i" * 70, "Deeper": {"Leaf": b"L" * 4096}}}
CONTENT = {"Big": b"B" * 5000, "Small": b"s" * 100, "Store/Inner": b"i" * 70, "Store/Deeper/Leaf": b"L" * 4096}
SHARED = "share the same sectors"


# --- reading and patching a file ---------------------------------------------------------------
def _root(opened: OleFile) -> OleEntry:
    assert opened.directory.root is not None
    return opened.directory.root


def _entry(opened: OleFile, path: str) -> OleEntry:
    entry = _root(opened)
    for name in path.split("/"):
        found = opened.child(entry, name)
        assert found is not None, path
        entry = found
    return entry


def _header(data: bytes) -> tuple[int, int, int]:
    """The sector size, the directory's first sector and the mini FAT's first sector."""

    return (1 << struct.unpack("<H", data[30:32])[0], struct.unpack("<i", data[48:52])[0],
            struct.unpack("<i", data[60:64])[0])


def _patched(data: bytes, entries: OleEntry | int | Iterable[OleEntry | int], *, start: int | None = None,
             size: int | None = None) -> bytes:
    """``data`` with the start sector and/or size (low dword) of some directory entries changed.
    The builder writes the directory in one run of sectors, and sector N lies at ``(N + 1) * size``."""

    sector_size, dir_start, _ = _header(data)
    per_sector = sector_size // 128
    patched = bytearray(data)
    for entry in [entries] if isinstance(entries, (OleEntry, int)) else entries:
        index = entry if isinstance(entry, int) else entry.index
        offset = sector_size * (1 + dir_start + index // per_sector) + index % per_sector * 128
        if start is not None:
            patched[offset + 116: offset + 120] = struct.pack("<i", start)
        if size is not None:
            patched[offset + 120: offset + 124] = struct.pack("<I", size)
    return bytes(patched)


def _read_all(data: bytes) -> dict[str, bytes]:
    opened = OleFile(data)
    return {path: opened.read(_entry(opened, path)) for path in CONTENT}


def _read(data: bytes, path: str) -> bytes:
    """One stream of a file, opened afresh (so the entry is the one the file holds)."""

    opened = OleFile(data)
    return opened.read(_entry(opened, path))


# --- the streams of both versions ----------------------------------------------------------------
def test_big_small_and_nested_streams_are_read() -> None:
    data = ole_tree(TREE)
    assert _read_all(data) == CONTENT
    opened = OleFile(data)
    assert [entry.name for entry in opened.children(_root(opened))] == ["Big", "Small", "Store"]
    store = _entry(opened, "Store")
    assert opened.child(store, "INNER") == _entry(opened, "Store/Inner")
    assert [entry.name for entry in opened.children(store)] == ["Deeper", "Inner"]


def test_version_4_files_are_read() -> None:
    data = ole_tree(TREE, sector_shift=12)
    assert data[26:28] == b"\x04\x00" and len(data) % 4096 == 0
    assert _read_all(data) == CONTENT


def test_the_directory_records_what_the_stream_reader_needs() -> None:
    for shift, reserved in ((9, {0, 1, 2, 3}), (12, {0, 1, 2})):  # the FAT, the directory, the mini FAT
        data = ole_tree(TREE, sector_shift=shift)
        directory = OleFile(data).directory
        names = {0: "Root Entry", **{entry.index: entry.name for entry in directory.entries}}
        assert {entry.name: names[directory.parents[entry.index]] for entry in directory.entries} == {
            "Big": "Root Entry", "Small": "Root Entry", "Store": "Root Entry", "Inner": "Store",
            "Deeper": "Store", "Leaf": "Deeper"}
        assert directory.root is not None and directory.root.name == "Root Entry"
        assert directory.reserved == reserved
        assert (directory.base, directory.sector_size) == (1 << shift, 1 << shift)
        assert directory.sector_count == (len(data) - (1 << shift)) // (1 << shift)
        assert directory.mini_sector_size == 64


def test_an_empty_stream_reads_empty() -> None:
    opened = OleFile(ole_tree({"E": b""}))
    assert opened.read(_entry(opened, "E")) == b""


def test_reading_a_stream_twice_is_not_an_overlap() -> None:
    opened = OleFile(ole_tree(TREE))
    for path in ("Big", "Small", "Store/Inner"):  # a big stream, and two in the mini stream
        entry = _entry(opened, path)
        assert opened.read(entry) == opened.read(entry) == CONTENT[path]
    assert opened.read(_entry(opened, "Store/Deeper/Leaf")) == CONTENT["Store/Deeper/Leaf"]


@pytest.mark.parametrize("size", [5000, 100], ids=["big", "mini"])
def test_streams_sharing_sectors_are_refused(size: int) -> None:
    opened = OleFile(ole_tree({"A": b"a" * size, "B": b"b" * size}, share=("A", "B")))
    a, b = _entry(opened, "A"), _entry(opened, "B")
    assert opened.read(a) == b"a" * size
    with pytest.raises(OleError, match=SHARED) as refused:
        opened.read(b)
    assert str(refused.value) == "Two streams share the same sectors."
    with pytest.raises(OleError, match=SHARED):  # a refused stream stays refused, the same way
        opened.read(b)
    assert opened.read(a) == b"a" * size


def test_the_first_stream_read_keeps_its_sectors_whichever_it_is() -> None:
    opened = OleFile(ole_tree({"A": b"a" * 5000, "B": b"b" * 5000}, share=("A", "B")))
    assert opened.read(_entry(opened, "B")) == b"a" * 5000  # B's entry points at A's sectors
    with pytest.raises(OleError, match=SHARED):
        opened.read(_entry(opened, "A"))


# --- sectors that belong to the file's own tables ------------------------------------------------
def _with_difat_sector(data: bytes) -> tuple[bytes, int]:
    """A version 3 file with one DIFAT sector (listing nothing) appended and named in the header."""

    index = (len(data) - 512) // 512
    sector = struct.pack("<128I", *([0xFFFFFFFF] * 127), 0xFFFFFFFE)
    return data[:68] + struct.pack("<ii", index, 1) + data[76:] + sector, index


def test_a_stream_pointing_into_the_directory_is_refused() -> None:
    data = ole_tree({"A": b"a" * 5000, "B": b"b" * 100, "Pad": b"p" * 3000})
    _, dir_start, mini_fat_start = _header(data)
    fat_start = struct.unpack("<i", data[76:80])[0]
    difat_file, difat_sector = _with_difat_sector(data)
    for label, file, sector in (("directory", data, dir_start), ("FAT", data, fat_start),
                                ("mini FAT", data, mini_fat_start), ("DIFAT", difat_file, difat_sector)):
        opened = OleFile(file)
        assert sector in opened.directory.reserved, label
        with pytest.raises(OleError, match=SHARED):
            _read(_patched(file, _entry(opened, "A"), start=sector), "A")


def test_the_mini_stream_is_claimed_once_and_by_the_first_to_need_it() -> None:
    data = ole_tree({"Big": b"B" * 5000, "S1": b"1" * 100, "S2": b"2" * 100})
    opened = OleFile(data)
    container = _root(opened).start
    assert opened.read(_entry(opened, "S1")) == b"1" * 100
    assert opened.read(_entry(opened, "S2")) == b"2" * 100  # the container is not claimed a second time
    inside = OleFile(_patched(data, _entry(opened, "Big"), start=container))
    assert inside.read(_entry(inside, "S1")) == b"1" * 100  # the mini stream was read first...
    with pytest.raises(OleError, match=SHARED):  # ...so a big stream cannot start inside it
        inside.read(_entry(inside, "Big"))
    # The other way round: the big stream's chain ends inside the mini stream, so it fails,
    # but it claimed the sector on its way: the mini stream is no longer anyone's to read.
    inside = OleFile(_patched(data, _entry(opened, "Big"), start=container))
    with pytest.raises(OleError, match="truncated"):
        inside.read(_entry(inside, "Big"))
    with pytest.raises(OleError, match=SHARED):
        inside.read(_entry(inside, "S1"))


# --- chains --------------------------------------------------------------------------------------
@pytest.mark.parametrize("options, looping, other", [({"loop": "A"}, "A", "S"), ({"mini_loop": "S"}, "S", "A")],
                         ids=["big", "mini"])
def test_looping_chains_are_refused(options: dict[str, str], looping: str, other: str) -> None:
    content = {"A": b"a" * 5000, "S": b"s" * 300}
    opened = OleFile(ole_tree(content, **options))
    with pytest.raises(OleError, match="loops"):
        opened.read(_entry(opened, looping))
    assert opened.read(_entry(opened, other)) == content[other]  # the other stream is still sound


def test_a_stream_longer_than_its_chain_is_refused() -> None:
    # The sizes stay inside the file (a size over the file's length is refused earlier, and
    # would hide this check): the chains simply end before the sectors the sizes need.
    data = ole_tree({"Big": b"B" * 5000, "S": b"s" * 100, "Pad": b"p" * 20_000})
    opened = OleFile(data)
    assert 7000 < len(data)
    for path, size in (("Big", 7000), ("S", 1000)):
        cut = OleFile(_patched(data, _entry(opened, path), size=size))
        with pytest.raises(OleError, match="truncated"):
            cut.read(_entry(cut, path))
        with pytest.raises(OleError, match="truncated"):  # refused again the same way, not as "shared"
            cut.read(_entry(cut, path))


def test_a_chain_longer_than_the_size_is_read_only_as_far_as_the_size_needs() -> None:
    data = ole_tree({"Big": b"B" * 8000, "Pad": b"p" * 3000})
    opened = OleFile(data)
    assert _read(_patched(data, _entry(opened, "Big"), size=5000), "Big") == b"B" * 5000


def test_a_chain_that_leaves_the_file_is_refused() -> None:
    data = ole_tree({"Big": b"B" * 5000, "S": b"s" * 100})
    opened = OleFile(data)
    for start in (opened.directory.sector_count, 10_000, -1, -2):
        with pytest.raises(OleError):
            _read(_patched(data, _entry(opened, "Big"), start=start), "Big")


def test_a_mini_sector_outside_the_mini_stream_is_refused() -> None:
    data = ole_tree({"S": b"s" * 100, "T": b"t" * 100})  # the mini stream: 4 mini sectors, 256 bytes
    opened = OleFile(data)
    assert _root(opened).size == 256
    for patched in (_patched(data, 0, size=64),  # the mini stream is cut to one mini sector
                    _patched(data, 0, size=0),  # there is no mini stream
                    _patched(data, _entry(opened, "S"), start=4),  # S starts past its end
                    _patched(data, _entry(opened, "S"), start=3)):  # S's second mini sector would be past it
        with pytest.raises(OleError, match="mini stream|truncated"):
            _read(patched, "S")


def test_a_mini_stream_that_cannot_be_read_refuses_every_small_stream() -> None:
    data = ole_tree({"S": b"s" * 100, "T": b"t" * 100, "Big": b"B" * 5000})
    opened = OleFile(data)
    cut = OleFile(_patched(data, 0, size=len(data) + 1))  # a mini stream larger than the file
    for path in ("S", "T"):
        with pytest.raises(OleError, match="mini stream's size"):
            cut.read(_entry(cut, path))
    assert cut.read(_entry(opened, "Big")) == b"B" * 5000  # the big streams are not affected


def test_a_chain_that_runs_past_its_allocation_table_is_refused() -> None:
    # The header lists only the first of the two allocation table sectors the file needs, so
    # the table stops at sector 127 while the stream's chain goes on to sector 128.
    data = ole_tree({"A": b"a" * 70_000, "B": b"b" * 5000})
    short = bytearray(data)
    short[80:84] = struct.pack("<i", -1)
    assert len(read_directory(data, cfb=True).fat) == 256 and len(read_directory(bytes(short), cfb=True).fat) == 128
    with pytest.raises(OleError, match="allocation table"):
        _read(bytes(short), "A")
    # The same for a mini stream larger than its mini FAT: 300 small streams need 3 mini FAT
    # sectors; the header names one.
    data = ole_tree({f"S{n:03d}": b"s" * 100 for n in range(300)})
    short = bytearray(data)
    short[64:68] = struct.pack("<i", 1)
    opened = OleFile(bytes(short))
    assert len(opened.directory.mini_fat) == 128 < 600
    with pytest.raises(OleError, match="allocation table"):
        opened.read(_entry(opened, "S299"))
    assert opened.read(_entry(opened, "S000")) == b"s" * 100


def test_a_file_cut_inside_its_last_sector_reads_what_is_there() -> None:
    data = ole_tree({"Big": b"B" * 5000})  # the last sector holds 392 bytes of the stream, then padding
    assert _read(data[:-100], "Big") == b"B" * 5000  # a writer that did not pad it
    with pytest.raises(OleError, match="truncated"):
        _read(data[:-200], "Big")


# --- entries that cannot be streams --------------------------------------------------------------
@pytest.mark.parametrize("size", [lambda data: 0xFFFFFFFF, lambda data: len(data) + 1], ids=["negative", "huge"])
def test_negative_and_huge_sizes_are_refused(size) -> None:
    data = ole_tree({"Big": b"B" * 5000, "S": b"s" * 100})
    opened = OleFile(data)
    for path in ("Big", "S"):
        with pytest.raises(OleError, match="size"):
            _read(_patched(data, _entry(opened, path), size=size(data)), path)


def test_a_storage_is_not_read_as_a_stream() -> None:
    opened = OleFile(ole_tree(TREE))
    for storage in (_entry(opened, "Store"), _root(opened)):
        with pytest.raises(OleError, match="not a stream"):
            opened.read(storage)
    assert opened.children(_entry(opened, "Big")) == [] and opened.child(_entry(opened, "Big"), "x") is None


def test_a_dag_directory_is_refused() -> None:
    with pytest.raises(OleError, match="reached twice"):
        OleFile(ole_tree({"A": b"a" * 100, "B": b"b" * 100, "C": {"D": b"d", "E": b"e"}}, dag=True))
    with pytest.raises(OleError, match="reached twice"):  # inside a storage too
        OleFile(ole_tree({"C": {"D": b"d", "E": b"e"}}, dag=True))


def test_names_are_sorted_and_found_ignoring_case_lowest_index_first() -> None:
    opened = OleFile(ole_tree({"zeta": b"z", "Alpha": b"1", "alpha": b"2", "Mid": {"x": b"x"}}))
    root = _root(opened)
    assert [entry.name for entry in opened.children(root)] == ["Alpha", "alpha", "Mid", "zeta"]
    found = opened.child(root, "ALPHA")
    assert found is not None and found.name == "Alpha" and opened.read(found) == b"1"  # the lower index
    assert opened.child(root, "mid") == _entry(opened, "Mid") and opened.child(root, "nope") is None
    swapped = OleFile(ole_tree({"alpha": b"2", "Alpha": b"1"}))
    found = swapped.child(_root(swapped), "Alpha")
    assert found is not None and found.name == "alpha"


# --- .xls keeps its addressing ---------------------------------------------------------------------
def _fields(directory: ole.OleDirectory) -> tuple[Any, ...]:
    return (directory.entries, directory.top_level, directory.sector_size, directory.mini_cutoff, directory.fat,
            directory.mini_fat)


def test_xls_directory_reading_is_unchanged() -> None:
    # With 512-byte sectors the two addressings agree; test_ole_xls_pin.py holds the values the
    # .xls reader gets, captured before this reader existed. Here: a version 4 file is where
    # they part, and cfb=False (xlrd's addressing) must keep misreading it as it always did.
    for data in (xls_bytes({"S": [["a", 1]]}), ole_tree(TREE)):
        assert _fields(read_directory(data)) == _fields(read_directory(data, cfb=True))
    wide = ole_tree(TREE, sector_shift=12)
    correct = read_directory(wide, cfb=True)
    assert [entry.name for entry in correct.top_level] == ["Big", "Small", "Store"]
    try:
        legacy: Any = _fields(read_directory(wide))
    except OleError:
        legacy = None
    assert legacy != _fields(correct)
    assert read_directory(ole_tree(TREE)).base == 512 and correct.base == 4096


# --- bounded work ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def many_big_streams() -> bytes:
    return ole_tree({f"S{n:04d}": bytes([n % 251]) * 8192 for n in range(2500)}, sector_shift=12)  # about 20 MB


def test_reading_every_stream_is_bounded_by_the_file(many_big_streams: bytes) -> None:
    started = time.perf_counter()
    opened = OleFile(many_big_streams)
    read = [opened.read(entry) for entry in opened.children(_root(opened))]
    assert time.perf_counter() - started < budget(0.5)  # about 0.01 s without coverage
    assert len(read) == 2500 and all(content == bytes([n % 251]) * 8192 for n, content in enumerate(read))


def test_reading_every_stream_takes_memory_bounded_by_the_file(many_big_streams: bytes) -> None:
    opened = OleFile(many_big_streams)
    entries = opened.children(_root(opened))
    tracemalloc.start()
    try:
        for entry in entries:
            opened.read(entry)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 1.5 * len(many_big_streams), peak  # the streams cached, and a sector's worth of joining


def test_thousands_of_entries_sharing_one_start_are_refused_in_time() -> None:
    data = ole_tree({f"S{n:04d}": b"s" * 100 for n in range(9000)})  # 9,000 streams in the mini stream
    first = _entry(OleFile(data), "S0000")
    others = [entry for entry in OleFile(data).children(_root(OleFile(data))) if entry.index != first.index]
    data = _patched(data, others, start=first.start)  # every entry now starts where the first does
    started = time.perf_counter()
    opened = OleFile(data)
    assert opened.read(_entry(opened, "S0000")) == b"s" * 100
    refused = 0
    for entry in opened.children(_root(opened)):
        try:
            opened.read(entry)
        except OleError as exc:
            assert "share the same sectors" in str(exc)
            refused += 1
    assert time.perf_counter() - started < budget(0.5)  # about 0.03 s without coverage
    assert refused == 8999


def test_entries_that_fail_on_a_shared_chain_do_not_each_walk_it() -> None:
    # 8,000 entries start at one 3,000-sector chain and need more sectors than it has. Walking
    # it once per entry is 24 million steps (2.4 s); each walk claims what it passes, so the
    # first entry pays for the chain and the others are stopped at its first sector.
    data = ole_tree({"L": b"L" * (3000 * 512), **{f"S{n:04d}": b"s" * 100 for n in range(8000)}})
    opened = OleFile(data)
    chain = _entry(opened, "L")
    entries = [entry for entry in opened.children(_root(opened)) if entry.name != "L"]
    data = _patched(data, entries, start=chain.start, size=len(data))  # as long as the whole file
    started = time.perf_counter()
    opened = OleFile(data)
    messages: list[str] = []
    for entry in opened.children(_root(opened)):
        if entry.name != "L":
            with pytest.raises(OleError) as refused:
                opened.read(entry)
            messages.append(str(refused.value))
    assert time.perf_counter() - started < budget(0.5)  # about 0.05 s without coverage
    assert sorted(set(messages)) == ["A stream's sector chain is truncated.", "Two streams share the same sectors."]
    assert messages.count("A stream's sector chain is truncated.") == 1
