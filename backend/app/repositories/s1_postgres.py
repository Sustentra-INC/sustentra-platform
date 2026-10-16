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
import uuid
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.core.db import get_sync_engine, tenant_transaction
from backend.app.core.s1_scope import S1Scope, current_scope

# table -> the columns filled from the record (besides org_id); must match migration 0013.
COLUMNS: dict[str, tuple[str, ...]] = {
    "s1_documents": ("document_id", "engagement_id", "evidence_id", "processing_status"),
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

    def _transaction(self):  # noqa: ANN202 - a context manager yielding a Connection
        return tenant_transaction(current_scope(), self._engine or get_sync_engine())

    def insert(self, record: dict[str, Any]) -> None:
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

    def select(self, **where: Any) -> list[dict[str, Any]]:
        """Records matching every ``column=value``, oldest first."""

        return self._query(where, "ORDER BY seq")

    def latest(self, **where: Any) -> dict[str, Any] | None:
        rows = self._query(where, "ORDER BY seq DESC LIMIT 1")
        return rows[0] if rows else None

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
