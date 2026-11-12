"""Migration 0017 on the real database, as ``app_user``: the chunk table isolated per organization
by RLS, the claim and requeue functions, the run's new ``waiting_on_chunks`` status inside the
one-active-run index, a parked run woken exactly once (also under concurrency), and the reader
reading a large PDF through chunks on the real queue.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.document_chunk_repository import DocumentChunkRepository
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import ProcessingRun, ProcessingRunRepository
from backend.app.services.document_chunk_service import ChunkingSettings, DocumentChunkService
from backend.app.services.document_processing_service import DocumentProcessingService, RunParams
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.workers.processing_reader import ProcessingReader, ReaderSettings
from backend.tests.services.test_document_chunks import BILL_LINES, make_pdf

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000017a1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000017b2")
FUNCTIONS = ("claim_s1_document_chunk(text,integer)", "requeue_expired_s1_document_chunks()",
             "s1_wake_parent_run(text)")
SETTINGS = ReaderSettings(poll_seconds=0.05, lease_seconds=60, heartbeat_seconds=30, max_run_seconds=60,
                          shutdown_grace_seconds=5)


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    await _admin("TRUNCATE s1_processing_runs")
    await _admin("TRUNCATE users, organizations CASCADE")  # cascades to s1_document_chunks
    await _admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 'chunks-org-a'), "
                 "($2, 'Org B', 'chunks-org-b')", ORG_A, ORG_B)


@pytest.fixture(autouse=True)
def seeded() -> None:
    run(_seed)


async def _as_app(work: Callable[[Any], Awaitable[Any]], *, tenant: uuid.UUID | None = None,
                  provider: bool = False) -> Any:
    conn = await asyncpg.connect(APP_URL)
    try:
        async with conn.transaction():
            if tenant is not None:
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if provider:
                await conn.execute("SELECT set_config('app.is_provider', 'true', true)")
            return await work(conn)
    finally:
        await conn.close()


def _as(work: Callable[[Any], Awaitable[Any]], **scope: Any) -> Any:
    return run(lambda: _as_app(work, **scope))


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=6, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


class Queue:
    """Runs and chunks on Postgres, as the reader sees them."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.runs = ProcessingRunRepository(engine)
        self.chunks = DocumentChunkRepository(engine)

    def parked_run(self, org: uuid.UUID, document: str, ranges: list[tuple[int, int]],
                   max_attempts: int = 3) -> ProcessingRun:
        """A run claimed by a reader that planned its chunks: parked in waiting_on_chunks."""

        with scoped(S1Scope.tenant(org)):
            queued, _ = self.runs.enqueue(org_id=str(org), engagement_id="ENG-1", document_id=document,
                                          evidence_id=None, params={}, requested_by="r@example.com")
        claimed = self.runs.claim("reader:plan", 60)
        assert claimed is not None and claimed.run_id == queued.run_id
        assert self.chunks.plan(claimed, "reader:plan", ranges, max_attempts)
        return claimed

    def run_row(self, run_id: str) -> Any:
        return run(_admin, "SELECT status, attempts, worker_id, lease_expires_at FROM s1_processing_runs "
                           "WHERE run_id = $1", run_id)[0]


@pytest.fixture
def queue(engine: Engine) -> Queue:
    return Queue(engine)


# --- plan: chunks and the parked run, together --------------------------------------------------

