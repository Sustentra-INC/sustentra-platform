"""Session persistence (intake Stage 0).

Sessions need their own store alongside magic-link tokens: a token is consumed
once, a session then lives for its own lifetime and can be revoked. Only the
session token hash is stored.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class SessionRepository(AppendOnlyRepository):
    id_field = "session_id"

    def get_by_token_hash(self, session_token_hash: str) -> dict | None:
        return self.find_latest(session_token_hash=session_token_hash)

    def list_by_user(self, user_id: str) -> list[dict]:
        return self.filter_latest(user_id=user_id)


class InMemorySessionRepository(SessionRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlSessionRepository(SessionRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("sessions")))
