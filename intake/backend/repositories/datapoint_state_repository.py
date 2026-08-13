"""Datapoint state persistence (intake Stage 2).

Append-only, latest-wins per ``state_id`` - so the full history of every answer
is retained, which is what makes the audit log meaningful.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class DatapointStateRepository(AppendOnlyRepository):
    id_field = "state_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return self.filter_latest(org_id=org_id)

    def find(self, org_id: str, datapoint_id: str, scope_ref: str | None) -> dict | None:
        matches = [
            record
            for record in self.list_by_org(org_id)
            if record.get("datapoint_id") == datapoint_id
            and record.get("scope_ref") == scope_ref
        ]
        return matches[-1] if matches else None

    def list_for_datapoint(self, org_id: str, datapoint_id: str) -> list[dict]:
        return [
            record
            for record in self.list_by_org(org_id)
            if record.get("datapoint_id") == datapoint_id
        ]

    def list_by_scope(self, org_id: str, scope_ref: str | None) -> list[dict]:
        return [
            record for record in self.list_by_org(org_id) if record.get("scope_ref") == scope_ref
        ]

    def history(self, state_id: str) -> list[dict]:
        return [record for record in self.list_records() if record.get("state_id") == state_id]


class InMemoryDatapointStateRepository(DatapointStateRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlDatapointStateRepository(DatapointStateRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("datapoint_states")))
