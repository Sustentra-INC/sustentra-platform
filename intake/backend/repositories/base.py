"""Append-only record stores shared by the intake repositories.

Follows the storage approach already used in ``backend/app/repositories/``:
one JSON object per line under the gitignored ``local-data/`` tree, with
in-memory equivalents for tests. No database, ORM or ``.env`` access.

Records are append-only. Updating an entity appends a new record with the same
ID; ``get`` and ``list_latest`` project the latest record per ID. This mirrors
the existing ``get_latest_by_candidate`` pattern and keeps the full history,
which matters for a verification product where edit history is itself evidence.

Concurrency: appends are single-process and unsynchronised, same as the S1
repositories. Multi-writer safety comes with a real database, not this layer.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel


def _to_dict(record: BaseModel | dict) -> dict[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump()
    if isinstance(record, dict):
        return copy.deepcopy(record)
    raise TypeError("record must be a pydantic model or dict.")


class RecordStore:
    """Abstract append-only store."""

    def append(self, record: dict[str, Any]) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def records(self) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError


class InMemoryStore(RecordStore):
    """Non-persistent store, primarily for tests."""

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def append(self, record: dict[str, Any]) -> None:
        self._records.append(copy.deepcopy(record))

    def records(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(record) for record in self._records]


class JsonlStore(RecordStore):
    """File-backed store writing one JSON object per line."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def records(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records


class AppendOnlyRepository:
    """Shared query behaviour over a :class:`RecordStore`.

    Subclasses set ``id_field``. ``save`` appends; ``get`` returns the latest
    record for an ID; ``list_latest`` returns the latest record per ID.
    """

    id_field: ClassVar[str] = "id"

    def __init__(self, store: RecordStore) -> None:
        self._store = store

    @property
    def store(self) -> RecordStore:
        return self._store

    def save(self, record: BaseModel | dict) -> dict[str, Any]:
        payload = _to_dict(record)
        if self.id_field not in payload:
            raise ValueError(f"record is missing {self.id_field!r}")
        self._store.append(payload)
        return payload

    def list_records(self) -> list[dict[str, Any]]:
        """Every record ever written, in write order (the audit trail)."""
        return self._store.records()

    def list_latest(self) -> list[dict[str, Any]]:
        """Latest record per ID, in first-seen order."""
        latest: dict[str, dict[str, Any]] = {}
        for record in self._store.records():
            key = record.get(self.id_field)
            if key is not None:
                latest[key] = record
        return list(latest.values())

    def get(self, record_id: str) -> dict[str, Any] | None:
        match = None
        for record in self._store.records():
            if record.get(self.id_field) == record_id:
                match = record
        return match

    def find_latest(self, **filters: Any) -> dict[str, Any] | None:
        """Latest record matching every supplied field value."""
        matches = [
            record
            for record in self.list_latest()
            if all(record.get(key) == value for key, value in filters.items())
        ]
        return matches[-1] if matches else None

    def filter_latest(self, **filters: Any) -> list[dict[str, Any]]:
        """All latest-per-ID records matching every supplied field value."""
        return [
            record
            for record in self.list_latest()
            if all(record.get(key) == value for key, value in filters.items())
        ]
