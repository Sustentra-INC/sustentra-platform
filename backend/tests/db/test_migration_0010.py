"""ORG-003: migration 0010 (users.invited_by, auth_resolve_invite_token) up and down.

Runs alembic against TEST_DATABASE_URL and always leaves the database at head.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

BACKEND = Path(__file__).resolve().parents[2]


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


async def _fetch(url: str, sql: str) -> list[Any]:
    conn = await asyncpg.connect(url)
    try:
        return list(await conn.fetch(sql))
    finally:
        await conn.close()


def fetch(sql: str, url: str | None = None) -> list[Any]:
    return asyncio.run(_fetch(url or ADMIN_URL or "", sql))


def _state() -> tuple[bool, bool]:
    column = bool(fetch("SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = 'invited_by'"))
    function = bool(fetch("SELECT 1 FROM pg_proc WHERE proname = 'auth_resolve_invite_token'"))
    return column, function


def test_0010_down_and_up() -> None:
    try:
        assert _state() == (True, True)
        alembic("downgrade", "0009")
        assert _state() == (False, False)
        alembic("upgrade", "head")
        assert _state() == (True, True)
    finally:
        alembic("upgrade", "head")


def test_app_user_may_call_the_lookup_but_not_read_tokens_without_a_tenant() -> None:
    # The function is the only way to find a token before the tenant is known.
    assert fetch("SELECT * FROM auth_resolve_invite_token('no-such-hash')", APP_URL) == []
    assert fetch("SELECT has_function_privilege('public', 'auth_resolve_invite_token(text)', 'EXECUTE') AS ok")[0][
        "ok"] is False
