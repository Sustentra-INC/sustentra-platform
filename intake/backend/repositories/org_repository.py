"""Org persistence (intake Stage 1)."""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class OrgRepository(AppendOnlyRepository):
    id_field = "org_id"

    def get_by_legal_name(self, legal_name: str) -> dict | None:
        return self.find_latest(legal_name=legal_name)


class InMemoryOrgRepository(OrgRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlOrgRepository(OrgRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("orgs")))
