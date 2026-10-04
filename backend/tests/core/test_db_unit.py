"""AUTH-002 unit tests (no database needed)."""

import asyncio
import uuid
from typing import Any

import pytest

from backend.app.core import db
from backend.app.core.config import Settings


def _settings(env: str, url: str | None) -> Settings:
    # Pass database_url explicitly (even None) so a DATABASE_URL env var, as in CI,
    # can't fill it in.
    return Settings(environment=env, database_url=url)  # type: ignore[call-arg]


def test_async_url_conversion() -> None:
    assert (
        db.to_async_url("postgresql://app_user:pw@db.example:5432/sustentra?sslmode=require")
        == "postgresql+asyncpg://app_user:pw@db.example:5432/sustentra?ssl=require"
    )


def test_prod_refuses_master_credentials() -> None:
    with pytest.raises(db.DatabaseNotConfiguredError, match="app_user"):
        db.runtime_database_url(_settings("prod", "postgresql://sustentra_admin:pw@h/sustentra?sslmode=require"))


def test_prod_accepts_app_user() -> None:
    url = "postgresql://app_user:pw@h/sustentra?sslmode=require"
    assert db.runtime_database_url(_settings("prod", url)) == url


def test_missing_database_url_is_an_error() -> None:
    with pytest.raises(db.DatabaseNotConfiguredError):
        db.runtime_database_url(_settings("local", None))


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.calls.append((str(statement), params))


def test_set_tenant_is_parameterized_and_transaction_local() -> None:
    session = _RecordingSession()
    org = uuid.uuid4()
    asyncio.run(db.set_tenant(session, org))  # type: ignore[arg-type]
    sql, params = session.calls[0]
    assert ":org_id" in sql and str(org) not in sql  # value is bound, never formatted in
    assert "true)" in sql  # is_local = true
    assert params == {"org_id": str(org)}


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "x'); DROP TABLE users; --"])
def test_set_tenant_rejects_non_uuid(bad: str) -> None:
    with pytest.raises(ValueError):
        asyncio.run(db.set_tenant(_RecordingSession(), bad))  # type: ignore[arg-type]


def test_set_provider_clears_tenant() -> None:
    session = _RecordingSession()
    asyncio.run(db.set_provider(session))  # type: ignore[arg-type]
    sql, _ = session.calls[0]
    assert "app.is_provider', 'true', true" in sql
    assert "app.tenant_id', '', true" in sql
