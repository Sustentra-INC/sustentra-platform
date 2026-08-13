"""User persistence (intake Stage 0).

Email lookup is case-insensitive: addresses are normalised to lower case on the
way in, and lookups normalise too.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


def normalise_email(email: str) -> str:
    return email.strip().lower()


class UserRepository(AppendOnlyRepository):
    id_field = "user_id"

    def get_by_email(self, email: str) -> dict | None:
        target = normalise_email(email)
        matches = [
            record
            for record in self.list_latest()
            if normalise_email(str(record.get("email", ""))) == target
        ]
        return matches[-1] if matches else None

    def list_by_org(self, org_id: str) -> list[dict]:
        return self.filter_latest(org_id=org_id)


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlUserRepository(UserRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("users")))
