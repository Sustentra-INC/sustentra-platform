"""Magic-link token persistence (intake Stage 0).

Only token hashes are stored (see ``intake/backend/domain/auth.py``). Lookup is
by hash, so a stolen store yields no usable links.
"""

from __future__ import annotations

from pathlib import Path

from intake.backend.config import load_settings
from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore


class MagicLinkTokenRepository(AppendOnlyRepository):
    id_field = "token_id"

    def get_by_token_hash(self, token_hash: str) -> dict | None:
        return self.find_latest(token_hash=token_hash)


class InMemoryMagicLinkTokenRepository(MagicLinkTokenRepository):
    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class JsonlMagicLinkTokenRepository(MagicLinkTokenRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        super().__init__(JsonlStore(path or load_settings().storage_path("magic_link_tokens")))
