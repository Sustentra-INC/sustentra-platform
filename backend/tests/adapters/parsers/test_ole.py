"""The OLE2 container check that runs before xlrd reads a workbook: every chain and the
directory tree walked once, and anything reached twice or outside the file refused."""

from __future__ import annotations

import struct

import pytest

from backend.app.adapters.parsers import ole
from backend.app.adapters.parsers.ole import OleError, read_directory
from backend.tests.adapters.parsers._xls_builder import biff_workbook, ole_file


def _file(**options) -> bytearray:
    return bytearray(ole_file({"Workbook": biff_workbook({"S": [["a", 1]]}), "Small": b"x" * 100},
                              ("_VBA_PROJECT_CUR",), **options))


def _set_fat(data: bytearray, sector: int, value: int) -> None:
    fat_sector = struct.unpack("<i", data[76:80])[0]
    offset = 512 + fat_sector * 512 + sector * 4
    data[offset:offset + 4] = struct.pack("<i", value)


def test_a_sound_file_gives_its_tree_and_checks_its_streams() -> None:
    directory = read_directory(bytes(_file()))
    assert [entry.name for entry in directory.top_level] == ["Workbook", "Small", "_VBA_PROJECT_CUR"]
    assert directory.names() == {"workbook", "small", "_vba_project_cur"}
    for entry in directory.top_level:
        if entry.kind == ole.STREAM:
            directory.check_chain(entry)  # one big stream, one in the mini stream


@pytest.mark.parametrize("damage, message", [
    (lambda data: data[:8] + bytes(600), "Not an OLE2"),
    (lambda data: data[:600], "truncated"),
    (lambda data: (_set_fat(data, struct.unpack("<i", data[48:52])[0], struct.unpack("<i", data[48:52])[0]),
                   data)[1], "directory chain"),
])
def test_a_damaged_container_is_refused(damage, message: str) -> None:
    with pytest.raises(OleError, match=message):
        read_directory(bytes(damage(_file())))


@pytest.mark.parametrize("shift", [0, 1, 6, 21])
def test_an_invalid_sector_size_is_refused_not_a_struct_error(shift: int) -> None:
    # Shift 0 and 1 give a sector too small to hold one 4-byte entry; at base this raised
    # struct.error (per_sector 0) and escaped as a 500. Any invalid size is a clean OleError.
    data = _file()
    data[30:32] = struct.pack("<H", shift)
    with pytest.raises(OleError, match="invalid sector size"):
        read_directory(bytes(data))


@pytest.mark.parametrize("mini_shift", [0, 1, 10])
def test_an_invalid_mini_sector_size_is_refused(mini_shift: int) -> None:
    data = _file()
    data[32:34] = struct.pack("<H", mini_shift)  # a sound file uses 6, and never more than the sector shift
    with pytest.raises(OleError, match="invalid sector size"):
        read_directory(bytes(data))


def test_a_looping_allocation_table_chain_is_refused() -> None:
    data = _file()
    data[68:76] = struct.pack("<ii", 0, 1)  # the DIFAT chain starts at the FAT sector...
    _set_fat(data, 127, 0)  # ...whose last entry points back to it
    with pytest.raises(OleError, match="allocation table"):
        read_directory(bytes(data))


def test_a_looping_mini_table_chain_is_refused() -> None:
    data = _file()
    mini_fat_start = struct.unpack("<i", data[60:64])[0]
    data[64:68] = struct.pack("<i", 2)  # two mini table sectors, the chain pointing back to the first
    _set_fat(data, mini_fat_start, mini_fat_start)
    with pytest.raises(OleError, match="mini allocation table"):
        read_directory(bytes(data))


def test_too_many_entries_are_refused(monkeypatch) -> None:
    monkeypatch.setattr(ole, "MAX_ENTRIES", 3)
    with pytest.raises(OleError, match="too many entries"):
        read_directory(bytes(_file()))


def test_an_entry_reached_twice_is_refused() -> None:
    with pytest.raises(OleError, match="reached twice"):
        read_directory(ole_file({"Workbook": b"x" * 5000}, ("A", "B"), dag=True))


def test_a_stream_chain_that_loops_or_leaves_its_table_is_refused() -> None:
    directory = read_directory(ole_file({"Workbook": b"x" * 100}, loop_mini_chain="Workbook"))
    with pytest.raises(OleError, match="stream 'Workbook'"):
        directory.check_chain(directory.top_level[0])
    outside = ole.OleEntry(9, "Book", ole.STREAM, -1, -1, -1, start=10_000, size=10)
    with pytest.raises(OleError, match="stream 'Book'"):
        directory.check_chain(outside)
