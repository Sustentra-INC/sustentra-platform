"""Page chunks (migration 0018) end to end against in-memory stores and real PDFs: the split, the
chunk queue (claim order, retry, backoff, lease), assembly in page order with the real page
numbers, partial runs for pages that could not be read, the document page cap, and that inline
mode and small documents read exactly as before. The Postgres side is in tests/db/test_document_chunks_db.py.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest

from backend.app.adapters.parsers.pdf_parser import PdfParser
from backend.app.repositories.document_chunk_repository import DocumentChunk, InMemoryDocumentChunkRepository
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import InMemoryProcessingRunRepository, ProcessingRun
from backend.app.services import document_chunk_service
from backend.app.services.document_chunk_service import (
    ChunkingSettings,
    DocumentChunkService,
    merge_chunk_outputs,
    pages_unread_message,
    split_pages,
)
from backend.app.services.document_processing_service import DocumentProcessingService, RunParams
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.parser_service import ParserService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.workers.processing_reader import ProcessingReader, ReaderSettings

fitz = pytest.importorskip("fitz", reason="pymupdf is needed to make PDFs")

ORG = "aaaaaaaa-0000-4000-8000-00000000000a"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
SETTINGS = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=30, max_run_seconds=60,
                          shutdown_grace_seconds=1)
CHUNKING = ChunkingSettings(enabled=True, threshold_pages=20, chunk_pages=10, max_pages=500, max_attempts=3)
BILL_LINES = ["Fuel Type: Natural Gas", "Total Usage: 120 therms", "Service Period: 01/01/2024 - 01/31/2024"]


def make_pdf(path: Path, pages: int, first_page: list[str] | None = None) -> Path:
    """A text PDF: ``first_page`` lines on page 1 (a gas bill), a distinct line on each other page."""

    with fitz.open() as pdf:
        for number in range(1, pages + 1):
            page = pdf.new_page()
            lines = first_page if number == 1 and first_page else [f"Filler text on page {number} of the file"]
            for index, line in enumerate(lines):
                page.insert_text((72, 72 + 20 * index), line)
        pdf.save(path)
    return path


class Clock:
    """The database's now() for the in-memory queues."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FlakyParser:
    """The real parser, except that reading chosen chunks (by first page) raises a number of times."""

    def __init__(self) -> None:
        self.real = ParserService()
        self.failures: dict[int, float] = {}  # first page -> reads that still fail (inf: always)
        self.calls: list[tuple[int, int] | None] = []
        self.delay = 0.0  # seconds each chunk read takes
        self.block: threading.Event | None = None  # when set up, a chunk read waits for it

    def parse_document(self, **kwargs: Any) -> dict:
        pages = kwargs.get("pages")
        self.calls.append(pages)
        if self.block is not None:
            self.block.wait(10)
        if self.delay:
            time.sleep(self.delay)
        if pages is not None and self.failures.get(pages[0], 0) > 0:
            self.failures[pages[0]] -= 1
            raise RuntimeError("the parser broke")
        return self.real.parse_document(**kwargs)

    def chunk_calls(self) -> list[tuple[int, int]]:
        return [c for c in self.calls if c is not None]


def fake_exit(code: int) -> NoReturn:
    raise AssertionError(f"the reader exited with {code}")


