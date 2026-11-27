"""The S1 document stores in Postgres (migration 0013), behind the same repository interface
as the JSONL files.

Each row keeps the exact record the repository returns (``record``) plus the columns queries
filter on, copied from the record; the table's CHECK constraints refuse a row where they
differ. ``seq`` is the file order of the JSONL stores: lists come back oldest first and
"latest" is the highest seq.

Every call is one short transaction in the scope bound for the request
(``core.s1_scope.current_scope``), so RLS limits it to the signed-in organization (or provider
scope). With no scope bound the call raises instead of reading every organization.

A record with an evidence id claims that id in ``s1_evidence_owners`` (migration 0014) in the
same transaction: the first organization to save it owns it, and a save by any other is
refused, even though RLS hides the owner's records from it.
"""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope, current_scope

# table -> the columns filled from the record (besides org_id); must match migration 0013.
COLUMNS: dict[str, tuple[str, ...]] = {
    "s1_documents": ("document_id", "engagement_id", "evidence_id", "processing_status", "batch_id"),
    "s1_pipeline_runs": ("pipeline_run_id", "engagement_id", "evidence_id", "document_id"),
    "s1_extraction_results": ("pipeline_run_id", "document_id", "evidence_id"),
    "s1_review_decisions": ("review_decision_id", "candidate_id", "evidence_id", "document_id", "field_name"),
    "s1_approved_evidence": ("approved_evidence_id", "engagement_id", "evidence_id", "document_id"),
}


def _column_value(value: Any) -> str | None:
    """What ``record->>'name'`` gives for the value, so the CHECK constraints hold."""

    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def _org_id(record: dict[str, Any]) -> str | None:
    owner = record.get("org_id")
    return None if owner in (None, "") else str(owner)


def _same_org(a: Any, b: Any) -> bool:
    if a in (None, "") or b in (None, ""):
        return a in (None, "") and b in (None, "")
    return uuid.UUID(str(a)) == uuid.UUID(str(b))


class EvidenceOwnedElsewhere(PermissionError):
    """The evidence id is already owned by another organization (or is unowned legacy evidence)."""


_CLAIM = text(
    "INSERT INTO s1_evidence_owners (evidence_id, org_id) VALUES (:evidence_id, :org_id) "
    "ON CONFLICT (evidence_id) DO NOTHING RETURNING evidence_id"
)
_OWNER = text("SELECT org_id FROM s1_evidence_owners WHERE evidence_id = :evidence_id")


def _claim_evidence(connection: Any, evidence_id: str, org_id: str | None) -> None:
    connection.execute(_CLAIM, {"evidence_id": evidence_id, "org_id": org_id})
    owner = connection.execute(_OWNER, {"evidence_id": evidence_id}).first()
    if owner is None or not _same_org(owner.org_id, org_id):
        raise EvidenceOwnedElsewhere(f"Evidence {evidence_id} belongs to another organization.")


def evidence_owner_status(evidence_id: str, engine: Engine | None = None) -> Literal["free", "own", "taken"]:
    """Whether the bound organization may use an evidence id: nobody has it ("free"), it does
    ("own"), or another organization (or unowned legacy evidence) does ("taken"). Provider
    scope owns nothing, so it only ever sees "free" or "taken"."""

    scope: S1Scope = current_scope()
    with tenant_transaction(scope, engine or get_sync_engine()) as connection:
        owner = connection.execute(_OWNER, {"evidence_id": evidence_id}).first()
        if owner is not None:
            return "own" if not scope.provider and _same_org(owner.org_id, scope.org_id) else "taken"
        if scope.provider:
            return "free"
        # RLS hides another organization's claim: a claim attempt, undone at once, tells.
        probe = connection.begin_nested()
        claimed = connection.execute(_CLAIM, {"evidence_id": evidence_id, "org_id": str(scope.org_id)}).first()
        probe.rollback()
        return "free" if claimed is not None else "taken"


_UPLOAD_LOCK_HOLDERS = threading.BoundedSemaphore(4)  # of a pool of 5 + 5 connections


