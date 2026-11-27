"""MVP-244: the text a reader made is kept by content hash, so a scan is read (and billed) once."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.repositories.parsed_text_repository import (
    InMemoryParsedTextRepository,
    JsonlParsedTextRepository,
)
from backend.app.services.parser_service import ParserService
from backend.app.services.textract_calls import register_textract_hook
from backend.tests.services.test_parser_service import FakeLiveTextractParser, _pdf

ORG = "eeeeeeee-0000-0000-0000-0000000000e5"
OTHER_ORG = "ffffffff-0000-0000-0000-0000000000f6"
SCAN = ["Cover letter with enough text to count", "", "Back page text that counts"]  # page 2 is a scan


@pytest.fixture(autouse=True)
def _ocr_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")


def _service(store: Any, live: Any | None = None, version: str | None = None) -> tuple[ParserService, Any]:
    live = live or FakeLiveTextractParser()
    service = ParserService(live_textract_parser=live, parsed_texts=store)
    if version:
        service.READER_VERSION = version
    return service, live


def test_a_reread_of_a_stored_document_makes_no_textract_call(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)

    first = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    again = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)

    assert len(live.byte_calls) == 1
    assert again["pages"] == first["pages"] and again["text_blocks"] == first["text_blocks"]
    assert again["processing_run_id"] == "RUN-2" and again["parser_output_id"].endswith("DOC-1-RUN-2")


def test_the_same_bytes_under_another_document_id_are_not_read_again(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    copy = tmp_path / "copy.pdf"
    copy.write_bytes(path.read_bytes())
    service, live = _service(store)

    service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    other = service.parse_document(copy, "DOC-2", "RUN-2", org_id=ORG)

    assert len(live.byte_calls) == 1
    assert other["document_id"] == "DOC-2"
    assert {r["document_id"] for r in other["source_references"]} == {"DOC-2"}


def test_a_different_reader_version_reads_again(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    old, live = _service(store, version="v0")
    new, _ = _service(store, live, version="v1")

    old.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    new.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)
    new.parse_document(path, "DOC-1", "RUN-3", org_id=ORG)

    assert len(live.byte_calls) == 2  # the new version read once, then reused


def test_ocr_switched_on_after_a_read_without_it_reads_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)

    monkeypatch.delenv("TEXTRACT_ENABLED")
    unread = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    assert unread["status"] == "partial" and live.byte_calls == []

    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    read = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)
    assert read["status"] == "parsed" and len(live.byte_calls) == 1


def test_another_organization_with_the_same_bytes_reads_again(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)

    service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    service.parse_document(path, "DOC-9", "RUN-9", org_id=OTHER_ORG)
    service.parse_document(path, "DOC-9", "RUN-10", org_id=OTHER_ORG)

    assert len(live.byte_calls) == 2
    assert store.get(OTHER_ORG, _sha(path), service.reader_version()) is not None


def test_without_an_organization_nothing_is_kept(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)

    service.parse_document(path, "DOC-1", "RUN-1")
    service.parse_document(path, "DOC-1", "RUN-2")

    assert len(live.byte_calls) == 2


@pytest.mark.parametrize("damage", ["not_a_dict", "no_pages", "page_count_mismatch", "bad_status", "empty_pages"])
def test_a_corrupt_or_empty_stored_row_falls_back_to_reading(tmp_path: Path, damage: str) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)
    service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    (key, row), = store._rows.items()
    if damage == "not_a_dict":
        store._rows[key] = "garbage"  # type: ignore[assignment]
    elif damage == "no_pages":
        row["parser_output"] = {"status": "parsed"}
    elif damage == "page_count_mismatch":
        row["parser_output"]["pages"] = row["parser_output"]["pages"][:1]
    elif damage == "bad_status":
        row["parser_output"]["status"] = "failed"
    else:
        row["parser_output"]["pages"] = []
        row["page_count"] = 0

    output = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)

    assert output["status"] == "parsed" and len(live.byte_calls) == 2
    service.parse_document(path, "DOC-1", "RUN-3", org_id=ORG)
    assert len(live.byte_calls) == 2  # the row was replaced by the good read


def test_a_store_that_raises_never_stops_a_read(tmp_path: Path) -> None:
    class Broken:
        def get(self, *args: Any) -> Any:
            raise RuntimeError("database down")

        def put(self, *args: Any) -> None:
            raise RuntimeError("database down")

    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(Broken())

    output = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)

    assert output["status"] == "parsed" and len(live.byte_calls) == 1


def test_an_output_with_a_failed_ocr_page_is_not_kept(tmp_path: Path) -> None:
    class Failing(FakeLiveTextractParser):
        def parse_bytes(self, document_bytes: bytes, document_id: str, processing_run_id: str) -> dict:
            self.byte_calls.append(document_bytes)
            return {"status": "failed", "warnings": []}

    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store, Failing())

    first = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)

    assert any(w["code"] == "ocr_page_failed" for w in first["warnings"])
    assert len(live.byte_calls) == 2 and store._rows == {}


def test_a_300_page_document_is_stored_and_reused(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "big.pdf", [f"Page {n} of the long statement, kWh 1,{n:03d}" for n in range(1, 301)])
    service, live = _service(store)
    reads: list[str] = []
    original = service._read_document

    def counted(*args: Any) -> dict:
        reads.append("read")
        return original(*args)

    service._read_document = counted  # type: ignore[method-assign]

    first = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    again = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)

    assert len(first["pages"]) == 300 and len(again["pages"]) == 300
    assert again["pages"][299]["text"] == first["pages"][299]["text"]
    assert reads == ["read"] and live.byte_calls == []
    (row,) = store._rows.values()
    assert row["page_count"] == 300 and row["reader_name"] and row["ocr_used"] is False


def test_chunks_are_kept_per_page_range(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "big.pdf", [f"Page {n} of the long statement text" for n in range(1, 11)])
    service, _ = _service(store)

    first = service.parse_document(path, "DOC-1", "RUN-1", pages=(1, 5), org_id=ORG)
    second = service.parse_document(path, "DOC-1", "RUN-1", pages=(6, 10), org_id=ORG)
    again = service.parse_document(path, "DOC-1", "RUN-2", pages=(6, 10), org_id=ORG)

    assert [p["page_number"] for p in first["pages"]] == [1, 2, 3, 4, 5]
    assert [p["page_number"] for p in again["pages"]] == [6, 7, 8, 9, 10] == [p["page_number"] for p in second["pages"]]
    assert len(store._rows) == 2


def test_empty_and_unicode_files_are_handled(tmp_path: Path) -> None:
    store = InMemoryParsedTextRepository()
    service, _ = _service(store)
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    unicode_file = tmp_path / "note.txt"
    unicode_file.write_text("Café ☕ 日本語 — 1,200 kWh", encoding="utf-8")

    service.parse_document(empty, "DOC-1", "RUN-1", org_id=ORG)
    service.parse_document(empty, "DOC-1", "RUN-2", org_id=ORG)
    first = service.parse_document(unicode_file, "DOC-2", "RUN-1", org_id=ORG)
    again = service.parse_document(unicode_file, "DOC-2", "RUN-2", org_id=ORG)

    assert again["pages"] == first["pages"] and "日本語" in json.dumps(again, ensure_ascii=False)


def test_every_textract_call_is_recorded_with_its_pages_mode_and_owner(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    remove = register_textract_hook(calls.append)

    class Client:
        def analyze_document(self, **kwargs: Any) -> dict:
            return {"Blocks": [
                {"BlockType": "PAGE", "Id": "p1", "Page": 1},
                {"BlockType": "LINE", "Id": "l1", "Text": "Total kWh Used: 700 kWh", "Confidence": 99.0, "Page": 1,
                 "Geometry": {"BoundingBox": {"Left": 0.1, "Top": 0.4, "Width": 0.5, "Height": 0.03}}}]}

    live = AwsTextractParser(client_factory=lambda *a, **k: Client(), feature_types=["TABLES"])
    store = InMemoryParsedTextRepository()
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, _ = _service(store, live)
    try:
        service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
        service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)  # reused: no call
    finally:
        remove()

    assert len(calls) == 1
    assert calls[0]["pages"] == 1 and calls[0]["mode"] == "analyze_document" and calls[0]["ok"] is True
    assert calls[0]["org_id"] == ORG and calls[0]["document_id"] == "DOC-1" and calls[0]["sha256"] == _sha(path)


def test_a_hook_that_raises_does_not_fail_a_read(tmp_path: Path) -> None:
    def bad(_: dict[str, Any]) -> None:
        raise RuntimeError("ledger down")

    remove = register_textract_hook(bad)

    class Client:
        def analyze_document(self, **kwargs: Any) -> dict:
            raise RuntimeError("throttled")

    live = AwsTextractParser(client_factory=lambda *a, **k: Client())
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, _ = _service(InMemoryParsedTextRepository(), live)
    try:
        output = service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    finally:
        remove()

    assert any(w["code"] == "ocr_page_failed" for w in output["warnings"])


def test_the_jsonl_store_keeps_by_key_and_skips_damaged_lines(tmp_path: Path) -> None:
    store = JsonlParsedTextRepository(tmp_path / "parsed.jsonl")
    path = _pdf(tmp_path / "scan.pdf", SCAN)
    service, live = _service(store)

    service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    again = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)
    service.parse_document(path, "DOC-1", "RUN-3", org_id=OTHER_ORG)

    assert again["status"] == "parsed" and len(live.byte_calls) == 2
    assert store.get(ORG, _sha(path), service.reader_version()) is not None
    assert store.get(OTHER_ORG, "0" * 64, service.reader_version()) is None


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
