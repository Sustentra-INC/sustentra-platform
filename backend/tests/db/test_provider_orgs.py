"""ORG-001: provider-admin organization endpoints, through the real app and Postgres (RLS on).

Needs TEST_DATABASE_URL (owner, for seeding/inspection) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
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
from backend.app.services.otp_delivery import get_invite_sender
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000f1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000f1")
A_ADMIN = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000f1")
A_MEMBER = uuid.UUID("aaaaaaaa-2222-0000-0000-0000000000f1")
B_MEMBER = uuid.UUID("bbbbbbbb-2222-0000-0000-0000000000f1")
PROVIDER = uuid.UUID("cccccccc-3333-0000-0000-0000000000f1")
TOKENS = {"a_admin": (A_ADMIN, ORG_A), "a_admin_2": (A_ADMIN, ORG_A), "a_member": (A_MEMBER, ORG_A),
          "b_member": (B_MEMBER, ORG_B), "provider": (PROVIDER, None)}
BASE = "/api/v1/provider/orgs"

SENT: list[tuple[str, str]] = []


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
            "INSERT INTO organizations (id, name, slug, created_at) VALUES "
            "($1, 'Acme Foods', 'acme', now() - interval '1 day'), ($2, 'Beta_Corp', 'beta', now())",
            ORG_A, ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, role, status) VALUES
              ($1, $2, 'admin@acme.test', 'org_admin', 'active'),
              ($3, $2, 'member@acme.test', 'org_member', 'active'),
              ($4, $5, 'member@beta.test', 'org_member', 'active'),
              ($6, NULL, 'ops@sustentra.test', 'provider_admin', 'active')
            """,
            A_ADMIN, ORG_A, A_MEMBER, B_MEMBER, ORG_B, PROVIDER,
        )
        # A deleted user does not take a seat.
        await conn.execute(
            "INSERT INTO users (org_id, email, role, status) VALUES ($1, 'gone@acme.test', 'org_member', 'deleted')",
            ORG_A,
        )
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
    SENT.clear()
    asyncio.run(_seed())


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    app.dependency_overrides[get_invite_sender] = lambda: (lambda to, link: SENT.append((to, link)))
    return app


async def _call(method: str, path: str, token: str | None, body: Any = None, params: Any = None) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        transport = httpx.ASGITransport(app=_app(engine))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            cookies = {SESSION_COOKIE: token} if token else None
            return await client.request(method, path, cookies=cookies, json=body, params=params,
                                        headers={"Origin": ORIGIN})
    finally:
        await engine.dispose()


def call(method: str, path: str, token: str | None = "provider", body: Any = None, params: Any = None) -> Any:
    return asyncio.run(_call(method, path, token, body, params))


def admin(sql: str, *args: Any) -> list[Any]:
    return asyncio.run(_admin(sql, *args))


def events() -> list[str]:
    return [r["event_type"] for r in admin("SELECT event_type FROM audit_logs ORDER BY created_at, event_type")]


# --- access ------------------------------------------------------------------------