@dataclass
class World:
    runs: InMemoryProcessingRunRepository
    chunks: InMemoryDocumentChunkRepository
    uploads: DocumentUploadService
    pipeline: PipelineOrchestrationService
    parser: FlakyParser
    reader: ProcessingReader
    service: DocumentProcessingService
    clock: Clock
    tmp: Path

    def queue(self, pages: int, first_page: list[str] | None = BILL_LINES, name: str = "big.pdf") -> ProcessingRun:
        content = make_pdf(self.tmp / f"src-{name}", pages, first_page).read_bytes()
        document = self.uploads.upload_document(
            engagement_id="ENG-1", file_name=name, content=content, mime_type="application/pdf",
            document_role="source_evidence", uploaded_by="reader@example.com", org_id=ORG)
        run, _ = self.service.request(document=document, org_id=ORG, requested_by="reader@example.com",
                                      params=RunParams())
        self.service.mark_queued(run)
        return run

    def run(self, run_id: str) -> ProcessingRun:
        run = self.runs.get(run_id)
        assert run is not None
        return run

    def chunk_rows(self, run: ProcessingRun) -> list[DocumentChunk]:
        return self.chunks.list_for_run(run.run_id)

    def pipeline_run(self, run: ProcessingRun) -> dict:
        finished = self.run(run.run_id)
        assert finished.pipeline_run_id, finished
        recorded = self.pipeline.get_pipeline_run(finished.pipeline_run_id)
        assert recorded is not None
        return recorded

    def items(self, run: ProcessingRun) -> list[dict]:
        return self.pipeline.list_extraction_results_by_document(run.document_id)[-1]["items"]

    def drain(self, limit: int = 30) -> int:
        """Run the reader until nothing is due; how many jobs (chunks and runs) it read."""

        done = 0
        while self.reader.run_once() is not None:
            done += 1
            assert done <= limit, "the reader keeps finding work"
        return done


class CountingChunks(InMemoryDocumentChunkRepository):
    def __init__(self, runs: Any, clock: Any) -> None:
        super().__init__(runs, clock)
        self.heartbeats: list[int] = []

    def heartbeat(self, chunk: DocumentChunk, worker_id: str, lease_seconds: int) -> DocumentChunk | None:
        self.heartbeats.append(lease_seconds)
        return super().heartbeat(chunk, worker_id, lease_seconds)


def make_world(tmp_path: Path, settings: ChunkingSettings = CHUNKING,
               reader_settings: ReaderSettings = SETTINGS) -> World:
    tmp_path.mkdir(parents=True, exist_ok=True)
    clock = Clock()
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository())
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    runs = InMemoryProcessingRunRepository(clock)
    chunks = CountingChunks(runs, clock)
    parser = FlakyParser()
    chunk_service = DocumentChunkService(chunks, uploads, storage, settings, parser=parser)
    reader = ProcessingReader(runs, uploads, pipeline, storage, settings=reader_settings, worker_id="reader:test",
                              alive_file=tmp_path / "alive", exit=fake_exit, chunks=chunks,
                              chunk_service=chunk_service)
    service = DocumentProcessingService(runs, uploads, pipeline, storage, worker_id="api")
    return World(runs, chunks, uploads, pipeline, parser, reader, service, clock, tmp_path)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return make_world(tmp_path)


# --- the split --------------------------------------------------------------------------------

@pytest.mark.parametrize(("pages", "ranges"), [
    (21, [(1, 10), (11, 20), (21, 21)]),
    (25, [(1, 10), (11, 20), (21, 25)]),
    (30, [(1, 10), (11, 20), (21, 30)]),
    (10, [(1, 10)]),
    (1, [(1, 1)]),
])
def test_split_pages_covers_every_page_once(pages: int, ranges: list[tuple[int, int]]) -> None:
    assert split_pages(pages, 10) == ranges


@pytest.mark.parametrize(("pages", "ranges"), [
    (21, [(1, 10), (11, 20), (21, 21)]),
    (25, [(1, 10), (11, 20), (21, 25)]),
    (30, [(1, 10), (11, 20), (21, 30)]),
])
def test_a_pdf_over_the_threshold_is_planned_in_chunks_and_the_run_waits(
    world: World, pages: int, ranges: list[tuple[int, int]]
) -> None:
    run = world.queue(pages)

    parked = world.reader.run_once()

    assert isinstance(parked, ProcessingRun) and parked.status == "waiting_on_chunks"
    assert (parked.worker_id, parked.lease_expires_at, parked.attempts) == (None, None, 0)  # the attempt is not spent
    assert [(c.chunk_index, c.page_from, c.page_to, c.status) for c in world.chunk_rows(run)] == [
        (i, a, b, "queued") for i, (a, b) in enumerate(ranges)]
    assert world.parser.calls == []  # nothing was parsed by the planning step
    assert world.uploads.get_document(run.document_id)["processing_status"] == "in_progress"


