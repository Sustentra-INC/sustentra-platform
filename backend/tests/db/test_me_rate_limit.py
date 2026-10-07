"""AUTH-007: GET /auth/me has its own per-session limit, outside the login brute-force bucket.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db
from backend.app.core import rate_limit
from backend.app.core.config import Settings
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
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000f7")
USER = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000f7")
LIMITS = Settings(auth_rate_limit="5/minute", session_rate_limit="20/minute")


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme')", ORG)
        await conn.execute(
            "INSERT INTO users (id, org_id, email, role) VALUES ($1, $2, 'member@acme.test', 'org_member')", USER, ORG
        )
        now = datetime.now(UTC)
        for token in ("tok-1", "tok-2"):
            await conn.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $4)",
                USER, ORG, hash_token(token), now, now + timedelta(days=1),
            )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    # The limits are read through rate_limit.get_settings() on every request.
    monkeypatch.setattr(rate_limit, "get_settings", lambda: LIMITS)
    rate_limit.limiter.reset()
    asyncio.run(_seed())
    yield
    rate_limit.limiter.reset()


async def _run(calls: list[tuple[str, str, str | None]]) -> list[int]:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
        sessionmaker = db.build_sessionmaker(engine)

        async def session_dep() -> AsyncIterator[AsyncSession]:
            async with sessionmaker() as session, session.begin():
                yield session

        app.dependency_overrides[db.get_db_session] = session_dep
        statuses = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
            for method, path, token in calls:
                client.cookies.clear()
                kwargs: dict[str, Any] = {"headers": {"Origin": ORIGIN}}
                if token:
                    client.cookies.set(SESSION_COOKIE, token)
                if method == "POST":
                    kwargs["json"] = {"email": "member@acme.test", "password": "wrong-password", "org_slug": "acme"}
                statuses.append((await client.request(method, path, **kwargs)).status_code)
        return statuses
    finally:
        await engine.dispose()


def run(calls: list[tuple[str, str, str | None]]) -> list[int]:
    return asyncio.run(_run(calls))


ME = ("GET", "/api/v1/auth/me", "tok-1")
LOGIN = ("POST", "/api/v1/auth/login", None)


def test_quick_navigation_never_hits_the_login_limit() -> None:
    # 20 page renders within a minute, with the login bucket at 5 / minute.
    assert run([ME] * 20) == [200] * 20


def test_me_does_not_use_up_the_login_bucket() -> None:
    statuses = run([ME] * 20 + [LOGIN] * 6)
    assert statuses[:20] == [200] * 20
    assert 429 not in statuses[20:25]  # all 5 login attempts are still available
    assert statuses[25] == 429  # and brute-force protection still applies


def test_login_brute_force_limit_is_unchanged() -> None:
    statuses = run([LOGIN] * 6)
    assert 429 not in statuses[:5] and statuses[5] == 429


def test_me_has_its_own_limit_per_session() -> None:
    statuses = run([ME] * 21 + [("GET", "/api/v1/auth/me", "tok-2")])
    assert statuses[:20] == [200] * 20
    assert statuses[20] == 429  # this session's own ceiling
    assert statuses[21] == 200  # another session is unaffected


def test_signed_out_me_is_still_401() -> None:
    assert run([("GET", "/api/v1/auth/me", None)]) == [401]
