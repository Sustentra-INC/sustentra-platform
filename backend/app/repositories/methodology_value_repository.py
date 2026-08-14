"""Methodology value persistence for Subsystem 2 PR5."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.app.domain.methodology_value import MethodologyValue

DEFAULT_JSONL_PATH = "local-data/methodology-values/methodology_values.jsonl"


def _to_dict(record: MethodologyValue | dict) -> dict[str, Any]:
    if isinstance(record, MethodologyValue):
        return record.model_dump()
    if isinstance(record, dict):
        return copy.deepcopy(record)
    raise TypeError("record must be a MethodologyValue or dict.")


class _BaseMethodologyValueRepository:
    """Shared query behavior expressed in terms of ``_records()``."""

    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, record: MethodologyValue | dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def save_many(self, records: list[MethodologyValue | dict]) -> list[dict]:
        return [self.save(record) for record in records]

    def list_all(self) -> list[dict]:
        return list(self._records())

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("engagement_id") == engagement_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def list_by_approved_evidence(self, approved_evidence_id: str) -> list[dict]:
        return [
            r
            for r in self._records()
            if r.get("approved_evidence_id") == approved_evidence_id
        ]

    def list_by_methodology_field(self, field_id: str) -> list[dict]:
        return [
            r for r in self._records() if r.get("methodology_field_id") == field_id
        ]

    def get_by_id(self, methodology_value_id: str) -> dict | None:
        for record in reversed(self._records()):
            if record.get("methodology_value_id") == methodology_value_id:
                return record
        return None


class InMemoryMethodologyValueRepository(_BaseMethodologyValueRepository):
    """Non-persistent repository, primarily for tests and transient use."""

    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, record: MethodologyValue | dict) -> dict:
        item = _to_dict(record)
        self._store.append(copy.deepcopy(item))
        return item

    def replace_for_approved_evidence(
        self,
        approved_evidence_id: str,
        records: list[MethodologyValue | dict],
    ) -> list[dict]:
        self._store = [
            record
            for record in self._store
            if record.get("approved_evidence_id") != approved_evidence_id
        ]
        return self.save_many(records)


class JsonlMethodologyValueRepository(_BaseMethodologyValueRepository):
    """File-backed repository writing one methodology value JSON per line."""

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

    def save(self, record: MethodologyValue | dict) -> dict:
        item = _to_dict(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def replace_for_approved_evidence(
        self,
        approved_evidence_id: str,
        records: list[MethodologyValue | dict],
    ) -> list[dict]:
        remaining = [
            record
            for record in self._records()
            if record.get("approved_evidence_id") != approved_evidence_id
        ]
        new_records = [_to_dict(record) for record in records]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            for record in [*remaining, *new_records]:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return [copy.deepcopy(record) for record in new_records]
