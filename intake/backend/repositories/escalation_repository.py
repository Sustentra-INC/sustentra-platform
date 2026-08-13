"""Escalation persistence (intake Stage 2).

Phase C writes and resolves escalations. Phase D adds the reviewer queue view
and the email pipeline on top of the same records.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class EscalationRepository(AppendOnlyRepository):
    id_field = "escalation_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return self.filter_latest(org_id=org_id)

    def list_open(self, org_id: str | None = None) -> list[dict]:
        records = self.list_by_org(org_id) if org_id else self.list_latest()
        return [record for record in records if record.get("status") == "pending_auditor_review"]

    def find_open_for_datapoint(
        self, org_id: str, datapoint_id: str, scope_ref: str | None
    ) -> dict | None:
        matches = [
            record
            for record in self.list_open(org_id)
            if record.get("datapoint_id") == datapoint_id
            and record.get("scope_ref") == scope_ref
        ]
        return matches[-1] if matches else None


class InMemoryEscalationRepository(EscalationRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlEscalationRepository(EscalationRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("escalations")))
