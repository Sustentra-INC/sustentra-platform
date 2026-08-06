from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_JSONL_PATH = "local-data/engagements/engagements.jsonl"


class _BaseEngagementRepository:
    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, engagement: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict]:
        return list(self._records())

    def get_by_id(self, engagement_id: str) -> dict | None:
        for record in reversed(self._records()):
            if record.get("engagement_id") == engagement_id:
                return record
        return None


class InMemoryEngagementRepository(_BaseEngagementRepository):
    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, engagement: dict) -> dict:
        record = copy.deepcopy(engagement)
        self._store.append(copy.deepcopy(record))
        return record


class JsonlEngagementRepository(_BaseEngagementRepository):
    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)

    def _records(self) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records

    def save(self, engagement: dict) -> dict:
        record = copy.deepcopy(engagement)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
