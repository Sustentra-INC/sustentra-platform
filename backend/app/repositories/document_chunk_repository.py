"""S1 document chunks (migration 0017): the page chunks of a large PDF, read as jobs on the queue.

A processing run for a PDF over the chunk threshold is split into chunks (``plan``): the run
is parked in ``waiting_on_chunks`` and one row per block of pages is queued. Readers claim
chunks before runs. A chunk that ends (``finalize_completed``, or ``finalize_failed`` after its
last attempt) wakes the parked run when it was the last unfinished one, exactly once.

Two implementations with the same interface, as ``processing_run_repository``:

* ``DocumentChunkRepository``: Postgres (``s1_document_chunks``) on the sync engine.
* ``InMemoryDocumentChunkRepository``: the same rules in memory, for tests. It parks and wakes
  runs in an ``InMemoryProcessingRunRepository``.

Which organization a call works in is as for runs: ``plan`` and the reads of one run's chunks
use the bound S1 scope; the updates of one chunk (``heartbeat``, ``finalize_*``, ``retry_later``,
``release``) run in the chunk's own organization and are fenced on (``worker_id``,
``in_progress``), returning ``None`` once the chunk is no longer the caller's; ``claim`` and
``requeue_expired`` serve every organization through the SECURITY DEFINER functions of 0017.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import Connection, text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope, current_scope
from backend.app.repositories.processing_run_repository import ProcessingRun

UNFINISHED = ("queued", "in_progress")
# A chunk kept on its last attempt although Textract failed on some of its pages: it is completed
# (with the pages that did read), carries this error_code, and its failed pages count as unread.
OCR_PAGE_FAILED = "ocr_page_failed"
_OCR_PAGE = re.compile(r"^Page (\d+) has no text layer")


def ocr_failed_pages(messages: list[str]) -> list[int]:
    """Page numbers named by the parser's ``ocr_page_failed`` warning messages."""

    return [int(m.group(1)) for text in messages if (m := _OCR_PAGE.match(text))]
DEFAULT_CHUNK_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    org_id: str
    run_id: str
    document_id: str
    chunk_index: int
    page_from: int  # 1-based, inclusive
    page_to: int
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    worker_id: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    parser_output: dict[str, Any] | None = None


class ExpiredChunk(NamedTuple):
    """A chunk ``requeue_expired`` changed: back to ``queued``, or ``failed`` after its last attempt."""

    id: str
    run_id: str
    org_id: str
    document_id: str
    status: str


class ChunkSummary(NamedTuple):
    total: int
    completed: int
    failed: int
    failed_pages: list[list[int]]  # [[from, to], ...] in page order


def new_chunk_id() -> str:
    return uuid.uuid4().hex


_FIELDS = tuple(name for name in DocumentChunk.__dataclass_fields__)


def _chunk(row: Any) -> DocumentChunk:
    values = dict(row._mapping)
    values["org_id"] = str(values["org_id"])
    output = values.get("parser_output")
    values["parser_output"] = json.loads(output) if isinstance(output, str) else output
    values.setdefault("parser_output", None)  # not selected by the update that finishes a chunk
    return DocumentChunk(**{name: values[name] for name in _FIELDS})


def _summary(rows: list[tuple[int, int, int, str, list[int]]]) -> ChunkSummary:
    """``rows``: (chunk_index, page_from, page_to, status, pages Textract failed on).
    ``failed`` counts failed chunks; ``failed_pages`` also lists single pages that failed OCR."""

    ordered = sorted(rows)
    failed = [[a, b] for _, a, b, status, _ in ordered if status == "failed"]
    ocr = [[n, n] for _, _, _, status, pages in ordered if status == "completed" for n in sorted(pages)]
    return ChunkSummary(len(ordered), sum(1 for row in ordered if row[3] == "completed"), len(failed),
                        sorted(failed + ocr))


# --- Postgres -------------------------------------------------------------------------------

_LEASE = "now() + make_interval(secs => :lease_seconds)"
_FENCE = "id = :id AND worker_id = :worker_id AND status = 'in_progress'"
_COLUMNS = ("id, org_id, run_id, document_id, chunk_index, page_from, page_to, status, attempts, max_attempts, "
            "available_at, created_at, updated_at, worker_id, lease_expires_at, error_code, parser_output")

