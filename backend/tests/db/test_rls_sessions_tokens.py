"""Integration tests for DB-002 (sessions, auth_tokens, purge). Run in CI against Postgres.

Same environment as test_rls_users.py: TEST_DATABASE_URL (owner) and
TEST_APP_DATABASE_URL (app_user, RLS enforced). Skipped locally without them.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from backend.app.db_maintenance import purge_expired_auth_rows

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000000a")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000000b")
ALICE = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000001")  # org A, org_admin
BOB = uuid.UUID("bbbbbbbb-1111-0000-0000-000000000002")  # org B, org_member


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'A', 'tenant-a'), ($2, 'B', 'tenant-b')",
            ORG_A,
            ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, role) VALUES
              ($1, $2, 'alice@a.test', 'org_admin'),
              ($3, $4, 'bob@b.test',   'org_member')
            """,
            ALICE, ORG_A, BOB, ORG_B,
        )
        # One live and one long-expired session/token per tenant.
        await conn.execute(
            """
            INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at) VALUES
              ($1, $2, 'sess-a-live',    now(),                    now() + interval '7 days'),
              ($1, $2, 'sess-a-old',     now() - interval '10 days', now() - interval '3 days'),
              ($3, $4, 'sess-b-live',    now(),                    now() + interval '7 days'),
              ($3, $4, 'sess-b-old',     now() - interval '10 days', now() - interval '3 days'),
              ($3, $4, 'sess-b-recent',  now() - interval '2 hours', now() - interval '1 hour')
            """,
            ALICE, ORG_A, BOB, ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO auth_tokens (user_id, org_id, type, token_hash, expires_at) VALUES
              ($1, $2, 'email_otp',      'tok-a-live', now() + interval '10 minutes'),
              ($1, $2, 'password_reset', 'tok-a-old',  now() - interval '2 days'),
              ($3, $4, 'email_otp',      'tok-b-live', now() + interval '10 minutes')
            """,
            ALICE, ORG_A, BOB, ORG_B,
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


def test_create_session_and_read_back_with_org_and_role() -> None:
    async def work(c: Any) -> Any:
        await c.execute(
            "INSERT INTO sessions (user_id, org_id, token_hash, expires_at) VALUES ($1, $2, 'new-hash', now() + interval '1 day')",
            ALICE, ORG_A,
        )
        return await c.fetchrow(
            """
            SELECT s.user_id, s.org_id, u.role, o.slug
              FROM sessions s
              JOIN users u ON u.id = s.user_id
              JOIN organizations o ON o.id = s.org_id
             WHERE s.token_hash = 'new-hash'
            """
        )

    row = run(lambda: _as_app(work, tenant=ORG_A))
    assert row["user_id"] == ALICE
    assert row["org_id"] == ORG_A
    assert row["role"] == "org_admin"
    assert row["slug"] == "tenant-a"


def test_cross_tenant_sessions_and_tokens_are_invisible() -> None:
    async def work(c: Any) -> tuple[set[str], set[str]]:
        sessions = {r["token_hash"] for r in await c.fetch("SELECT token_hash FROM sessions")}
        tokens = {r["token_hash"] for r in await c.fetch("SELECT token_hash FROM auth_tokens")}
        return sessions, tokens

    sessions, tokens = run(lambda: _as_app(work, tenant=ORG_A))
    assert sessions == {"sess-a-live", "sess-a-old"}
    assert tokens == {"tok-a-live", "tok-a-old"}


def test_no_tenant_sees_no_sessions_or_tokens() -> None:
    async def work(c: Any) -> tuple[int, int]:
        return await c.fetchval("SELECT count(*) FROM sessions"), await c.fetchval("SELECT count(*) FROM auth_tokens")

    assert run(lambda: _as_app(work)) == (0, 0)


def test_cannot_write_session_for_another_tenant() -> None:
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="row-level security"):
        run(lambda: _as_app(
            lambda c: c.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, expires_at) VALUES ($1, $2, 'x', now() + interval '1 day')",
                BOB, ORG_B,
            ),
            tenant=ORG_A,
        ))


def test_token_org_must_match_the_users_org() -> None:
    # Alice belongs to org A; claiming org B breaks the composite FK.
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        run(lambda: _as_app(
            lambda c: c.execute(
                "INSERT INTO auth_tokens (user_id, org_id, type, token_hash, expires_at) "
                "VALUES ($1, $2, 'email_otp', 'mismatch', now() + interval '5 minutes')",
                ALICE, ORG_B,
            ),
            provider=True,
        ))


def test_session_token_hash_is_unique() -> None:
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        run(lambda: _as_app(
            lambda c: c.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, expires_at) VALUES ($1, $2, 'sess-a-live', now() + interval '1 day')",
                ALICE, ORG_A,
            ),
            tenant=ORG_A,
        ))


def test_purge_removes_rows_expired_over_a_day_and_keeps_the_rest() -> None:
    # Called as app_user inside tenant A (like after a login) - still purges all tenants.
    removed = run(lambda: _as_app(purge_expired_auth_rows, tenant=ORG_A))
    assert removed == 3  # sess-a-old, sess-b-old, tok-a-old

    async def remaining() -> tuple[set[str], set[str]]:
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            s = {r["token_hash"] for r in await conn.fetch("SELECT token_hash FROM sessions")}
            t = {r["token_hash"] for r in await conn.fetch("SELECT token_hash FROM auth_tokens")}
            return s, t
        finally:
            await conn.close()

    sessions, tokens = run(remaining)
    # Expired less than a day ago is kept (sess-b-recent); live rows are kept.
    assert sessions == {"sess-a-live", "sess-b-live", "sess-b-recent"}
    assert tokens == {"tok-a-live", "tok-b-live"}


def test_app_user_still_cannot_see_other_tenants_after_purge() -> None:
    run(lambda: _as_app(purge_expired_auth_rows, tenant=ORG_A))
    count = run(lambda: _as_app(lambda c: c.fetchval("SELECT count(*) FROM sessions"), tenant=ORG_A))
    assert count == 1  # only sess-a-live
