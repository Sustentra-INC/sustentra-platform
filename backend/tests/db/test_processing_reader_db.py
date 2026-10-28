"""The reader process on the real queue (migration 0015, as ``app_user``): it claims runs across
organizations and records each in its own organization's scope, takes back a run whose reader
died, and two readers never claim the same run. The documents and the pipeline stay in memory.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import ProcessingRun, ProcessingRunRepository
from backend.app.services.document_processing_service import DocumentProcessingService, RunParams
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.workers.processing_reader import ProcessingReader, ReaderSettings

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000015f1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000015f1")
BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"
SETTINGS = ReaderSettings(poll_seconds=0.05, lease_seconds=60, heartbeat_seconds=1, max_run_seconds=60,
                          shutdown_grace_seconds=5)


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    await _admin("TRUNCATE s1_processing_runs")
    await _admin("TRUNCATE users, organizations CASCADE")
    await _admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'reader-acme'), "
                 "($2, 'Beta', 'reader-beta')", ORG_A, ORG_B)


def exit_never(code: int) -> NoReturn:
    raise AssertionError(f"the reader exited with {code}")


@dataclass
class World:
    repo: ProcessingRunRepository
    uploads: DocumentUploadService
    service: DocumentProcessingService
    reader: ProcessingReader
    engine: Engine
    storage: LocalStorageService
    pipeline: PipelineOrchestrationService
    tmp: Path

    def document(self, org: uuid.UUID, engagement: str = "ENG-READER") -> dict:
        return self.uploads.upload_document(engagement_id=engagement, file_name="bill.txt", content=BILL,
                                            mime_type="text/plain", document_role="source_evidence",
                                            uploaded_by="member@acme.test", org_id=str(org))

    def queue(self, org: uuid.UUID, document: dict) -> ProcessingRun:
        """The run as the api queues it in queued mode, in the organization's own scope."""

        with scoped(S1Scope.tenant(org)):
            run, created = self.service.request(document=document, org_id=str(org), requested_by="member@acme.test",
                                                params=RunParams())
            self.service.mark_queued(run)
        assert created
        return run

    def status(self, document_id: str) -> str:
        document = self.uploads.get_document(document_id)
        assert document is not None
        return str(document["processing_status"])

    def reader_on(self, engine: Engine, name: str) -> ProcessingReader:
        return ProcessingReader(ProcessingRunRepository(engine), self.uploads, self.pipeline, self.storage,
                                settings=SETTINGS, worker_id=name, alive_file=self.tmp / f"alive-{name}",
                                exit=exit_never)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    asyncio.run(_seed())
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository())
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=4, max_overflow=0)
    repo = ProcessingRunRepository(engine)
    service = DocumentProcessingService(repo, uploads, pipeline, storage, worker_id="api:test")
    reader = ProcessingReader(repo, uploads, pipeline, storage, settings=SETTINGS, worker_id="reader:db",
                              alive_file=tmp_path / "alive", exit=exit_never)
    try:
        yield World(repo, uploads, service, reader, engine, storage, pipeline, tmp_path)
    finally:
        engine.dispose()


def test_the_reader_claims_across_organizations_and_records_in_each_scope(world: World) -> None:
    doc_a, doc_b = world.document(ORG_A, "ENG-A"), world.document(ORG_B, "ENG-B")
    run_a, run_b = world.queue(ORG_A, doc_a), world.queue(ORG_B, doc_b)

    first, second = world.reader.run_once(), world.reader.run_once()

    assert first is not None and second is not None
    assert [(r.run_id, r.status) for r in (first, second)] == [(run_a.run_id, "completed"), (run_b.run_id, "completed")]
    assert first.pipeline_run_id and second.pipeline_run_id and first.pipeline_run_id != second.pipeline_run_id
    assert world.status(doc_a["document_id"]) == "completed" and world.status(doc_b["document_id"]) == "completed"
    assert world.reader.run_once() is None

    with scoped(S1Scope.tenant(ORG_A)):  # RLS: each organization sees only its own run
        assert world.repo.get(run_a.run_id) is not None and world.repo.get(run_b.run_id) is None
        assert [r.run_id for r in world.repo.latest_per_document("ENG-A")] == [run_a.run_id]
        assert world.repo.latest_per_document("ENG-B") == []
    with scoped(S1Scope.tenant(ORG_B)):
        assert world.repo.get(run_b.run_id) is not None and world.repo.get(run_a.run_id) is None
        assert [r.run_id for r in world.repo.latest_per_document("ENG-B")] == [run_b.run_id]
        assert world.repo.latest_per_document("ENG-A") == []

    rows = asyncio.run(_admin("SELECT run_id, org_id, status, worker_id, lease_expires_at FROM s1_processing_runs "
                              "ORDER BY created_at"))
    assert [(r["run_id"], r["org_id"], r["status"], r["worker_id"], r["lease_expires_at"]) for r in rows] == [
        (run_a.run_id, ORG_A, "completed", "reader:db", None), (run_b.run_id, ORG_B, "completed", "reader:db", None)]


