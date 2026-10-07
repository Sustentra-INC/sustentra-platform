"""AUTH-004 integration tests: /me, expiry, logout, RBAC through the real app.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
Requests go through create_app() with the DB dependency pointed at a test engine,
using httpx.AsyncClient on https:// so the Secure session cookie is sent.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db
from backend.app.core.auth import CurrentUser, require_role
from backend.app.core.config import Settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000d1")
ADMIN_ID = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000d1")
MEMBER_ID = uuid.UUID("aaaaaaaa-2222-0000-0000-0000000000d1")
PROVIDER_ID = uuid.UUID("cccccccc-3333-0000-0000-0000000000d1")


def _now() -> datetime:
    return datetime.now(UTC)


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme')", ORG)
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, role, first_name, last_name, full_name) VALUES
              ($1, $2, 'admin@acme.test', 'org_admin', 'Ada', 'Admin', 'Ada Admin'),
              ($3, $2, 'member@acme.test', 'org_member', 'Max', 'Member', 'Max Member'),
              ($4, NULL, 'ops@sustentra.test', 'provider_admin', 'Pat', 'Provider', 'Pat Provider')
            """,
            ADMIN_ID, ORG, MEMBER_ID, PROVIDER_ID,
        )
    finally:
        await conn.close()


async def _add_session(user_id: uuid.UUID, org_id: uuid.UUID | None, token: str, *,
                       created: timedelta = timedelta(minutes=5),
                       last_seen: timedelta | None = timedelta(minutes=5),
                       expires_in: timedelta = timedelta(days=7)) -> None:
    now = _now()
    await _admin(
        """
        INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id, org_id, hash_token(token), now - created, now - created + expires_in,
        None if last_seen is None else now - last_seen,
    )


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    asyncio.run(_seed())


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep

    @app.get("/api/v1/_test/admin-only")
    async def admin_only(user: CurrentUser = Depends(require_role("org_admin"))) -> dict[str, str]:
        return {"ok": user.email}

    return app


async def _call(method: str, path: str, token: str | None = None) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        transport = httpx.ASGITransport(app=_app(engine))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            if token is None:
                client.cookies.pop(SESSION_COOKIE, None)
            else:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, headers={"Origin": ORIGIN})
    finally:
        await engine.dispose()


def call(method: str, path: str, token: str | None = None) -> Any:
    return asyncio.run(_call(method, path, token))


# --- /me ------------------------------------------------------------------------

def test_me_with_valid_cookie_returns_user() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-admin"))
    response = call("GET", "/api/v1/auth/me", "tok-admin")
    assert response.status_code == 200
    assert response.json() == {
        "id": str(ADMIN_ID), "email": "admin@acme.test", "first_name": "Ada", "last_name": "Admin",
        "full_name": "Ada Admin", "role": "org_admin", "org_id": str(ORG), "org_slug": "acme",
    }


def test_me_without_cookie_is_401() -> None:
    assert call("GET", "/api/v1/auth/me").status_code == 401


def test_me_with_unknown_token_is_401() -> None:
    assert call("GET", "/api/v1/auth/me", "not-a-real-token").status_code == 401


def test_provider_admin_me_has_no_org() -> None:
    asyncio.run(_add_session(PROVIDER_ID, None, "tok-provider"))
    body = call("GET", "/api/v1/auth/me", "tok-provider").json()
    assert body["role"] == "provider_admin"
    assert body["org_id"] is None and body["org_slug"] is None


# --- expiry ------------------------------------------------------------------------

def test_idle_expired_session_is_401() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-idle", created=timedelta(hours=10), last_seen=timedelta(hours=9)))
    assert call("GET", "/api/v1/auth/me", "tok-idle").status_code == 401


def test_absolute_expired_session_is_401() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-old", created=timedelta(days=8), last_seen=timedelta(minutes=1)))
    assert call("GET", "/api/v1/auth/me", "tok-old").status_code == 401


def test_suspended_user_or_org_is_401() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-s"))
    asyncio.run(_admin("UPDATE users SET status = 'suspended' WHERE id = $1", ADMIN_ID))
    assert call("GET", "/api/v1/auth/me", "tok-s").status_code == 401

    asyncio.run(_admin("UPDATE users SET status = 'active' WHERE id = $1", ADMIN_ID))
    asyncio.run(_admin("UPDATE organizations SET status = 'suspended' WHERE id = $1", ORG))
    assert call("GET", "/api/v1/auth/me", "tok-s").status_code == 401


def test_last_seen_is_refreshed_at_most_once_a_minute() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-seen", last_seen=timedelta(minutes=30)))
    call("GET", "/api/v1/auth/me", "tok-seen")
    [row] = asyncio.run(_admin("SELECT last_seen_at FROM sessions WHERE token_hash = $1", hash_token("tok-seen")))
    first = row["last_seen_at"]
    assert _now() - first < timedelta(minutes=1)

    call("GET", "/api/v1/auth/me", "tok-seen")
    [row] = asyncio.run(_admin("SELECT last_seen_at FROM sessions WHERE token_hash = $1", hash_token("tok-seen")))
    assert row["last_seen_at"] == first  # not rewritten within the same minute


# --- logout ------------------------------------------------------------------------

def test_logout_ends_only_the_current_session() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-a"))
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-b"))

    response = call("POST", "/api/v1/auth/logout", "tok-a")
    assert response.status_code == 200
    set_cookie = response.headers["set-cookie"].lower()
    assert set_cookie.startswith(SESSION_COOKIE.lower()) and "max-age=0" in set_cookie

    assert call("GET", "/api/v1/auth/me", "tok-a").status_code == 401
    assert call("GET", "/api/v1/auth/me", "tok-b").status_code == 200


def test_logout_writes_audit_event() -> None:
    asyncio.run(_add_session(MEMBER_ID, ORG, "tok-m"))
    call("POST", "/api/v1/auth/logout", "tok-m")
    rows = asyncio.run(_admin("SELECT org_id, actor_user_id, event_type FROM audit_logs"))
    assert [(r["org_id"], r["actor_user_id"], r["event_type"]) for r in rows] == [(ORG, MEMBER_ID, "logout")]


def test_logout_without_session_is_401() -> None:
    assert call("POST", "/api/v1/auth/logout").status_code == 401


# --- RBAC ------------------------------------------------------------------------

def test_require_role_allows_right_role_and_forbids_others() -> None:
    asyncio.run(_add_session(ADMIN_ID, ORG, "tok-admin"))
    asyncio.run(_add_session(MEMBER_ID, ORG, "tok-member"))
    assert call("GET", "/api/v1/_test/admin-only", "tok-admin").status_code == 200
    assert call("GET", "/api/v1/_test/admin-only", "tok-member").status_code == 403
    assert call("GET", "/api/v1/_test/admin-only").status_code == 401
