"""Approved evidence persistence (PR8)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from backend.app.domain.evidence import ApprovedEvidence
from backend.app.repositories.s1_postgres import S1Table

DEFAULT_JSONL_PATH = "local-data/approved-evidence/approved_evidence.jsonl"


def _to_dict(record: ApprovedEvidence | dict) -> dict[str, Any]:
    if isinstance(record, ApprovedEvidence):
        return record.model_dump()
    if isinstance(record, dict):
        return copy.deepcopy(record)
    raise TypeError("record must be an ApprovedEvidence or dict.")


class _BaseApprovedEvidenceRepository:
    """Shared query behavior expressed in terms of ``_records()``."""

    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, record: ApprovedEvidence | dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict]:
        return list(self._records())

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("engagement_id") == engagement_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def list_by_document(self, document_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("document_id") == document_id]

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None

    def get_by_id(self, approved_evidence_id: str) -> dict | None:
        for record in reversed(self._records()):
            if record.get("approved_evidence_id") == approved_evidence_id:
                return record
        return None


class InMemoryApprovedEvidenceRepository(_BaseApprovedEvidenceRepository):
    """Non-persistent repository, primarily for tests and transient use."""

    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, record: ApprovedEvidence | dict) -> dict:
        item = _to_dict(record)
        self._store.append(copy.deepcopy(item))
        return item


class JsonlApprovedEvidenceRepository(_BaseApprovedEvidenceRepository):
    """File-backed repository writing one approved evidence JSON per line."""

    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _records(self) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records

    def save(self, record: ApprovedEvidence | dict) -> dict:
        item = _to_dict(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item


class PostgresApprovedEvidenceRepository(_BaseApprovedEvidenceRepository):
    def __init__(self, engine: Engine | None = None) -> None:
        self._table = S1Table("s1_approved_evidence", engine=engine)

    def _records(self) -> list[dict]:
        return self._table.select()

    def save(self, record: ApprovedEvidence | dict) -> dict:
        item = _to_dict(record)
        self._table.insert(item)
        return item

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return self._table.select(engagement_id=engagement_id)

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return self._table.select(evidence_id=evidence_id)

    def list_by_document(self, document_id: str) -> list[dict]:
        return self._table.select(document_id=document_id)

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        return self._table.latest(evidence_id=evidence_id)

    def get_by_id(self, approved_evidence_id: str) -> dict | None:
        return self._table.latest(approved_evidence_id=approved_evidence_id)
