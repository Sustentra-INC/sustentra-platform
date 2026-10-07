"""S1-BE-001 - persisted extraction results (the candidates a pipeline run produced).

Append-only like the other S1 stores: one record per persisted pipeline run, so
"latest" for a document is the last record written for it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_JSONL_PATH = "local-data/extraction-results/extraction_results.jsonl"


class _BaseExtractionResultRepository:
    def _records(self) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, record: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._records())

    def list_by_document(self, document_id: str) -> list[dict[str, Any]]:
        return [r for r in self._records() if r.get("document_id") == document_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict[str, Any]]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]


class InMemoryExtractionResultRepository(_BaseExtractionResultRepository):
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    def _records(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self._store.append(copy.deepcopy(record))
        return copy.deepcopy(record)


class JsonlExtractionResultRepository(_BaseExtractionResultRepository):
    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _records(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        return [
            json.loads(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