ENDPOINTS = [
    ("GET", BASE, None),
    ("POST", BASE, {"name": "New", "slug": "new-org"}),
    ("GET", f"{BASE}/{ORG_A}", None),
    ("PATCH", f"{BASE}/{ORG_A}", {"name": "X"}),
    ("POST", f"{BASE}/{ORG_A}/suspend", None),
    ("POST", f"{BASE}/{ORG_A}/activate", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
@pytest.mark.parametrize("token", ["a_admin", "a_member", "b_member"])
def test_org_users_get_403_on_every_endpoint(token: str, method: str, path: str, body: Any) -> None:
    assert call(method, path, token, body).status_code == 403
    assert admin("SELECT status FROM organizations WHERE id = $1", ORG_A)[0]["status"] == "active"
    assert admin("SELECT count(*) AS n FROM organizations")[0]["n"] == 2


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_anonymous_gets_401(method: str, path: str, body: Any) -> None:
    assert call(method, path, None, body).status_code == 401


# --- list / get --------------------------------------------------------------------

def test_list_is_flat_paginated_newest_first_with_seat_counts() -> None:
    response = call("GET", BASE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (2, 1, 20)
    assert [o["slug"] for o in body["items"]] == ["beta", "acme"]
    acme = body["items"][1]
    assert acme["user_count"] == 2  # the deleted user is not counted
    assert acme["max_users"] == 25 and acme["status"] == "active"

    page2 = call("GET", BASE, params={"page": 2, "page_size": 1}).json()
    assert page2["total"] == 2 and [o["slug"] for o in page2["items"]] == ["acme"]


def test_list_search_and_status_filter() -> None:
    assert [o["slug"] for o in call("GET", BASE, params={"search": "ACME"}).json()["items"]] == ["acme"]
    assert [o["slug"] for o in call("GET", BASE, params={"search": "foods"}).json()["items"]] == ["acme"]
    # LIKE wildcards are matched literally.
    assert [o["slug"] for o in call("GET", BASE, params={"search": "_"}).json()["items"]] == ["beta"]
    assert call("GET", BASE, params={"search": "%"}).json()["total"] == 0
    call("POST", f"{BASE}/{ORG_B}/suspend")
    assert [o["slug"] for o in call("GET", BASE, params={"status": "suspended"}).json()["items"]] == ["beta"]
    assert call("GET", BASE, params={"status": "bogus"}).status_code == 422


def test_get_one_and_404() -> None:
    response = call("GET", f"{BASE}/{ORG_A}")
    assert response.status_code == 200 and response.json()["name"] == "Acme Foods"
    missing = call("GET", f"{BASE}/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.json()["detail"] == "Organization not found"
    assert call("GET", f"{BASE}/not-a-uuid").status_code == 422


# --- create ------------------------------------------------------------------------

def test_create_without_admin() -> None:
    response = call("POST", BASE, body={"name": "  Gamma  ", "slug": "gamma"})
    assert response.status_code == 201, response.text
    org = response.json()
    assert (org["name"], org["slug"], org["status"], org["max_users"], org["user_count"]) == (
        "Gamma", "gamma", "active", 25, 0)
    assert SENT == []
    assert events() == ["org_created"]


def test_create_with_initial_admin_invites_them() -> None:
    body = {"name": "Delta", "slug": "delta-co", "max_users": 5,
            "initial_admin": {"email": " Jane@Delta.TEST ", "first_name": "Jane", "last_name": "Doe"}}
    response = call("POST", BASE, body=body)
    assert response.status_code == 201, response.text
    org = response.json()
    assert org["max_users"] == 5 and org["user_count"] == 1

    user = admin("SELECT id, email, role, status, first_name, last_name, full_name, password_hash "
                 "FROM users WHERE org_id = $1", uuid.UUID(org["id"]))
    assert len(user) == 1
    u = user[0]
    assert (u["email"], u["role"], u["status"], u["full_name"]) == ("jane@delta.test", "org_admin", "invited",
                                                                    "Jane Doe")
    assert u["password_hash"] is None

    [(to, link)] = SENT
    assert to == "jane@delta.test"
    assert urlparse(link).path == "/invite/accept"
    raw = parse_qs(urlparse(link).query)["token"][0]
    token = admin("SELECT type, user_id, org_id, expires_at - created_at AS ttl, consumed_at FROM auth_tokens "
                  "WHERE token_hash = $1", hash_token(raw))
    assert len(token) == 1
    t = token[0]
    assert (t["type"], t["user_id"], str(t["org_id"]), t["consumed_at"]) == ("invite", u["id"], org["id"], None)
    assert t["ttl"] == timedelta(hours=24)
    assert events() == ["org_created", "user_invited"]


def test_duplicate_slug_is_409_and_writes_nothing() -> None:
    response = call("POST", BASE, body={"name": "Acme again", "slug": "acme",
                                        "initial_admin": {"email": "x@y.test", "first_name": "X", "last_name": "Y"}})
    assert response.status_code == 409
    assert response.json()["detail"] == "An organization with this slug already exists"
    assert admin("SELECT count(*) AS n FROM organizations")[0]["n"] == 2
    assert SENT == [] and events() == []


@pytest.mark.parametrize("bad_admin", [
    {"email": "not-an-email", "first_name": "A", "last_name": "B"},
    {"email": "a@b.test", "first_name": "   ", "last_name": "B"},
    {"email": "a@b.test", "first_name": "A"},
])
def test_invalid_initial_admin_creates_no_org(bad_admin: dict[str, str]) -> None:
    response = call("POST", BASE, body={"name": "Eps", "slug": "eps", "initial_admin": bad_admin})
    assert response.status_code == 422
    assert admin("SELECT count(*) AS n FROM organizations WHERE slug = 'eps'")[0]["n"] == 0
    assert admin("SELECT count(*) AS n FROM users")[0]["n"] == 5
    assert SENT == [] and events() == []


@pytest.mark.parametrize("body", [
    {"name": "X", "slug": "ab"},  # too short
    {"name": "X", "slug": "Upper"},
    {"name": "X", "slug": "has space"},
    {"name": "", "slug": "fine"},
    {"name": "   ", "slug": "fine"},
    {"name": "X", "slug": "fine", "max_users": 0},
    {"name": "X", "slug": "fine", "max_users": 10001},
    {"name": "X", "slug": "fine", "status": "suspended"},
])
def test_create_validation(body: dict[str, Any]) -> None:
    assert call("POST", BASE, body=body).status_code == 422
    assert admin("SELECT count(*) AS n FROM organizations")[0]["n"] == 2


def test_a_failure_after_the_org_insert_rolls_everything_back() -> None:
    # Force the initial-admin INSERT to fail after the org row and its audit event are written.
    admin("ALTER TABLE users ADD CONSTRAINT ck_test_boom CHECK (email <> 'boom@x.test')")
    try:
        # ASGITransport re-raises the app's unhandled DB error (a real client sees a 500).
        with pytest.raises(Exception, match="ck_test_boom"):
            call("POST", BASE, body={"name": "Zeta", "slug": "zeta", "initial_admin": {
                "email": "boom@x.test", "first_name": "B", "last_name": "C"}})
    finally:
        admin("ALTER TABLE users DROP CONSTRAINT ck_test_boom")
    assert admin("SELECT count(*) AS n FROM organizations WHERE slug = 'zeta'")[0]["n"] == 0
    assert SENT == [] and events() == []


# --- update ------------------------------------------------------------------------

def test_update_name_and_seats() -> None:
    response = call("PATCH", f"{BASE}/{ORG_A}", body={"name": "Acme Holdings", "max_users": 1})
    assert response.status_code == 200, response.text
    org = response.json()
    # Lowering below the current seat count is allowed; it only blocks new seats.
    assert (org["name"], org["max_users"], org["user_count"], org["slug"]) == ("Acme Holdings", 1, 2, "acme")
    [row] = admin("SELECT metadata FROM audit_logs WHERE event_type = 'org_updated'")
    assert '"fields": ["max_users", "name"]' in row["metadata"]


def test_update_cannot_change_slug_or_status() -> None:
    assert call("PATCH", f"{BASE}/{ORG_A}", body={"slug": "new-slug"}).status_code == 422
    assert call("PATCH", f"{BASE}/{ORG_A}", body={"status": "suspended"}).status_code == 422
    assert call("PATCH", f"{BASE}/{ORG_A}", body={"max_users": 0}).status_code == 422
    assert admin("SELECT slug, status FROM organizations WHERE id = $1", ORG_A)[0]["slug"] == "acme"


def test_empty_update_is_a_no_op() -> None:
    response = call("PATCH", f"{BASE}/{ORG_A}", body={})
    assert response.status_code == 200 and response.json()["name"] == "Acme Foods"
    assert events() == []


def test_update_unknown_org_is_404() -> None:
    assert call("PATCH", f"{BASE}/{uuid.uuid4()}", body={"name": "X"}).status_code == 404


# --- suspend / activate ------------------------------------------------------------

def test_suspend_revokes_every_session_of_the_org_immediately() -> None:
    assert call("GET", "/api/v1/auth/me", "a_admin").status_code == 200
    response = call("POST", f"{BASE}/{ORG_A}/suspend")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"

    remaining = {r["user_id"] for r in admin("SELECT user_id FROM sessions")}
    assert remaining == {B_MEMBER, PROVIDER}
    for token in ("a_admin", "a_admin_2", "a_member"):
        assert call("GET", "/api/v1/auth/me", token).status_code == 401
    assert call("GET", "/api/v1/auth/me", "b_member").status_code == 200

    [row] = admin("SELECT org_id, actor_user_id, metadata FROM audit_logs WHERE event_type = 'org_suspended'")
    assert row["org_id"] == ORG_A and row["actor_user_id"] == PROVIDER
    assert '"sessions_revoked": 3' in row["metadata"]


def test_suspend_and_activate_are_idempotent() -> None:
    assert call("POST", f"{BASE}/{ORG_A}/suspend").json()["status"] == "suspended"
    assert call("POST", f"{BASE}/{ORG_A}/suspend").json()["status"] == "suspended"
    assert call("POST", f"{BASE}/{ORG_A}/activate").json()["status"] == "active"
    assert call("POST", f"{BASE}/{ORG_A}/activate").json()["status"] == "active"
    assert events() == ["org_suspended", "org_activated"]
    # Revoked sessions stay revoked after re-activation.
    assert call("GET", "/api/v1/auth/me", "a_admin").status_code == 401


def test_suspend_unknown_org_is_404() -> None:
    assert call("POST", f"{BASE}/{uuid.uuid4()}/suspend").status_code == 404
    assert call("POST", f"{BASE}/{uuid.uuid4()}/activate").status_code == 404
