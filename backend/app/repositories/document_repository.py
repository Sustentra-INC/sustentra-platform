from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.app.domain.document import Document

DEFAULT_JSONL_PATH = "local-data/documents/documents.jsonl"


def _to_dict(document: Document | dict) -> dict[str, Any]:
    if isinstance(document, Document):
        return document.model_dump()
    if isinstance(document, dict):
        return copy.deepcopy(document)
    raise TypeError("document must be a Document or dict.")


class _BaseDocumentRepository:
    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, document: Document | dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict]:
        return list(self._records())

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("engagement_id") == engagement_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def get_by_id(self, document_id: str) -> dict | None:
        for record in reversed(self._records()):
            if record.get("document_id") == document_id:
                return record
        return None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None

    def update_processing_status(self, document_id: str, processing_status: str) -> dict:
        existing = self.get_by_id(document_id)
        if existing is None:
            raise KeyError(f"Document not found: {document_id}")

        updated = copy.deepcopy(existing)
        updated["processing_status"] = processing_status
        return self.save(updated)


class InMemoryDocumentRepository(_BaseDocumentRepository):
    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, document: Document | dict) -> dict:
        record = _to_dict(document)
        self._store.append(copy.deepcopy(record))
        return record


class JsonlDocumentRepository(_BaseDocumentRepository):
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

    def save(self, document: Document | dict) -> dict:
        record = _to_dict(document)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
