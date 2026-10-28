"""The reader process: claiming, reading under the run's organization, renewing the lease, and the
ways a read can end (finished, retried, lost, overran, stopped), against in-memory stores.

The in-memory repositories here refuse to be used outside a bound S1 scope where Postgres would
(``get``, ``enqueue``, the document store), so a call the reader makes with no scope fails these
tests as it would fail in production. The real queue is exercised in tests/db/test_processing_reader_db.py.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.core.s1_scope import S1Scope, current_scope, scoped
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.processing_run_repository import InMemoryProcessingRunRepository, ProcessingRun
from backend.app.services.document_processing_service import (
    WORKER_ERROR_MESSAGE,
    DocumentProcessingService,
    RunParams,
)
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.workers import processing_reader, reader_health
from backend.app.workers.processing_reader import (
    EXIT_OVERRAN,
    ProcessingReader,
    ReaderSettings,
    reader_active,
)
from backend.tests.services.test_document_processing_service import FakePipeline, completed_result

ORG = "aaaaaaaa-0000-4000-8000-00000000000a"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
SETTINGS = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                          shutdown_grace_seconds=1)


class ReaderExited(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def fake_exit(code: int) -> NoReturn:
    raise ReaderExited(code)


class Clock:
    """The database's now() for the in-memory queue."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class ScopedRuns(InMemoryProcessingRunRepository):
    """The queue, refusing the calls that read in the bound scope (as Postgres does) when none is bound."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        super().__init__(clock)
        self.heartbeats: list[int] = []

    def enqueue(self, **kwargs: Any) -> Any:
        current_scope()
        return super().enqueue(**kwargs)

    def get(self, run_id: str) -> ProcessingRun | None:
        current_scope()
        return super().get(run_id)

    def peek(self, run_id: str) -> ProcessingRun:
        run = super().get(run_id)
        assert run is not None
        return run

    def heartbeat(self, run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        self.heartbeats.append(lease_seconds)
        return super().heartbeat(run, worker_id, lease_seconds)


class ScopedDocuments(InMemoryDocumentRepository):
    def get_by_id(self, document_id: str) -> dict | None:
        current_scope()
        return super().get_by_id(document_id)

    def peek(self, document_id: str) -> dict:
        document = super().get_by_id(document_id)
        assert document is not None
        return document


class BlockingPipeline(FakePipeline):
    """The pipeline, optionally held until ``block`` is set and/or slowed by ``delay`` seconds."""

    def __init__(self, result: dict | Exception | None = None, *, block: bool = False, delay: float = 0.0) -> None:
        super().__init__(result)
        self.block = threading.Event() if block else None
        self.delay = delay
        self.started = threading.Event()

    def process_local_document(self, **kwargs: Any) -> dict:
        self.started.set()
        if self.block is not None:
            self.block.wait(10)
        if self.delay:
            time.sleep(self.delay)
        return super().process_local_document(**kwargs)

    def unblock(self) -> None:
        assert self.block is not None
        self.block.set()


@dataclass
class World:
    reader: ProcessingReader
    runs: ScopedRuns
    documents: ScopedDocuments
    uploads: DocumentUploadService
    storage: LocalStorageService
    pipeline: BlockingPipeline
    clock: Clock
    service: DocumentProcessingService
    alive: Path

    def add_document(self) -> dict:
        return self.uploads.upload_document(engagement_id="ENG-1", file_name="bill.txt", content=b"Total: 120 therms",
                                            mime_type="text/plain", document_role="source_evidence",
                                            uploaded_by="reader@example.com", org_id=ORG)

    def queue(self, document: dict | None = None) -> ProcessingRun:
        """A run asked for in queued mode: the run is queued, and so is its document."""

        document = document or self.add_document()
        with scoped(S1Scope.tenant(ORG)):
            run, _ = self.service.request(document=document, org_id=ORG, requested_by="reader@example.com",
                                          params=RunParams())
            self.service.mark_queued(run)
        return run

    def claimed(self, attempts: int = 1, lease_seconds: int = 60) -> ProcessingRun:
        """A run claimed by a reader that then died: in_progress, on its ``attempts``-th attempt."""

        run = self.queue()
        for attempt in range(1, attempts + 1):
            taken = self.runs.claim("reader:dead", lease_seconds)
            assert taken is not None and taken.run_id == run.run_id and taken.attempts == attempt
            if attempt < attempts:
                assert self.runs.retry_later(taken, "reader:dead", 0) is not None
        with scoped(S1Scope.tenant(ORG)):
            self.uploads.update_processing_status(run.document_id, "in_progress")
        return self.runs.peek(run.run_id)

    def run(self, run_id: str) -> ProcessingRun:
        return self.runs.peek(run_id)

    def status(self, document_id: str) -> str:
        return str(self.documents.peek(document_id)["processing_status"])


def make_world(tmp_path: Path, pipeline: BlockingPipeline | None = None, *, settings: ReaderSettings = SETTINGS,
               stop: threading.Event | None = None, wait: Callable[[float], bool] | None = None,
               clock: Callable[[], float] = time.monotonic) -> World:
    database_clock = Clock()
    storage = LocalStorageService(tmp_path / "uploads")
    documents = ScopedDocuments()
    uploads = DocumentUploadService(storage_service=storage, document_repository=documents)
    runs = ScopedRuns(database_clock)
    pipeline = pipeline or BlockingPipeline()
    alive = tmp_path / "alive"
    reader = ProcessingReader(runs, uploads, pipeline, storage, settings=settings, worker_id="reader:test",
                              stop=stop, alive_file=alive, exit=fake_exit, wait=wait, clock=clock)
    service = DocumentProcessingService(runs, uploads, pipeline, storage, worker_id="api")
    return World(reader, runs, documents, uploads, storage, pipeline, database_clock, service, alive)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return make_world(tmp_path)


@pytest.fixture(autouse=True)
def logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)


def eventually(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.01)


def read_in_background(reader: ProcessingReader) -> tuple[threading.Thread, dict[str, Any]]:
    result: dict[str, Any] = {}

    def work() -> None:
        result["run"] = reader.run_once()

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, result


def join_read_threads() -> None:
    for thread in threading.enumerate():
        if thread.name == "reader-read":
            thread.join(5)


def logged(caplog: pytest.LogCaptureFixture, message: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.getMessage() == message]


# --- one run ------------------------------------------------------------------------------------

def test_run_once_reads_the_oldest_due_run_and_records_it_completed(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    doc_a, doc_b = world.add_document(), world.add_document()
    run_a, run_b = world.queue(doc_a), world.queue(doc_b)

    done = world.reader.run_once()

    assert done is not None
    assert (done.run_id, done.status, done.pipeline_run_id) == (run_a.run_id, "completed", "P-1")
    assert world.status(doc_a["document_id"]) == "completed"
    assert world.run(run_b.run_id).status == "queued" and world.status(doc_b["document_id"]) == "queued"
    assert world.pipeline.calls[0]["processing_run_id"] == run_a.run_id
    assert world.pipeline.calls[0]["org_id"] == ORG

    [claimed] = logged(caplog, "processing_run_claimed")
    assert (claimed.run_id, claimed.org_id, claimed.document_id, claimed.attempt) == (
        run_a.run_id, ORG, doc_a["document_id"], 1)
    assert claimed.wait_ms >= 0
    [finished] = logged(caplog, "processing_run_finished")
    assert (finished.run_id, finished.status, finished.error_code, finished.attempt) == (
        run_a.run_id, "completed", None, 1)
    assert finished.duration_ms >= 0
    assert "bill.txt" not in caplog.text  # ids and codes only, never a file name


def test_run_once_returns_none_when_nothing_is_due(world: World) -> None:
    assert world.reader.run_once() is None

    run = world.queue()
    taken = world.runs.claim("reader:other", 60)
    assert taken is not None and world.runs.retry_later(taken, "reader:other", 30) is not None
    assert world.reader.run_once() is None  # due in 30s
    assert world.pipeline.calls == []
    assert world.run(run.run_id).status == "queued"


def test_a_problem_on_our_side_is_retried_after_30s_then_120s_then_fails(tmp_path: Path) -> None:
    world = make_world(tmp_path, BlockingPipeline(RuntimeError("db gone")))
    document = world.add_document()
    run = world.queue(document)

    first = world.reader.run_once()
    assert first is not None
    assert (first.status, first.attempts, first.error_code) == ("queued", 1, "worker_error")
    assert first.run_after == world.clock.now + timedelta(seconds=30)
    assert world.status(document["document_id"]) == "queued"

    world.clock.advance(30)
    second = world.reader.run_once()
    assert second is not None and (second.status, second.attempts) == ("queued", 2)
    assert second.run_after == world.clock.now + timedelta(seconds=120)

    world.clock.advance(120)
    third = world.reader.run_once()
    assert third is not None and third.run_id == run.run_id
    assert (third.status, third.attempts, third.error_code, third.error) == (
        "failed", 3, "worker_error", WORKER_ERROR_MESSAGE)
    assert world.status(document["document_id"]) == "failed"
    assert len(world.pipeline.calls) == 3


def test_a_halt_fails_at_once_without_a_retry(tmp_path: Path) -> None:
    halt = {"code": "unreadable_document", "message": "Unreadable document: no text."}
    world = make_world(tmp_path, BlockingPipeline(completed_result("failed", halt)))
    document = world.add_document()
    world.queue(document)

    failed = world.reader.run_once()

    assert failed is not None
    assert (failed.status, failed.attempts, failed.error_code, failed.error) == (
        "failed", 1, "unreadable_document", "Unreadable document: no text.")
    assert world.status(document["document_id"]) == "failed"
    assert len(world.pipeline.calls) == 1


def test_the_lease_is_renewed_while_reading(tmp_path: Path) -> None:
    world = make_world(tmp_path, BlockingPipeline(delay=0.3))
    world.queue()

    done = world.reader.run_once()

    assert done is not None and done.status == "completed"
    assert len(world.runs.heartbeats) >= 2
    assert set(world.runs.heartbeats) == {60}
    assert world.alive.exists()  # touched while the read went on


def test_a_failed_heartbeat_is_tried_again_and_does_not_stop_the_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    world = make_world(tmp_path, BlockingPipeline(delay=0.3))
    world.queue()
    heartbeat = world.runs.heartbeat
    failures = []

    def flaky(run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        if not failures:
            failures.append(1)
            raise RuntimeError("connection reset password=hunter2")
        return heartbeat(run, worker_id, lease_seconds)

    monkeypatch.setattr(world.runs, "heartbeat", flaky)

    done = world.reader.run_once()

    assert done is not None and done.status == "completed"
    [warning] = logged(caplog, "processing_run_heartbeat_failed")
    assert (warning.error_type, warning.error_code) == ("RuntimeError", "heartbeat_failed")
    assert "hunter2" not in caplog.text
    assert not logged(caplog, "processing_run_lost_lease")


def test_a_reader_that_lost_its_lease_records_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    world = make_world(tmp_path, BlockingPipeline(block=True))
    run = world.queue()
    reading, result = read_in_background(world.reader)
    assert world.pipeline.started.wait(5)

    with world.runs._lock:  # a heartbeat cannot land between the steps
        world.clock.advance(61)
        assert len(world.runs.requeue_expired()) == 1
        taken = world.runs.claim("reader:other", 60)
        assert taken is not None and taken.run_id == run.run_id
    time.sleep(0.2)  # a few heartbeats, all fenced
    world.pipeline.unblock()
    reading.join(5)

    now = world.run(run.run_id)
    assert (now.status, now.worker_id, now.pipeline_run_id) == ("in_progress", "reader:other", None)
    assert result["run"] is not None and result["run"].worker_id == "reader:other"
    assert len(logged(caplog, "processing_run_lost_lease")) == 1  # once, then it stops heartbeating


def test_a_read_that_overruns_exits_the_process(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=0.1,
                              shutdown_grace_seconds=1)
    world = make_world(tmp_path, BlockingPipeline(block=True), settings=settings)
    run = world.queue()

    with pytest.raises(ReaderExited) as exited:
        world.reader.run_once()

    assert exited.value.code == EXIT_OVERRAN == 75
    [overran] = logged(caplog, "processing_run_overran")
    assert overran.levelno == logging.ERROR
    assert overran.run_id == run.run_id and overran.elapsed_s >= 0.1
    world.pipeline.unblock()  # clean up the read thread
    eventually(lambda: world.run(run.run_id).status == "completed")


# --- stopping -------------------------------------------------------------------------------------

def test_stopping_waits_for_the_read_to_finish(tmp_path: Path) -> None:
    world = make_world(tmp_path, BlockingPipeline(delay=0.2))
    run = world.queue()
    threading.Timer(0.05, world.reader.request_stop).start()

    assert world.reader.run_forever() == 0

    assert world.run(run.run_id).status == "completed"
    assert world.status(run.document_id) == "completed"


def test_stopping_past_the_grace_puts_the_run_back(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                              shutdown_grace_seconds=0.1)
    world = make_world(tmp_path, BlockingPipeline(block=True), settings=settings)
    run = world.queue()
    threading.Timer(0.05, world.reader.request_stop).start()

    assert world.reader.run_forever() == 0

    released = world.run(run.run_id)
    assert (released.status, released.attempts, released.worker_id) == ("queued", 0, None)
    assert world.status(run.document_id) == "queued"
    [record] = logged(caplog, "processing_run_released")
    assert record.run_id == run.run_id
    assert logged(caplog, "reader_stopped")

    world.pipeline.unblock()  # the abandoned read ends later and records nothing
    join_read_threads()
    assert world.run(run.run_id).status == "queued" and world.status(run.document_id) == "queued"


def test_a_stop_with_no_grace_releases_the_run_at_once(tmp_path: Path) -> None:
    settings = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                              shutdown_grace_seconds=0)
    world = make_world(tmp_path, BlockingPipeline(block=True), settings=settings)
    run = world.queue()
    world.reader.stop.set()

    released = world.reader.run_once()

    assert released is not None and (released.run_id, released.status, released.attempts) == (
        run.run_id, "queued", 0)
    world.pipeline.unblock()
    join_read_threads()


# --- runs whose reader stopped ---------------------------------------------------------------------

def test_expired_runs_are_requeued_or_failed_and_their_documents_follow(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    retried = world.claimed(attempts=1)
    exhausted = world.claimed(attempts=3)
    world.clock.advance(61)

    assert world.reader.requeue_expired() == 2

    assert (world.run(retried.run_id).status, world.status(retried.document_id)) == ("queued", "queued")
    gone = world.run(exhausted.run_id)
    assert (gone.status, gone.error_code, world.status(exhausted.document_id)) == ("failed", "timed_out", "failed")
    [record] = logged(caplog, "processing_runs_requeued")
    assert (record.count, record.failed) == (2, 1)


def test_nothing_expired_changes_nothing_and_logs_nothing(world: World, caplog: pytest.LogCaptureFixture) -> None:
    world.claimed()
    assert world.reader.requeue_expired() == 0  # its lease has not run out
    assert not logged(caplog, "processing_runs_requeued")


def test_one_documents_status_failure_does_not_leave_the_others_behind(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    first, second, third = world.claimed(), world.claimed(), world.claimed()
    world.clock.advance(61)
    update = world.uploads.update_processing_status

    def update_status(document_id: str, status: str) -> dict:
        if document_id == first.document_id:
            raise RuntimeError("store down")
        if document_id == second.document_id:
            raise KeyError(document_id)  # the document is gone: ignored
        return update(document_id, status)

    monkeypatch.setattr(world.uploads, "update_processing_status", update_status)

    assert world.reader.requeue_expired() == 3

    assert world.status(third.document_id) == "queued"
    [warning] = logged(caplog, "processing_run_status_failed")
    assert (warning.run_id, warning.error_type) == (first.run_id, "RuntimeError")


# --- crashes ------------------------------------------------------------------------------------------

def test_a_crash_before_the_pipeline_is_retried(world: World, monkeypatch: pytest.MonkeyPatch,
                                                caplog: pytest.LogCaptureFixture) -> None:
    run = world.queue()
    get_document = world.uploads.get_document
    crashes = []

    def flaky(document_id: str) -> dict | None:
        if not crashes:
            crashes.append(1)
            raise RuntimeError("could not connect: password=hunter2 SELECT * FROM documents WHERE x = 'secret'")
        return get_document(document_id)

    monkeypatch.setattr(world.uploads, "get_document", flaky)

    first = world.reader.run_once()
    assert first is not None
    assert (first.status, first.error_code, first.attempts) == ("queued", "worker_error", 1)
    assert world.status(run.document_id) == "queued"

    world.clock.advance(30)
    second = world.reader.run_once()
    assert second is not None and (second.status, second.attempts) == ("completed", 2)

    [crash] = logged(caplog, "processing_run_crashed")
    assert crash.levelno == logging.ERROR and crash.run_id == run.run_id
    assert (crash.error_type, crash.error_code) == ("RuntimeError", "worker_error")
    assert crash.exc_info is None  # the type and a code only: a traceback can carry SQL parameters
    assert "hunter2" not in caplog.text and "SELECT" not in caplog.text


def test_a_crash_whose_own_record_also_fails_is_left_for_the_lease(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run = world.queue()

    def crash(document_id: str) -> dict | None:
        raise RuntimeError("could not connect")

    def cannot_record(*args: Any, **kwargs: Any) -> ProcessingRun | None:
        raise ConnectionError("password=hunter2")

    monkeypatch.setattr(world.uploads, "get_document", crash)
    monkeypatch.setattr(world.runs, "retry_later", cannot_record)

    left = world.reader.run_once()  # reads the run back in its organization's scope

    assert left is not None and (left.run_id, left.status) == (run.run_id, "in_progress")
    [failed] = logged(caplog, "processing_run_finish_failed")
    assert (failed.error_type, failed.error_code) == ("ConnectionError", "finish_failed")
    assert logged(caplog, "processing_run_crashed")
    assert "hunter2" not in caplog.text

    world.clock.advance(61)  # its lease runs out and the run is taken back
    assert world.reader.requeue_expired() == 1
    assert world.run(run.run_id).status == "queued" and world.status(run.document_id) == "queued"


# --- the loop --------------------------------------------------------------------------------------------

def test_errors_back_off_and_the_loop_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                               caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    delays: list[float] = []

    def wait(delay: float) -> bool:
        delays.append(delay)
        if len(delays) == 3:
            stop.set()
        return stop.is_set()

    settings = ReaderSettings(poll_seconds=0.01, lease_seconds=60, heartbeat_seconds=0.05, max_run_seconds=5,
                              shutdown_grace_seconds=1, s1_store="postgres+jsonl", s1_processing="queued")
    world = make_world(tmp_path, settings=settings, stop=stop, wait=wait)
    claims = []

    def claim(worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        claims.append(worker_id)
        if len(claims) <= 2:
            raise RuntimeError("database is starting password=hunter2")
        return None

    monkeypatch.setattr(world.runs, "claim", claim)

    assert world.reader.run_forever() == 0

    assert delays == [2, 5, settings.poll_seconds]
    errors = logged(caplog, "reader_error")
    assert [(e.failures, e.backoff_s, e.error_type, e.error_code) for e in errors] == [
        (1, 2, "RuntimeError", "reader_error"), (2, 5, "RuntimeError", "reader_error")]
    assert all(e.exc_info is None for e in errors) and "hunter2" not in caplog.text
    [started] = logged(caplog, "reader_started")
    assert (started.worker_id, started.s1_store, started.s1_processing) == ("reader:test", "postgres+jsonl", "queued")
    assert (started.poll_seconds, started.lease_seconds, started.heartbeat_seconds, started.max_run_seconds) == (
        0.01, 60, 0.05, 5)
    assert logged(caplog, "reader_stopped")


def test_the_backoff_grows_to_a_minute_and_a_good_pass_resets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    delays: list[float] = []

    def wait(delay: float) -> bool:
        delays.append(delay)
        if len(delays) == 9:
            stop.set()
        return stop.is_set()

    world = make_world(tmp_path, stop=stop, wait=wait)
    outcomes = iter([RuntimeError] * 7 + [None] + [RuntimeError, None])

    def claim(worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        error = next(outcomes)
        if error is not None:
            raise error("down")
        return None

    monkeypatch.setattr(world.runs, "claim", claim)

    assert world.reader.run_forever() == 0

    # 7 failures climb 2, 5, 15, 30, 60 and stay there; a clean pass waits the poll; the next failure starts over
    assert delays == [2, 5, 15, 30, 60, 60, 60, 0.01, 2]


def test_a_backlog_drains_without_waiting(tmp_path: Path) -> None:
    stop = threading.Event()
    delays: list[float] = []

    def wait(delay: float) -> bool:
        delays.append(delay)
        stop.set()
        return True

    world = make_world(tmp_path, stop=stop, wait=wait)
    runs = [world.queue() for _ in range(3)]

    assert world.reader.run_forever() == 0

    assert [world.run(r.run_id).status for r in runs] == ["completed"] * 3
    assert delays == [SETTINGS.poll_seconds]  # only once the queue was empty


def test_expired_runs_are_requeued_on_the_first_pass_and_every_30s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = threading.Event()
    now = {"t": 1000.0}
    waits = []

    def wait(delay: float) -> bool:
        waits.append(delay)
        now["t"] += 10
        if len(waits) == 7:
            stop.set()
        return stop.is_set()

    world = make_world(tmp_path, stop=stop, wait=wait, clock=lambda: now["t"])
    calls = []
    requeue = world.runs.requeue_expired
    monkeypatch.setattr(world.runs, "requeue_expired", lambda: calls.append(now["t"]) or requeue())

    assert world.reader.run_forever() == 0

    assert calls == [1000.0, 1030.0, 1060.0]


def test_a_failing_requeue_does_not_block_the_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    delays: list[float] = []

    def wait(delay: float) -> bool:
        delays.append(delay)
        if len(delays) == 2:
            stop.set()
        return stop.is_set()

    world = make_world(tmp_path, stop=stop, wait=wait)
    run = world.queue()

    def broken() -> list:
        raise RuntimeError("function does not exist")

    monkeypatch.setattr(world.runs, "requeue_expired", broken)

    assert world.reader.run_forever() == 0

    assert delays[0] == 2  # the failed pass backs off ...
    assert world.run(run.run_id).status == "completed"  # ... and the next one reads, without trying the requeue again


def test_two_readers_never_read_the_same_run(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    for _ in range(5):
        world.queue()
    other = ProcessingReader(world.runs, world.uploads, world.pipeline, world.storage, settings=SETTINGS,
                             worker_id="reader:other", alive_file=world.alive, exit=fake_exit)

    def drain(reader: ProcessingReader) -> None:
        while reader.run_once() is not None:
            pass

    threads = [threading.Thread(target=drain, args=(r,)) for r in (world.reader, other)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    ids = [call["processing_run_id"] for call in world.pipeline.calls]
    assert len(ids) == 5 and len(set(ids)) == 5


def test_the_reader_gets_its_own_worker_id_and_stop_event() -> None:
    runs = ScopedRuns(Clock())
    reader = ProcessingReader(runs, None, None, None, settings=SETTINGS)
    other = ProcessingReader(runs, None, None, None, settings=SETTINGS)

    assert reader.worker_id.startswith("reader:") and reader.worker_id.count(":") >= 3
    assert reader.worker_id != other.worker_id
    assert reader.stop is not other.stop and not reader.stop.is_set()
    reader.request_stop(signal.SIGTERM, None)
    assert reader.stop.is_set()


def test_the_alive_file_defaults_to_the_health_modules_file_when_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alive = tmp_path / "default-alive"
    monkeypatch.setattr(reader_health, "ALIVE_FILE", alive)
    stop = threading.Event()
    reader = ProcessingReader(ScopedRuns(Clock()), None, None, None, settings=SETTINGS, stop=stop,
                              wait=lambda delay: stop.set() or True)

    assert reader.run_forever() == 0

    assert alive.exists()  # the health check's file, however late it was patched


# --- idle, main, settings, health -----------------------------------------------------------------------------

def test_the_reader_is_active_unless_the_records_are_the_apis_files() -> None:
    assert reader_active(Settings(s1_store="jsonl")) == (
        False, "S1_STORE=jsonl: the reader would write the same files as the api")
    assert reader_active(Settings(s1_store="postgres+jsonl")) == (True, "")
    assert reader_active(Settings(s1_store="postgres", s1_processing="inline")) == (True, "")


def test_the_reader_stays_idle_under_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    stop.set()
    alive = tmp_path / "alive"
    registered: list[int] = []

    def never_built(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the reader must open no store under jsonl")

    monkeypatch.setattr(processing_reader, "get_settings", lambda: Settings(s1_store="jsonl"))
    monkeypatch.setattr(processing_reader, "ProcessingRunRepository", never_built)
    monkeypatch.setattr(processing_reader, "DocumentUploadService", never_built)
    monkeypatch.setattr(processing_reader, "configure_logging", lambda *a, **k: None)
    monkeypatch.setattr(processing_reader.signal, "signal", lambda signum, handler: registered.append(signum))
    monkeypatch.setattr(reader_health, "ALIVE_FILE", alive)

    assert processing_reader.main(stop=stop) == 0

    [idle] = logged(caplog, "reader_idle")
    assert "S1_STORE=jsonl" in idle.reason
    assert alive.exists()
    assert registered == [signal.SIGTERM, signal.SIGINT]


def test_main_reads_when_the_stores_are_in_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = threading.Event()
    registered: dict[int, Any] = {}
    built: list[Settings] = []

    class FakeReader:
        def run_forever(self) -> int:
            return 0

    def build(settings: Settings, event: threading.Event) -> FakeReader:
        assert event is stop
        built.append(settings)
        return FakeReader()

    monkeypatch.setattr(processing_reader, "get_settings", lambda: Settings(s1_store="postgres"))
    monkeypatch.setattr(processing_reader, "configure_logging", lambda *a, **k: None)
    monkeypatch.setattr(processing_reader.signal, "signal",
                        lambda signum, handler: registered.update({signum: handler}))
    monkeypatch.setattr(processing_reader, "build_reader", build)

    assert processing_reader.main(stop=stop) == 0

    assert [s.s1_store for s in built] == ["postgres"]
    registered[signal.SIGTERM](signal.SIGTERM, None)  # the handlers stop the reader
    assert stop.is_set()


def test_idle_touches_the_alive_file_until_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alive = tmp_path / "alive"
    stop = threading.Event()
    waits: list[float] = []

    def wait(timeout: float | None = None) -> bool:
        waits.append(timeout or 0)
        if len(waits) == 2:
            stop.set()
        return stop.is_set()

    monkeypatch.setattr(stop, "wait", wait)

    assert processing_reader.idle(stop, "reason", alive) == 0
    assert alive.exists() and waits == [processing_reader.IDLE_TOUCH_SECONDS] * 2


def test_reader_health_follows_the_alive_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alive = tmp_path / "alive"
    monkeypatch.setattr(reader_health, "ALIVE_FILE", alive)

    alive.touch()
    assert reader_health.is_alive(alive) is True
    assert reader_health.main() == 0

    stale = time.time() - 91
    os.utime(alive, (stale, stale))
    assert reader_health.is_alive(alive) is False
    assert reader_health.main() == 1

    alive.unlink()
    assert reader_health.is_alive(alive) is False
    assert reader_health.main() == 1


def test_reader_health_allows_exactly_ninety_seconds(tmp_path: Path) -> None:
    alive = tmp_path / "alive"
    alive.touch()
    modified = alive.stat().st_mtime
    assert reader_health.is_alive(alive, now=modified + 90) is True
    assert reader_health.is_alive(alive, now=modified + 90.5) is False
    assert reader_health.is_alive(alive, now=modified + 10, max_age=5) is False


def test_reader_settings_refuse_a_heartbeat_over_a_third_of_the_lease() -> None:
    with pytest.raises(ValidationError, match="S1_READER_HEARTBEAT_SECONDS"):
        Settings(s1_reader_heartbeat_seconds=50, s1_reader_lease_seconds=120)

    assert Settings(s1_reader_heartbeat_seconds=40, s1_reader_lease_seconds=120).s1_reader_heartbeat_seconds == 40


def test_reader_settings_have_bounds_and_defaults() -> None:
    settings = Settings()
    assert (settings.s1_reader_poll_seconds, settings.s1_reader_lease_seconds, settings.s1_reader_heartbeat_seconds,
            settings.s1_reader_max_run_seconds, settings.s1_reader_shutdown_grace_seconds) == (2.0, 120, 30, 900, 45)
    for field, value in (("s1_reader_poll_seconds", 0.4), ("s1_reader_lease_seconds", 29),
                         ("s1_reader_heartbeat_seconds", 4), ("s1_reader_max_run_seconds", 59),
                         ("s1_reader_shutdown_grace_seconds", 301)):
        with pytest.raises(ValidationError):
            Settings(**{field: value})


def test_reader_settings_are_taken_from_the_settings() -> None:
    reader = ReaderSettings.from_settings(Settings(
        s1_store="postgres+jsonl", s1_processing="queued", s1_reader_poll_seconds=1.5, s1_reader_lease_seconds=90,
        s1_reader_heartbeat_seconds=20, s1_reader_max_run_seconds=600, s1_reader_shutdown_grace_seconds=10))

    assert reader == ReaderSettings(poll_seconds=1.5, lease_seconds=90, heartbeat_seconds=20, max_run_seconds=600,
                                    shutdown_grace_seconds=10, s1_store="postgres+jsonl", s1_processing="queued")
    assert isinstance(reader.lease_seconds, int)  # claim_s1_processing_run takes an integer
