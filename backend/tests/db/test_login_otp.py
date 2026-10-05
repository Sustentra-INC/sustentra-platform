"""AUTH-005 integration tests: password + email OTP login through the real app.

Needs TEST_DATABASE_URL (owner, seeding) and TEST_APP_DATABASE_URL (app_user).
The OTP email is captured by overriding get_otp_sender ("mocked email").
Time is moved by monkeypatching backend.app.services.login.utcnow.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db
from backend.app.core.config import Settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_password
from backend.app.main import create_app
from backend.app.services import login as login_service
from backend.app.services.otp_delivery import get_otp_sender
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
HEADERS = {"Origin": ORIGIN}
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000e1")
ALICE = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000e1")
SUSPENDED = uuid.UUID("aaaaaaaa-2222-0000-0000-0000000000e1")
PROVIDER = uuid.UUID("cccccccc-3333-0000-0000-0000000000e1")
PASSWORD = "violet tractor sings at dawn"
_HASH = hash_password(PASSWORD)  # computed once (bcrypt cost 12)


async def _admin(sql: str, *args: Any) -> list[Any]:
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
            INSERT INTO users (id, org_id, email, role, password_hash, status) VALUES
              ($1, $2, 'alice@acme.test', 'org_admin', $5, 'active'),
              ($3, $2, 'sam@acme.test', 'org_member', $5, 'suspended'),
              ($4, NULL, 'ops@sustentra.test', 'provider_admin', $5, 'active')
            """,
            ALICE, ORG, SUSPENDED, PROVIDER, _HASH,
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    asyncio.run(_seed())