def test_plan_parks_the_run_and_queues_its_chunks_in_one_step(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-1", [(1, 10), (11, 20), (21, 25)])

    row = queue.run_row(parked.run_id)
    assert (row["status"], row["attempts"], row["worker_id"], row["lease_expires_at"]) == (
        "waiting_on_chunks", 0, None, None)
    with scoped(S1Scope.tenant(ORG_A)):
        chunks = queue.chunks.list_for_run(parked.run_id)
        summary = queue.chunks.summaries([parked.run_id])[parked.run_id]
    assert [(c.chunk_index, c.page_from, c.page_to, c.status, c.max_attempts) for c in chunks] == [
        (0, 1, 10, "queued", 3), (1, 11, 20, "queued", 3), (2, 21, 25, "queued", 3)]
    assert (summary.total, summary.completed, summary.failed, summary.failed_pages) == (3, 0, 0, [])


def test_plan_by_a_reader_that_lost_the_run_creates_nothing(queue: Queue) -> None:
    with scoped(S1Scope.tenant(ORG_A)):
        queued, _ = queue.runs.enqueue(org_id=str(ORG_A), engagement_id="ENG-1", document_id="DOC-1",
                                       evidence_id=None, params={}, requested_by="r@example.com")
    claimed = queue.runs.claim("reader:1", 60)
    assert claimed is not None and claimed.run_id == queued.run_id

    assert queue.chunks.plan(claimed, "reader:other", [(1, 10)]) is False

    assert run(_admin, "SELECT count(*) AS n FROM s1_document_chunks")[0]["n"] == 0
    assert queue.run_row(claimed.run_id)["status"] == "in_progress"


def test_a_parked_run_still_counts_as_the_documents_active_run(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-1", [(1, 10)])

    with scoped(S1Scope.tenant(ORG_A)):
        again, created = queue.runs.enqueue(org_id=str(ORG_A), engagement_id="ENG-1", document_id="DOC-1",
                                            evidence_id=None, params={}, requested_by="other@example.com")

    assert (again.run_id, again.status, created) == (parked.run_id, "waiting_on_chunks", False)
    assert queue.runs.claim("reader:2", 60) is None  # a parked run is not claimable


# --- claiming ---------------------------------------------------------------------------------------

def test_chunks_are_claimed_across_organizations_oldest_first_and_recorded_in_their_own_scope(queue: Queue) -> None:
    run_a = queue.parked_run(ORG_A, "DOC-A", [(1, 10), (11, 12)])
    run_b = queue.parked_run(ORG_B, "DOC-B", [(1, 10)])

    claimed = [queue.chunks.claim("reader:1", 60) for _ in range(4)]

    assert [c is not None and (c.run_id, c.chunk_index, c.attempts, c.status) for c in claimed[:3]] == [
        (run_a.run_id, 0, 1, "in_progress"), (run_a.run_id, 1, 1, "in_progress"), (run_b.run_id, 0, 1, "in_progress")]
    assert claimed[3] is None
    first = claimed[0]
    assert first is not None and first.org_id == str(ORG_A)
    done = queue.chunks.finalize_completed(first, "reader:1", {"status": "parsed", "pages": []})
    assert done is not None and (done.status, done.worker_id, done.parser_output) == (
        "completed", None, {"status": "parsed", "pages": []})


def test_two_readers_claim_different_chunks(queue: Queue, engine: Engine) -> None:
    queue.parked_run(ORG_A, "DOC-A", [(1, 10), (11, 20)])
    repos = [DocumentChunkRepository(create_engine(to_sync_url(APP_URL or ""), pool_size=1, max_overflow=0))
             for _ in range(2)]
    barrier = threading.Barrier(2)
    claimed: list[Any] = [None, None]

    def claim(index: int) -> None:
        barrier.wait(5)
        claimed[index] = repos[index].claim(f"reader:{index}", 60)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    assert all(claimed) and {c.chunk_index for c in claimed} == {0, 1}


def test_a_stale_reader_cannot_record_a_chunk_it_lost(queue: Queue) -> None:
    queue.parked_run(ORG_A, "DOC-A", [(1, 10)])
    mine = queue.chunks.claim("reader:slow", 1)
    assert mine is not None
    time.sleep(1.2)
    assert [e.status for e in queue.chunks.requeue_expired()] == ["queued"]
    theirs = queue.chunks.claim("reader:fast", 60)
    assert theirs is not None and theirs.attempts == 2

    assert queue.chunks.heartbeat(mine, "reader:slow", 60) is None
    assert queue.chunks.finalize_completed(mine, "reader:slow", {"status": "parsed"}) is None
    assert queue.chunks.finalize_failed(mine, "reader:slow", "x") is None
    assert queue.chunks.finalize_completed(theirs, "reader:fast", {"status": "parsed"}) is not None


# --- retry, backoff, lease --------------------------------------------------------------------------

def test_retry_later_makes_the_chunk_due_again_only_after_its_backoff(queue: Queue) -> None:
    queue.parked_run(ORG_A, "DOC-A", [(1, 10)])
    chunk = queue.chunks.claim("reader:1", 60)
    assert chunk is not None

    retried = queue.chunks.retry_later(chunk, "reader:1", 1.0, "chunk_error")

    assert retried is not None and (retried.status, retried.error_code, retried.worker_id) == (
        "queued", "chunk_error", None)
    assert queue.chunks.claim("reader:1", 60) is None  # backing off
    time.sleep(1.2)
    again = queue.chunks.claim("reader:1", 60)
    assert again is not None and again.attempts == 2


def test_the_last_chunk_to_fail_for_good_wakes_the_run_and_the_summary_names_its_pages(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-A", [(1, 10), (11, 20), (21, 25)])
    claimed = [queue.chunks.claim("reader:1", 60) for _ in range(3)]
    assert all(claimed) and claimed[0] and claimed[1] and claimed[2]

    queue.chunks.finalize_completed(claimed[0], "reader:1", {"status": "parsed"})
    queue.chunks.finalize_completed(claimed[2], "reader:1", {"status": "parsed"})
    assert queue.run_row(parked.run_id)["status"] == "waiting_on_chunks"  # one chunk still unfinished
    queue.chunks.finalize_failed(claimed[1], "reader:1", "chunk_error")

    assert queue.run_row(parked.run_id)["status"] == "queued"
    with scoped(S1Scope.tenant(ORG_A)):
        summary = queue.chunks.summaries([parked.run_id])[parked.run_id]
    assert (summary.total, summary.completed, summary.failed, summary.failed_pages) == (3, 2, 1, [[11, 20]])


def test_expired_chunks_are_requeued_then_failed_after_their_last_attempt_and_wake_the_run(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-A", [(1, 10)], max_attempts=2)
    for attempt in (1, 2):
        taken = queue.chunks.claim("reader:dead", 1)
        assert taken is not None and taken.attempts == attempt
        time.sleep(1.2)
        expired = queue.chunks.requeue_expired()
        assert [(e.run_id, e.status) for e in expired] == [(parked.run_id, "queued" if attempt == 1 else "failed")]

    with scoped(S1Scope.tenant(ORG_A)):
        chunk = queue.chunks.list_for_run(parked.run_id)[0]
    assert (chunk.status, chunk.error_code) == ("failed", "timed_out")
    assert queue.run_row(parked.run_id)["status"] == "queued"


def test_requeue_expired_heals_a_parked_run_whose_wake_was_missed(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-A", [(1, 10)])
    chunk = queue.chunks.claim("reader:1", 60)
    assert chunk is not None
    # The chunk ends, but the wake-up never happened (as if the reader died between the two).
    run(_admin, "UPDATE s1_document_chunks SET status = 'completed', worker_id = NULL, lease_expires_at = NULL")
    assert queue.run_row(parked.run_id)["status"] == "waiting_on_chunks"

    queue.chunks.requeue_expired()

    assert queue.run_row(parked.run_id)["status"] == "queued"


# --- exactly once -----------------------------------------------------------------------------------

def test_two_readers_ending_the_last_two_chunks_at_once_wake_the_run_once(queue: Queue) -> None:
    engines = [create_engine(to_sync_url(APP_URL or ""), pool_size=1, max_overflow=0) for _ in range(2)]
    try:
        for trial in range(25):
            parked = queue.parked_run(ORG_A, f"DOC-{trial}", [(1, 10), (11, 20)])
            claimed = [queue.chunks.claim(f"reader:{i}", 60) for i in range(2)]
            assert all(claimed)
            barrier = threading.Barrier(2)
            errors: list[BaseException] = []

            def finish(index: int, chunk: Any) -> None:
                try:
                    barrier.wait(5)
                    done = DocumentChunkRepository(engines[index]).finalize_completed(
                        chunk, f"reader:{index}", {"status": "parsed"})
                    assert done is not None
                except BaseException as exc:  # noqa: BLE001 - reported below
                    errors.append(exc)

            threads = [threading.Thread(target=finish, args=(i, c)) for i, c in enumerate(claimed)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

            assert errors == []
            assert queue.run_row(parked.run_id)["status"] == "queued", f"trial {trial}: the run was never woken"
            first = queue.runs.claim("reader:a", 60)
            assert first is not None and first.run_id == parked.run_id
            assert queue.runs.claim("reader:b", 60) is None  # woken once: one claim
            queue.runs.finalize_completed(first, "reader:a", "P-1")
    finally:
        for engine in engines:
            engine.dispose()


def test_waking_is_fenced_on_the_status_and_on_unfinished_chunks(queue: Queue) -> None:
    parked = queue.parked_run(ORG_A, "DOC-A", [(1, 10), (11, 20)])

    async def wake_now(conn: Any) -> bool:
        return bool(await conn.fetchval("SELECT s1_wake_parent_run($1)", parked.run_id))

    assert _as(wake_now, tenant=ORG_A) is False  # chunks are unfinished
    run(_admin, "UPDATE s1_document_chunks SET status = 'completed'")
    assert _as(wake_now, tenant=ORG_A) is True
    assert _as(wake_now, tenant=ORG_A) is False  # already queued
    assert _as(wake_now, tenant=ORG_B) is False  # not this organization's run


# --- RLS --------------------------------------------------------------------------------------------

async def _chunk_ids(conn: Any) -> set[str]:
    return {row["id"] for row in await conn.fetch("SELECT id FROM s1_document_chunks")}


def test_each_org_sees_only_its_own_chunks_and_provider_sees_all(queue: Queue) -> None:
    queue.parked_run(ORG_A, "DOC-A", [(1, 10)])
    queue.parked_run(ORG_B, "DOC-B", [(1, 10), (11, 20)])

    a, b = _as(_chunk_ids, tenant=ORG_A), _as(_chunk_ids, tenant=ORG_B)

    assert len(a) == 1 and len(b) == 2 and not a & b
    assert len(_as(_chunk_ids, provider=True)) == 3
    assert _as(_chunk_ids) == set()  # no tenant context: nothing


def test_another_org_cannot_see_update_or_claim_a_chunk_through_the_repository_or_sql(queue: Queue) -> None:
    run_a = queue.parked_run(ORG_A, "DOC-A", [(1, 10)])
    with scoped(S1Scope.tenant(ORG_B)):
        assert queue.chunks.list_for_run(run_a.run_id) == []
        assert queue.chunks.summaries([run_a.run_id]) == {}

    async def take_other_orgs_chunk(conn: Any) -> str:
        return await conn.execute("UPDATE s1_document_chunks SET status = 'in_progress', worker_id = 'x', "
                                  "lease_expires_at = now() + interval '1 minute' WHERE org_id = $1", ORG_A)

    assert _as(take_other_orgs_chunk, tenant=ORG_B) == "UPDATE 0"

    async def insert_for_a(conn: Any) -> None:
        await conn.execute("INSERT INTO s1_document_chunks (id, org_id, run_id, document_id, chunk_index, "
                           "page_from, page_to) VALUES ('sneaky', $1, 'r', 'd', 0, 1, 2)", ORG_A)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):  # RLS WITH CHECK
        _as(insert_for_a, tenant=ORG_B)

    async def delete_own(conn: Any) -> None:
        await conn.execute("DELETE FROM s1_document_chunks WHERE org_id = $1", ORG_A)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _as(delete_own, tenant=ORG_A)

    # An organization's reader scope cannot finish another organization's chunk either.
    claimed = queue.chunks.claim("reader:1", 60)
    assert claimed is not None and claimed.org_id == str(ORG_A)
    foreign = DocumentChunkRepository(queue.engine)
    wrong_org = claimed.__class__(**{**claimed.__dict__, "org_id": str(ORG_B)})
    assert foreign.finalize_completed(wrong_org, "reader:1", {"status": "parsed"}) is None
    assert foreign.finalize_completed(claimed, "reader:1", {"status": "parsed"}) is not None


def test_rls_is_forced_and_the_functions_are_locked_down() -> None:
    flags = run(_admin, "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 's1_document_chunks'")
    assert flags[0]["relrowsecurity"] and flags[0]["relforcerowsecurity"]
    for signature in FUNCTIONS:
        row = run(_admin, "SELECT p.prosecdef, p.proacl::text AS acl, "
                          "has_function_privilege('app_user', p.oid, 'EXECUTE') AS app_user_may "
                          "FROM pg_proc p WHERE p.oid = $1::regprocedure", signature)[0]
        assert row["app_user_may"], signature
        assert "{=" not in row["acl"] and ",=" not in row["acl"], (signature, row["acl"])  # nothing for PUBLIC
        # The two that serve every organization run as owner; the wake-up runs as its caller.
        assert row["prosecdef"] == (signature != "s1_wake_parent_run(text)"), signature


# --- constraints ------------------------------------------------------------------------------------

@pytest.mark.parametrize("columns", [
    {"page_from": 0, "page_to": 5},  # pages are 1-based
    {"page_from": 5, "page_to": 4},
    {"status": "paused"},
    {"status": "in_progress"},  # a chunk being read has a reader and a lease
    {"attempts": -1},
    {"max_attempts": 0},
    {"chunk_index": -1},
])
def test_a_chunk_must_be_consistent(columns: dict[str, Any]) -> None:
    values = {"id": "c", "org_id": ORG_A, "run_id": "r", "document_id": "d", "chunk_index": 0, "page_from": 1,
              "page_to": 2, **columns}

    async def insert(conn: Any) -> None:
        names = ", ".join(values)
        marks = ", ".join(f"${i}" for i in range(1, len(values) + 1))
        await conn.execute(f"INSERT INTO s1_document_chunks ({names}) VALUES ({marks})", *values.values())

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        _as(insert, tenant=ORG_A)


def test_a_run_has_one_chunk_per_index() -> None:
    async def twice(conn: Any) -> None:
        for chunk_id in ("c1", "c2"):
            await conn.execute("INSERT INTO s1_document_chunks (id, org_id, run_id, document_id, chunk_index, "
                               "page_from, page_to) VALUES ($1, $2, 'r', 'd', 0, 1, 2)", chunk_id, ORG_A)

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        _as(twice, tenant=ORG_A)


# --- the reader, end to end on the real queue ----------------------------------------------------------

def exit_never(code: int) -> NoReturn:
    raise AssertionError(f"the reader exited with {code}")


def test_the_reader_reads_a_large_pdf_through_chunks_on_the_real_queue(engine: Engine, tmp_path: Path) -> None:
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository())
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    runs, chunks = ProcessingRunRepository(engine), DocumentChunkRepository(engine)
    chunk_service = DocumentChunkService(chunks, uploads, storage, ChunkingSettings(enabled=True))
    reader = ProcessingReader(runs, uploads, pipeline, storage, settings=SETTINGS, worker_id="reader:db",
                              alive_file=tmp_path / "alive", exit=exit_never, chunks=chunks,
                              chunk_service=chunk_service)
    api = DocumentProcessingService(runs, uploads, pipeline, storage, worker_id="api")
    content = make_pdf(tmp_path / "src.pdf", 25, BILL_LINES).read_bytes()
    document = uploads.upload_document(engagement_id="ENG-1", file_name="big.pdf", content=content,
                                       mime_type="application/pdf", document_role="source_evidence",
                                       uploaded_by="member@acme.test", org_id=str(ORG_A))
    with scoped(S1Scope.tenant(ORG_A)):
        queued, _ = api.request(document=document, org_id=str(ORG_A), requested_by="member@acme.test",
                                params=RunParams())
        api.mark_queued(queued)

    seen = []
    for _ in range(10):
        job = reader.run_once()
        if job is None:
            break
        seen.append(getattr(job, "status", None))

    assert seen == ["waiting_on_chunks", "completed", "completed", "completed", "completed"]
    with scoped(S1Scope.tenant(ORG_A)):
        finished = runs.get(queued.run_id)
        assert finished is not None and finished.status == "completed" and finished.pipeline_run_id
        assert [c.status for c in chunks.list_for_run(queued.run_id)] == ["completed"] * 3
    recorded = pipeline.get_pipeline_run(finished.pipeline_run_id)
    assert recorded is not None and recorded["status"] == "completed"
    assert uploads.get_document(document["document_id"])["processing_status"] == "completed"
