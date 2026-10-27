"""The processing-run queue behaves the same in memory and in Postgres (migration 0015).

Every contract test runs against both. The Postgres runs need TEST_DATABASE_URL (owner, for
seeding and moving leases into the past) and TEST_APP_DATABASE_URL (app_user, which the
repository uses, so RLS applies); without them only the Postgres runs are skipped.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import MissingS1Scope, S1Scope, scoped
from backend.app.repositories.processing_run_repository import (
    TIMED_OUT,
    TIMED_OUT_MESSAGE,
    ExpiredRun,
    InMemoryProcessingRunRepository,
    ProcessingRun,
    ProcessingRunRepository,
)

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
ORG = uuid.UUID("eeeeeeee-0000-0000-0000-0000000000e5")
OTHER_ORG = uuid.UUID("ffffffff-0000-0000-0000-0000000000f6")
PARAMS = {"canonical_type_id_override": None, "include_optional": True, "include_deprecated": False}


@dataclass
class Queue:
    runs: Any
    expire_lease: Callable[[str], None]  # the run's lease ran out (its reader stopped)
    make_due: Callable[[str], None]  # a run waiting to be retried is due now


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(microseconds=1)  # like now(): later calls are later
        return self.now


@pytest.fixture(scope="module")
def pg_engines() -> Iterator[tuple[Any, Any]]:
    if not (ADMIN_URL and APP_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")
    admin = create_engine(to_sync_url(ADMIN_URL), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL), pool_size=2, max_overflow=0)
    try:
        yield admin, app
    finally:
        admin.dispose()
        app.dispose()


def _reset(admin: Any) -> None:
    with admin.begin() as connection:
        connection.execute(text("TRUNCATE s1_processing_runs"))
        connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'Queue A', 's1-queue-a'), "
                 "(:b, 'Queue B', 's1-queue-b') ON CONFLICT DO NOTHING"),
            {"a": ORG, "b": OTHER_ORG},
        )


def _admin_update(admin: Any, run_id: str, assignment: str) -> None:
    with admin.begin() as connection:
        connection.execute(text(f"UPDATE s1_processing_runs SET {assignment} WHERE run_id = :id"), {"id": run_id})


def _memory_queue() -> Queue:
    clock = Clock()
    runs = InMemoryProcessingRunRepository(clock)

    def change(run_id: str, **fields: Any) -> None:
        stored = runs._runs[run_id]
        stored.run = replace(stored.run, **fields)

    return Queue(runs,
                 expire_lease=lambda run_id: change(run_id, lease_expires_at=clock.now - timedelta(seconds=1)),
                 make_due=lambda run_id: change(run_id, run_after=clock.now))


@pytest.fixture(params=["memory", "postgres"])
def queue(request: pytest.FixtureRequest) -> Iterator[Queue]:
    if request.param == "memory":
        yield _memory_queue()
        return
    admin, app = request.getfixturevalue("pg_engines")
    _reset(admin)
    yield Queue(ProcessingRunRepository(app),
                expire_lease=lambda run_id: _admin_update(admin, run_id,
                                                          "lease_expires_at = now() - interval '1 second'"),
                make_due=lambda run_id: _admin_update(admin, run_id, "run_after = now()"))


def _enqueue(runs: Any, document_id: str, org: uuid.UUID = ORG, **overrides: Any) -> tuple[ProcessingRun, bool]:
    fields: dict[str, Any] = {
        "org_id": str(org), "engagement_id": "ENG-1", "document_id": document_id,
        "evidence_id": f"EV-{document_id}", "params": PARAMS, "requested_by": "reader@example.com",
    }
    fields.update(overrides)
    with scoped(S1Scope.tenant(org)):
        return runs.enqueue(**fields)


def _get(runs: Any, run_id: str, org: uuid.UUID = ORG) -> ProcessingRun:
    with scoped(S1Scope.tenant(org)):
        run = runs.get(run_id)
    assert run is not None
    return run


# --- contract: both stores ------------------------------------------------------------------

def test_a_document_has_one_active_run(queue: Queue) -> None:
    first, created = _enqueue(queue.runs, "DOC-1")
    assert created
    assert (first.status, first.attempts, first.max_attempts, first.kind) == ("queued", 0, 3, "process_document")
    assert (first.org_id, first.document_id, first.evidence_id) == (str(ORG), "DOC-1", "EV-DOC-1")
    assert first.params == PARAMS and first.requested_by == "reader@example.com"
    assert first.worker_id is None and first.started_at is None and first.completed_at is None

    again, created_again = _enqueue(queue.runs, "DOC-1", params={"canonical_type_id_override": "CT-S1-ELEC"})
    assert not created_again
    assert again.run_id == first.run_id and again.params == PARAMS  # the run already asked for

    other, created_other = _enqueue(queue.runs, "DOC-2")
    assert created_other and other.run_id != first.run_id
    assert _get(queue.runs, first.run_id) == first


def test_a_finished_run_makes_room_for_the_next_and_is_still_listed(queue: Queue) -> None:
    first, _ = _enqueue(queue.runs, "DOC-1")
    started = queue.runs.start(first, "inline:host:1", 60)
    assert started is not None
    done = queue.runs.finalize_completed(started, "inline:host:1", "pipeline::EV-DOC-1::abc")
    assert done is not None and done.status == "completed" and done.pipeline_run_id == "pipeline::EV-DOC-1::abc"
    assert done.completed_at is not None and done.lease_expires_at is None

    second, created = _enqueue(queue.runs, "DOC-1", params={**PARAMS, "canonical_type_id_override": "CT-S1-ELEC"})
    assert created and second.run_id != first.run_id
    third, _ = _enqueue(queue.runs, "DOC-2")
    _enqueue(queue.runs, "DOC-3", engagement_id="ENG-2")

    with scoped(S1Scope.tenant(ORG)):
        latest = queue.runs.latest_per_document("ENG-1")
        assert queue.runs.latest_per_document("ENG-404") == []
    assert [run.run_id for run in latest] == [second.run_id, third.run_id]  # one per document, oldest first
    assert _get(queue.runs, first.run_id).status == "completed"


def test_claim_takes_the_oldest_due_run_from_any_organization(queue: Queue) -> None:
    other, _ = _enqueue(queue.runs, "DOC-B", org=OTHER_ORG)
    own, _ = _enqueue(queue.runs, "DOC-A")
    later, _ = _enqueue(queue.runs, "DOC-C")
    waiting = queue.runs.claim("w0", 60)
    assert waiting is not None and waiting.run_id == other.run_id
    assert queue.runs.retry_later(waiting, "w0", 3600, "worker_error") is not None  # not due for an hour

    first = queue.runs.claim("w1", 120)
    second = queue.runs.claim("w2", 120)
    assert first is not None and second is not None
    assert (first.run_id, second.run_id) == (own.run_id, later.run_id)
    assert (first.status, first.attempts, first.worker_id) == ("in_progress", 1, "w1")
    assert first.started_at is not None and first.lease_expires_at is not None
    assert first.lease_expires_at > first.started_at
    assert queue.runs.claim("w3", 120) is None  # the other organization's run is not due yet

    queue.make_due(other.run_id)
    retried = queue.runs.claim("w3", 120)
    assert retried is not None and retried.run_id == other.run_id and retried.attempts == 2
    assert retried.org_id == str(OTHER_ORG) and retried.error_code == "worker_error"


def test_start_and_every_update_are_fenced_to_the_reader_holding_the_run(queue: Queue) -> None:
    run, _ = _enqueue(queue.runs, "DOC-1")
    started = queue.runs.start(run, "w1", 60)
    assert started is not None and (started.status, started.attempts, started.worker_id) == ("in_progress", 1, "w1")
    assert queue.runs.start(run, "w2", 60) is None  # no longer queued
    assert queue.runs.claim("w2", 60) is None

    assert queue.runs.heartbeat(started, "w2", 600) is None
    assert queue.runs.finalize_completed(started, "w2", "P-1") is None
    assert queue.runs.finalize_failed(started, "w2", "pipeline_failed", "No.") is None
    assert queue.runs.retry_later(started, "w2", 30) is None
    assert queue.runs.release(started, "w2") is None
    assert _get(queue.runs, run.run_id) == started  # nothing changed

    renewed = queue.runs.heartbeat(started, "w1", 600)
    assert renewed is not None and renewed.lease_expires_at > started.lease_expires_at  # type: ignore[operator]
    failed = queue.runs.finalize_failed(renewed, "w1", "unreadable_document", "This PDF could not be opened.",
                                        "pipeline::EV-DOC-1::halted")
    assert failed is not None
    assert (failed.status, failed.error_code, failed.error, failed.pipeline_run_id) == (
        "failed", "unreadable_document", "This PDF could not be opened.", "pipeline::EV-DOC-1::halted")
    assert failed.completed_at is not None and failed.lease_expires_at is None
    assert queue.runs.finalize_completed(failed, "w1", "P-1") is None  # finished runs stay finished


def test_release_puts_the_run_back_without_counting_the_attempt(queue: Queue) -> None:
    run, _ = _enqueue(queue.runs, "DOC-1")
    claimed = queue.runs.claim("w1", 60)
    assert claimed is not None and claimed.attempts == 1
    released = queue.runs.release(claimed, "w1")
    assert released is not None
    assert (released.status, released.attempts, released.worker_id, released.lease_expires_at) == (
        "queued", 0, None, None)
    again = queue.runs.claim("w2", 60)
    assert again is not None and again.run_id == run.run_id and again.attempts == 1
    assert again.started_at == claimed.started_at  # first started then


def test_expired_leases_are_requeued_then_timed_out(queue: Queue) -> None:
    run, _ = _enqueue(queue.runs, "DOC-1", max_attempts=2)
    first = queue.runs.claim("w1", 60)
    assert first is not None
    assert queue.runs.requeue_expired() == []  # the lease is still good
    queue.expire_lease(run.run_id)
    assert queue.runs.requeue_expired() == [ExpiredRun(run.run_id, str(ORG), "DOC-1", "queued")]
    assert queue.runs.finalize_completed(first, "w1", "P-1") is None  # the stale reader's result is dropped

    second = queue.runs.claim("w2", 60)
    assert second is not None and second.attempts == 2
    queue.expire_lease(run.run_id)
    assert queue.runs.requeue_expired() == [ExpiredRun(run.run_id, str(ORG), "DOC-1", "failed")]
    timed_out = _get(queue.runs, run.run_id)
    assert (timed_out.status, timed_out.error_code, timed_out.worker_id) == ("failed", TIMED_OUT, None)
    assert timed_out.error == "Reading stopped 2 times before it finished. Try again later, or upload a smaller file."
    assert timed_out.completed_at is not None
    assert queue.runs.requeue_expired() == []


def test_a_run_whose_reader_stopped_no_longer_blocks_a_new_request(queue: Queue) -> None:
    run, _ = _enqueue(queue.runs, "DOC-1")
    assert queue.runs.start(run, "inline:host:1", 900) is not None
    queue.expire_lease(run.run_id)  # e.g. the API restarted mid-read

    fresh, created = _enqueue(queue.runs, "DOC-1")
    assert created and fresh.run_id != run.run_id and fresh.status == "queued"
    stale = _get(queue.runs, run.run_id)
    assert (stale.status, stale.error_code, stale.error) == ("failed", TIMED_OUT, TIMED_OUT_MESSAGE)


# --- Postgres only --------------------------------------------------------------------------

def test_postgres_runs_stay_in_their_organization(pg_engines: tuple[Any, Any]) -> None:
    admin, app = pg_engines
    _reset(admin)
    runs = ProcessingRunRepository(app)
    own, _ = _enqueue(runs, "DOC-A")
    foreign, _ = _enqueue(runs, "DOC-B", org=OTHER_ORG)

    with scoped(S1Scope.tenant(ORG)):
        assert runs.get(foreign.run_id) is None
        assert [run.run_id for run in runs.latest_per_document("ENG-1")] == [own.run_id]
    with scoped(S1Scope.platform()):
        assert {run.run_id for run in runs.latest_per_document("ENG-1")} == {own.run_id, foreign.run_id}

    from sqlalchemy.exc import DBAPIError

    with scoped(S1Scope.tenant(ORG)), pytest.raises(DBAPIError):  # RLS WITH CHECK
        runs.enqueue(org_id=str(OTHER_ORG), engagement_id="ENG-1", document_id="DOC-X", evidence_id=None,
                     params={}, requested_by="sneaky@example.com")


def test_postgres_runs_need_a_bound_organization(pg_engines: tuple[Any, Any]) -> None:
    _admin, app = pg_engines
    runs = ProcessingRunRepository(app)
    with pytest.raises(MissingS1Scope):
        runs.get("run")
    with pytest.raises(MissingS1Scope):
        runs.enqueue(org_id=str(ORG), engagement_id="ENG-1", document_id="DOC-1", evidence_id=None, params={},
                     requested_by="reader@example.com")
