"""Integration tests for DB-003 (audit_logs). Run in CI against Postgres.

TEST_DATABASE_URL (owner) and TEST_APP_DATABASE_URL (app_user, RLS enforced);
skipped locally unless both are set.
"""

from __future__ import annotations

import asyncio
import json
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

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b2")


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute(
            """
            INSERT INTO audit_logs (org_id, event_type, metadata) VALUES
              ($1, 'login_success', '{"method": "otp"}'),
              ($1, 'logout',        '{}'),
              ($2, 'login_success', '{}'),
              (NULL, 'login_fail',  '{"reason": "unknown_org"}')
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


def _org_ids(rows: list[Any]) -> list[uuid.UUID | None]:
    return sorted((r["org_id"] for r in rows), key=lambda v: str(v))


# --- visibility --------------------------------------------------------------

def test_each_org_sees_only_its_own_events() -> None:
    rows_a = run(lambda: _as_app(lambda c: c.fetch("SELECT org_id FROM audit_logs"), tenant=ORG_A))
    rows_b = run(lambda: _as_app(lambda c: c.fetch("SELECT org_id FROM audit_logs"), tenant=ORG_B))
    assert _org_ids(rows_a) == [ORG_A, ORG_A]
    assert _org_ids(rows_b) == [ORG_B]


def test_provider_sees_all_events_including_provider_level() -> None:
    rows = run(lambda: _as_app(lambda c: c.fetch("SELECT org_id FROM audit_logs"), provider=True))
    assert len(rows) == 4
    assert None in {r["org_id"] for r in rows}


def test_no_context_sees_nothing() -> None:
    assert run(lambda: _as_app(lambda c: c.fetchval("SELECT count(*) FROM audit_logs"))) == 0


# --- append-only ---------------------------------------------------------------

def test_update_as_app_user_is_a_permission_error() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="permission denied"):
        run(lambda: _as_app(lambda c: c.execute("UPDATE audit_logs SET event_type = 'tampered'"), provider=True))


def test_delete_as_app_user_is_a_permission_error() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="permission denied"):
        run(lambda: _as_app(lambda c: c.execute("DELETE FROM audit_logs"), provider=True))


def test_truncate_as_app_user_is_a_permission_error() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        run(lambda: _as_app(lambda c: c.execute("TRUNCATE audit_logs"), provider=True))


# --- inserts ---------------------------------------------------------------

def test_tenant_can_insert_own_event_and_read_it_back() -> None:
    async def work(c: Any) -> Any:
        await c.execute(
            "INSERT INTO audit_logs (org_id, event_type, metadata) VALUES ($1, 'user_invited', $2::jsonb)",
            ORG_A,
            json.dumps({"invitee": "x@a.test"}),
        )
        return await c.fetchval("SELECT count(*) FROM audit_logs WHERE event_type = 'user_invited'")

    assert run(lambda: _as_app(work, tenant=ORG_A)) == 1


def test_tenant_cannot_insert_event_for_another_org() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        run(lambda: _as_app(
            lambda c: c.execute("INSERT INTO audit_logs (org_id, event_type) VALUES ($1, 'login_success')", ORG_B),
            tenant=ORG_A,
        ))


def test_pre_login_event_without_org_can_be_written_but_not_read_by_tenant() -> None:
    async def work(c: Any) -> Any:
        await c.execute("INSERT INTO audit_logs (org_id, event_type) VALUES (NULL, 'login_fail')")
        return await c.fetchval("SELECT count(*) FROM audit_logs WHERE org_id IS NULL")

    assert run(lambda: _as_app(work, tenant=ORG_A)) == 0


@pytest.mark.parametrize("bad", ["Login Success", "x", "1abc", "has-dash"])
def test_event_type_format_is_enforced(bad: str) -> None:
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(lambda: _as_app(
            lambda c: c.execute("INSERT INTO audit_logs (org_id, event_type) VALUES ($1, $2)", ORG_A, bad),
            tenant=ORG_A,
        ))
