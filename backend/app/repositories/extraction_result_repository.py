from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_JSONL_PATH = "local-data/extraction-results/extraction_results.jsonl"


class _BaseExtractionResultRepository:
    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, result: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_by_document(self, document_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("document_id") == document_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def get_latest_by_document(self, document_id: str) -> dict | None:
        matches = self.list_by_document(document_id)
        return matches[-1] if matches else None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None


class InMemoryExtractionResultRepository(_BaseExtractionResultRepository):
    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, result: dict) -> dict:
        record = copy.deepcopy(result)
        self._store.append(copy.deepcopy(record))
        return record


class JsonlExtractionResultRepository(_BaseExtractionResultRepository):
    def __init__(self, path: str | Path = DEFAULT_JSONL_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _records(self) -> list[dict]:
        if not self._path.exists():
            return []

        records: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records

    def save(self, result: dict) -> dict:
        record = copy.deepcopy(result)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
