"""ORG-003: invite (org admin) and validate/accept (public), through the real app and Postgres (RLS on).

Needs TEST_DATABASE_URL (owner, for seeding/inspection) and TEST_APP_DATABASE_URL (app_user).
Invite and OTP emails are captured by overriding their senders.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db
from backend.app.core.config import Settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.services.otp_delivery import get_invite_sender, get_otp_sender
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a3")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000a3")
ADMIN = uuid.UUID("aaaaaaaa-0001-0000-0000-0000000000a3")
MEMBER = uuid.UUID("aaaaaaaa-0002-0000-0000-0000000000a3")
B_ADMIN = uuid.UUID("bbbbbbbb-0001-0000-0000-0000000000a3")
PROVIDER = uuid.UUID("cccccccc-0001-0000-0000-0000000000a3")
TOKENS = {"admin": (ADMIN, ORG_A), "member": (MEMBER, ORG_A), "b_admin": (B_ADMIN, ORG_B),
          "provider": (PROVIDER, None)}
INVALID = "This invite link is invalid or has expired. Ask your administrator to send a new one."
PASSWORD = "a-perfectly-fine-passphrase-42"
NEW = {"email": " New.Person@Acme.TEST ", "role": "org_member", "first_name": " Nia ", "last_name": "Person"}

INVITES: list[tuple[str, str]] = []
OTPS: list[tuple[str, str]] = []


def invites_url(org: uuid.UUID | str = ORG_A, user: uuid.UUID | str | None = None) -> str:
    return f"/api/v1/orgs/{org}/invites" + (f"/{user}/resend" if user is not None else "")


async def _admin(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug, max_users) VALUES ($1, 'Acme Foods', 'acme', 3), "
            "($2, 'Beta', 'beta', 25)", ORG_A, ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, first_name, last_name, role, status) VALUES
              ($1, $2, 'admin@acme.test', 'Ann', 'Admin', 'org_admin', 'active'),
              ($3, $2, 'member@acme.test', 'Meg', 'Member', 'org_member', 'active'),
              ($4, $5, 'admin@beta.test', 'Ben', 'Beta', 'org_admin', 'active'),
              ($6, NULL, 'ops@sustentra.test', 'Op', 'S', 'provider_admin', 'active')
            """,
            ADMIN, ORG_A, MEMBER, B_ADMIN, ORG_B, PROVIDER,
        )
        # Deleted users (COMP-001) hold no seat.
        await conn.execute("INSERT INTO users (org_id, email, role, status) VALUES "
                           "($1, 'deleted_1@deleted', 'org_member', 'deleted')", ORG_A)
        now = datetime.now(UTC)
        for token, (user_id, org_id) in TOKENS.items():
            await conn.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $4)",
                user_id, org_id, hash_token(token), now, now + timedelta(days=1),
            )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    INVITES.clear()
    OTPS.clear()
    asyncio.run(_seed())


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    app.dependency_overrides[get_invite_sender] = lambda: (lambda to, link: INVITES.append((to, link)))
    app.dependency_overrides[get_otp_sender] = lambda: (lambda to, code: OTPS.append((to, code)))
    return app


