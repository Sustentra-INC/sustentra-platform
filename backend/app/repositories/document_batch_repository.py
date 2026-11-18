"""S1 document batches (migration 0019): files uploaded together share a batch.

Two implementations with the same interface:

* ``DocumentBatchRepository``: Postgres (``s1_document_batches``) on the sync engine, in the
  bound S1 scope, so RLS keeps every call to the signed-in organization. It lives in Postgres
  whatever S1_STORE is, like the processing-run queue.
* ``InMemoryDocumentBatchRepository``: the same interface in memory, for tests.

``get`` answers ``None`` for a batch of another organization (RLS hides it); provider scope
sees every organization's, and the API's ``can_see`` check applies as for every S1 record.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import current_scope


@dataclass(frozen=True)
class DocumentBatch:
    id: str
    org_id: str
    engagement_id: str
    created_by: str
    created_at: datetime
    label: str | None = None


def new_batch_id() -> str:
    return uuid.uuid4().hex


_INSERT = text(
    "INSERT INTO s1_document_batches (id, org_id, engagement_id, created_by, label) "
    "VALUES (:id, :org_id, :engagement_id, :created_by, :label) RETURNING *"
)
_GET = text("SELECT * FROM s1_document_batches WHERE id = :id")


def _batch(row: Any) -> DocumentBatch:
    values = row._mapping
    return DocumentBatch(
        id=values["id"],
        org_id=str(values["org_id"]),
        engagement_id=values["engagement_id"],
        created_by=values["created_by"],
        created_at=values["created_at"],
        label=values["label"],
    )


class DocumentBatchRepository:
    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    def _bound(self):  # noqa: ANN202 - a context manager yielding a Connection
        return tenant_transaction(current_scope(), self._engine or get_sync_engine())

    def create(self, *, org_id: str, engagement_id: str, created_by: str, label: str | None = None) -> DocumentBatch:
        with self._bound() as connection:
            row = connection.execute(_INSERT, {
                "id": new_batch_id(), "org_id": org_id, "engagement_id": engagement_id,
                "created_by": created_by, "label": label}).one()
        return _batch(row)

    def get(self, batch_id: str) -> DocumentBatch | None:
        with self._bound() as connection:
            row = connection.execute(_GET, {"id": batch_id}).first()
        return _batch(row) if row is not None else None


class InMemoryDocumentBatchRepository:
    def __init__(self) -> None:
        self._batches: dict[str, DocumentBatch] = {}

    def create(self, *, org_id: str, engagement_id: str, created_by: str, label: str | None = None) -> DocumentBatch:
        batch = DocumentBatch(new_batch_id(), org_id, engagement_id, created_by, datetime.now(UTC), label)
        self._batches[batch.id] = batch
        return batch

    def get(self, batch_id: str) -> DocumentBatch | None:
        return self._batches.get(batch_id)
