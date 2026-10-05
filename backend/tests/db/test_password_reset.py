"""AUTH-006 integration tests: password reset through the real app.

TEST_DATABASE_URL (owner, seeding) and TEST_APP_DATABASE_URL (app_user).
Reset links and OTP codes are captured by overriding the email senders.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db
from backend.app.core.config import Settings, get_settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import VIOLATION_TOO_SHORT, hash_password, hash_token
from backend.app.main import create_app
from backend.app.services import password_reset as reset_service
from backend.app.services.otp_delivery import get_otp_sender, get_reset_sender
from backend.app.services.password_reset import REQUEST_ACCEPTED_MESSAGE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
HEADERS = {"Origin": ORIGIN}
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000f1")
ALICE = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000f1")
PROVIDER = uuid.UUID("cccccccc-3333-0000-0000-0000000000f1")
OLD_PASSWORD = "violet tractor sings at dawn"
NEW_PASSWORD = "copper lantern over quiet harbour"
_OLD_HASH = hash_password(OLD_PASSWORD)


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
            "INSERT INTO users (id, org_id, email, role, password_hash) VALUES "
            "($1, $2, 'alice@acme.test', 'org_admin', $4), "
            "($3, NULL, 'ops@sustentra.test', 'provider_admin', $4)",
            ALICE, ORG, PROVIDER, _OLD_HASH,
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter.reset()
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.sustentra.test")
    get_settings.cache_clear()
    asyncio.run(_seed())
    yield
    get_settings.cache_clear()


class Mailbox:
    def __init__(self) -> None:
        self.links: list[tuple[str, str]] = []
        self.codes: list[tuple[str, str]] = []

    def token(self, index: int = -1) -> str:
        return parse_qs(urlsplit(self.links[index][1]).query)["token"][0]


Scenario = Callable[[Any, Mailbox], Awaitable[None]]


def run(scenario: Scenario) -> Mailbox:
    mailbox = Mailbox()

    async def main() -> None:
        engine = db.create_engine(APP_URL or "", pool_size=3, max_overflow=0)
        sessionmaker = db.build_sessionmaker(engine)
        app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]

        async def session_dep() -> AsyncIterator[AsyncSession]:
            async with sessionmaker() as session, session.begin():
                yield session

        app.dependency_overrides[db.get_db_session] = session_dep
        app.dependency_overrides[db.get_sessionmaker_dependency] = lambda: sessionmaker
        app.dependency_overrides[get_otp_sender] = lambda: (lambda to, code: mailbox.codes.append((to, code)))
        app.dependency_overrides[get_reset_sender] = lambda: (lambda to, link: mailbox.links.append((to, link)))
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
                await scenario(client, mailbox)
        finally:
            await engine.dispose()

    asyncio.run(main())
    return mailbox


async def request_reset(client: Any, email: str = "alice@acme.test", org_slug: str | None = "acme") -> Any:
    body: dict[str, Any] = {"email": email}
    if org_slug:
        body["org_slug"] = org_slug
    return await client.post("/api/v1/auth/password-reset/request", json=body, headers=HEADERS)


async def confirm(client: Any, token: str, password: str = NEW_PASSWORD) -> Any:
    return await client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "password": password},
                             headers=HEADERS)


async def full_login(client: Any, mailbox: Mailbox, password: str) -> int:
    first = await client.post("/api/v1/auth/login",
                              json={"email": "alice@acme.test", "password": password, "org_slug": "acme"},
                              headers=HEADERS)
    if first.status_code != 200:
        return first.status_code
    second = await client.post("/api/v1/auth/login/verify",
                               json={"challenge_id": first.json()["challenge_id"], "code": mailbox.codes[-1][1]},
                               headers=HEADERS)
    return second.status_code


# --- tests --------------------------------------------------------------------------

def test_full_reset_flow_then_new_password_works_with_otp_login() -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        response = await request_reset(client)
        assert response.status_code == 200 and response.json() == {"message": REQUEST_ACCEPTED_MESSAGE}
        assert mailbox.links[-1][0] == "alice@acme.test"
        assert mailbox.links[-1][1].startswith("https://app.sustentra.test/org/acme/reset-password?token=")

        done = await confirm(client, mailbox.token())
        assert done.status_code == 200
        assert "set-cookie" not in done.headers  # reset does not log the user in

        assert await full_login(client, mailbox, OLD_PASSWORD) == 401
        assert await full_login(client, mailbox, NEW_PASSWORD) == 200

    run(scenario)
    [row] = asyncio.run(_admin("SELECT token_hash FROM auth_tokens WHERE type = 'password_reset'"))
    assert "token=" not in row["token_hash"]  # only the SHA-256 hash is stored


def test_unknown_email_gets_identical_response_and_no_email() -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        known = await request_reset(client)
        unknown = await request_reset(client, email="nobody@acme.test")
        unknown_org = await request_reset(client, org_slug="no-such-org")
        for response in (known, unknown, unknown_org):
            assert response.status_code == 200
            assert response.json() == {"message": REQUEST_ACCEPTED_MESSAGE}
        assert len(mailbox.links) == 1

    run(scenario)


def test_provider_admin_link_uses_provider_path() -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        await request_reset(client, email="ops@sustentra.test", org_slug=None)
        assert mailbox.links[-1][1].startswith("https://app.sustentra.test/provider-admin/reset-password?token=")

    run(scenario)


def test_expired_and_reused_tokens_return_400(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        await request_reset(client)
        token = mailbox.token()
        assert (await confirm(client, token)).status_code == 200
        reused = await confirm(client, token, "another fine long passphrase")
        assert reused.status_code == 400

        await request_reset(client)
        expired_token = mailbox.token()
        monkeypatch.setattr(reset_service, "utcnow", lambda: datetime.now(UTC) + timedelta(minutes=16))
        assert (await confirm(client, expired_token)).status_code == 400
        assert (await confirm(client, "made-up-token")).status_code == 400

    run(scenario)


def test_second_request_invalidates_the_first_token() -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        await request_reset(client)
        await request_reset(client)
        assert (await confirm(client, mailbox.token(0))).status_code == 400
        assert (await confirm(client, mailbox.token(1))).status_code == 200

    run(scenario)


def test_weak_password_returns_422_with_violations_and_token_stays_valid() -> None:
    async def scenario(client: Any, mailbox: Mailbox) -> None:
        await request_reset(client)
        weak = await confirm(client, mailbox.token(), "short")
        assert weak.status_code == 422
        assert VIOLATION_TOO_SHORT in weak.json()["violations"]
        assert (await confirm(client, mailbox.token())).status_code == 200

    run(scenario)


def test_reset_revokes_all_sessions_and_clears_lock() -> None:
    now = datetime.now(UTC)
    for name in ("s1", "s2"):
        asyncio.run(_admin(
            "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
            "VALUES ($1, $2, $3, $4, $5, $4)", ALICE, ORG, hash_token(name), now, now + timedelta(days=7),
        ))
    asyncio.run(_admin("UPDATE users SET failed_login_count = 3, locked_until = $2 WHERE id = $1",
                       ALICE, now + timedelta(minutes=10)))

    async def scenario(client: Any, mailbox: Mailbox) -> None:
        await request_reset(client)
        assert (await confirm(client, mailbox.token())).status_code == 200

    run(scenario)
    assert asyncio.run(_admin("SELECT 1 FROM sessions WHERE user_id = $1", ALICE)) == []
    [user] = asyncio.run(_admin("SELECT failed_login_count, locked_until FROM users WHERE id = $1", ALICE))
    assert user["failed_login_count"] == 0 and user["locked_until"] is None
    events = {r["event_type"] for r in asyncio.run(_admin("SELECT event_type FROM audit_logs"))}
    assert {"password_reset_requested", "password_reset"} <= events
