from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

DEFAULT_IDENTITY_DIR = "local-data/identity"


def _copy(record: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(record)


class _BaseRecordStore:
    def _versions(self) -> list[dict[str, Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def save(self, record: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def latest_by_id(self, id_field: str) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in self._versions():
            key = record.get(id_field)
            if key:
                latest[str(key)] = _copy(record)
        return latest

    def get_by_id(self, id_field: str, value: str) -> dict[str, Any] | None:
        record = self.latest_by_id(id_field).get(value)
        if record is None or record.get("status") == "deleted":
            return None
        return record

    def list_active(self, id_field: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.latest_by_id(id_field).values()
            if record.get("status") != "deleted"
        ]

    def find_latest(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        match: dict[str, Any] | None = None
        for record in self._versions():
            if predicate(record):
                match = _copy(record)
        if match is None:
            return None
        if not include_deleted and match.get("status") == "deleted":
            return None
        return match


class InMemoryRecordStore(_BaseRecordStore):
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    def _versions(self) -> list[dict[str, Any]]:
        return [_copy(record) for record in self._store]

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = _copy(record)
        self._store.append(_copy(saved))
        return saved


class JsonlRecordStore(_BaseRecordStore):
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _versions(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        saved = _copy(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(saved, ensure_ascii=False) + "\n")
        return saved


class IdentityRepository:
    """File-or-memory persistence for identity. No database required."""

    def __init__(
        self,
        *,
        users: _BaseRecordStore | None = None,
        clients: _BaseRecordStore | None = None,
        client_users: _BaseRecordStore | None = None,
        sessions: _BaseRecordStore | None = None,
        resets: _BaseRecordStore | None = None,
        challenges: _BaseRecordStore | None = None,
        audit: _BaseRecordStore | None = None,
    ) -> None:
        self.users = users or InMemoryRecordStore()
        self.clients = clients or InMemoryRecordStore()
        self.client_users = client_users or InMemoryRecordStore()
        self.sessions = sessions or InMemoryRecordStore()
        self.resets = resets or InMemoryRecordStore()
        self.challenges = challenges or InMemoryRecordStore()
        self.audit = audit or InMemoryRecordStore()

    @classmethod
    def in_memory(cls) -> IdentityRepository:
        return cls()

    @classmethod
    def jsonl(cls, root: str | Path = DEFAULT_IDENTITY_DIR) -> IdentityRepository:
        base = Path(root)
        return cls(
            users=JsonlRecordStore(base / "users.jsonl"),
            clients=JsonlRecordStore(base / "clients.jsonl"),
            client_users=JsonlRecordStore(base / "client_users.jsonl"),
            sessions=JsonlRecordStore(base / "sessions.jsonl"),
            resets=JsonlRecordStore(base / "password_resets.jsonl"),
            challenges=JsonlRecordStore(base / "mfa_challenges.jsonl"),
            audit=JsonlRecordStore(base / "audit_events.jsonl"),
        )
