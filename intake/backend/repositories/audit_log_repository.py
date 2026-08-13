"""Audit log persistence (intake Stage 2).

Strictly append-only: entries are written once and never updated, so the
inherited ``save`` is the only mutation path.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class AuditLogRepository(AppendOnlyRepository):
    id_field = "audit_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return [record for record in self.list_records() if record.get("org_id") == org_id]

    def list_for_datapoint(
        self, org_id: str, datapoint_id: str, scope_ref: str | None = None
    ) -> list[dict]:
        return [
            record
            for record in self.list_by_org(org_id)
            if record.get("datapoint_id") == datapoint_id
            and (scope_ref is None or record.get("scope_ref") == scope_ref)
        ]


class InMemoryAuditLogRepository(AuditLogRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlAuditLogRepository(AuditLogRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("audit_log")))