_PARK = text(
    "UPDATE s1_processing_runs SET status = 'waiting_on_chunks', attempts = greatest(attempts - 1, 0), "
    "worker_id = NULL, lease_expires_at = NULL, updated_at = now() "
    "WHERE run_id = :run_id AND worker_id = :worker_id AND status = 'in_progress' RETURNING run_id"
)
_INSERT = text(
    "INSERT INTO s1_document_chunks (id, org_id, run_id, document_id, chunk_index, page_from, page_to, max_attempts) "
    "VALUES (:id, :org_id, :run_id, :document_id, :chunk_index, :page_from, :page_to, :max_attempts) "
    "ON CONFLICT (run_id, chunk_index) DO NOTHING"
)
_FOR_RUN = text(f"SELECT {_COLUMNS} FROM s1_document_chunks WHERE run_id = :run_id ORDER BY chunk_index")
_NO_OUTPUT = _COLUMNS.replace(", parser_output", "")
_FOR_RUNS = text(
    "SELECT run_id, chunk_index, page_from, page_to, status, "
    "CASE WHEN error_code = 'ocr_page_failed' AND status = 'completed' THEN "
    "(SELECT coalesce(jsonb_agg(w->>'message'), '[]'::jsonb) FROM jsonb_array_elements(parser_output->'warnings') w "
    "WHERE w->>'code' = 'ocr_page_failed') END AS ocr_messages "
    "FROM s1_document_chunks WHERE run_id = ANY(:run_ids)"
)
_CLAIM = text("SELECT * FROM claim_s1_document_chunk(:worker_id, :lease_seconds)")
_REQUEUE_EXPIRED = text("SELECT * FROM requeue_expired_s1_document_chunks()")
_HEARTBEAT = text(
    f"UPDATE s1_document_chunks SET lease_expires_at = {_LEASE}, updated_at = now() WHERE {_FENCE} RETURNING *"
)
_COMPLETED = text(
    "UPDATE s1_document_chunks SET status = 'completed', parser_output = CAST(:output AS jsonb), "
    "error_code = :error_code, worker_id = NULL, lease_expires_at = NULL, updated_at = now() "
    f"WHERE {_FENCE} RETURNING {_NO_OUTPUT}"  # the output is already known to the caller: not sent back
)
_FAILED = text(
    "UPDATE s1_document_chunks SET status = 'failed', error_code = :error_code, worker_id = NULL, "
    f"lease_expires_at = NULL, updated_at = now() WHERE {_FENCE} RETURNING *"
)
_RETRY_LATER = text(
    "UPDATE s1_document_chunks SET status = 'queued', error_code = :error_code, worker_id = NULL, "
    "lease_expires_at = NULL, available_at = now() + make_interval(secs => :delay_seconds), updated_at = now() "
    f"WHERE {_FENCE} RETURNING *"
)
_RELEASE = text(
    "UPDATE s1_document_chunks SET status = 'queued', attempts = greatest(attempts - 1, 0), worker_id = NULL, "
    f"lease_expires_at = NULL, available_at = now(), updated_at = now() WHERE {_FENCE} RETURNING *"
)
_WAKE = text("SELECT s1_wake_parent_run(:run_id)")


