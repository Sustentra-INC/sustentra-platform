"""S1 processing runs (migration 0015): the queue of document reads.

A run is one request to read a document. It is ``queued`` when asked for, ``in_progress``
once something claims it (with a worker id and a lease that the reader renews), and then
``completed`` (with the pipeline run it produced) or ``failed`` (with a message for the user).
A document has at most one active (queued or in_progress) run.

Two implementations with the same interface:

* ``ProcessingRunRepository``: Postgres (``s1_processing_runs``) on the sync engine.
* ``InMemoryProcessingRunRepository``: the same rules in memory, for tests.

Which organization a call works in:

* ``enqueue``, ``get`` and ``latest_per_document`` run in the bound S1 scope
  (``core.s1_scope.current_scope``): the signed-in organization, so RLS keeps them to it.
* The updates of one run (``start``, ``heartbeat``, ``finalize_completed``, ``finalize_failed``,
  ``retry_later``, ``release``) run in the run's own organization (an explicit
  ``S1Scope.tenant``), so a reader with no request behind it can use them. Each is fenced:
  it changes the run only while it is still the caller's (``worker_id``, ``in_progress``;
  ``start``: still ``queued``) and returns ``None`` otherwise, so a reader that lost its lease
  changes nothing.
* ``claim`` and ``requeue_expired`` serve every organization. They call the SECURITY DEFINER
  functions of migration 0015 on a plain transaction: the functions switch provider scope on
  for themselves only, and the caller never holds it.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope, current_scope

ACTIVE_STATUSES = ("queued", "in_progress")
DEFAULT_MAX_ATTEMPTS = 3
# A run whose lease ran out while it was being read (the reader was killed, or hung) and that
# is not read again: the user's message.
TIMED_OUT = "timed_out"
TIMED_OUT_MESSAGE = "Reading stopped before it finished. Try again later, or upload a smaller file."


@dataclass(frozen=True)
class ProcessingRun:
    run_id: str
    org_id: str
    engagement_id: str
    document_id: str
    evidence_id: str | None
    params: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    requested_by: str
    run_after: datetime
    created_at: datetime
    updated_at: datetime
    kind: str = "process_document"
    lease_expires_at: datetime | None = None
    worker_id: str | None = None
    pipeline_run_id: str | None = None
    error_code: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class ExpiredRun(NamedTuple):
    """A run ``requeue_expired`` changed: back to ``queued``, or ``failed`` after its last attempt."""

    run_id: str
    org_id: str
    document_id: str
    status: str


def new_run_id() -> str:
    return uuid.uuid4().hex


_FIELDS = tuple(name for name in ProcessingRun.__dataclass_fields__)


def _run(row: Any) -> ProcessingRun:
    values = dict(row._mapping)
    values["org_id"] = str(values["org_id"])
    params = values.get("params")
    values["params"] = dict(json.loads(params) if isinstance(params, str) else params or {})
    return ProcessingRun(**{name: values[name] for name in _FIELDS})


# --- Postgres -------------------------------------------------------------------------------

_LEASE = "now() + make_interval(secs => :lease_seconds)"
_FENCE = "run_id = :run_id AND worker_id = :worker_id AND status = 'in_progress'"
_ACTIVE = "status IN ('queued', 'in_progress')"

_EXPIRE_STALE = text(
    "UPDATE s1_processing_runs SET status = 'failed', error_code = :code, error = :message, "
    "worker_id = NULL, lease_expires_at = NULL, completed_at = now(), updated_at = now() "
    "WHERE org_id = :org_id AND document_id = :document_id AND status = 'in_progress' "
    "AND lease_expires_at < now()"
)
_INSERT = text(
    "INSERT INTO s1_processing_runs "
    "(run_id, org_id, engagement_id, document_id, evidence_id, params, requested_by, max_attempts) "
    "VALUES (:run_id, :org_id, :engagement_id, :document_id, :evidence_id, CAST(:params AS jsonb), "
    ":requested_by, :max_attempts) "
    f"ON CONFLICT (org_id, document_id) WHERE {_ACTIVE} DO NOTHING RETURNING *"
)
_ACTIVE_RUN = text(
    f"SELECT * FROM s1_processing_runs WHERE org_id = :org_id AND document_id = :document_id AND {_ACTIVE}"
)
_GET = text("SELECT * FROM s1_processing_runs WHERE run_id = :run_id")
_LATEST_PER_DOCUMENT = text(
    "SELECT * FROM (SELECT DISTINCT ON (document_id) * FROM s1_processing_runs "
    "WHERE engagement_id = :engagement_id ORDER BY document_id, created_at DESC, run_id DESC) latest "
    "ORDER BY created_at, run_id"
)
_START = text(
    "UPDATE s1_processing_runs SET status = 'in_progress', attempts = attempts + 1, worker_id = :worker_id, "
    f"started_at = coalesce(started_at, now()), lease_expires_at = {_LEASE}, updated_at = now() "
    "WHERE run_id = :run_id AND status = 'queued' RETURNING *"
)
_HEARTBEAT = text(
    f"UPDATE s1_processing_runs SET lease_expires_at = {_LEASE}, updated_at = now() WHERE {_FENCE} RETURNING *"
)
_COMPLETED = text(
    "UPDATE s1_processing_runs SET status = 'completed', pipeline_run_id = :pipeline_run_id, "
    "error_code = NULL, error = NULL, lease_expires_at = NULL, completed_at = now(), updated_at = now() "
    f"WHERE {_FENCE} RETURNING *"
)
_FAILED = text(
    "UPDATE s1_processing_runs SET status = 'failed', error_code = :error_code, error = :error, "
    "pipeline_run_id = coalesce(:pipeline_run_id, pipeline_run_id), "
    "lease_expires_at = NULL, completed_at = now(), updated_at = now() "
    f"WHERE {_FENCE} RETURNING *"
)
_RETRY_LATER = text(
    "UPDATE s1_processing_runs SET status = 'queued', error_code = :error_code, worker_id = NULL, "
    "lease_expires_at = NULL, run_after = now() + make_interval(secs => :delay_seconds), updated_at = now() "
    f"WHERE {_FENCE} RETURNING *"
)
_RELEASE = text(
    "UPDATE s1_processing_runs SET status = 'queued', attempts = greatest(attempts - 1, 0), worker_id = NULL, "
    f"lease_expires_at = NULL, run_after = now(), updated_at = now() WHERE {_FENCE} RETURNING *"
)
_CLAIM = text("SELECT * FROM claim_s1_processing_run(:worker_id, :lease_seconds)")
_REQUEUE_EXPIRED = text("SELECT * FROM requeue_expired_s1_processing_runs()")


class ProcessingRunRepository:
    """``s1_processing_runs`` in Postgres. Every call is one short transaction."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def _db(self) -> Engine:
        return self._engine or get_sync_engine()

    def _bound(self) -> AbstractContextManager[Connection]:
        return tenant_transaction(current_scope(), self._db())

    def _of(self, run: ProcessingRun) -> AbstractContextManager[Connection]:
        return tenant_transaction(S1Scope.tenant(run.org_id), self._db())

    def _one(self, run: ProcessingRun, statement: Any, **params: Any) -> ProcessingRun | None:
        with self._of(run) as connection:
            row = connection.execute(statement, {"run_id": run.run_id, **params}).first()
        return _run(row) if row is not None else None

    def enqueue(
        self,
        *,
        org_id: str,
        engagement_id: str,
        document_id: str,
        evidence_id: str | None,
        params: dict[str, Any],
        requested_by: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        run_id: str | None = None,
    ) -> tuple[ProcessingRun, bool]:
        """A new queued run for the document, or the active run it already has.

        Returns ``(run, created)``. An in_progress run whose lease has run out (its reader
        stopped) no longer counts as active: it is failed as timed out and a new run is made.
        """

        values = {
            "run_id": run_id or new_run_id(),
            "org_id": str(org_id),
            "engagement_id": engagement_id,
            "document_id": document_id,
            "evidence_id": evidence_id,
            "params": json.dumps(params),
            "requested_by": requested_by,
            "max_attempts": max_attempts,
        }
        with self._bound() as connection:
            connection.execute(_EXPIRE_STALE, {**values, "code": TIMED_OUT, "message": TIMED_OUT_MESSAGE})
            # The active run can finish between the refused insert and the read: try again.
            for _ in range(3):
                created = connection.execute(_INSERT, values).first()
                if created is not None:
                    return _run(created), True
                active = connection.execute(_ACTIVE_RUN, values).first()
                if active is not None:
                    return _run(active), False
        raise RuntimeError(f"Could not enqueue a processing run for document {document_id}.")

    def get(self, run_id: str) -> ProcessingRun | None:
        with self._bound() as connection:
            row = connection.execute(_GET, {"run_id": run_id}).first()
        return _run(row) if row is not None else None

    def latest_per_document(self, engagement_id: str) -> list[ProcessingRun]:
        """Each document's most recent run in the engagement, oldest request first."""

        with self._bound() as connection:
            rows = connection.execute(_LATEST_PER_DOCUMENT, {"engagement_id": engagement_id}).all()
        return [_run(row) for row in rows]

    def claim(self, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        """The oldest queued run that is due, from any organization, now leased to ``worker_id``."""

        with self._db().begin() as connection:
            row = connection.execute(_CLAIM, {"worker_id": worker_id, "lease_seconds": lease_seconds}).first()
        return _run(row) if row is not None else None

    def start(self, run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        """Claim this run (still queued) for ``worker_id``: reading it in the request (inline)."""

        return self._one(run, _START, worker_id=worker_id, lease_seconds=lease_seconds)

    def heartbeat(self, run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        return self._one(run, _HEARTBEAT, worker_id=worker_id, lease_seconds=lease_seconds)

    def finalize_completed(self, run: ProcessingRun, worker_id: str, pipeline_run_id: str) -> ProcessingRun | None:
        return self._one(run, _COMPLETED, worker_id=worker_id, pipeline_run_id=pipeline_run_id)

    def finalize_failed(
        self, run: ProcessingRun, worker_id: str, error_code: str, error: str, pipeline_run_id: str | None = None
    ) -> ProcessingRun | None:
        """Failed, with the message for the user (and the pipeline run, when one recorded the failure)."""

        return self._one(run, _FAILED, worker_id=worker_id, error_code=error_code, error=error,
                         pipeline_run_id=pipeline_run_id)

    def retry_later(
        self, run: ProcessingRun, worker_id: str, delay_seconds: float, error_code: str | None = None
    ) -> ProcessingRun | None:
        """Back to queued, due again after ``delay_seconds``; the attempt still counts."""

        return self._one(run, _RETRY_LATER, worker_id=worker_id, delay_seconds=delay_seconds, error_code=error_code)

    def release(self, run: ProcessingRun, worker_id: str) -> ProcessingRun | None:
        """Back to queued and due now, without counting the attempt (the reader is stopping)."""

        return self._one(run, _RELEASE, worker_id=worker_id)

    def requeue_expired(self) -> list[ExpiredRun]:
        with self._db().begin() as connection:
            rows = connection.execute(_REQUEUE_EXPIRED).all()
        return [ExpiredRun(row.run_id, str(row.org_id), row.document_id, row.status) for row in rows]


# --- in memory ------------------------------------------------------------------------------

@dataclass
class _Stored:
    run: ProcessingRun
    seq: int = field(default=0)


class InMemoryProcessingRunRepository:
    """The same rules in memory. ``clock`` stands in for the database's now()."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._runs: dict[str, _Stored] = {}
        self._seq = 0
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        return self._clock()

    def _ordered(self) -> Iterator[ProcessingRun]:
        for stored in sorted(self._runs.values(), key=lambda s: s.seq):
            yield stored.run

    def _save(self, run: ProcessingRun) -> ProcessingRun:
        stored = self._runs.get(run.run_id)
        if stored is None:
            self._seq += 1
            self._runs[run.run_id] = _Stored(run, self._seq)
        else:
            stored.run = run
        return run

    def _update(self, run: ProcessingRun, holder: str, **changes: Any) -> ProcessingRun | None:
        """Change the run only while ``holder`` is reading it (the Postgres fence)."""

        with self._lock:
            current = self._runs.get(run.run_id)
            if current is None or current.run.worker_id != holder or current.run.status != "in_progress":
                return None
            return self._save(replace(current.run, updated_at=self._now(), **changes))

    def enqueue(
        self,
        *,
        org_id: str,
        engagement_id: str,
        document_id: str,
        evidence_id: str | None,
        params: dict[str, Any],
        requested_by: str,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        run_id: str | None = None,
    ) -> tuple[ProcessingRun, bool]:
        with self._lock:
            now = self._now()
            for run in list(self._ordered()):
                if run.org_id != str(org_id) or run.document_id != document_id or not run.active:
                    continue
                if run.status == "in_progress" and run.lease_expires_at is not None and run.lease_expires_at < now:
                    self._save(replace(run, status="failed", error_code=TIMED_OUT, error=TIMED_OUT_MESSAGE,
                                       worker_id=None, lease_expires_at=None, completed_at=now, updated_at=now))
                    continue
                return run, False
            created = ProcessingRun(
                run_id=run_id or new_run_id(), org_id=str(org_id), engagement_id=engagement_id,
                document_id=document_id, evidence_id=evidence_id, params=json.loads(json.dumps(params)),
                status="queued", attempts=0, max_attempts=max_attempts, requested_by=requested_by,
                run_after=now, created_at=now, updated_at=now,
            )
            return self._save(created), True

    def get(self, run_id: str) -> ProcessingRun | None:
        with self._lock:
            stored = self._runs.get(run_id)
            return stored.run if stored else None

    def latest_per_document(self, engagement_id: str) -> list[ProcessingRun]:
        with self._lock:
            latest: dict[str, tuple[datetime, int, ProcessingRun]] = {}
            for stored in self._runs.values():
                run = stored.run
                if run.engagement_id != engagement_id:
                    continue
                key = (run.created_at, stored.seq, run)
                if run.document_id not in latest or key[:2] > latest[run.document_id][:2]:
                    latest[run.document_id] = key
            return [entry[2] for entry in sorted(latest.values(), key=lambda entry: entry[:2])]

    def claim(self, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        with self._lock:
            now = self._now()
            due = [s for s in self._runs.values() if s.run.status == "queued" and s.run.run_after <= now]
            if not due:
                return None
            oldest = min(due, key=lambda s: (s.run.run_after, s.run.created_at, s.seq)).run
            return self._start(oldest, worker_id, lease_seconds, now)

    def _start(self, run: ProcessingRun, worker_id: str, lease_seconds: int, now: datetime) -> ProcessingRun:
        return self._save(replace(
            run, status="in_progress", attempts=run.attempts + 1, worker_id=worker_id,
            started_at=run.started_at or now, lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now,
        ))

    def start(self, run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        with self._lock:
            current = self._runs.get(run.run_id)
            if current is None or current.run.status != "queued":
                return None
            return self._start(current.run, worker_id, lease_seconds, self._now())

    def heartbeat(self, run: ProcessingRun, worker_id: str, lease_seconds: int) -> ProcessingRun | None:
        return self._update(run, worker_id, lease_expires_at=self._now() + timedelta(seconds=lease_seconds))

    def finalize_completed(self, run: ProcessingRun, worker_id: str, pipeline_run_id: str) -> ProcessingRun | None:
        return self._update(run, worker_id, status="completed", pipeline_run_id=pipeline_run_id, error_code=None,
                            error=None, lease_expires_at=None, completed_at=self._now())

    def finalize_failed(
        self, run: ProcessingRun, worker_id: str, error_code: str, error: str, pipeline_run_id: str | None = None
    ) -> ProcessingRun | None:
        with self._lock:
            current = self._runs.get(run.run_id)
            recorded = pipeline_run_id or (current.run.pipeline_run_id if current else None)
            return self._update(run, worker_id, status="failed", error_code=error_code, error=error,
                                pipeline_run_id=recorded, lease_expires_at=None, completed_at=self._now())

    def retry_later(
        self, run: ProcessingRun, worker_id: str, delay_seconds: float, error_code: str | None = None
    ) -> ProcessingRun | None:
        return self._update(run, worker_id, status="queued", error_code=error_code, worker_id=None,
                            lease_expires_at=None, run_after=self._now() + timedelta(seconds=delay_seconds))

    def release(self, run: ProcessingRun, worker_id: str) -> ProcessingRun | None:
        with self._lock:
            current = self._runs.get(run.run_id)
            attempts = max((current.run.attempts if current else run.attempts) - 1, 0)
            return self._update(run, worker_id, status="queued", attempts=attempts, worker_id=None,
                                lease_expires_at=None, run_after=self._now())

    def requeue_expired(self) -> list[ExpiredRun]:
        with self._lock:
            now = self._now()
            changed: list[ExpiredRun] = []
            for run in list(self._ordered()):
                if run.status != "in_progress" or run.lease_expires_at is None or run.lease_expires_at >= now:
                    continue
                if run.attempts < run.max_attempts:
                    updated = replace(run, status="queued", run_after=now, worker_id=None, lease_expires_at=None,
                                      updated_at=now)
                else:
                    message = TIMED_OUT_MESSAGE if run.attempts <= 1 else (
                        f"Reading stopped {run.attempts} times before it finished. "
                        "Try again later, or upload a smaller file.")
                    updated = replace(run, status="failed", worker_id=None, lease_expires_at=None,
                                      error_code=TIMED_OUT, error=message, completed_at=now, updated_at=now)
                self._save(updated)
                changed.append(ExpiredRun(run.run_id, run.org_id, run.document_id, updated.status))
            return changed
