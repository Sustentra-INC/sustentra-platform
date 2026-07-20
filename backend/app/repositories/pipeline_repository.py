from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.app.domain.pipeline import PipelineRun

DEFAULT_JSONL_PATH = "local-data/pipeline-runs/pipeline_runs.jsonl"


def _to_dict(run: PipelineRun | dict) -> dict[str, Any]:
    if isinstance(run, PipelineRun):
        return run.model_dump()
    if isinstance(run, dict):
        return copy.deepcopy(run)
    raise TypeError("run must be a PipelineRun or dict.")


class _BasePipelineRunRepository:
    def _records(self) -> list[dict]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, run: PipelineRun | dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_all(self) -> list[dict]:
        return list(self._records())

    def list_by_engagement(self, engagement_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("engagement_id") == engagement_id]

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        return [r for r in self._records() if r.get("evidence_id") == evidence_id]

    def get_by_id(self, pipeline_run_id: str) -> dict | None:
        for record in reversed(self._records()):
            if record.get("pipeline_run_id") == pipeline_run_id:
                return record
        return None

    def get_latest_by_evidence(self, evidence_id: str) -> dict | None:
        matches = self.list_by_evidence(evidence_id)
        return matches[-1] if matches else None


class InMemoryPipelineRunRepository(_BasePipelineRunRepository):
    def __init__(self) -> None:
        self._store: list[dict] = []

    def _records(self) -> list[dict]:
        return [copy.deepcopy(record) for record in self._store]

    def save(self, run: PipelineRun | dict) -> dict:
        record = _to_dict(run)
        self._store.append(copy.deepcopy(record))
        return record


class JsonlPipelineRunRepository(_BasePipelineRunRepository):
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

    def save(self, run: PipelineRun | dict) -> dict:
        record = _to_dict(run)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