class Clock:
    """Moves login_service.utcnow forward."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.offset = timedelta()
        monkeypatch.setattr(login_service, "utcnow", lambda: datetime.now(UTC) + self.offset)

    def advance(self, delta: timedelta) -> None:
        self.offset += delta


Scenario = Callable[[Any, list[tuple[str, str]]], Awaitable[None]]


def run(scenario: Scenario) -> list[tuple[str, str]]:
    """Run a scenario against one app + one engine; returns captured (email, code)."""
    sent: list[tuple[str, str]] = []

    async def main() -> None:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
        sessionmaker = db.build_sessionmaker(engine)

        async def session_dep() -> AsyncIterator[AsyncSession]:
            async with sessionmaker() as session, session.begin():
                yield session

        app.dependency_overrides[db.get_db_session] = session_dep
        app.dependency_overrides[get_otp_sender] = lambda: (lambda to, code: sent.append((to, code)))
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
                await scenario(client, sent)
        finally:
            await engine.dispose()

    asyncio.run(main())
    return sent


async def login(client: Any, email: str = "alice@acme.test", password: str = PASSWORD,
                org_slug: str | None = "acme") -> Any:
    body: dict[str, Any] = {"email": email, "password": password}
    if org_slug is not None:
        body["org_slug"] = org_slug
    return await client.post("/api/v1/auth/login", json=body, headers=HEADERS)


async def verify(client: Any, challenge_id: str, code: str) -> Any:
    return await client.post("/api/v1/auth/login/verify", json={"challenge_id": challenge_id, "code": code},
                             headers=HEADERS)


async def resend(client: Any, challenge_id: str) -> Any:
    return await client.post("/api/v1/auth/login/resend", json={"challenge_id": challenge_id}, headers=HEADERS)


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# --- happy path ---------------------------------------------------------------------

def test_full_happy_path_login_otp_verify_then_me() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        first = await login(client)
        assert first.status_code == 200
        assert first.json()["expires_in"] == 600
        assert SESSION_COOKIE not in first.headers.get("set-cookie", "")  # no cookie after password step
        assert sent and sent[-1][0] == "alice@acme.test"

        second = await verify(client, first.json()["challenge_id"], sent[-1][1])
        assert second.status_code == 200
        assert second.json() == {"user_id": str(ALICE), "org_id": str(ORG), "role": "org_admin"}
        assert SESSION_COOKIE in second.headers["set-cookie"]

        me = await client.get("/api/v1/auth/me", headers=HEADERS)  # cookie jar carries the session
        assert me.status_code == 200 and me.json()["email"] == "alice@acme.test"

    run(scenario)
    [user] = asyncio.run(_admin("SELECT failed_login_count, last_login_at FROM users WHERE id = $1", ALICE))
    assert user["failed_login_count"] == 0 and user["last_login_at"] is not None


def test_provider_admin_logs_in_without_org_slug() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        first = await login(client, "ops@sustentra.test", org_slug=None)
        assert first.status_code == 200
        second = await verify(client, first.json()["challenge_id"], sent[-1][1])
        assert second.json()["role"] == "provider_admin" and second.json()["org_id"] is None

    run(scenario)


# --- password step failures -----------------------------------------------------------

def test_failures_look_identical_and_wrong_password_counts() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        wrong = await login(client, password="not the password at all")
        unknown_user = await login(client, email="nobody@acme.test")
        unknown_org = await login(client, org_slug="no-such-org")
        no_org_provider = await login(client, email="alice@acme.test", org_slug=None)
        for response in (wrong, unknown_user, unknown_org, no_org_provider):
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid credentials"}
        assert sent == []

    run(scenario)
    [row] = asyncio.run(_admin("SELECT failed_login_count FROM users WHERE id = $1", ALICE))
    assert row["failed_login_count"] == 1


def test_five_failures_lock_then_correct_password_gets_429_until_unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)

    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        for _ in range(5):
            assert (await login(client, password="wrong wrong wrong")).status_code == 401
        locked = await login(client)  # correct password
        assert locked.status_code == 429
        assert 0 < int(locked.headers["Retry-After"]) <= 15 * 60

        clock.advance(timedelta(minutes=15, seconds=5))
        assert (await login(client)).status_code == 200

    run(scenario)
    events = [r["event_type"] for r in asyncio.run(_admin("SELECT event_type FROM audit_logs ORDER BY created_at"))]
    assert events.count("account_locked") == 1


def test_suspended_user_or_org_cannot_log_in() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        assert (await login(client, email="sam@acme.test")).status_code == 401

    run(scenario)
    asyncio.run(_admin("UPDATE organizations SET status = 'suspended' WHERE id = $1", ORG))

    async def scenario_org(client: Any, sent: list[tuple[str, str]]) -> None:
        response = await login(client)
        assert response.status_code == 401 and response.json() == {"detail": "Invalid credentials"}

    run(scenario_org)


# --- OTP step -----------------------------------------------------------------------

def test_three_wrong_codes_kill_the_challenge() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        challenge = (await login(client)).json()["challenge_id"]
        code = sent[-1][1]
        for _ in range(3):
            assert (await verify(client, challenge, _wrong(code))).status_code == 401
        assert (await verify(client, challenge, code)).status_code == 401  # correct, but too late

    run(scenario)
    [row] = asyncio.run(_admin("SELECT failed_login_count FROM users WHERE id = $1", ALICE))
    assert row["failed_login_count"] == 1  # the exhausted challenge counts as one failed login


def test_reused_and_expired_codes_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)

    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        challenge = (await login(client)).json()["challenge_id"]
        code = sent[-1][1]
        assert (await verify(client, challenge, code)).status_code == 200
        assert (await verify(client, challenge, code)).status_code == 401  # reused

        challenge = (await login(client)).json()["challenge_id"]
        code = sent[-1][1]
        clock.advance(timedelta(minutes=10, seconds=1))
        assert (await verify(client, challenge, code)).status_code == 401  # expired

    run(scenario)


def test_new_login_invalidates_earlier_unused_code() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        first = (await login(client)).json()["challenge_id"]
        first_code = sent[-1][1]
        await login(client)
        assert (await verify(client, first, first_code)).status_code == 401

    run(scenario)


# --- resend -------------------------------------------------------------------------

def test_resend_cooldown_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(monkeypatch)

    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        challenge = (await login(client)).json()["challenge_id"]
        original = sent[-1][1]

        assert (await resend(client, challenge)).status_code == 429  # within 60 s

        for _ in range(3):
            clock.advance(timedelta(seconds=61))
            assert (await resend(client, challenge)).status_code == 202
        clock.advance(timedelta(seconds=61))
        assert (await resend(client, challenge)).status_code == 429  # 4th resend refused

        latest = sent[-1][1]
        assert len(sent) == 4
        if latest != original:
            assert (await verify(client, challenge, original)).status_code == 401  # old code invalid
        assert (await verify(client, challenge, latest)).status_code == 200

    run(scenario)


def test_resend_for_unknown_challenge_is_202() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        assert (await resend(client, str(uuid.uuid4()))).status_code == 202
        assert (await resend(client, "not-a-uuid")).status_code == 202
        assert sent == []

    run(scenario)


# --- audit + purge ------------------------------------------------------------------

def test_audit_events_never_contain_codes_or_passwords() -> None:
    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        await login(client, password="wrong wrong wrong")
        challenge = (await login(client)).json()["challenge_id"]
        await verify(client, challenge, _wrong(sent[-1][1]))
        await verify(client, challenge, sent[-1][1])

    sent = run(scenario)
    rows = asyncio.run(_admin("SELECT event_type, metadata::text AS meta FROM audit_logs"))
    events = {r["event_type"] for r in rows}
    assert {"login_fail", "login_password_ok", "otp_fail", "login_success"} <= events
    blob = " ".join(r["meta"] for r in rows)
    assert PASSWORD not in blob and "wrong wrong wrong" not in blob
    for _, code in sent:
        assert code not in blob


def test_successful_login_purges_long_expired_rows() -> None:
    asyncio.run(_admin(
        "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at) "
        "VALUES ($1, $2, 'stale', now() - interval '10 days', now() - interval '3 days')",
        ALICE, ORG,
    ))

    async def scenario(client: Any, sent: list[tuple[str, str]]) -> None:
        challenge = (await login(client)).json()["challenge_id"]
        assert (await verify(client, challenge, sent[-1][1])).status_code == 200

    run(scenario)
    assert asyncio.run(_admin("SELECT 1 FROM sessions WHERE token_hash = 'stale'")) == []