@pytest.mark.parametrize("pages", [20, 12, 1])
def test_a_pdf_at_or_under_the_threshold_is_read_in_one_go(world: World, pages: int) -> None:
    run = world.queue(pages)

    finished = world.reader.run_once()

    assert isinstance(finished, ProcessingRun) and finished.status == "completed"
    assert world.chunk_rows(run) == []
    assert world.parser.calls == []  # the chunk parser was not used: the pipeline read the whole file


# --- reading chunks and assembling ------------------------------------------------------------

def test_chunks_are_claimed_before_runs(world: World) -> None:
    big = world.queue(25)
    world.reader.run_once()  # plans the chunks
    small = world.queue(3, name="small.pdf")  # a plain run, queued after the chunks

    first = world.reader.run_once()

    assert isinstance(first, DocumentChunk) and first.run_id == big.run_id
    assert world.run(small.run_id).status == "queued"


def test_the_last_chunk_queues_the_run_and_assembly_reads_the_whole_document(world: World) -> None:
    run = world.queue(25)
    world.reader.run_once()

    for index in range(3):
        chunk = world.reader.run_once()
        assert isinstance(chunk, DocumentChunk) and chunk.status == "completed"
        expected = "waiting_on_chunks" if index < 2 else "queued"
        assert world.run(run.run_id).status == expected  # woken only when the last chunk ends

    finished = world.reader.run_once()

    assert isinstance(finished, ProcessingRun) and finished.status == "completed"
    assert finished.attempts == 1  # planning, chunks and assembly are one attempt
    assert world.parser.chunk_calls() == [(1, 10), (11, 20), (21, 25)]
    assert world.uploads.get_document(run.document_id)["processing_status"] == "completed"
    recorded = world.pipeline_run(run)
    assert recorded["status"] == "completed" and not any("pages_unread" in w for w in recorded["warnings"])
    assert world.reader.run_once() is None


def test_chunked_reading_extracts_the_same_values_as_reading_in_one_pass(tmp_path: Path) -> None:
    chunked = make_world(tmp_path / "chunked")
    whole = make_world(tmp_path / "whole", ChunkingSettings(enabled=False))
    chunked_run, whole_run = chunked.queue(25), whole.queue(25)

    assert chunked.drain() == 5 and whole.drain() == 1  # plan, 3 chunks, assembly; one read

    assert whole.chunk_rows(whole_run) == []

    def values(items: list[dict]) -> list[tuple]:
        return [(i["field_name"], i["raw_value"], i["normalized_value"], i["unit"], i["confidence"],
                 i["source_reference"]["page_number"], i["source_reference"]["text_snippet"]) for i in items]

    assert values(chunked.items(chunked_run)) == values(whole.items(whole_run))
    assert len(chunked.items(chunked_run)) > 0
    assert [c["canonical_type_id"] for c in (chunked.pipeline_run(chunked_run), whole.pipeline_run(whole_run))] == [
        "CT-S1-FUELQTY"] * 2


def test_real_page_numbers_survive_the_merge(world: World, tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "pages.pdf", 25, BILL_LINES)
    parts = [ParserService().parse_document(pdf, "DOC-1", "RUN-1", "application/pdf", pages=span)
             for span in split_pages(25, 10)]
    chunks = [DocumentChunk(
        id=str(i), org_id=ORG, run_id="RUN-1", document_id="DOC-1", chunk_index=i, page_from=a, page_to=b,
        status="completed", attempts=1, max_attempts=3, available_at=NOW, created_at=NOW, updated_at=NOW,
        parser_output=part) for i, ((a, b), part) in enumerate(zip(split_pages(25, 10), parts, strict=True))]

    merged, unread = merge_chunk_outputs(list(reversed(chunks)), "DOC-1", "RUN-1")  # given out of order

    whole = ParserService().parse_document(pdf, "DOC-1", "RUN-1", "application/pdf")
    assert unread == [] and merged["status"] == "parsed"
    assert [p["page_number"] for p in merged["pages"]] == list(range(1, 26))
    assert [(b["page_number"], b["text"]) for b in merged["text_blocks"]] == [
        (b["page_number"], b["text"]) for b in whole["text_blocks"]]
    assert [(r["page_number"], r["text_snippet"]) for r in merged["source_references"]] == [
        (r["page_number"], r["text_snippet"]) for r in whole["source_references"]]
    block_ids = [b["block_id"] for b in merged["text_blocks"]]
    assert len(block_ids) == len(set(block_ids))
    on_page_22 = [b for b in merged["text_blocks"] if b["page_number"] == 22]
    assert [b["text"] for b in on_page_22] == ["Filler text on page 22 of the file"]  # not page 2 of its chunk


