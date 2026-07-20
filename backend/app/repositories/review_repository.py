"""Review decision persistence (PR7).

Provides in-memory and JSONL file-backed repositories for ``review_decision``
records. The JSONL repository writes one JSON object per line under the ignored
``local-data/`` tree. No database, ORM, or ``.env`` access is used.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.app.domain.review import ReviewDecision

DEFAULT_JSONL_PATH = "local-data/review-decisions/review_decisions.jsonl"


def _to_dict(decision: ReviewDecision | dict) -> dict[str, Any]:
    if isinstance(decision, ReviewDecision):
        return decision.model_dump()
    if isinstance(decision, dict):
        return copy.deepcopy(decision)
    raise TypeError("decision must be a ReviewDecision or dict.")


class _BaseReviewDecisionRepository:
    """Shared query behavior expressed in terms of ``_records()``."""

    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, decision: ReviewDecision | dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict]:
        return list(self._records())

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def list_by_document(self, document_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("document_id") == document_id]

    def list_by_candidate(self, candidate_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("candidate_id") == candidate_id]

    def get_latest_by_candidate(self, candidate_id: str) -> dict | None:
        matches = self.list_by_candidate(candidate_id)
        return matches[-1] if matches else None

    def get_latest_by_field(self, evidence_id: str, field_name: str) -> dict | None:
        matches = [
            r
            for r in self._records()
            if r.get("evidence_id") == evidence_id and r.get("field_name") == field_name
        ]
        return matches[-1] if matches else None


class InMemoryReviewDecisionRepository(_BaseReviewDecisionRepository):
    """Non-persistent repository, primarily for tests and transient use."""

    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, decision: ReviewDecision | dict) -> dict:
        record = _to_dict(decision)
        self._store.append(copy.deepcopy(record))
        return record


class JsonlReviewDecisionRepository(_BaseReviewDecisionRepository):
    """File-backed repository writing one review decision JSON per line."""

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

    def save(self, decision: ReviewDecision | dict) -> dict:
        record = _to_dict(decision)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
