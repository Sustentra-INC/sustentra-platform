"""What ``ole.read_directory(data)`` gives the .xls reader, pinned file by file.

The .xls reader calls ``read_directory(data)`` with no ``cfb`` argument (xlrd's own sector
addressing, sector N at ``512 + N * size``) and shipped after four adversarial review rounds.
Adding the stream reader to ``ole.py`` must not change that call at all, so this file records,
for every .xls shape the builders write and for each hostile one in ``test_ole.py`` and
``test_xls_parser.py`` (and more), exactly what it returned before: the six original
``OleDirectory`` fields, ``names()``, what ``check_chain`` says about every stream, or the
exact ``OleError`` message. Files with 4096-byte sectors are covered both laid out as xlrd
reads them (``base`` 512) and as the format lays them out (``base`` 4096).

The expected values below were captured from ``ole.py`` before the stream reader was added.
They are not to be edited to follow a change: if one fails, the change altered .xls behaviour.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Any

import pytest

from backend.app.adapters.parsers import ole
from backend.app.adapters.parsers.ole import OleError, read_directory
from backend.tests.adapters.parsers._xls_builder import (
    biff_workbook,
    embedded_block_xls,
    ole_file,
    past_the_stream_xls,
    xls_bytes,
)

_FREE, _END = -1, -2


# --- how a result is written down ------------------------------------------------------------------
def _table(values: list[int]) -> str:
    """An allocation table as text: free entries left out, a run of "sector i points at i + 1"
    folded to ``i..j=+1``. ``len 128: 0=-3, 1..7=+1, 8=-2``."""

    parts: list[str] = []
    index = 0
    while index < len(values):
        value = values[index]
        if value == _FREE:
            index += 1
        elif value == index + 1:
            last = index
            while last + 1 < len(values) and values[last + 1] == last + 2:
                last += 1
            parts.append(f"{index}..{last}=+1" if last > index else f"{index}={value}")
            index = last + 1
        else:
            parts.append(f"{index}={value}")
            index += 1
    return f"len {len(values)}: " + ", ".join(parts)


def _row(entry: ole.OleEntry) -> tuple[int, str, int, int, int, int, int, int]:
    return (entry.index, entry.name, entry.kind, entry.left, entry.right, entry.child, entry.start, entry.size)


def _snapshot(data: bytes) -> Any:
    try:
        directory = read_directory(data)
    except Exception as exc:  # noqa: BLE001 - whatever escaped before must escape the same way
        return f"{type(exc).__name__}: {exc}"
    chains: dict[int, str] = {}
    for entry in directory.entries:
        if entry.kind == ole.STREAM:
            try:
                directory.check_chain(entry)
                chains[entry.index] = "ok"
            except OleError as exc:
                chains[entry.index] = str(exc)
    return {
        "entries": [_row(entry) for entry in directory.entries],
        "top_level": [_row(entry) for entry in directory.top_level],
        "sector_size": directory.sector_size,
        "mini_cutoff": directory.mini_cutoff,
        "fat": _table(directory.fat),
        "mini_fat": _table(directory.mini_fat),
        "names": sorted(directory.names()),
        "chains": chains,
    }


# --- files: the builders' ----------------------------------------------------------------------------
def _sound() -> bytes:  # test_ole.py's _file(): a big stream, a mini stream and a storage
    return ole_file({"Workbook": biff_workbook({"S": [["a", 1]]}), "Small": b"x" * 100}, ("_VBA_PROJECT_CUR",))


# --- files: hostile edits of a sound one --------------------------------------------------------------
def _edit(data: bytes, offset: int, fmt: str, *values: int) -> bytes:
    patched = bytearray(data)
    patched[offset:offset + struct.calcsize(fmt)] = struct.pack(fmt, *values)
    return bytes(patched)


def _fat_entry(data: bytes, sector: int, value: int) -> bytes:  # the first FAT sector, as test_ole's _set_fat
    fat_sector = struct.unpack("<i", data[76:80])[0]
    return _edit(data, 512 + fat_sector * 512 + sector * 4, "<i", value)


def _dir_start(data: bytes) -> int:
    return int(struct.unpack("<i", data[48:52])[0])


def _entry(data: bytes, index: int, field: str, *values: int) -> bytes:
    """Edit one field of directory entry ``index`` (the builders lay the directory out in one run)."""

    offset = 512 + _dir_start(data) * 512 + index * 128
    where = {"name_size": (64, "<H"), "kind": (66, "<B"), "links": (68, "<iii"), "chain": (116, "<ii")}[field]
    return _edit(data, offset + where[0], where[1], *values)


def _with_appended(data: bytes, *sectors: bytes) -> bytes:
    return data + b"".join(sectors)


def _difat_chain(extra_fat: bool) -> bytes:
    """One DIFAT sector appended to the file; with ``extra_fat`` it lists one more (all free)
    allocation table sector, appended after it."""

    data = _sound()
    new = (len(data) - 512) // 512  # the index of the first appended sector
    listed = [new + 1] if extra_fat else []
    difat = struct.pack("<128i", *listed, *([_FREE] * (127 - len(listed))), _END)
    appended = [difat, struct.pack("<128i", *([_FREE] * 128))] if extra_fat else [difat]
    return _edit(_with_appended(data, *appended), 68, "<ii", new, 1)


def _many_entries() -> bytes:  # 40 entries: the directory runs over 10 sectors
    return ole_file({f"S{n}": bytes(100 + n) for n in range(36)}, ("A", "B", "C"))


# --- files: 4096-byte sectors ---------------------------------------------------------------------------
def _wide(base: int, variant: str = "sound") -> bytes:
    """A compound file with 4096-byte sectors, small enough to write out here: an allocation table,
    a directory (Workbook of 5000 bytes, Small of 100), a mini table and mini stream, the big
    stream. ``base`` is where sector 0 starts: 4096 as the format lays it out (the header fills
    a whole sector), 512 as xlrd reads it. ``variant``: ``mini_loop`` makes Small's mini chain
    loop, ``dag`` links two entries both ways."""

    size = 4096
    mini_fat = [1, _END] if variant != "mini_loop" else [1, 0]
    fat = [-3, _END, _END, _END, 5, _END]  # [MS-CFB] 2.3: 0 FAT, 1 directory, 2 mini FAT, 3 mini stream, 4-5 Workbook

    def entry(name: str, kind: int, start: int, length: int, left: int = -1, right: int = -1, child: int = -1) -> bytes:
        encoded = (name.encode("utf-16-le") + b"\x00\x00") if name else b""
        return (encoded.ljust(64, b"\x00") + struct.pack("<HBBiii", len(encoded), kind, 1, left, right, child)
                + bytes(16 + 4 + 8 + 8) + struct.pack("<iq", start, length))

    entries = [entry("Root Entry", 5, 3, 128, child=1),
               entry("Workbook", 2, 4, 5000, left=2 if variant == "dag" else -1, right=2),
               entry("Small", 2, 0, 100)]
    directory = b"".join(entries).ljust(size, b"\x00")
    header = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(16) + struct.pack("<HHHHH", 0x3E, 4, 0xFFFE, 12, 6) + bytes(6)
              + struct.pack("<iiiiiiiii", 1, 1, 1, 0, 4096, 2, 1, _END, 0)
              + struct.pack("<109i", 0, *([_FREE] * 108)))
    sectors = [struct.pack("<1024i", *(fat + [_FREE] * (1024 - len(fat)))), directory,
               struct.pack("<1024i", *(mini_fat + [_FREE] * (1024 - len(mini_fat)))).ljust(size, b"\x00"),
               (b"s" * 100).ljust(128, b"\x00").ljust(size, b"\x00"), b"B" * 4096, (b"B" * 904).ljust(size, b"\x00")]
    return header.ljust(base, b"\x00") + b"".join(sectors)


CASES: dict[str, Callable[[], bytes]] = {
    # files the builders write
    "xls": lambda: xls_bytes({"S": [["a", 1]]}),
    "xls_with_macros": lambda: xls_bytes({"S": [["a", 1]]}, macros=True),
    "xls_encrypted": lambda: xls_bytes({"S": [["a", 1]]}, encrypted=True),
    "xls_several_sheets": lambda: xls_bytes({"A": [["a", 1]], "B": [[2.5, None, "c"]]}),
    "xls_with_a_big_workbook_over_two_allocation_sectors": lambda: ole_file({"Workbook": bytes(70_000)}),
    "workbook_in_the_mini_stream": lambda: ole_file({"Workbook": biff_workbook({"S": [["Gallons", 450]]}, pad_to=0)}),
    "empty_workbook": lambda: ole_file({"Workbook": b""}),
    "empty_workbook_then_book": lambda: ole_file({"Workbook": b"", "Book": b"x" * 100}),
    "no_streams": lambda: ole_file({}),
    "storages_only": lambda: ole_file({}, ("A", "B")),
    "sound_with_a_mini_stream_and_a_storage": _sound,
    "forty_entries": _many_entries,
    "encrypted_xlsx_wrapper": lambda: ole_file({"EncryptionInfo": b"\x04\x00\x04\x00" + bytes(200),
                                                "EncryptedPackage": bytes(5000)}),
    "embedded_chart_overlapping": lambda: embedded_block_xls(overlap=True),
    "embedded_chart_clean": lambda: embedded_block_xls(overlap=False),
    "past_the_stream_identical": lambda: past_the_stream_xls("identical"),
    "past_the_stream_adjacent": lambda: past_the_stream_xls("adjacent"),
    "past_the_stream_no_eof": lambda: past_the_stream_xls("no_eof"),
    # looping and shared shapes
    "mini_chain_loops_small_workbook": lambda: ole_file({"Workbook": b"x" * 100}, loop_mini_chain="Workbook"),
    "mini_chain_loops_empty_workbook": lambda: ole_file({"Workbook": b""}, loop_mini_chain="Workbook"),
    "mini_chain_loops_book_after_empty_workbook": lambda: ole_file({"Workbook": b"", "Book": b"x" * 100},
                                                                   loop_mini_chain="Book"),
    "dag_two_storages": lambda: ole_file({"Workbook": b"x" * 5000}, ("A", "B"), dag=True),
    "dag_24_entries": lambda: ole_file({"Workbook": biff_workbook({"S": [["Gallons", 450]]})},
                                       tuple(f"S{n}" for n in range(24)), dag=True),
    # damaged containers (test_ole.py and test_xls_parser.py)
    "signature_wrong": lambda: _sound()[:8] + bytes(600),
    "truncated_inside_the_allocation_table": lambda: _sound()[:600],
    "shorter_than_a_header": lambda: _sound()[:100],
    "xls_truncated_at_700": lambda: xls_bytes({"S": [["Gallons", 450]]})[:700],
    "xls_garbage_after_the_signature": lambda: xls_bytes({"S": [["Gallons", 450]]})[:8] + bytes(range(256)) * 8,
    "directory_chain_points_at_itself": lambda: _fat_entry(_sound(), _dir_start(_sound()), _dir_start(_sound())),
    "directory_chain_leaves_the_file": lambda: _edit(_sound(), 48, "<i", 9999),
    "directory_chain_starts_free": lambda: _edit(_sound(), 48, "<i", _FREE),
    "directory_cut_inside_its_sector": lambda: _sound()[:512 + _dir_start(_sound()) * 512 + 200],
    "difat_chain_loops": lambda: _fat_entry(_edit(_sound(), 68, "<ii", 0, 1), 127, 0),
    "mini_table_chain_loops": lambda: _fat_entry(_edit(_sound(), 64, "<i", 2), struct.unpack("<i", _sound()[60:64])[0],
                                                 struct.unpack("<i", _sound()[60:64])[0]),
    "mini_table_starts_outside": lambda: _edit(_sound(), 60, "<i", 9999),
    "mini_table_count_zero": lambda: _edit(_sound(), 64, "<i", 0),
    "mini_table_count_over_chain": lambda: _edit(_sound(), 64, "<i", 5),
    "mini_stream_starts_outside": lambda: _entry(_sound(), 0, "chain", 9999, 4096),
    "mini_stream_empty": lambda: _entry(_sound(), 0, "chain", 3, 0),
    "mini_stream_start_free": lambda: _entry(_sound(), 0, "chain", _FREE, 4096),
    "mini_cutoff_zero": lambda: _edit(_sound(), 56, "<i", 0),
    "mini_cutoff_huge": lambda: _edit(_sound(), 56, "<i", 2**31 - 1),
    # allocation table sector lists (the header's 109, and a DIFAT chain)
    "fat_sector_listed_twice": lambda: _edit(_sound(), 80, "<i", struct.unpack("<i", _sound()[76:80])[0]),
    "fat_sector_listed_as_minus_three": lambda: _edit(_sound(), 80, "<i", -3),
    "fat_sector_listed_as_minus_four": lambda: _edit(_sound(), 80, "<i", -4),
    "fat_sector_listed_beyond_the_file": lambda: _edit(_sound(), 80, "<i", 9999),
    "fat_sector_listed_as_end": lambda: _edit(_sound(), 80, "<i", _END),
    "fat_sector_list_names_the_directory": lambda: _edit(_sound(), 80, "<i", _dir_start(_sound())),
    "difat_sector_with_no_more_tables": lambda: _difat_chain(False),
    "difat_sector_adds_a_second_table": lambda: _difat_chain(True),
    "difat_start_outside": lambda: _edit(_sound(), 68, "<ii", 9999, 1),
    "difat_count_zero_but_start_set": lambda: _edit(_sound(), 68, "<ii", 5, 0),
    # sector sizes
    **{f"sector_shift_{shift}": (lambda shift=shift: _edit(_sound(), 30, "<H", shift)) for shift in (0, 1, 6, 7, 8, 12, 21)},
    **{f"mini_shift_{shift}": (lambda shift=shift: _edit(_sound(), 32, "<H", shift)) for shift in (0, 1, 2, 7, 9, 10)},
    # the directory's tree
    "root_is_not_a_root": lambda: _entry(_sound(), 0, "kind", 1),
    "sibling_out_of_range": lambda: _entry(_sound(), 1, "links", _FREE, 99, _FREE),
    "sibling_points_back_to_root": lambda: _entry(_sound(), 1, "links", _FREE, 0, _FREE),
    "sibling_points_at_itself": lambda: _entry(_sound(), 2, "links", _FREE, 2, _FREE),
    "unreached_entries_are_left_out": lambda: _entry(_sound(), 1, "links", _FREE, _FREE, _FREE),
    "left_and_right_siblings": lambda: _entry(_entry(_entry(_sound(), 0, "links", _FREE, _FREE, 2), 2, "links", 1, 3, _FREE),
                                              1, "links", _FREE, _FREE, _FREE),
    "a_storage_with_a_child": lambda: _entry(_entry(_entry(_sound(), 1, "links", _FREE, 3, _FREE),
                                                    3, "links", _FREE, _FREE, 2), 2, "links", _FREE, _FREE, _FREE),
    "a_stream_with_a_child_is_not_followed": lambda: _entry(_sound(), 2, "links", _FREE, 3, 1),
    "storage_child_loops_to_root": lambda: _entry(_sound(), 3, "links", _FREE, _FREE, 0),
    "name_size_over_64": lambda: _entry(_sound(), 1, "name_size", 200),
    "name_size_zero": lambda: _entry(_sound(), 1, "name_size", 0),
    "name_size_one": lambda: _entry(_sound(), 1, "name_size", 1),
    "stream_with_a_negative_size": lambda: _entry(_sound(), 1, "chain", 4, -1),
    # 4096-byte sectors: laid out as xlrd reads them, and as the format lays them out
    "wide_sectors_as_xlrd_reads_them": lambda: _wide(512),
    "wide_sectors_as_the_format_lays_them_out": lambda: _wide(4096),
    "wide_sectors_as_xlrd_reads_them_mini_loop": lambda: _wide(512, "mini_loop"),
    "wide_sectors_as_the_format_lays_them_out_mini_loop": lambda: _wide(4096, "mini_loop"),
    "wide_sectors_as_xlrd_reads_them_dag": lambda: _wide(512, "dag"),
    "wide_sectors_as_the_format_lays_them_out_dag": lambda: _wide(4096, "dag"),
    "wide_sectors_file_cut_after_the_directory": lambda: _wide(4096)[:4096 * 3],
}

# Captured from ole.py before the stream reader existed (see the module docstring).
EXPECTED: dict[str, Any] = {'a_storage_with_a_child': {'chains': {1: 'ok', 2: 'ok'},
                            'entries': [(1, 'Workbook', 2, -1, 3, -1, 4, 4096),
                                        (3, '_VBA_PROJECT_CUR', 1, -1, -1, 2, 0, 0),
                                        (2, 'Small', 2, -1, -1, -1, 0, 100)],
                            'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                            'mini_cutoff': 4096,
                            'mini_fat': 'len 128: 0=1, 1=-2',
                            'names': ['_vba_project_cur', 'small', 'workbook'],
                            'sector_size': 512,
                            'top_level': [(1, 'Workbook', 2, -1, 3, -1, 4, 4096),
                                          (3, '_VBA_PROJECT_CUR', 1, -1, -1, 2, 0, 0)]},
 'a_stream_with_a_child_is_not_followed': {'chains': {1: 'ok', 2: 'ok'},
                                           'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                       (2, 'Small', 2, -1, 3, 1, 0, 100),
                                                       (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                           'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                           'mini_cutoff': 4096,
                                           'mini_fat': 'len 128: 0=1, 1=-2',
                                           'names': ['_vba_project_cur', 'small', 'workbook'],
                                           'sector_size': 512,
                                           'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                         (2, 'Small', 2, -1, 3, 1, 0, 100),
                                                         (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'dag_24_entries': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'dag_two_storages': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'difat_chain_loops': "OleError: The allocation table's chain is damaged.",
 'difat_count_zero_but_start_set': 'OleError: The allocation table is damaged.',
 'difat_sector_adds_a_second_table': {'chains': {1: 'ok', 2: 'ok'},
                                      'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                  (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                  (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                      'fat': 'len 256: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                      'mini_cutoff': 4096,
                                      'mini_fat': 'len 128: 0=1, 1=-2',
                                      'names': ['_vba_project_cur', 'small', 'workbook'],
                                      'sector_size': 512,
                                      'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                    (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                    (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'difat_sector_with_no_more_tables': {'chains': {1: 'ok', 2: 'ok'},
                                      'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                  (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                  (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                      'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                      'mini_cutoff': 4096,
                                      'mini_fat': 'len 128: 0=1, 1=-2',
                                      'names': ['_vba_project_cur', 'small', 'workbook'],
                                      'sector_size': 512,
                                      'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                    (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                    (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'difat_start_outside': "OleError: The allocation table's chain is damaged.",
 'directory_chain_leaves_the_file': 'OleError: The directory chain is damaged.',
 'directory_chain_points_at_itself': 'OleError: The directory chain is damaged.',
 'directory_chain_starts_free': 'OleError: The directory has no root entry.',
 'directory_cut_inside_its_sector': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'embedded_chart_clean': {'chains': {1: 'ok'},
                          'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 3814)],
                          'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3..9=+1, 10=-2',
                          'mini_cutoff': 4096,
                          'mini_fat': 'len 128: 0..58=+1, 59=-2',
                          'names': ['workbook'],
                          'sector_size': 512,
                          'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 3814)]},
 'embedded_chart_overlapping': {'chains': {1: 'ok'},
                                'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 3814)],
                                'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3..9=+1, 10=-2',
                                'mini_cutoff': 4096,
                                'mini_fat': 'len 128: 0..58=+1, 59=-2',
                                'names': ['workbook'],
                                'sector_size': 512,
                                'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 3814)]},
 'empty_workbook': {'chains': {1: 'ok'},
                    'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 0)],
                    'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                    'mini_cutoff': 4096,
                    'mini_fat': 'len 128: 0=-2',
                    'names': ['workbook'],
                    'sector_size': 512,
                    'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 0)]},
 'empty_workbook_then_book': {'chains': {1: 'ok', 2: 'ok'},
                              'entries': [(1, 'Workbook', 2, -1, 2, -1, 0, 0), (2, 'Book', 2, -1, -1, -1, 1, 100)],
                              'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                              'mini_cutoff': 4096,
                              'mini_fat': 'len 128: 0=-2, 1=2, 2=-2',
                              'names': ['book', 'workbook'],
                              'sector_size': 512,
                              'top_level': [(1, 'Workbook', 2, -1, 2, -1, 0, 0), (2, 'Book', 2, -1, -1, -1, 1, 100)]},
 'encrypted_xlsx_wrapper': {'chains': {1: 'ok', 2: 'ok'},
                            'entries': [(1, 'EncryptionInfo', 2, -1, 2, -1, 0, 204),
                                        (2, 'EncryptedPackage', 2, -1, -1, -1, 4, 5000)],
                            'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..12=+1, 13=-2',
                            'mini_cutoff': 4096,
                            'mini_fat': 'len 128: 0..2=+1, 3=-2',
                            'names': ['encryptedpackage', 'encryptioninfo'],
                            'sector_size': 512,
                            'top_level': [(1, 'EncryptionInfo', 2, -1, 2, -1, 0, 204),
                                          (2, 'EncryptedPackage', 2, -1, -1, -1, 4, 5000)]},
 'fat_sector_list_names_the_directory': {'chains': {1: 'ok', 2: 'ok'},
                                         'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                     (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                     (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                         'fat': 'len 256: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2, 128=7274578, '
                                                '129=7602287, 130=4522016, 131=7602286, 132=7929970, 133=0, 134=0, '
                                                '135=0, 136=0, 137=0, 138=0, 139=0, 140=0, 141=0, 142=0, 143=0, '
                                                '144=17104918, 147=1, 148=0, 149=0, 150=0, 151=0, 152=0, 153=0, '
                                                '154=0, 155=0, 156=0, 157=3, 158=128, 159=0, 160=7274583, '
                                                '161=7012466, 162=7274594, 163=7012463, 164=0, 165=0, 166=0, 167=0, '
                                                '168=0, 169=0, 170=0, 171=0, 172=0, 173=0, 174=0, 175=0, '
                                                '176=16908306, 178=2, 180=0, 181=0, 182=0, 183=0, 184=0, 185=0, '
                                                '186=0, 187=0, 188=0, 189=4, 190=4096, 191=0, 192=7143507, '
                                                '193=7077985, 194=108, 195=0, 196=0, 197=0, 198=0, 199=0, 200=0, '
                                                '201=0, 202=0, 203=0, 204=0, 205=0, 206=0, 207=0, 208=16908300, '
                                                '210=3, 212=0, 213=0, 214=0, 215=0, 216=0, 217=0, 218=0, 219=0, '
                                                '220=0, 221=0, 222=100, 223=0, 224=5636191, 225=4259906, '
                                                '226=5242975, 227=5177426, 228=4522058, 229=5505091, 230=4391007, '
                                                '231=5374037, 232=0, 233=0, 234=0, 235=0, 236=0, 237=0, 238=0, '
                                                '239=0, 240=16842786, 244=0, 245=0, 246=0, 247=0, 248=0, 249=0, '
                                                '250=0, 251=0, 252=0, 253=0, 254=0, 255=0',
                                         'mini_cutoff': 4096,
                                         'mini_fat': 'len 128: 0=1, 1=-2',
                                         'names': ['_vba_project_cur', 'small', 'workbook'],
                                         'sector_size': 512,
                                         'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                       (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                       (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'fat_sector_listed_as_end': {'chains': {1: 'ok', 2: 'ok'},
                              'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                          (2, 'Small', 2, -1, 3, -1, 0, 100),
                                          (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                              'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                              'mini_cutoff': 4096,
                              'mini_fat': 'len 128: 0=1, 1=-2',
                              'names': ['_vba_project_cur', 'small', 'workbook'],
                              'sector_size': 512,
                              'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                            (2, 'Small', 2, -1, 3, -1, 0, 100),
                                            (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'fat_sector_listed_as_minus_four': 'OleError: The allocation table is damaged.',
 'fat_sector_listed_as_minus_three': 'OleError: The allocation table is damaged.',
 'fat_sector_listed_beyond_the_file': {'chains': {1: 'ok', 2: 'ok'},
                                       'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                   (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                   (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                       'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                       'mini_cutoff': 4096,
                                       'mini_fat': 'len 128: 0=1, 1=-2',
                                       'names': ['_vba_project_cur', 'small', 'workbook'],
                                       'sector_size': 512,
                                       'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                     (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                     (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'fat_sector_listed_twice': 'OleError: The allocation table is damaged.',
 'forty_entries': {'chains': {1: 'ok',
                              2: 'ok',
                              3: 'ok',
                              4: 'ok',
                              5: 'ok',
                              6: 'ok',
                              7: 'ok',
                              8: 'ok',
                              9: 'ok',
                              10: 'ok',
                              11: 'ok',
                              12: 'ok',
                              13: 'ok',
                              14: 'ok',
                              15: 'ok',
                              16: 'ok',
                              17: 'ok',
                              18: 'ok',
                              19: 'ok',
                              20: 'ok',
                              21: 'ok',
                              22: 'ok',
                              23: 'ok',
                              24: 'ok',
                              25: 'ok',
                              26: 'ok',
                              27: 'ok',
                              28: 'ok',
                              29: 'ok',
                              30: 'ok',
                              31: 'ok',
                              32: 'ok',
                              33: 'ok',
                              34: 'ok',
                              35: 'ok',
                              36: 'ok'},
                   'entries': [(1, 'S0', 2, -1, 2, -1, 0, 100),
                               (2, 'S1', 2, -1, 3, -1, 2, 101),
                               (3, 'S2', 2, -1, 4, -1, 4, 102),
                               (4, 'S3', 2, -1, 5, -1, 6, 103),
                               (5, 'S4', 2, -1, 6, -1, 8, 104),
                               (6, 'S5', 2, -1, 7, -1, 10, 105),
                               (7, 'S6', 2, -1, 8, -1, 12, 106),
                               (8, 'S7', 2, -1, 9, -1, 14, 107),
                               (9, 'S8', 2, -1, 10, -1, 16, 108),
                               (10, 'S9', 2, -1, 11, -1, 18, 109),
                               (11, 'S10', 2, -1, 12, -1, 20, 110),
                               (12, 'S11', 2, -1, 13, -1, 22, 111),
                               (13, 'S12', 2, -1, 14, -1, 24, 112),
                               (14, 'S13', 2, -1, 15, -1, 26, 113),
                               (15, 'S14', 2, -1, 16, -1, 28, 114),
                               (16, 'S15', 2, -1, 17, -1, 30, 115),
                               (17, 'S16', 2, -1, 18, -1, 32, 116),
                               (18, 'S17', 2, -1, 19, -1, 34, 117),
                               (19, 'S18', 2, -1, 20, -1, 36, 118),
                               (20, 'S19', 2, -1, 21, -1, 38, 119),
                               (21, 'S20', 2, -1, 22, -1, 40, 120),
                               (22, 'S21', 2, -1, 23, -1, 42, 121),
                               (23, 'S22', 2, -1, 24, -1, 44, 122),
                               (24, 'S23', 2, -1, 25, -1, 46, 123),
                               (25, 'S24', 2, -1, 26, -1, 48, 124),
                               (26, 'S25', 2, -1, 27, -1, 50, 125),
                               (27, 'S26', 2, -1, 28, -1, 52, 126),
                               (28, 'S27', 2, -1, 29, -1, 54, 127),
                               (29, 'S28', 2, -1, 30, -1, 56, 128),
                               (30, 'S29', 2, -1, 31, -1, 58, 129),
                               (31, 'S30', 2, -1, 32, -1, 61, 130),
                               (32, 'S31', 2, -1, 33, -1, 64, 131),
                               (33, 'S32', 2, -1, 34, -1, 67, 132),
                               (34, 'S33', 2, -1, 35, -1, 70, 133),
                               (35, 'S34', 2, -1, 36, -1, 73, 134),
                               (36, 'S35', 2, -1, 37, -1, 76, 135),
                               (37, 'A', 1, -1, 38, -1, 0, 0),
                               (38, 'B', 1, -1, 39, -1, 0, 0),
                               (39, 'C', 1, -1, -1, -1, 0, 0)],
                   'fat': 'len 128: 0=-3, 1..9=+1, 10=-2, 11=-2, 12..20=+1, 21=-2',
                   'mini_cutoff': 4096,
                   'mini_fat': 'len 128: 0=1, 1=-2, 2=3, 3=-2, 4=5, 5=-2, 6=7, 7=-2, 8=9, 9=-2, 10=11, 11=-2, 12=13, '
                               '13=-2, 14=15, 15=-2, 16=17, 17=-2, 18=19, 19=-2, 20=21, 21=-2, 22=23, 23=-2, 24=25, '
                               '25=-2, 26=27, 27=-2, 28=29, 29=-2, 30=31, 31=-2, 32=33, 33=-2, 34=35, 35=-2, 36=37, '
                               '37=-2, 38=39, 39=-2, 40=41, 41=-2, 42=43, 43=-2, 44=45, 45=-2, 46=47, 47=-2, 48=49, '
                               '49=-2, 50=51, 51=-2, 52=53, 53=-2, 54=55, 55=-2, 56=57, 57=-2, 58..59=+1, 60=-2, '
                               '61..62=+1, 63=-2, 64..65=+1, 66=-2, 67..68=+1, 69=-2, 70..71=+1, 72=-2, 73..74=+1, '
                               '75=-2, 76..77=+1, 78=-2',
                   'names': ['a',
                             'b',
                             'c',
                             's0',
                             's1',
                             's10',
                             's11',
                             's12',
                             's13',
                             's14',
                             's15',
                             's16',
                             's17',
                             's18',
                             's19',
                             's2',
                             's20',
                             's21',
                             's22',
                             's23',
                             's24',
                             's25',
                             's26',
                             's27',
                             's28',
                             's29',
                             's3',
                             's30',
                             's31',
                             's32',
                             's33',
                             's34',
                             's35',
                             's4',
                             's5',
                             's6',
                             's7',
                             's8',
                             's9'],
                   'sector_size': 512,
                   'top_level': [(1, 'S0', 2, -1, 2, -1, 0, 100),
                                 (2, 'S1', 2, -1, 3, -1, 2, 101),
                                 (3, 'S2', 2, -1, 4, -1, 4, 102),
                                 (4, 'S3', 2, -1, 5, -1, 6, 103),
                                 (5, 'S4', 2, -1, 6, -1, 8, 104),
                                 (6, 'S5', 2, -1, 7, -1, 10, 105),
                                 (7, 'S6', 2, -1, 8, -1, 12, 106),
                                 (8, 'S7', 2, -1, 9, -1, 14, 107),
                                 (9, 'S8', 2, -1, 10, -1, 16, 108),
                                 (10, 'S9', 2, -1, 11, -1, 18, 109),
                                 (11, 'S10', 2, -1, 12, -1, 20, 110),
                                 (12, 'S11', 2, -1, 13, -1, 22, 111),
                                 (13, 'S12', 2, -1, 14, -1, 24, 112),
                                 (14, 'S13', 2, -1, 15, -1, 26, 113),
                                 (15, 'S14', 2, -1, 16, -1, 28, 114),
                                 (16, 'S15', 2, -1, 17, -1, 30, 115),
                                 (17, 'S16', 2, -1, 18, -1, 32, 116),
                                 (18, 'S17', 2, -1, 19, -1, 34, 117),
                                 (19, 'S18', 2, -1, 20, -1, 36, 118),
                                 (20, 'S19', 2, -1, 21, -1, 38, 119),
                                 (21, 'S20', 2, -1, 22, -1, 40, 120),
                                 (22, 'S21', 2, -1, 23, -1, 42, 121),
                                 (23, 'S22', 2, -1, 24, -1, 44, 122),
                                 (24, 'S23', 2, -1, 25, -1, 46, 123),
                                 (25, 'S24', 2, -1, 26, -1, 48, 124),
                                 (26, 'S25', 2, -1, 27, -1, 50, 125),
                                 (27, 'S26', 2, -1, 28, -1, 52, 126),
                                 (28, 'S27', 2, -1, 29, -1, 54, 127),
                                 (29, 'S28', 2, -1, 30, -1, 56, 128),
                                 (30, 'S29', 2, -1, 31, -1, 58, 129),
                                 (31, 'S30', 2, -1, 32, -1, 61, 130),
                                 (32, 'S31', 2, -1, 33, -1, 64, 131),
                                 (33, 'S32', 2, -1, 34, -1, 67, 132),
                                 (34, 'S33', 2, -1, 35, -1, 70, 133),
                                 (35, 'S34', 2, -1, 36, -1, 73, 134),
                                 (36, 'S35', 2, -1, 37, -1, 76, 135),
                                 (37, 'A', 1, -1, 38, -1, 0, 0),
                                 (38, 'B', 1, -1, 39, -1, 0, 0),
                                 (39, 'C', 1, -1, -1, -1, 0, 0)]},
 'left_and_right_siblings': {'chains': {1: 'ok', 2: 'ok'},
                             'entries': [(2, 'Small', 2, 1, 3, -1, 0, 100),
                                         (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0),
                                         (1, 'Workbook', 2, -1, -1, -1, 4, 4096)],
                             'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                             'mini_cutoff': 4096,
                             'mini_fat': 'len 128: 0=1, 1=-2',
                             'names': ['_vba_project_cur', 'small', 'workbook'],
                             'sector_size': 512,
                             'top_level': [(2, 'Small', 2, 1, 3, -1, 0, 100),
                                           (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0),
                                           (1, 'Workbook', 2, -1, -1, -1, 4, 4096)]},
 'mini_chain_loops_book_after_empty_workbook': {'chains': {1: 'ok', 2: "The stream 'Book' chain is damaged."},
                                                'entries': [(1, 'Workbook', 2, -1, 2, -1, 0, 0),
                                                            (2, 'Book', 2, -1, -1, -1, 1, 100)],
                                                'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                                                'mini_cutoff': 4096,
                                                'mini_fat': 'len 128: 0=-2, 1=2, 2=1',
                                                'names': ['book', 'workbook'],
                                                'sector_size': 512,
                                                'top_level': [(1, 'Workbook', 2, -1, 2, -1, 0, 0),
                                                              (2, 'Book', 2, -1, -1, -1, 1, 100)]},
 'mini_chain_loops_empty_workbook': {'chains': {1: "The stream 'Workbook' chain is damaged."},
                                     'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 0)],
                                     'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                                     'mini_cutoff': 4096,
                                     'mini_fat': 'len 128: 0=0',
                                     'names': ['workbook'],
                                     'sector_size': 512,
                                     'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 0)]},
 'mini_chain_loops_small_workbook': {'chains': {1: "The stream 'Workbook' chain is damaged."},
                                     'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 100)],
                                     'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                                     'mini_cutoff': 4096,
                                     'mini_fat': 'len 128: 0=1, 1=0',
                                     'names': ['workbook'],
                                     'sector_size': 512,
                                     'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 100)]},
 'mini_cutoff_huge': {'chains': {1: 'ok', 2: 'ok'},
                      'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                  (2, 'Small', 2, -1, 3, -1, 0, 100),
                                  (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                      'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                      'mini_cutoff': 2147483647,
                      'mini_fat': 'len 128: 0=1, 1=-2',
                      'names': ['_vba_project_cur', 'small', 'workbook'],
                      'sector_size': 512,
                      'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                    (2, 'Small', 2, -1, 3, -1, 0, 100),
                                    (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_cutoff_zero': {'chains': {1: 'ok', 2: 'ok'},
                      'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                  (2, 'Small', 2, -1, 3, -1, 0, 100),
                                  (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                      'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                      'mini_cutoff': 0,
                      'mini_fat': 'len 128: 0=1, 1=-2',
                      'names': ['_vba_project_cur', 'small', 'workbook'],
                      'sector_size': 512,
                      'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                    (2, 'Small', 2, -1, 3, -1, 0, 100),
                                    (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_shift_0': 'OleError: The compound file header has an invalid sector size.',
 'mini_shift_1': 'OleError: The compound file header has an invalid sector size.',
 'mini_shift_10': 'OleError: The compound file header has an invalid sector size.',
 'mini_shift_2': {'chains': {1: 'ok', 2: 'ok'},
                  'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                              (2, 'Small', 2, -1, 3, -1, 0, 100),
                              (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                  'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                  'mini_cutoff': 4096,
                  'mini_fat': 'len 128: 0=1, 1=-2',
                  'names': ['_vba_project_cur', 'small', 'workbook'],
                  'sector_size': 512,
                  'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                (2, 'Small', 2, -1, 3, -1, 0, 100),
                                (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_shift_7': {'chains': {1: 'ok', 2: 'ok'},
                  'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                              (2, 'Small', 2, -1, 3, -1, 0, 100),
                              (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                  'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                  'mini_cutoff': 4096,
                  'mini_fat': 'len 128: 0=1, 1=-2',
                  'names': ['_vba_project_cur', 'small', 'workbook'],
                  'sector_size': 512,
                  'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                (2, 'Small', 2, -1, 3, -1, 0, 100),
                                (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_shift_9': {'chains': {1: 'ok', 2: 'ok'},
                  'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                              (2, 'Small', 2, -1, 3, -1, 0, 100),
                              (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                  'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                  'mini_cutoff': 4096,
                  'mini_fat': 'len 128: 0=1, 1=-2',
                  'names': ['_vba_project_cur', 'small', 'workbook'],
                  'sector_size': 512,
                  'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                (2, 'Small', 2, -1, 3, -1, 0, 100),
                                (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_stream_empty': {'chains': {1: 'ok', 2: "The stream 'Small' chain is damaged."},
                       'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                   (2, 'Small', 2, -1, 3, -1, 0, 100),
                                   (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                       'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                       'mini_cutoff': 4096,
                       'mini_fat': 'len 0: ',
                       'names': ['_vba_project_cur', 'small', 'workbook'],
                       'sector_size': 512,
                       'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                     (2, 'Small', 2, -1, 3, -1, 0, 100),
                                     (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_stream_start_free': {'chains': {1: 'ok', 2: "The stream 'Small' chain is damaged."},
                            'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                        (2, 'Small', 2, -1, 3, -1, 0, 100),
                                        (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                            'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                            'mini_cutoff': 4096,
                            'mini_fat': 'len 0: ',
                            'names': ['_vba_project_cur', 'small', 'workbook'],
                            'sector_size': 512,
                            'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                          (2, 'Small', 2, -1, 3, -1, 0, 100),
                                          (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_stream_starts_outside': 'OleError: The mini stream chain is damaged.',
 'mini_table_chain_loops': "OleError: The mini allocation table's chain is damaged.",
 'mini_table_count_over_chain': {'chains': {1: 'ok', 2: 'ok'},
                                 'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                             (2, 'Small', 2, -1, 3, -1, 0, 100),
                                             (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                 'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                 'mini_cutoff': 4096,
                                 'mini_fat': 'len 128: 0=1, 1=-2',
                                 'names': ['_vba_project_cur', 'small', 'workbook'],
                                 'sector_size': 512,
                                 'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                               (2, 'Small', 2, -1, 3, -1, 0, 100),
                                               (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_table_count_zero': {'chains': {1: 'ok', 2: "The stream 'Small' chain is damaged."},
                           'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                       (2, 'Small', 2, -1, 3, -1, 0, 100),
                                       (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                           'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                           'mini_cutoff': 4096,
                           'mini_fat': 'len 0: ',
                           'names': ['_vba_project_cur', 'small', 'workbook'],
                           'sector_size': 512,
                           'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                         (2, 'Small', 2, -1, 3, -1, 0, 100),
                                         (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'mini_table_starts_outside': "OleError: The mini allocation table's chain is damaged.",
 'name_size_one': {'chains': {1: 'ok', 2: 'ok'},
                   'entries': [(1, '', 2, -1, 2, -1, 4, 4096),
                               (2, 'Small', 2, -1, 3, -1, 0, 100),
                               (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                   'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                   'mini_cutoff': 4096,
                   'mini_fat': 'len 128: 0=1, 1=-2',
                   'names': ['', '_vba_project_cur', 'small'],
                   'sector_size': 512,
                   'top_level': [(1, '', 2, -1, 2, -1, 4, 4096),
                                 (2, 'Small', 2, -1, 3, -1, 0, 100),
                                 (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'name_size_over_64': {'chains': {1: 'ok', 2: 'ok'},
                       'entries': [(1,
                                    'Workbook\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                                    2,
                                    -1,
                                    2,
                                    -1,
                                    4,
                                    4096),
                                   (2, 'Small', 2, -1, 3, -1, 0, 100),
                                   (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                       'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                       'mini_cutoff': 4096,
                       'mini_fat': 'len 128: 0=1, 1=-2',
                       'names': ['_vba_project_cur',
                                 'small',
                                 'workbook\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'],
                       'sector_size': 512,
                       'top_level': [(1,
                                      'Workbook\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                                      2,
                                      -1,
                                      2,
                                      -1,
                                      4,
                                      4096),
                                     (2, 'Small', 2, -1, 3, -1, 0, 100),
                                     (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'name_size_zero': {'chains': {1: 'ok', 2: 'ok'},
                    'entries': [(1, '', 2, -1, 2, -1, 4, 4096),
                                (2, 'Small', 2, -1, 3, -1, 0, 100),
                                (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                    'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                    'mini_cutoff': 4096,
                    'mini_fat': 'len 128: 0=1, 1=-2',
                    'names': ['', '_vba_project_cur', 'small'],
                    'sector_size': 512,
                    'top_level': [(1, '', 2, -1, 2, -1, 4, 4096),
                                  (2, 'Small', 2, -1, 3, -1, 0, 100),
                                  (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'no_streams': {'chains': {},
                'entries': [],
                'fat': 'len 128: 0=-3, 1=-2',
                'mini_cutoff': 4096,
                'mini_fat': 'len 0: ',
                'names': [],
                'sector_size': 512,
                'top_level': []},
 'past_the_stream_adjacent': {'chains': {1: 'ok'},
                              'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 6125)],
                              'fat': 'len 128: 0=-3, 1=-2, 2..12=+1, 13=-2',
                              'mini_cutoff': 4096,
                              'mini_fat': 'len 0: ',
                              'names': ['workbook'],
                              'sector_size': 512,
                              'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 6125)]},
 'past_the_stream_identical': {'chains': {1: 'ok'},
                               'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 6124)],
                               'fat': 'len 128: 0=-3, 1=-2, 2..12=+1, 13=-2',
                               'mini_cutoff': 4096,
                               'mini_fat': 'len 0: ',
                               'names': ['workbook'],
                               'sector_size': 512,
                               'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 6124)]},
 'past_the_stream_no_eof': {'chains': {1: 'ok'},
                            'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 4334)],
                            'fat': 'len 128: 0=-3, 1=-2, 2..9=+1, 10=-2',
                            'mini_cutoff': 4096,
                            'mini_fat': 'len 0: ',
                            'names': ['workbook'],
                            'sector_size': 512,
                            'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 4334)]},
 'root_is_not_a_root': 'OleError: The directory has no root entry.',
 'sector_shift_0': 'OleError: The compound file header has an invalid sector size.',
 'sector_shift_1': 'OleError: The compound file header has an invalid sector size.',
 'sector_shift_12': 'OleError: The directory has no root entry.',
 'sector_shift_21': 'OleError: The compound file header has an invalid sector size.',
 'sector_shift_6': 'OleError: The compound file header has an invalid sector size.',
 'sector_shift_7': 'OleError: The directory has no root entry.',
 'sector_shift_8': 'OleError: The directory has no root entry.',
 'shorter_than_a_header': 'OleError: Not an OLE2 compound file.',
 'sibling_out_of_range': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'sibling_points_at_itself': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'sibling_points_back_to_root': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'signature_wrong': 'OleError: Not an OLE2 compound file.',
 'sound_with_a_mini_stream_and_a_storage': {'chains': {1: 'ok', 2: 'ok'},
                                            'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                        (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                        (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                            'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                            'mini_cutoff': 4096,
                                            'mini_fat': 'len 128: 0=1, 1=-2',
                                            'names': ['_vba_project_cur', 'small', 'workbook'],
                                            'sector_size': 512,
                                            'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 4096),
                                                          (2, 'Small', 2, -1, 3, -1, 0, 100),
                                                          (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'storage_child_loops_to_root': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'storages_only': {'chains': {},
                   'entries': [(1, 'A', 1, -1, 2, -1, 0, 0), (2, 'B', 1, -1, -1, -1, 0, 0)],
                   'fat': 'len 128: 0=-3, 1=-2',
                   'mini_cutoff': 4096,
                   'mini_fat': 'len 0: ',
                   'names': ['a', 'b'],
                   'sector_size': 512,
                   'top_level': [(1, 'A', 1, -1, 2, -1, 0, 0), (2, 'B', 1, -1, -1, -1, 0, 0)]},
 'stream_with_a_negative_size': {'chains': {1: 'ok', 2: 'ok'},
                                 'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, -1),
                                             (2, 'Small', 2, -1, 3, -1, 0, 100),
                                             (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                                 'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                 'mini_cutoff': 4096,
                                 'mini_fat': 'len 128: 0=1, 1=-2',
                                 'names': ['_vba_project_cur', 'small', 'workbook'],
                                 'sector_size': 512,
                                 'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, -1),
                                               (2, 'Small', 2, -1, 3, -1, 0, 100),
                                               (3, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]},
 'truncated_inside_the_allocation_table': 'OleError: The file is truncated.',
 'unreached_entries_are_left_out': {'chains': {1: 'ok'},
                                    'entries': [(1, 'Workbook', 2, -1, -1, -1, 4, 4096)],
                                    'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2, 4..10=+1, 11=-2',
                                    'mini_cutoff': 4096,
                                    'mini_fat': 'len 128: 0=1, 1=-2',
                                    'names': ['workbook'],
                                    'sector_size': 512,
                                    'top_level': [(1, 'Workbook', 2, -1, -1, -1, 4, 4096)]},
 'wide_sectors_as_the_format_lays_them_out': 'OleError: The directory chain is damaged.',
 'wide_sectors_as_the_format_lays_them_out_dag': 'OleError: The directory chain is damaged.',
 'wide_sectors_as_the_format_lays_them_out_mini_loop': 'OleError: The directory chain is damaged.',
 'wide_sectors_as_xlrd_reads_them': {'chains': {1: 'ok', 2: 'ok'},
                                     'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 5000),
                                                 (2, 'Small', 2, -1, -1, -1, 0, 100)],
                                     'fat': 'len 1024: 0=-3, 1=-2, 2=-2, 3=-2, 4=5, 5=-2',
                                     'mini_cutoff': 4096,
                                     'mini_fat': 'len 1024: 0=1, 1=-2',
                                     'names': ['small', 'workbook'],
                                     'sector_size': 4096,
                                     'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 5000),
                                                   (2, 'Small', 2, -1, -1, -1, 0, 100)]},
 'wide_sectors_as_xlrd_reads_them_dag': 'OleError: The directory tree is damaged (an entry is reached twice).',
 'wide_sectors_as_xlrd_reads_them_mini_loop': {'chains': {1: 'ok', 2: "The stream 'Small' chain is damaged."},
                                               'entries': [(1, 'Workbook', 2, -1, 2, -1, 4, 5000),
                                                           (2, 'Small', 2, -1, -1, -1, 0, 100)],
                                               'fat': 'len 1024: 0=-3, 1=-2, 2=-2, 3=-2, 4=5, 5=-2',
                                               'mini_cutoff': 4096,
                                               'mini_fat': 'len 1024: 0=1, 1=0',
                                               'names': ['small', 'workbook'],
                                               'sector_size': 4096,
                                               'top_level': [(1, 'Workbook', 2, -1, 2, -1, 4, 5000),
                                                             (2, 'Small', 2, -1, -1, -1, 0, 100)]},
 'wide_sectors_file_cut_after_the_directory': 'OleError: The directory chain is damaged.',
 'workbook_in_the_mini_stream': {'chains': {1: 'ok'},
                                 'entries': [(1, 'Workbook', 2, -1, -1, -1, 0, 197)],
                                 'fat': 'len 128: 0=-3, 1=-2, 2=-2, 3=-2',
                                 'mini_cutoff': 4096,
                                 'mini_fat': 'len 128: 0..2=+1, 3=-2',
                                 'names': ['workbook'],
                                 'sector_size': 512,
                                 'top_level': [(1, 'Workbook', 2, -1, -1, -1, 0, 197)]},
 'xls': {'chains': {1: 'ok'},
         'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)],
         'fat': 'len 128: 0=-3, 1=-2, 2..8=+1, 9=-2',
         'mini_cutoff': 4096,
         'mini_fat': 'len 0: ',
         'names': ['workbook'],
         'sector_size': 512,
         'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)]},
 'xls_encrypted': {'chains': {1: 'ok'},
                   'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)],
                   'fat': 'len 128: 0=-3, 1=-2, 2..8=+1, 9=-2',
                   'mini_cutoff': 4096,
                   'mini_fat': 'len 0: ',
                   'names': ['workbook'],
                   'sector_size': 512,
                   'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)]},
 'xls_garbage_after_the_signature': 'OleError: Not an OLE2 compound file.',
 'xls_several_sheets': {'chains': {1: 'ok'},
                        'entries': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)],
                        'fat': 'len 128: 0=-3, 1=-2, 2..8=+1, 9=-2',
                        'mini_cutoff': 4096,
                        'mini_fat': 'len 0: ',
                        'names': ['workbook'],
                        'sector_size': 512,
                        'top_level': [(1, 'Workbook', 2, -1, -1, -1, 2, 4096)]},
 'xls_truncated_at_700': 'OleError: The file is truncated.',
 'xls_with_a_big_workbook_over_two_allocation_sectors': {'chains': {1: 'ok'},
                                                         'entries': [(1, 'Workbook', 2, -1, -1, -1, 3, 70000)],
                                                         'fat': 'len 256: 0=-3, 1=-3, 2=-2, 3..138=+1, 139=-2',
                                                         'mini_cutoff': 4096,
                                                         'mini_fat': 'len 0: ',
                                                         'names': ['workbook'],
                                                         'sector_size': 512,
                                                         'top_level': [(1, 'Workbook', 2, -1, -1, -1, 3, 70000)]},
 'xls_with_macros': {'chains': {1: 'ok'},
                     'entries': [(1, 'Workbook', 2, -1, 2, -1, 2, 4096),
                                 (2, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)],
                     'fat': 'len 128: 0=-3, 1=-2, 2..8=+1, 9=-2',
                     'mini_cutoff': 4096,
                     'mini_fat': 'len 0: ',
                     'names': ['_vba_project_cur', 'workbook'],
                     'sector_size': 512,
                     'top_level': [(1, 'Workbook', 2, -1, 2, -1, 2, 4096),
                                   (2, '_VBA_PROJECT_CUR', 1, -1, -1, -1, 0, 0)]}}


@pytest.mark.parametrize("name", sorted(CASES))
def test_read_directory_gives_what_it_gave_before(name: str) -> None:
    assert _snapshot(CASES[name]()) == EXPECTED[name]


def test_every_case_is_pinned() -> None:
    assert sorted(EXPECTED) == sorted(CASES)


def test_the_entry_cap_is_enforced_with_the_same_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ole, "MAX_ENTRIES", 3)
    assert _snapshot(_sound()) == "OleError: The directory has too many entries."
    monkeypatch.setattr(ole, "MAX_ENTRIES", 4)  # four entries are allowed
    assert isinstance(_snapshot(_sound()), dict)