def test_ids_that_collide_across_chunks_are_prefixed_with_their_chunk() -> None:
    def chunk(index: int, page: int) -> DocumentChunk:
        output = {"status": "parsed", "pages": [{"page_number": page, "text": "x"}], "warnings": [],
                  "text_blocks": [{"block_id": "b1", "page_number": page, "source_reference_id": "s1", "text": "x"}],
                  "source_references": [{"source_reference_id": "s1", "page_number": page, "parser_block_ids": ["b1"]}]}
        return DocumentChunk(id=str(index), org_id=ORG, run_id="R", document_id="D", chunk_index=index,
                             page_from=page, page_to=page, status="completed", attempts=1, max_attempts=3,
                             available_at=NOW, created_at=NOW, updated_at=NOW, parser_output=output)

    merged, _ = merge_chunk_outputs([chunk(0, 1), chunk(1, 2)], "D", "R")

    assert [b["block_id"] for b in merged["text_blocks"]] == ["b1", "c1:b1"]
    assert [b["source_reference_id"] for b in merged["text_blocks"]] == ["s1", "c1:s1"]
    assert [r["parser_block_ids"] for r in merged["source_references"]] == [["b1"], ["c1:b1"]]


def test_a_chunk_reads_only_its_pages_and_keeps_the_document_page_numbers(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "pages.pdf", 25)

    output = ParserService().parse_document(pdf, "DOC-1", "RUN-1", "application/pdf", pages=(21, 25))

    assert [p["page_number"] for p in output["pages"]] == [21, 22, 23, 24, 25]
    assert {b["page_number"] for b in output["text_blocks"]} == {21, 22, 23, 24, 25}
    assert all(f"Filler text on page {b['page_number']} " in b["text"] for b in output["text_blocks"])
    assert all(r["page_number"] >= 21 for r in output["source_references"])


def test_reading_a_whole_range_is_the_same_as_reading_without_one(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "pages.pdf", 4, BILL_LINES)

    def stable(output: dict) -> dict:
        return {k: v for k, v in output.items() if k != "created_at"}

    assert stable(PdfParser().parse(pdf, "D", "R", (1, 4))) == stable(PdfParser().parse(pdf, "D", "R"))
    assert stable(PdfParser().parse(pdf, "D", "R", (1, 99))) == stable(PdfParser().parse(pdf, "D", "R"))