def run(scenario: Callable[[Any], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            transport = httpx.ASGITransport(app=_app(engine))
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                         headers={"Origin": ORIGIN}) as client:
                return await scenario(client)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def call(method: str, path: str, token: str | None = "admin", body: Any = None, params: Any = None) -> Any:
    async def scenario(client: Any) -> Any:
        if token:
            client.cookies.set(SESSION_COOKIE, token)
        return await client.request(method, path, json=body, params=params)

    return run(scenario)


def admin(sql: str, *args: Any) -> list[Any]:
    return asyncio.run(_admin(sql, *args))


def events() -> list[str]:
    return [r["event_type"] for r in admin("SELECT event_type FROM audit_logs ORDER BY created_at, event_type")]


def token_from(link: str) -> str:
    assert urlparse(link).path == "/invite/accept"
    return parse_qs(urlparse(link).query)["token"][0]


def invite(body: dict[str, Any] | None = None, as_: str = "admin") -> tuple[Any, str]:
    response = call("POST", invites_url(), as_, body or NEW)
    assert response.status_code == 201, response.text
    return response.json(), token_from(INVITES[-1][1])


# --- create ------------------------------------------------------------------------

def test_invite_creates_an_invited_user_and_emails_a_24h_link() -> None:
    body, token = invite()
    assert (body["email"], body["first_name"], body["last_name"], body["role"], body["status"]) == (
        "new.person@acme.test", "Nia", "Person", "org_member", "invited")
    assert body["id"] == body["user_id"] and body["org_id"] == str(ORG_A)
    assert INVITES[-1][0] == "new.person@acme.test"

    [user] = admin("SELECT status, password_hash, invited_by, full_name FROM users WHERE id = $1",
                   uuid.UUID(body["id"]))
    assert (user["status"], user["password_hash"], user["invited_by"], user["full_name"]) == (
        "invited", None, ADMIN, "Nia Person")
    [row] = admin("SELECT type, expires_at - created_at AS ttl, consumed_at FROM auth_tokens WHERE token_hash = $1",
                  hash_token(token))
    assert (row["type"], row["ttl"], row["consumed_at"]) == ("invite", timedelta(hours=24), None)
    assert events() == ["user_invited"]


def test_provider_admin_can_invite_into_any_org() -> None:
    response = call("POST", invites_url(ORG_B), "provider", {**NEW, "role": "org_admin"})
    assert response.status_code == 201
    assert admin("SELECT invited_by FROM users WHERE email = 'new.person@acme.test'")[0]["invited_by"] == PROVIDER


def test_member_gets_403_and_other_orgs_admin_gets_404() -> None:
    assert call("POST", invites_url(), "member", NEW).status_code == 403
    assert call("POST", invites_url(), "b_admin", NEW).status_code == 404
    assert call("POST", invites_url(), None, NEW).status_code == 401
    assert call("POST", invites_url(uuid.uuid4()), "provider", NEW).status_code == 404
    assert INVITES == [] and events() == []


def test_duplicate_email_in_the_org_is_409() -> None:
    response = call("POST", invites_url(), body={**NEW, "email": "MEMBER@acme.test"})
    assert response.status_code == 409
    invite()
    assert call("POST", invites_url(), body=NEW).status_code == 409  # already invited
    # The same email in another org is fine.
    assert call("POST", invites_url(ORG_B), "b_admin", NEW).status_code == 201


def test_seat_limit_is_422() -> None:
    invite()  # 3 of 3 seats now (admin, member, invitee; the deleted user does not count)
    response = call("POST", invites_url(), body={**NEW, "email": "fourth@acme.test"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("All 3 seats are in use")
    assert admin("SELECT count(*) AS n FROM users WHERE email = 'fourth@acme.test'")[0]["n"] == 0


def test_two_invites_racing_for_the_last_seat() -> None:
    admin("UPDATE organizations SET max_users = 3 WHERE id = $1", ORG_A)

    async def both(client: Any) -> list[Any]:
        client.cookies.set(SESSION_COOKIE, "admin")
        return list(await asyncio.gather(
            client.post(invites_url(), json={**NEW, "email": "one@acme.test"}),
            client.post(invites_url(), json={**NEW, "email": "two@acme.test"}),
        ))

    codes = sorted(r.status_code for r in run(both))
    assert codes == [201, 422]


@pytest.mark.parametrize("body", [
    {**NEW, "email": "nope"},
    {**NEW, "role": "provider_admin"},
    {**NEW, "first_name": "  "},
    {"email": "x@y.test", "role": "org_member", "first_name": "X"},
    {**NEW, "status": "active"},
])
def test_invite_validation(body: dict[str, Any]) -> None:
    assert call("POST", invites_url(), body=body).status_code == 422
    assert INVITES == []


# --- resend ------------------------------------------------------------------------

def test_resend_invalidates_the_old_link() -> None:
    body, old = invite()
    response = call("POST", invites_url(user=body["id"]))
    assert response.status_code == 200, response.text
    new = token_from(INVITES[-1][1])
    assert new != old
    assert call("GET", "/api/v1/auth/invite/validate", None, params={"token": old}).status_code == 400
    assert call("GET", "/api/v1/auth/invite/validate", None, params={"token": new}).status_code == 200
    assert sorted(events()) == ["user_invite_resent", "user_invited"]


def test_resend_only_for_invited_users() -> None:
    response = call("POST", invites_url(user=MEMBER))
    assert response.status_code == 409
    assert call("POST", invites_url(user=uuid.uuid4())).status_code == 404
    assert call("POST", invites_url(user="nope")).status_code == 404
    assert call("POST", invites_url(user=B_ADMIN)).status_code == 404  # other org's user
    assert call("POST", invites_url(ORG_B, MEMBER), "b_admin").status_code == 404
    assert INVITES == []


# --- validate ----------------------------------------------------------------------

def test_validate_returns_what_the_accept_page_needs() -> None:
    _, token = invite()
    response = call("GET", "/api/v1/auth/invite/validate", None, params={"token": token})
    assert response.status_code == 200
    assert response.json() == {"email": "new.person@acme.test", "first_name": "Nia", "last_name": "Person",
                               "org_name": "Acme Foods", "org_slug": "acme"}


def _break(how: str, token: str) -> None:
    if how == "expired":
        admin("UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE token_hash = $1",
              hash_token(token))
    elif how == "used":
        admin("UPDATE auth_tokens SET consumed_at = now() WHERE token_hash = $1", hash_token(token))
    elif how == "user_suspended":
        admin("UPDATE users SET status = 'suspended' WHERE email = 'new.person@acme.test'")
    elif how == "org_suspended":
        admin("UPDATE organizations SET status = 'suspended' WHERE id = $1", ORG_A)
    elif how == "reset_token":  # a password-reset token is not an invite token
        admin("UPDATE auth_tokens SET type = 'password_reset' WHERE token_hash = $1", hash_token(token))


@pytest.mark.parametrize("how", ["unknown", "expired", "used", "user_suspended", "org_suspended", "reset_token"])
def test_every_unusable_token_gets_the_same_400(how: str) -> None:
    _, token = invite()
    _break(how, token)
    if how == "unknown":
        token = "not-a-real-token"
    validate = call("GET", "/api/v1/auth/invite/validate", None, params={"token": token})
    accept = call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": PASSWORD})
    for response in (validate, accept):
        assert response.status_code == 400
        assert response.json() == {"detail": INVALID}
    assert admin("SELECT password_hash FROM users WHERE email = 'new.person@acme.test'")[0]["password_hash"] is None


# --- accept ------------------------------------------------------------------------

def test_accept_activates_and_the_user_can_then_log_in_with_otp() -> None:
    body, token = invite()
    response = call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": PASSWORD})
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert (accepted["user_id"], accepted["org_slug"], accepted["email"]) == (body["id"], "acme",
                                                                           "new.person@acme.test")
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")  # no session
    [user] = admin("SELECT status, password_hash FROM users WHERE id = $1", uuid.UUID(body["id"]))
    assert user["status"] == "active" and user["password_hash"]
    assert sorted(events()) == ["invite_accepted", "user_invited"]
    [row] = admin("SELECT actor_user_id, org_id FROM audit_logs WHERE event_type = 'invite_accepted'")
    assert (row["actor_user_id"], row["org_id"]) == (uuid.UUID(body["id"]), ORG_A)

    async def login(client: Any) -> Any:
        first = await client.post("/api/v1/auth/login", json={"email": "new.person@acme.test",
                                                               "password": PASSWORD, "org_slug": "acme"})
        assert first.status_code == 200, first.text
        second = await client.post("/api/v1/auth/login/verify",
                                   json={"challenge_id": first.json()["challenge_id"], "code": OTPS[-1][1]})
        assert second.status_code == 200, second.text
        return await client.get("/api/v1/auth/me")

    me = run(login)
    assert me.status_code == 200 and me.json()["email"] == "new.person@acme.test"


def test_a_used_link_cannot_be_used_again() -> None:
    _, token = invite()
    assert call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": PASSWORD}).status_code == 200
    again = call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": "another-passphrase-99"})
    assert again.status_code == 400 and again.json() == {"detail": INVALID}


def test_a_weak_password_is_422_and_the_link_still_works() -> None:
    _, token = invite()
    weak = call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["violations"]
    assert admin("SELECT status FROM users WHERE email = 'new.person@acme.test'")[0]["status"] == "invited"
    same_as_email = call("POST", "/api/v1/auth/invite/accept", None,
                         {"token": token, "password": "new.person@acme.test"})
    assert same_as_email.status_code == 422
    assert call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": PASSWORD}).status_code == 200


def test_accepting_an_older_link_after_a_resend_fails_and_the_new_one_works() -> None:
    body, old = invite()
    call("POST", invites_url(user=body["id"]))
    new = token_from(INVITES[-1][1])
    assert call("POST", "/api/v1/auth/invite/accept", None, {"token": old, "password": PASSWORD}).status_code == 400
    assert call("POST", "/api/v1/auth/invite/accept", None, {"token": new, "password": PASSWORD}).status_code == 200


def test_org_created_with_an_initial_admin_uses_the_same_invite_flow() -> None:
    response = call("POST", "/api/v1/provider/orgs", "provider", {
        "name": "Gamma", "slug": "gamma",
        "initial_admin": {"email": "first@gamma.test", "first_name": "Gil", "last_name": "First"}})
    assert response.status_code == 201, response.text
    token = token_from(INVITES[-1][1])
    assert admin("SELECT invited_by FROM users WHERE email = 'first@gamma.test'")[0]["invited_by"] == PROVIDER
    details = call("GET", "/api/v1/auth/invite/validate", None, params={"token": token}).json()
    assert (details["org_name"], details["org_slug"], details["first_name"]) == ("Gamma", "gamma", "Gil")
    assert call("POST", "/api/v1/auth/invite/accept", None, {"token": token, "password": PASSWORD}).status_code == 200
