"""Seed-form submission persistence (intake Stage 1)."""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class SeedProfileRepository(AppendOnlyRepository):
    id_field = "seed_profile_id"

    def list_by_org(self, org_id: str) -> list[dict]:
        return [record for record in self.list_records() if record.get("org_id") == org_id]

    def latest_for_org(self, org_id: str) -> dict | None:
        submissions = self.list_by_org(org_id)
        return submissions[-1] if submissions else None


class InMemorySeedProfileRepository(SeedProfileRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlSeedProfileRepository(SeedProfileRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("seed_profiles")))