class DocumentChunkRepository:
    """``s1_document_chunks`` in Postgres. Every call is one short transaction."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def _db(self) -> Engine:
        return self._engine or get_sync_engine()

    def _bound(self) -> AbstractContextManager[Connection]:
        return tenant_transaction(current_scope(), self._db())

    def _of(self, org_id: str) -> AbstractContextManager[Connection]:
        return tenant_transaction(S1Scope.tenant(org_id), self._db())

    def plan(self, run: ProcessingRun, worker_id: str, ranges: list[tuple[int, int]],
             max_attempts: int = DEFAULT_CHUNK_MAX_ATTEMPTS) -> bool:
        """Queue one chunk per page range and park the run in ``waiting_on_chunks``, in one
        transaction (no chunk can finish before the run is parked). ``False`` when the run is
        no longer this reader's, in which case nothing is created."""

        with self._of(run.org_id) as connection:
            parked = connection.execute(_PARK, {"run_id": run.run_id, "worker_id": worker_id}).first()
            if parked is None:
                return False
            for index, (page_from, page_to) in enumerate(ranges):
                connection.execute(_INSERT, {
                    "id": new_chunk_id(), "org_id": run.org_id, "run_id": run.run_id, "document_id": run.document_id,
                    "chunk_index": index, "page_from": page_from, "page_to": page_to, "max_attempts": max_attempts})
        return True

    def list_for_run(self, run_id: str) -> list[DocumentChunk]:
        """The run's chunks with their parser output, in page order (the bound scope)."""

        with self._bound() as connection:
            rows = connection.execute(_FOR_RUN, {"run_id": run_id}).all()
        return [_chunk(row) for row in rows]

    def summaries(self, run_ids: list[str]) -> dict[str, ChunkSummary]:
        """Per run that has chunks: how many, how many are done or failed and which pages (the bound scope)."""

        if not run_ids:
            return {}
        with self._bound() as connection:
            rows = connection.execute(_FOR_RUNS, {"run_ids": list(run_ids)}).all()
        by_run: dict[str, list[tuple[int, int, int, str, list[int]]]] = {}
        for row in rows:
            messages = row.ocr_messages
            messages = json.loads(messages) if isinstance(messages, str) else (messages or [])
            by_run.setdefault(row.run_id, []).append(
                (row.chunk_index, row.page_from, row.page_to, row.status, ocr_failed_pages(messages)))
        return {run_id: _summary(items) for run_id, items in by_run.items()}

    def claim(self, worker_id: str, lease_seconds: int) -> DocumentChunk | None:
        """The oldest queued chunk that is due, from any organization, now leased to ``worker_id``."""

        with self._db().begin() as connection:
            row = connection.execute(_CLAIM, {"worker_id": worker_id, "lease_seconds": lease_seconds}).first()
        return _chunk(row) if row is not None else None

    def _one(self, chunk: DocumentChunk, statement: Any, wake: bool = False, **params: Any) -> DocumentChunk | None:
        with self._of(chunk.org_id) as connection:
            row = connection.execute(statement, {"id": chunk.id, **params}).first()
            if row is not None and wake:
                # After this chunk's own update: the run's row lock makes whoever takes it last
                # see every other chunk's outcome (see s1_wake_parent_run).
                connection.execute(_WAKE, {"run_id": chunk.run_id})
        return _chunk(row) if row is not None else None

    def heartbeat(self, chunk: DocumentChunk, worker_id: str, lease_seconds: int) -> DocumentChunk | None:
        return self._one(chunk, _HEARTBEAT, worker_id=worker_id, lease_seconds=lease_seconds)

    def finalize_completed(self, chunk: DocumentChunk, worker_id: str, parser_output: dict[str, Any],
                           error_code: str | None = None) -> DocumentChunk | None:
        return self._one(chunk, _COMPLETED, wake=True, worker_id=worker_id, output=json.dumps(parser_output),
                         error_code=error_code)

    def finalize_failed(self, chunk: DocumentChunk, worker_id: str, error_code: str) -> DocumentChunk | None:
        return self._one(chunk, _FAILED, wake=True, worker_id=worker_id, error_code=error_code)

    def retry_later(self, chunk: DocumentChunk, worker_id: str, delay_seconds: float,
                    error_code: str | None = None) -> DocumentChunk | None:
        """Back to queued, due again after ``delay_seconds``; the attempt still counts."""

        return self._one(chunk, _RETRY_LATER, worker_id=worker_id, delay_seconds=delay_seconds,
                         error_code=error_code)

    def release(self, chunk: DocumentChunk, worker_id: str) -> DocumentChunk | None:
        """Back to queued and due now, without counting the attempt (the reader is stopping)."""

        return self._one(chunk, _RELEASE, worker_id=worker_id)

    def requeue_expired(self) -> list[ExpiredChunk]:
        with self._db().begin() as connection:
            rows = connection.execute(_REQUEUE_EXPIRED).all()
        return [ExpiredChunk(row.id, row.run_id, str(row.org_id), row.document_id, row.status) for row in rows]


def _ocr_pages_of(chunk: DocumentChunk) -> list[int]:
    if chunk.status != "completed" or chunk.error_code != OCR_PAGE_FAILED:
        return []
    warnings = (chunk.parser_output or {}).get("warnings") or []
    return ocr_failed_pages([str(w.get("message")) for w in warnings if w.get("code") == OCR_PAGE_FAILED])


# --- in memory ------------------------------------------------------------------------------