def upload_lock(key: str, engine: Engine | None = None):  # noqa: ANN201 - a context manager
    """Holds a Postgres advisory lock for ``key`` until the block ends, in its own short-lived
    connection. Two requests with the same key (a retried upload arriving while the first attempt
    is still being stored) run one after the other, across every server process. The lock is
    transaction-level, so it is released even if the process dies."""

    @contextmanager
    def held():  # noqa: ANN202
        # A holder keeps one pooled connection for the whole upload while the store uses others, so at
        # most a few may hold at once: waiting here costs no connection, and the store can never be
        # starved of the connection it needs to finish (which would hold the lock until timeout).
        with _UPLOAD_LOCK_HOLDERS:
            with tenant_transaction(current_scope(), engine or get_sync_engine()) as connection:
                # never wait for ever on another server process: past this the request fails and is retried by hand
                connection.execute(text("SELECT set_config('lock_timeout', '20s', true)"))
                connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
                yield

    return held()


class S1Table:
    """One S1 store table. ``unique`` names the column whose row a save replaces (documents
    keep one row per document); without it every save adds a row."""

    def __init__(self, name: str, *, unique: str | None = None, engine: Engine | None = None) -> None:
        if name not in COLUMNS:
            raise ValueError(f"not an S1 store table: {name}")
        self._name = name
        self._columns = COLUMNS[name]
        self._unique = unique
        self._engine = engine

    @property
    def name(self) -> str:
        return self._name

    @property
    def engine(self) -> Engine | None:
        return self._engine

    def _transaction(self):  # noqa: ANN202 - a context manager yielding a Connection
        return tenant_transaction(current_scope(), self._engine or get_sync_engine())

    def insert(self, record: dict[str, Any], *, also: Callable[[Any], None] | None = None) -> None:
        """Add the record. ``also`` runs on the same connection, in the same transaction, after the
        insert: if it raises, the record is not saved either."""

        names = ("org_id", *self._columns, "record")
        params: dict[str, Any] = {name: _column_value(record.get(name)) for name in self._columns}
        params["org_id"] = _org_id(record)
        params["record"] = json.dumps(record, ensure_ascii=False)
        values = ", ".join("CAST(:record AS jsonb)" if n == "record" else f":{n}" for n in names)
        statement = f"INSERT INTO {self._name} ({', '.join(names)}) VALUES ({values})"
        if self._unique:
            updates = ", ".join(f"{n} = EXCLUDED.{n}" for n in names if n != self._unique)
            statement += f" ON CONFLICT ({self._unique}) DO UPDATE SET {updates}, updated_at = now()"
        evidence_id = record.get("evidence_id") if "evidence_id" in self._columns else None
        with self._transaction() as connection:
            if evidence_id not in (None, ""):
                _claim_evidence(connection, str(evidence_id), params["org_id"])
            connection.execute(text(statement), params)
            if also is not None:
                also(connection)

    def select(self, **where: Any) -> list[dict[str, Any]]:
        """Records matching every ``column=value``, oldest first."""

        return self._query(where, "ORDER BY seq")

    def select_in(self, column: str, values: list[str]) -> list[dict[str, Any]]:
        """Records whose ``column`` is any of ``values`` (one query, however many), oldest first."""

        if column not in self._columns:
            raise ValueError(f"{self._name} has no filter column {column!r}")
        if not values:
            return []
        statement = text(
            f"SELECT record FROM {self._name} WHERE {column} = ANY(:values) ORDER BY seq"
        ).bindparams(bindparam("values", type_=ARRAY(Text())))
        with self._transaction() as connection:
            return [row.record for row in connection.execute(statement, {"values": list(values)})]

    def select_grouped(self, column: str, values: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Records whose ``column`` is any of ``values``, oldest first, grouped by that column (one query).

        The rows come back as JSON text, one text per group, and are parsed here: this is several times cheaper
        than having the driver turn every jsonb value into Python one row at a time (50,000 decisions: about
        0.5 s against 0.8 s), and the objects are the same."""

        if column not in self._columns:
            raise ValueError(f"{self._name} has no filter column {column!r}")
        grouped: dict[str, list[dict[str, Any]]] = {value: [] for value in values}
        if not values:
            return grouped
        statement = text(
            f"SELECT {column} AS key, '[' || string_agg(record::text, ',' ORDER BY seq) || ']' AS records "
            f"FROM {self._name} WHERE {column} = ANY(:values) GROUP BY {column}"
        ).bindparams(bindparam("values", type_=ARRAY(Text())))
        with self._transaction() as connection:
            rows = connection.execute(statement, {"values": list(values)}).fetchall()
        for row in rows:
            grouped[row.key] = json.loads(row.records)
        return grouped

    def engagement_stamp(self, engagement_id: str) -> str:
        """A short text that changes whenever a row of this engagement's documents is added or replaced
        (for the document-keyed tables: whenever a row of those documents is added; they are append-only).
        One cheap aggregate query: the evidence cache compares it instead of reading the rows."""

        if self._name == "s1_documents":
            statement = (
                "SELECT count(*) AS n, coalesce(max(seq), 0) || '.' || coalesce(max(updated_at)::text, '') AS top, "
                "md5(coalesce(string_agg(document_id || ':' || md5(record::text), '|' ORDER BY document_id), '')) "
                "AS digest FROM s1_documents WHERE engagement_id = :engagement_id"
            )
        elif self._name in ("s1_extraction_results", "s1_review_decisions"):
            # append-only: a new row always raises the count (even when it commits out of seq order)
            statement = (
                f"SELECT count(*) AS n, coalesce(max(seq), 0) AS top, '' AS digest FROM {self._name} "
                "WHERE document_id IN (SELECT document_id FROM s1_documents WHERE engagement_id = :engagement_id)"
            )
        else:
            raise ValueError(f"{self._name} has no engagement stamp")
        with self._transaction() as connection:
            row = connection.execute(text(statement), {"engagement_id": engagement_id}).one()
        return f"{row.n}.{row.top}.{row.digest}"

    def latest(self, **where: Any) -> dict[str, Any] | None:
        rows = self._query(where, "ORDER BY seq DESC LIMIT 1")
        return rows[0] if rows else None

    def find_in_record(self, key: str, value: str, **where: Any) -> dict[str, Any] | None:
        """The newest row whose record has ``record->>key = value`` and the given column values
        (``org_id`` too: RLS already limits the call to the bound organization, this keeps the
        match exact for provider scope)."""

        unknown = set(where) - set(self._columns) - {"org_id"}
        if unknown or not key.isidentifier():
            raise ValueError(f"{self._name} cannot be searched by {sorted(unknown) or key}")
        params: dict[str, Any] = {"value": value}
        clauses = ["record->>CAST(:key AS text) = :value"]
        params["key"] = key
        for column, wanted in where.items():
            if wanted is None:
                clauses.append(f"{column} IS NULL")
            else:
                params[column] = _column_value(wanted)
                clauses.append(f"{column}::text = lower(:{column})" if column == "org_id" else f"{column} = :{column}")
        statement = f"SELECT record FROM {self._name} WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT 1"
        with self._transaction() as connection:
            row = connection.execute(text(statement), params).first()
        return row.record if row is not None else None

    def _query(self, where: dict[str, Any], tail: str) -> list[dict[str, Any]]:
        unknown = set(where) - set(self._columns)
        if unknown:
            raise ValueError(f"{self._name} has no filter column {sorted(unknown)}")
        params = {column: _column_value(value) for column, value in where.items()}
        clause = " AND ".join(
            f"{column} IS NULL" if value is None else f"{column} = :{column}" for column, value in params.items()
        )
        statement = f"SELECT record FROM {self._name}{' WHERE ' + clause if clause else ''} {tail}"
        with self._transaction() as connection:
            return [row.record for row in connection.execute(text(statement), params)]