def test_the_ocr_page_cap_is_per_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan of 30 pages, read as 3 chunks, is OCRed up to the cap in each (not 50 in all)."""

    pdf = make_pdf(tmp_path / "scan.pdf", 30)
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    monkeypatch.setattr("backend.app.services.parser_service.OCR_MAX_PAGES", 5)
    monkeypatch.setattr("backend.app.services.parser_service.OCR_MIN_PAGE_CHARACTERS", 10_000)  # every page is a scan

    class Textract:
        def parse_bytes(self, *_a: Any) -> dict:
            return {"status": "parsed", "pages": [{"page_number": 1, "text": "ocr text"}], "text_blocks": [],
                    "tables": [], "key_value_pairs": [], "source_references": [], "warnings": []}

    service = ParserService(live_textract_parser=Textract())  # type: ignore[arg-type]
    read = [service.parse_document(pdf, "D", "R", "application/pdf", pages=span) for span in split_pages(30, 10)]

    for output in read:
        assert sum(1 for p in output["pages"] if p["text"] == "ocr text") == 5
        assert any(w["code"] == "ocr_page_limit" for w in output["warnings"])


# --- retries, backoff and leases ---------------------------------------------------------------

def test_a_failing_chunk_is_retried_after_a_growing_backoff_then_succeeds(world: World) -> None:
    run = world.queue(25)
    world.reader.run_once()
    world.parser.failures[11] = 2  # the second chunk fails twice
    first = world.reader.run_once()  # chunk 0
    assert isinstance(first, DocumentChunk) and first.status == "completed"

    failed_once = world.reader.run_once()  # chunk 1, first attempt
    assert isinstance(failed_once, DocumentChunk)
    assert (failed_once.status, failed_once.attempts, failed_once.error_code) == ("queued", 1, "chunk_error")
    assert failed_once.available_at == world.clock() + timedelta(seconds=30)

    third = world.reader.run_once()  # chunk 2 is due; chunk 1 waits out its backoff
    assert isinstance(third, DocumentChunk) and third.chunk_index == 2
    assert world.reader.run_once() is None
    world.clock.advance(29)
    assert world.reader.run_once() is None
    world.clock.advance(1)

    failed_twice = world.reader.run_once()
    assert isinstance(failed_twice, DocumentChunk)
    assert (failed_twice.status, failed_twice.attempts) == ("queued", 2)
    assert failed_twice.available_at == world.clock() + timedelta(seconds=120)  # longer the second time
    world.clock.advance(120)

    ok = world.reader.run_once()
    assert isinstance(ok, DocumentChunk) and (ok.status, ok.attempts) == ("completed", 3)
    assert world.run(run.run_id).status == "queued"  # the last chunk ended: the run is due
    finished = world.reader.run_once()
    assert isinstance(finished, ProcessingRun) and finished.status == "completed"
    assert "pages_unread" not in " ".join(world.pipeline_run(run)["warnings"])


def test_a_chunk_that_fails_every_attempt_makes_a_partial_run_that_says_which_pages(world: World) -> None:
    run = world.queue(25)
    world.parser.failures[11] = float("inf")
    world.reader.run_once()

    jobs = 0
    while (job := world.reader.run_once()) is not None or world.run(run.run_id).status == "waiting_on_chunks":
        jobs += 1
        assert jobs < 20
        if job is None:
            world.clock.advance(150)  # past the backoff

    chunks = {c.chunk_index: c for c in world.chunk_rows(run)}
    assert (chunks[1].status, chunks[1].attempts, chunks[1].error_code) == ("failed", 3, "chunk_error")
    assert chunks[0].status == chunks[2].status == "completed"
    finished = world.run(run.run_id)
    assert finished.status == "completed"  # the read ended; what it found is marked partial
    recorded = world.pipeline_run(run)
    assert recorded["status"] == "partial"
    unread = [w for w in recorded["warnings"] if w.startswith("pages_unread")]
    assert unread == ["pages_unread: Pages 11-20 could not be read, so any values on them are missing."]
    assert recorded["parser_status"] == "partial"
    assert recorded["candidate_count"] > 0  # what could be read is still extracted
    merged, ranges = merge_chunk_outputs(world.chunk_rows(run), run.document_id, run.run_id)
    assert ranges == [(11, 20)]
    assert {b["page_number"] for b in merged["text_blocks"]} == {*range(1, 11), *range(21, 26)}
    assert any(w["code"] == "pages_unread" for w in merged["warnings"])


def test_a_run_whose_chunks_all_failed_is_partial_not_failed(world: World) -> None:
    run = world.queue(21)
    for first in (1, 11, 21):
        world.parser.failures[first] = float("inf")
    world.reader.run_once()
    for _ in range(40):
        if world.run(run.run_id).status != "waiting_on_chunks":
            break
        if world.reader.run_once() is None:
            world.clock.advance(150)
    world.reader.run_once()

    recorded = world.pipeline_run(run)
    assert recorded["status"] == "partial"
    assert [w for w in recorded["warnings"] if w.startswith("pages_unread")] == [
        "pages_unread: Pages 1-21 could not be read, so any values on them are missing."]


def test_a_chunk_whose_reader_died_is_claimable_again_after_its_lease(world: World) -> None:
    run = world.queue(21)
    world.reader.run_once()
    taken = world.chunks.claim("reader:dead", 30)
    assert taken is not None and taken.status == "in_progress"

    assert world.chunks.requeue_expired() == []  # still leased
    world.clock.advance(31)
    expired = world.chunks.requeue_expired()

    assert [(e.id, e.status) for e in expired] == [(taken.id, "queued")]
    reclaimed = [world.chunks.claim("reader:2", 30) for _ in range(3)]  # it queues behind the untouched ones
    again = next(c for c in reclaimed if c is not None and c.id == taken.id)
    assert again.attempts == 2
    assert world.run(run.run_id).status == "waiting_on_chunks"


def test_a_chunk_that_used_every_attempt_before_its_lease_ran_out_fails_and_can_wake_the_run(world: World) -> None:
    run = world.queue(21)
    world.reader.run_once()
    for _ in range(2):
        job = world.reader.run_once()
        assert isinstance(job, DocumentChunk) and job.status == "completed"
    last = None
    for attempt in (1, 2, 3):  # readers that took the last chunk and died, three times over
        last = world.chunks.claim("reader:dead", 30)
        assert last is not None and last.attempts == attempt
        world.clock.advance(31)
        expired = world.chunks.requeue_expired()
        assert [e.status for e in expired] == ["failed" if attempt == 3 else "queued"]

    assert last is not None
    failed = [c for c in world.chunk_rows(run) if c.status == "failed"]
    assert [(c.chunk_index, c.error_code) for c in failed] == [(2, "timed_out")]
    assert world.run(run.run_id).status == "queued"  # nothing left to wait for


def test_a_stale_reader_cannot_record_a_chunk_it_lost(world: World) -> None:
    world.queue(21)
    world.reader.run_once()
    mine = world.chunks.claim("reader:slow", 30)
    assert mine is not None
    world.clock.advance(31)
    world.chunks.requeue_expired()
    theirs = world.chunks.claim("reader:fast", 30)
    assert theirs is not None

    assert world.chunks.heartbeat(mine, "reader:slow", 30) is None
    assert world.chunks.finalize_completed(mine, "reader:slow", {"status": "parsed"}) is None
    assert world.chunks.retry_later(mine, "reader:slow", 5) is None
    assert world.chunks.finalize_completed(theirs, "reader:fast", {"status": "parsed"}) is not None


def test_two_readers_ending_the_last_chunks_at_once_wake_the_run_once(world: World) -> None:
    run = world.queue(21)
    world.reader.run_once()
    claimed = [world.chunks.claim(f"reader:{i}", 60) for i in range(3)]
    assert all(claimed)
    for chunk in claimed[:1]:
        assert chunk is not None
        world.chunks.finalize_completed(chunk, chunk.worker_id or "", {"status": "parsed"})
    barrier = threading.Barrier(2)

    def finish(chunk: DocumentChunk | None) -> None:
        assert chunk is not None
        barrier.wait(5)
        world.chunks.finalize_completed(chunk, chunk.worker_id or "", {"status": "parsed"})

    threads = [threading.Thread(target=finish, args=(chunk,)) for chunk in claimed[1:]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert world.run(run.run_id).status == "queued"
    first = world.runs.claim("reader:a", 60)
    assert first is not None and first.run_id == run.run_id
    assert world.runs.claim("reader:b", 60) is None  # one run to read, not two


# --- pages Textract could not read -------------------------------------------------------------

class OcrFailingParser(FlakyParser):
    """Every chunk read succeeds, except that page 13 of the file failed OCR (Textract was down)."""

    def parse_document(self, **kwargs: Any) -> dict:
        output = super().parse_document(**kwargs)
        pages = kwargs.get("pages")
        if pages is not None and pages[0] <= 13 <= pages[1]:
            output["warnings"].append({"code": "ocr_page_failed", "severity": "warning",
                                       "message": "Page 13 has no text layer and Textract could not read it."})
        return output


def test_pages_textract_failed_on_are_unread_even_though_their_chunk_was_kept(world: World) -> None:
    run = world.queue(25)
    world.reader.run_once()
    flaky = OcrFailingParser()
    world.reader._chunk_service._parser = flaky  # type: ignore[attr-defined]

    for _ in range(40):
        if world.run(run.run_id).status != "waiting_on_chunks":
            break
        if world.reader.run_once() is None:
            world.clock.advance(150)  # past the backoff of the chunk being tried again
    world.reader.run_once()  # assembly

    chunk = world.chunk_rows(run)[1]
    assert (chunk.status, chunk.attempts, chunk.error_code) == ("completed", 3, "ocr_page_failed")
    summary = world.chunks.summaries([run.run_id])[run.run_id]
    assert (summary.completed, summary.failed, summary.failed_pages) == (3, 0, [[13, 13]])
    recorded = world.pipeline_run(run)
    assert recorded["status"] == "partial"
    assert [w for w in recorded["warnings"] if w.startswith("pages_unread")] == [
        "pages_unread: Pages 13 could not be read, so any values on them are missing."]
    assert recorded["candidate_count"] > 0  # the rest of the document is still read


def test_a_chunk_whose_ocr_failure_clears_on_retry_leaves_nothing_unread(world: World) -> None:
    run = world.queue(25)
    world.reader.run_once()
    flaky = OcrFailingParser()
    world.reader._chunk_service._parser = flaky  # type: ignore[attr-defined]
    first = world.reader.run_once()  # chunk 0: pages 1-10, fine
    assert isinstance(first, DocumentChunk) and first.error_code is None
    retried = world.reader.run_once()  # chunk 1: Textract failed on page 13: tried again, not kept
    assert isinstance(retried, DocumentChunk) and (retried.status, retried.error_code) == ("queued", "ocr_page_failed")
    assert world.chunks.summaries([run.run_id])[run.run_id].failed_pages == []


# --- the reader's supervision of a chunk ---------------------------------------------------------

def test_the_lease_of_a_chunk_is_renewed_while_it_is_read(tmp_path: Path) -> None:
    fast = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                          shutdown_grace_seconds=1)
    world = make_world(tmp_path, reader_settings=fast)
    world.queue(21)
    world.reader.run_once()
    world.parser.delay = 0.3

    chunk = world.reader.run_once()

    assert isinstance(chunk, DocumentChunk) and chunk.status == "completed"
    assert len(world.chunks.heartbeats) >= 2 and set(world.chunks.heartbeats) == {60}  # type: ignore[attr-defined]


def test_a_stopping_reader_puts_the_chunk_back_without_counting_the_attempt(tmp_path: Path) -> None:
    stopping = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                              shutdown_grace_seconds=0)
    world = make_world(tmp_path, reader_settings=stopping)
    run = world.queue(21)
    world.reader.run_once()
    world.parser.block = threading.Event()
    world.reader.stop.set()

    released = world.reader.run_once()

    assert isinstance(released, DocumentChunk)
    assert (released.status, released.attempts, released.worker_id) == ("queued", 0, None)
    assert world.run(run.run_id).status == "waiting_on_chunks"
    world.parser.block.set()  # the abandoned read ends later and records nothing
    for thread in threading.enumerate():
        if thread.name == "reader-chunk":
            thread.join(5)
    assert [c.status for c in world.chunk_rows(run)] == ["queued"] * 3


# --- the document page cap, and what is unchanged -----------------------------------------------

def test_a_document_over_the_page_cap_is_a_partial_run_with_its_own_halt(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = world.queue(3)
    monkeypatch.setattr(document_chunk_service, "pdf_page_count", lambda _path: 501)

    finished = world.reader.run_once()

    assert isinstance(finished, ProcessingRun) and finished.status == "completed"
    recorded = world.pipeline_run(run)
    assert recorded["status"] == "partial"
    assert recorded["halt_reason"]["code"] == "document_too_long"
    assert "501 pages" in recorded["halt_reason"]["message"] and "500" in recorded["halt_reason"]["message"]
    assert recorded["candidate_count"] == 0
    assert world.chunk_rows(run) == [] and world.parser.calls == []  # nothing was read


def test_a_document_at_the_page_cap_is_still_chunked(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    run = world.queue(3)
    monkeypatch.setattr(document_chunk_service, "pdf_page_count", lambda _path: 500)

    parked = world.reader.run_once()

    assert isinstance(parked, ProcessingRun) and parked.status == "waiting_on_chunks"
    assert len(world.chunk_rows(run)) == 50


def test_inline_mode_reads_a_large_pdf_exactly_as_before(tmp_path: Path) -> None:
    off = make_world(tmp_path / "off", ChunkingSettings(enabled=False))
    run = off.queue(25)

    finished = off.reader.run_once()

    assert isinstance(finished, ProcessingRun) and finished.status == "completed"
    assert off.chunk_rows(run) == [] and off.parser.calls == []


GOLDEN = Path(__file__).parent / "data" / "inline_golden.json"
FIXTURES = Path(__file__).resolve().parents[3] / "parser_reliability_test_set" / "raw_documents" / "pdf"


@pytest.mark.parametrize("name", ["PDF-NG-001.pdf", "PDF-BLR-001.pdf"])
def test_the_inline_pipeline_gives_what_it_gave_before_chunking_existed(name: str) -> None:
    """Golden: ``data/inline_golden.json`` was recorded by running the pipeline on these existing
    fixtures at origin/staging, before this change (ids and timestamps removed). Nothing in it
    may move: parser output, the pipeline run and every extracted value."""

    import json

    skipped = {"pipeline_run_id", "created_at", "completed_at", "parser_output_id"}

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in skipped}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    result = pipeline.process_local_document(
        local_file_path=str(FIXTURES / name), engagement_id="ENG-GOLDEN", evidence_id="EV-" + name,
        document_id="DOC-" + name, processing_run_id="RUN-" + name, mime_type="application/pdf", org_id=None)

    got = strip({"pipeline_run": result["pipeline_run"], "parser_output": result["parser_output"],
                 "items": result["extraction_result"]["items"]})
    assert json.loads(json.dumps(got, sort_keys=True)) == json.loads(GOLDEN.read_text())[name]


def test_the_pipeline_is_unchanged_without_the_chunk_arguments(tmp_path: Path) -> None:
    """The pre-parsed output, unread pages and halt override are opt-in: a call without them
    parses the file, and its run is ``completed`` (no pages_unread)."""

    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    pdf = make_pdf(tmp_path / "bill.pdf", 2, BILL_LINES)

    result = pipeline.process_local_document(local_file_path=str(pdf), engagement_id="ENG-1",
                                             mime_type="application/pdf", org_id=ORG)

    assert result["pipeline_run"]["status"] == "completed"
    assert not any("pages_unread" in w for w in result["pipeline_run"]["warnings"])


def test_pages_unread_message_joins_neighbouring_ranges() -> None:
    assert pages_unread_message([(31, 40), (11, 20), (21, 30), (51, 51)]) == (
        "Pages 11-40, 51 could not be read, so any values on them are missing.")


def test_logs_carry_ids_and_counts_never_text(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.queue(21)
    with caplog.at_level(logging.INFO):
        world.drain()

    logged = " ".join(f"{r.getMessage()} {sorted(vars(r).items())}" for r in caplog.records
                      if r.name.startswith("sustentra"))
    assert "chunks_planned" in logged and "chunk_finished" in logged
    assert "Filler text" not in logged and "Natural Gas" not in logged