class InMemoryDocumentChunkRepository:
    """The same rules in memory. ``runs`` is the in-memory run repository whose runs are parked
    and woken; ``clock`` stands in for the database's now()."""

    def __init__(self, runs: Any, clock: Callable[[], datetime] | None = None) -> None:
        self._runs = runs
        self._clock = clock or (lambda: datetime.now(UTC))
        self._chunks: dict[str, DocumentChunk] = {}
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        return self._clock()

    def _update(self, chunk: DocumentChunk, holder: str, **changes: Any) -> DocumentChunk | None:
        """Change the chunk only while ``holder`` is reading it (the Postgres fence)."""

        current = self._chunks.get(chunk.id)
        if current is None or current.worker_id != holder or current.status != "in_progress":
            return None
        updated = replace(current, updated_at=self._now(), **changes)
        self._chunks[chunk.id] = updated
        return updated

    def _wake(self, run_id: str) -> None:
        if not any(c.run_id == run_id and c.status in UNFINISHED for c in self._chunks.values()):
            self._runs._wake(run_id)

    def plan(self, run: ProcessingRun, worker_id: str, ranges: list[tuple[int, int]],
             max_attempts: int = DEFAULT_CHUNK_MAX_ATTEMPTS) -> bool:
        with self._lock:
            if not self._runs._park(run, worker_id):
                return False
            now = self._now()
            for index, (page_from, page_to) in enumerate(ranges):
                if any(c.run_id == run.run_id and c.chunk_index == index for c in self._chunks.values()):
                    continue
                chunk = DocumentChunk(
                    id=new_chunk_id(), org_id=run.org_id, run_id=run.run_id, document_id=run.document_id,
                    chunk_index=index, page_from=page_from, page_to=page_to, status="queued", attempts=0,
                    max_attempts=max_attempts, available_at=now, created_at=now, updated_at=now)
                self._chunks[chunk.id] = chunk
            return True

    def list_for_run(self, run_id: str) -> list[DocumentChunk]:
        with self._lock:
            return sorted((c for c in self._chunks.values() if c.run_id == run_id), key=lambda c: c.chunk_index)

    def summaries(self, run_ids: list[str]) -> dict[str, ChunkSummary]:
        with self._lock:
            result: dict[str, ChunkSummary] = {}
            for run_id in run_ids:
                rows = [(c.chunk_index, c.page_from, c.page_to, c.status, _ocr_pages_of(c))
                        for c in self._chunks.values() if c.run_id == run_id]
                if rows:
                    result[run_id] = _summary(rows)
            return result

    def claim(self, worker_id: str, lease_seconds: int) -> DocumentChunk | None:
        with self._lock:
            now = self._now()
            due = [c for c in self._chunks.values() if c.status == "queued" and c.available_at <= now]
            if not due:
                return None
            oldest = min(due, key=lambda c: (c.available_at, c.created_at, c.chunk_index))
            claimed = replace(oldest, status="in_progress", attempts=oldest.attempts + 1, worker_id=worker_id,
                              lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
            self._chunks[claimed.id] = claimed
            return claimed

    def heartbeat(self, chunk: DocumentChunk, worker_id: str, lease_seconds: int) -> DocumentChunk | None:
        with self._lock:
            return self._update(chunk, worker_id, lease_expires_at=self._now() + timedelta(seconds=lease_seconds))

    def finalize_completed(self, chunk: DocumentChunk, worker_id: str, parser_output: dict[str, Any],
                           error_code: str | None = None) -> DocumentChunk | None:
        with self._lock:
            done = self._update(chunk, worker_id, status="completed", parser_output=json.loads(json.dumps(parser_output)),
                                error_code=error_code, worker_id=None, lease_expires_at=None)
            if done is not None:
                self._wake(chunk.run_id)
            return done

    def finalize_failed(self, chunk: DocumentChunk, worker_id: str, error_code: str) -> DocumentChunk | None:
        with self._lock:
            failed = self._update(chunk, worker_id, status="failed", error_code=error_code, worker_id=None,
                                  lease_expires_at=None)
            if failed is not None:
                self._wake(chunk.run_id)
            return failed

    def retry_later(self, chunk: DocumentChunk, worker_id: str, delay_seconds: float,
                    error_code: str | None = None) -> DocumentChunk | None:
        with self._lock:
            return self._update(chunk, worker_id, status="queued", error_code=error_code, worker_id=None,
                                lease_expires_at=None, available_at=self._now() + timedelta(seconds=delay_seconds))

    def release(self, chunk: DocumentChunk, worker_id: str) -> DocumentChunk | None:
        with self._lock:
            current = self._chunks.get(chunk.id)
            attempts = max((current.attempts if current else chunk.attempts) - 1, 0)
            return self._update(chunk, worker_id, status="queued", attempts=attempts, worker_id=None,
                                lease_expires_at=None, available_at=self._now())

    def requeue_expired(self) -> list[ExpiredChunk]:
        with self._lock:
            now = self._now()
            changed: list[ExpiredChunk] = []
            for chunk in list(self._chunks.values()):
                if chunk.status != "in_progress" or chunk.lease_expires_at is None or chunk.lease_expires_at >= now:
                    continue
                if chunk.attempts < chunk.max_attempts:
                    updated = replace(chunk, status="queued", available_at=now, worker_id=None,
                                      lease_expires_at=None, updated_at=now)
                else:
                    updated = replace(chunk, status="failed", worker_id=None, lease_expires_at=None,
                                      error_code="timed_out", updated_at=now)
                self._chunks[chunk.id] = updated
                changed.append(ExpiredChunk(chunk.id, chunk.run_id, chunk.org_id, chunk.document_id, updated.status))
            for run_id in {c.run_id for c in changed}:
                self._wake(run_id)
            return changed
