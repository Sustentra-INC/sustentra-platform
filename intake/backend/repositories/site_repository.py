"""Site persistence (intake Stage 1)."""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class SiteRepository(AppendOnlyRepository):
    id_field = "site_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return self.filter_latest(org_id=org_id)


class InMemorySiteRepository(SiteRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlSiteRepository(SiteRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("sites")))
