"""DB-004: migration 0009 (organizations.max_users, user status vocabulary) up and down.

Runs alembic against TEST_DATABASE_URL and always leaves the database at head.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
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
BIG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000b9")
SMALL = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b9")


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


async def _sql(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        async with conn.transaction():
            # Provider scope, so this works even when the owner does not bypass RLS (RDS).
            await conn.execute("SELECT set_config('app.is_provider', 'true', true)")
            return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def sql(query: str, *args: Any) -> list[Any]:
    return asyncio.run(_sql(query, *args))


@pytest.fixture
def at_0008() -> Any:
    sql("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
    alembic("downgrade", "0008")
    try:
        sql("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Big', 'big-org'), ($2, 'Small', 'small-org')",
            BIG, SMALL)
        # 30 live users in Big (over the default 25), one deleted; one disabled user in Small.
        for i in range(30):
            sql("INSERT INTO users (org_id, email, role) VALUES ($1, $2, 'org_member')", BIG, f"u{i}@big.test")
        sql("INSERT INTO users (org_id, email, role, status) VALUES ($1, 'gone@big.test', 'org_member', 'deleted')",
            BIG)
        sql("INSERT INTO users (org_id, email, role, status) VALUES ($1, 'off@small.test', 'org_admin', 'disabled')",
            SMALL)
        yield
    finally:
        alembic("upgrade", "head")
        sql("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")


def _seats() -> dict[str, int]:
    return {r["slug"]: r["max_users"] for r in sql("SELECT slug, max_users FROM organizations")}


def test_upgrade_backfills_seats_and_maps_statuses(at_0008: None) -> None:
    alembic("upgrade", "0009")
    assert _seats() == {"big-org": 30, "small-org": 25}  # never below the current head count
    assert [r["status"] for r in sql("SELECT status FROM users WHERE email = 'off@small.test'")] == ["suspended"]
    assert sql("SELECT count(*) AS n FROM users WHERE status = 'disabled'")[0]["n"] == 0

    # New orgs default to 25; the range is enforced; 'invited' is allowed, 'disabled' is not.
    sql("INSERT INTO organizations (name, slug) VALUES ('New', 'new-org')")
    assert _seats()["new-org"] == 25
    for bad in (0, 10_001):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            sql("UPDATE organizations SET max_users = $1 WHERE slug = 'new-org'", bad)
    sql("INSERT INTO users (org_id, email, role, status) VALUES ($1, 'new@small.test', 'org_member', 'invited')",
        SMALL)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        sql("INSERT INTO users (org_id, email, role, status) VALUES ($1, 'x@small.test', 'org_member', 'disabled')",
            SMALL)


def test_downgrade_restores_0008(at_0008: None) -> None:
    alembic("upgrade", "0009")
    sql("INSERT INTO users (org_id, email, role, status) VALUES ($1, 'new@small.test', 'org_member', 'invited')",
        SMALL)
    alembic("downgrade", "0008")
    columns = {r["column_name"] for r in sql(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'organizations'")}
    assert "max_users" not in columns
    statuses = {r["email"]: r["status"] for r in sql("SELECT email, status FROM users WHERE org_id = $1", SMALL)}
    assert statuses == {"off@small.test": "suspended", "new@small.test": "disabled"}


def test_rls_and_app_role_unchanged_after_upgrade() -> None:
    # Runs at head (the fixtures above always finish there).
    rows = sql("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_user'")
    assert [(r["rolsuper"], r["rolbypassrls"]) for r in rows] == [(False, False)]
    flags = sql("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'users'")[0]
    assert flags["relrowsecurity"] and flags["relforcerowsecurity"]

    async def as_app(tenant: uuid.UUID) -> int:
        conn = await asyncpg.connect(APP_URL)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
                return len(await conn.fetch("SELECT id FROM users"))
        finally:
            await conn.close()

    sql("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
    sql("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Big', 'big-org'), ($2, 'Small', 'small-org')",
        BIG, SMALL)
    sql("INSERT INTO users (org_id, email, role) VALUES ($1, 'a@big.test', 'org_admin')", BIG)
    try:
        assert asyncio.run(as_app(BIG)) == 1
        assert asyncio.run(as_app(SMALL)) == 0
    finally:
        sql("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