def test_a_run_whose_reader_died_is_taken_back_after_its_lease(world: World) -> None:
    document = world.document(ORG_A)
    run = world.queue(ORG_A, document)
    claimed = world.repo.claim("reader:dead", 1)  # a reader that took it and then died
    assert claimed is not None and claimed.run_id == run.run_id
    with scoped(S1Scope.tenant(ORG_A)):
        world.uploads.update_processing_status(run.document_id, "in_progress")
    assert world.reader.run_once() is None  # still leased

    time.sleep(1.5)

    assert world.reader.requeue_expired() == 1
    assert world.status(run.document_id) == "queued"
    done = world.reader.run_once()
    assert done is not None
    assert (done.run_id, done.status, done.attempts, done.worker_id) == (run.run_id, "completed", 2, "reader:db")
    assert world.status(run.document_id) == "completed"


def test_a_run_that_used_every_attempt_is_failed_after_its_lease(world: World) -> None:
    run = world.queue(ORG_A, world.document(ORG_A))
    for attempt in (1, 2, 3):  # three readers in turn took it and died
        taken = world.repo.claim("reader:dead", 1)
        assert taken is not None and taken.attempts == attempt
        time.sleep(1.1)
        assert world.reader.requeue_expired() == 1

    with scoped(S1Scope.tenant(ORG_A)):
        failed = world.repo.get(run.run_id)
    assert failed is not None and (failed.status, failed.error_code) == ("failed", "timed_out")
    assert world.status(run.document_id) == "failed"
    assert world.reader.run_once() is None


def test_two_readers_claim_different_runs(world: World) -> None:
    runs = [world.queue(ORG_A, world.document(ORG_A)) for _ in range(2)]
    engines = [create_engine(to_sync_url(APP_URL or ""), pool_size=1, max_overflow=0) for _ in range(2)]
    barrier = threading.Barrier(2)
    claimed: list[ProcessingRun | None] = [None, None]

    def claim(index: int) -> None:
        repo = ProcessingRunRepository(engines[index])
        barrier.wait(5)
        claimed[index] = repo.claim(f"reader:{index}", 60)

    try:
        threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
    finally:
        for engine in engines:
            engine.dispose()

    assert all(run is not None for run in claimed)
    ids = {run.run_id for run in claimed if run is not None}
    assert ids == {run.run_id for run in runs}  # one each, none twice


def test_two_readers_drain_the_queue_without_reading_a_run_twice(world: World) -> None:
    runs = [world.queue(ORG_A if i % 2 else ORG_B, world.document(ORG_A if i % 2 else ORG_B)) for i in range(6)]
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=4, max_overflow=0)
    readers = [world.reader_on(world.engine, "reader:1"), world.reader_on(engine, "reader:2")]
    done: list[list[str]] = [[], []]

    def drain(index: int) -> None:
        while (run := readers[index].run_once()) is not None:
            done[index].append(run.run_id)

    try:
        threads = [threading.Thread(target=drain, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        engine.dispose()

    assert sorted(done[0] + done[1]) == sorted(run.run_id for run in runs)  # each exactly once
    rows = asyncio.run(_admin("SELECT status, attempts FROM s1_processing_runs"))
    assert [(r["status"], r["attempts"]) for r in rows] == [("completed", 1)] * 6
