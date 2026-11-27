"""MVP-244 follow-ups: the reader version follows the parser code; size cap, memory, NUL, the jsonl index
and the file kind in the key."""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories import parsed_text_repository as repo
from backend.app.repositories.parsed_text_repository import (
    InMemoryParsedTextRepository,
    JsonlParsedTextRepository,
)
from backend.app.services import parser_service
from backend.app.services.parser_service import ParserService, _for_run
from backend.tests.services.test_parser_service import FakeLiveTextractParser

ORG = "eeeeeeee-0000-0000-0000-0000000000e5"
SHA = "c" * 64


# --- the reader version follows the parser code ----------------------------------------------------

def test_the_reader_version_covers_every_parser_module() -> None:
    adapters = set((Path(parser_service.__file__).resolve().parents[1] / "adapters" / "parsers").glob("*.py"))
    assert adapters and adapters <= set(parser_service.PARSER_SOURCE_FILES)
    names = {p.name for p in parser_service.PARSER_SOURCE_FILES}
    assert {"pdf_parser.py", "excel_parser.py", "textract_parser.py", "aws_textract_parser.py",
            "pdf_scan_pages.py", "parser_service.py"} <= names


def test_a_change_to_a_parser_module_changes_the_digest_and_the_version(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = tmp_path / "pdf_parser.py"
    module.write_text("x = 1\n")
    before = parser_service.reader_source_digest([module])
    assert parser_service.reader_source_digest([module]) == before
    module.write_text("x = 2\n")
    after = parser_service.reader_source_digest([module])
    assert after != before and len(after) == 12

    old_version = ParserService().reader_version()
    assert parser_service._SOURCE_DIGEST in old_version
    monkeypatch.setattr(ParserService, "READER_VERSION", f"v0-{after}")
    assert ParserService().reader_version() != old_version


# --- size, memory, NUL, index, key -----------------------------------------------------------------

def _big_output(megabytes: float) -> dict[str, Any]:
    line = "kWh 1,234.56 " * 8
    count = int(megabytes * 1024 * 1024 / (len(line) + 40))
    return {"status": "parsed", "parser_name": "pdf_parser", "document_id": "DOC-1", "processing_run_id": "R",
            "pages": [{"page_number": 1, "text": "p"}],
            "text_blocks": [{"block_id": f"b{n}", "text": line, "page_number": 1} for n in range(count)],
            "source_references": [{"document_id": "DOC-1", "page_number": 1}], "warnings": []}


@pytest.mark.parametrize("kind", ["memory", "jsonl"])
def test_a_9_mb_output_is_stored_and_reused_without_a_second_copy(tmp_path: Path, kind: str) -> None:
    store = InMemoryParsedTextRepository() if kind == "memory" else JsonlParsedTextRepository(tmp_path / "p.jsonl")
    output = _big_output(9)
    assert 8.5e6 < len(json.dumps(output).encode()) < repo.MAX_STORED_BYTES
    store.put(ORG, SHA, "v0", 0, 0, output, ".pdf")

    kept = store.get(ORG, SHA, "v0", 0, 0, ".pdf")
    assert kept is not None
    tracemalloc.start()
    reused = _for_run(kept, "DOC-2", "RUN-2")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert reused is kept and len(reused["text_blocks"]) == len(output["text_blocks"])
    assert reused["source_references"][0]["document_id"] == "DOC-2" and reused["processing_run_id"] == "RUN-2"
    assert peak < 2 * 1024 * 1024  # the swap builds no second copy of a 9 MB output


def test_an_output_over_the_cap_is_not_kept_and_logged_once(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo._logged_too_large.clear()
    store = JsonlParsedTextRepository(tmp_path / "p.jsonl")
    output = _big_output(11)
    with caplog.at_level("WARNING", logger="sustentra.parsed_texts"):
        store.put(ORG, SHA, "v0", 0, 0, output, ".pdf")
        store.put(ORG, SHA, "v0", 0, 0, output, ".pdf")
    assert store.get(ORG, SHA, "v0", 0, 0, ".pdf") is None
    assert len([r for r in caplog.records if "size cap" in r.getMessage()]) == 1


def test_the_cap_counts_encoded_bytes_not_characters(tmp_path: Path) -> None:
    store = JsonlParsedTextRepository(tmp_path / "p.jsonl")
    text = "日本語" * 1_500_000  # 4.5 million characters, 13.5 million bytes
    out = {"status": "parsed", "parser_name": "p", "pages": [{"page_number": 1, "text": text}], "warnings": []}
    assert len(text) < repo.MAX_STORED_BYTES < len(text.encode())
    store.put(ORG, "d" * 64, "v0", 0, 0, out, ".pdf")
    assert store.get(ORG, "d" * 64, "v0", 0, 0, ".pdf") is None


def test_nul_characters_are_stripped_from_strings_not_from_the_json(tmp_path: Path) -> None:
    store = JsonlParsedTextRepository(tmp_path / "p.jsonl")
    output = {"status": "parsed", "parser_name": "p", "pages": [{"page_number": 1, "text": "a\x00b \\u0000 c"}],
              "warnings": []}
    store.put(ORG, SHA, "v0", 0, 0, output, ".txt")
    kept = store.get(ORG, SHA, "v0", 0, 0, ".txt")
    assert kept is not None and kept["pages"][0]["text"] == "ab \\u0000 c"  # the literal backslash text survives
    assert output["pages"][0]["text"] == "a\x00b \\u0000 c"  # the caller's output is untouched


def test_the_jsonl_store_indexes_once_and_reads_one_line_per_get(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JsonlParsedTextRepository(tmp_path / "p.jsonl")
    out = {"status": "parsed", "parser_name": "p", "pages": [{"page_number": 1, "text": "t"}], "warnings": []}
    for n in range(50):
        store.put(ORG, f"{n:064x}", "v0", 0, 0, out, ".txt")
    other = JsonlParsedTextRepository(store.path)  # another process: indexes on its first get
    assert other.get(ORG, f"{7:064x}", "v0", 0, 0, ".txt") is not None
    store.put(ORG, SHA, "v0", 0, 0, out, ".txt")  # appended by someone else: seen without a full re-read

    calls: list[int] = []
    real = repo.json.loads
    monkeypatch.setattr(repo.json, "loads", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    assert other.get(ORG, SHA, "v0", 0, 0, ".txt") is not None
    assert len(calls) == 2  # the one new line to index, and the line asked for
    calls.clear()
    assert other.get(ORG, f"{9:064x}", "v0", 0, 0, ".txt") is not None
    assert len(calls) == 1


def test_the_file_extension_is_part_of_the_key(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    service = ParserService(live_textract_parser=FakeLiveTextractParser(), parsed_texts=store)
    a = tmp_path / "a.txt"
    a.write_text("Same bytes in two kinds of file")
    b = tmp_path / "b.md"
    b.write_bytes(a.read_bytes())
    reads: list[str] = []
    original = service._read_document
    service._read_document = lambda *args: (reads.append("r"), original(*args))[1]  # type: ignore[method-assign]

    service.parse_document(a, "DOC-1", "RUN-1", org_id=ORG)
    service.parse_document(b, "DOC-2", "RUN-2", org_id=ORG)
    service.parse_document(b, "DOC-2", "RUN-3", org_id=ORG)

    assert len(reads) == 2
