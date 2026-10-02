"""Integration tests for DB-001 (organizations, users, RLS, app_user role).

They need a migrated Postgres 16 and run in CI (see .github/workflows/ci.yml):
    TEST_DATABASE_URL      admin/owner connection (bypasses RLS: superuser in CI)
    TEST_APP_DATABASE_URL  connection as app_user (RLS enforced)
Locally they are skipped unless both variables are set.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE users, organizations CASCADE")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 'org-a'), ($2, 'Org B', 'org-b')",
            ORG_A,
            ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (org_id, email, role) VALUES
              ($1, 'alice@a.test', 'org_admin'),
              ($2, 'bob@b.test',   'org_member'),
              (NULL, 'ops@sustentra.test', 'provider_admin')
            """,
            ORG_A,
            ORG_B,
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    run(_seed)


async def _as_app(work: Callable[[Any], Awaitable[Any]], *, tenant: uuid.UUID | None = None,
                  provider: bool = False) -> Any:
    conn = await asyncpg.connect(APP_URL)
    try:
        async with conn.transaction():
            if tenant is not None:
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if provider:
                await conn.execute("SELECT set_config('app.is_provider', 'true', true)")
            return await work(conn)
    finally:
        await conn.close()


def _emails(rows: list[Any]) -> set[str]:
    return {r["email"] for r in rows}


# --- RLS -------------------------------------------------------------------

def test_tenant_sees_only_its_own_users() -> None:
    rows = run(lambda: _as_app(lambda c: c.fetch("SELECT email FROM users"), tenant=ORG_A))
    assert _emails(rows) == {"alice@a.test"}


def test_tenant_cannot_update_other_org_users() -> None:
    status = run(lambda: _as_app(
        lambda c: c.execute("UPDATE users SET full_name = 'hacked' WHERE email = 'bob@b.test'"), tenant=ORG_A
    ))
    assert status == "UPDATE 0"


def test_tenant_cannot_insert_into_other_org() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        run(lambda: _as_app(
            lambda c: c.execute(
                "INSERT INTO users (org_id, email, role) VALUES ($1, 'mallory@b.test', 'org_member')", ORG_B
            ),
            tenant=ORG_A,
        ))


def test_no_tenant_set_returns_zero_rows() -> None:
    rows = run(lambda: _as_app(lambda c: c.fetch("SELECT email FROM users")))
    assert rows == []


def test_provider_sees_all_users() -> None:
    rows = run(lambda: _as_app(lambda c: c.fetch("SELECT email FROM users"), provider=True))
    assert _emails(rows) == {"alice@a.test", "bob@b.test", "ops@sustentra.test"}


def test_organizations_are_readable_without_tenant_for_slug_lookup() -> None:
    row = run(lambda: _as_app(lambda c: c.fetchrow("SELECT id FROM organizations WHERE slug = 'org-b'")))
    assert row["id"] == ORG_B


# --- constraints -------------------------------------------------------------

async def _admin_execute(sql: str, *args: Any) -> str:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


def test_same_email_allowed_in_two_orgs_but_not_twice_in_one() -> None:
    run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES ($1, 'same@x.test', 'org_member')", ORG_A)
    run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES ($1, 'same@x.test', 'org_member')", ORG_B)
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES ($1, 'same@x.test', 'org_admin')", ORG_A)


def test_email_must_be_lowercase() -> None:
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES ($1, 'Upper@x.test', 'org_member')", ORG_A)


def test_org_id_null_iff_provider_admin() -> None:
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES ($1, 'p@x.test', 'provider_admin')", ORG_A)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(_admin_execute, "INSERT INTO users (org_id, email, role) VALUES (NULL, 'm@x.test', 'org_member')")


@pytest.mark.parametrize("slug", ["ab", "Has-Upper", "under_score", "x" * 64])
def test_slug_format_is_enforced(slug: str) -> None:
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(_admin_execute, "INSERT INTO organizations (name, slug) VALUES ('n', $1)", slug)


# --- app_user role -----------------------------------------------------------

def test_app_user_role_attributes() -> None:
    async def attrs() -> Any:
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            return await conn.fetchrow(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = 'app_user'"
            )
        finally:
            await conn.close()

    row = run(attrs)
    assert row is not None
    assert not any(row.values())


def test_app_user_cannot_run_ddl() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        run(lambda: _as_app(lambda c: c.execute("CREATE TABLE should_fail (id int)"), provider=True))
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        run(lambda: _as_app(lambda c: c.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY"), provider=True))
