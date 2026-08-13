"""Evidence request persistence (intake Stage 4).

Append-only like every other intake repository, so a request's history - first
expected, later received, later accepted - is preserved rather than overwritten.
The compiler recomputes requests from the client's answers on every run; because
IDs are derived from identity, a rerun appends an updated record to the same ID
instead of creating a duplicate.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class EvidenceRequestRepository(AppendOnlyRepository):
    id_field = "evidence_request_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return self.filter_latest(org_id=org_id)

    def list_open(self, org_id: str) -> list[dict]:
        """Requests still waiting on a document."""
        return [
            record
            for record in self.list_by_org(org_id)
            if record.get("status") == "expected"
        ]

    def list_safe_to_parse(self, org_id: str) -> list[dict]:
        """What S1 may start on now (SPEC section 5, Stage 5)."""
        return [record for record in self.list_by_org(org_id) if record.get("safe_to_parse")]


class InMemoryEvidenceRequestRepository(EvidenceRequestRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlEvidenceRequestRepository(EvidenceRequestRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("evidence_requests")))
