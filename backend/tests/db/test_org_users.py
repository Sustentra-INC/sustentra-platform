"""ORG-002: org-admin user management, through the real app and Postgres (RLS on).

Needs TEST_DATABASE_URL (owner, for seeding/inspection) and TEST_APP_DATABASE_URL (app_user).
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
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a2")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000a2")
A1 = uuid.UUID("aaaaaaaa-0001-0000-0000-0000000000a2")  # org admin (the caller)
A2 = uuid.UUID("aaaaaaaa-0002-0000-0000-0000000000a2")  # second org admin
MEM = uuid.UUID("aaaaaaaa-0003-0000-0000-0000000000a2")  # member with a password
INV = uuid.UUID("aaaaaaaa-0004-0000-0000-0000000000a2")  # invited, no password yet
GONE = uuid.UUID("aaaaaaaa-0005-0000-0000-0000000000a2")  # deleted (COMP-001)
B_ADMIN = uuid.UUID("bbbbbbbb-0001-0000-0000-0000000000a2")
PROVIDER = uuid.UUID("cccccccc-0001-0000-0000-0000000000a2")
TOKENS = {"a1": (A1, ORG_A), "a2": (A2, ORG_A), "mem": (MEM, ORG_A), "mem_2": (MEM, ORG_A),
          "b_admin": (B_ADMIN, ORG_B), "provider": (PROVIDER, None)}


def users_url(org: uuid.UUID | str = ORG_A, user: uuid.UUID | str | None = None, action: str = "") -> str:
    url = f"/api/v1/orgs/{org}/users"
    if user is not None:
        url += f"/{user}"
    return url + (f"/{action}" if action else "")


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
            "INSERT INTO organizations (id, name, slug, max_users) VALUES ($1, 'Acme', 'acme', 10), "
            "($2, 'Beta', 'beta', 25)", ORG_A, ORG_B,
        )
        rows = [
            (A1, ORG_A, "a1@acme.test", "Ann", "Admin", "org_admin", "active", "x", 5),
            (A2, ORG_A, "a2@acme.test", "Bob", "Admin", "org_admin", "active", "x", 4),
            (MEM, ORG_A, "mem@acme.test", "Meg", "Member", "org_member", "active", "x", 3),
            (INV, ORG_A, "inv@acme.test", "Ivy", "Invited", "org_member", "invited", None, 2),
            (GONE, ORG_A, "deleted_x@deleted", "Deleted", "User", "org_member", "deleted", None, 1),
            (B_ADMIN, ORG_B, "admin@beta.test", "Ben", "Beta", "org_admin", "active", "x", 1),
            (PROVIDER, None, "ops@sustentra.test", "Op", "S", "provider_admin", "active", "x", 1),
        ]
        for uid, org, email, first, last, role, status, pw, age in rows:
            await conn.execute(
                "INSERT INTO users (id, org_id, email, first_name, last_name, role, status, password_hash, "
                "created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now() - make_interval(hours => $9))",
                uid, org, email, first, last, role, status, pw, age,
            )
        now = datetime.now(UTC)
        for token, (user_id, org_id) in TOKENS.items():
            await conn.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $4)",
                user_id, org_id, hash_token(token), now, now + timedelta(days=1),
            )
        await conn.execute(
            "INSERT INTO auth_tokens (user_id, org_id, type, token_hash, created_at, expires_at) VALUES "
            "($1, $2, 'password_reset', 'h-mem', now(), now() + interval '1 hour'), "
            "($3, $2, 'invite', 'h-inv', now(), now() + interval '1 day')",
            MEM, ORG_A, INV,
        )
    finally:
        await conn.close()


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


def call(method: str, path: str, token: str | None = "a1", body: Any = None, params: Any = None) -> Any:
    return asyncio.run(_call(method, path, token, body, params))


def admin(sql: str, *args: Any) -> list[Any]:
    return asyncio.run(_admin(sql, *args))


def events() -> list[str]:
    return [r["event_type"] for r in admin("SELECT event_type FROM audit_logs ORDER BY created_at, event_type")]


def audit() -> list[Any]:
    return admin("SELECT event_type, org_id, actor_user_id, target_id, metadata FROM audit_logs "
                 "ORDER BY created_at, event_type")


def status_of(user: uuid.UUID) -> tuple[str, str]:
    row = admin("SELECT role, status FROM users WHERE id = $1", user)[0]
    return row["role"], row["status"]


# --- access ------------------------------------------------------------------------

ENDPOINTS = [
    ("GET", users_url(), None),
    ("GET", users_url(user=MEM), None),
    ("PATCH", users_url(user=MEM), {"role": "org_admin"}),
    ("POST", users_url(user=MEM, action="suspend"), None),
    ("POST", users_url(user=MEM, action="reactivate"), None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_org_member_gets_403(method: str, path: str, body: Any) -> None:
    assert call(method, path, "mem", body).status_code == 403
    assert status_of(MEM) == ("org_member", "active")


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_anonymous_gets_401(method: str, path: str, body: Any) -> None:
    assert call(method, path, None, body).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_another_orgs_admin_gets_404(method: str, path: str, body: Any) -> None:
    response = call(method, path, "b_admin", body)
    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
    assert status_of(MEM) == ("org_member", "active")


def test_an_org_admin_cannot_reach_another_orgs_user_through_their_own_org() -> None:
    # Own org in the path, other org's user id: still 404 (WHERE + RLS).
    assert call("GET", users_url(ORG_A, B_ADMIN)).status_code == 404
    assert call("POST", users_url(ORG_A, B_ADMIN, "suspend")).status_code == 404
    assert status_of(B_ADMIN) == ("org_admin", "active")


@pytest.mark.parametrize("path", [users_url("not-a-uuid"), users_url(user="not-a-uuid"),
                                  users_url(user=uuid.uuid4()), users_url(user=GONE)])
def test_unknown_ids_are_404(path: str) -> None:
    assert call("GET", path, "provider").status_code == 404


def test_provider_admin_can_use_every_endpoint_for_any_org() -> None:
    assert call("GET", users_url(ORG_B), "provider").json()["total"] == 1
    assert call("GET", users_url(ORG_A, MEM), "provider").status_code == 200
    assert call("PATCH", users_url(ORG_A, MEM), "provider", {"role": "org_admin"}).json()["role"] == "org_admin"
    assert call("POST", users_url(ORG_A, MEM, "suspend"), "provider").json()["status"] == "suspended"
    assert call("POST", users_url(ORG_A, MEM, "reactivate"), "provider").json()["status"] == "active"
    assert call("GET", users_url(uuid.uuid4()), "provider").status_code == 404


# --- list / get --------------------------------------------------------------------

def test_list_is_flat_newest_first_without_deleted_users() -> None:
    response = call("GET", users_url())
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["page"], body["page_size"], body["max_users"], body["seats_used"]) == (
        4, 1, 20, 10, 4)
    assert [u["email"] for u in body["items"]] == ["inv@acme.test", "mem@acme.test", "a2@acme.test",
                                                   "a1@acme.test"]
    first = body["items"][0]
    assert (first["first_name"], first["last_name"], first["role"], first["status"]) == (
        "Ivy", "Invited", "org_member", "invited")
    assert "password_hash" not in first


def test_list_filters_and_pages() -> None:
    assert [u["email"] for u in call("GET", users_url(), params={"role": "org_admin"}).json()["items"]] == [
        "a2@acme.test", "a1@acme.test"]
    invited = call("GET", users_url(), params={"status": "invited"}).json()
    assert [u["email"] for u in invited["items"]] == ["inv@acme.test"]
    assert (invited["total"], invited["seats_used"]) == (1, 4)  # seats ignore the filters
    page = call("GET", users_url(), params={"page": 2, "page_size": 3}).json()
    assert page["total"] == 4 and [u["email"] for u in page["items"]] == ["a1@acme.test"]
    assert call("GET", users_url(), params={"status": "deleted"}).status_code == 422
    assert call("GET", users_url(), params={"role": "provider_admin"}).status_code == 422


def test_get_one() -> None:
    response = call("GET", users_url(user=MEM))
    assert response.status_code == 200
    assert response.json()["email"] == "mem@acme.test" and response.json()["org_id"] == str(ORG_A)


# --- role --------------------------------------------------------------------------

def test_promote_and_demote() -> None:
    response = call("PATCH", users_url(user=MEM), body={"role": "org_admin"})
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "org_admin"
    assert call("PATCH", users_url(user=MEM), body={"role": "org_member"}).json()["role"] == "org_member"
    rows = audit()
    assert [r["event_type"] for r in rows] == ["user_role_changed", "user_role_changed"]
    assert rows[0]["actor_user_id"] == A1 and rows[0]["target_id"] == str(MEM) and rows[0]["org_id"] == ORG_A
    assert '"to": "org_admin"' in rows[0]["metadata"] and '"from": "org_member"' in rows[0]["metadata"]


def test_same_role_is_a_no_op() -> None:
    assert call("PATCH", users_url(user=MEM), body={"role": "org_member"}).status_code == 200
    assert audit() == []


@pytest.mark.parametrize("body", [{"role": "provider_admin"}, {"role": "owner"}, {},
                                  {"role": "org_admin", "status": "active"}])
def test_role_validation(body: dict[str, Any]) -> None:
    assert call("PATCH", users_url(user=MEM), body=body).status_code == 422
    assert status_of(MEM) == ("org_member", "active")


def test_an_admin_cannot_demote_themselves() -> None:
    response = call("PATCH", users_url(user=A1), body={"role": "org_member"})
    assert response.status_code == 409 and response.json()["detail"] == "You cannot demote yourself"
    assert status_of(A1) == ("org_admin", "active")


def test_the_last_active_admin_cannot_be_demoted() -> None:
    assert call("PATCH", users_url(user=A2), body={"role": "org_member"}).status_code == 200
    response = call("PATCH", users_url(user=A1), "provider", {"role": "org_member"})
    assert response.status_code == 409
    assert response.json()["detail"] == "The organization must keep at least one active admin"
    assert status_of(A1) == ("org_admin", "active")


def test_an_invited_admin_does_not_count_as_the_remaining_admin() -> None:
    admin("UPDATE users SET role = 'org_admin' WHERE id = $1", INV)
    assert call("PATCH", users_url(user=A2), body={"role": "org_member"}).status_code == 200
    assert call("PATCH", users_url(user=A1), "provider", {"role": "org_member"}).status_code == 409
    # Demoting the invited admin itself is fine: they are not active.
    assert call("PATCH", users_url(user=INV), "provider", {"role": "org_member"}).status_code == 200


def test_two_admins_demoting_each_other_at_once_leaves_one_admin() -> None:
    async def both() -> list[Any]:
        return list(await asyncio.gather(
            _call("PATCH", users_url(user=A2), "a1", {"role": "org_member"}),
            _call("PATCH", users_url(user=A1), "a2", {"role": "org_member"}),
        ))

    codes = sorted(r.status_code for r in asyncio.run(both()))
    assert codes == [200, 409]
    active_admins = admin("SELECT id FROM users WHERE org_id = $1 AND role = 'org_admin' AND status = 'active'",
                          ORG_A)
    assert len(active_admins) == 1


# --- suspend / reactivate ----------------------------------------------------------

def test_suspend_revokes_sessions_and_outstanding_tokens_immediately() -> None:
    assert call("GET", "/api/v1/auth/me", "mem").status_code == 200
    response = call("POST", users_url(user=MEM, action="suspend"))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    for token in ("mem", "mem_2"):
        assert call("GET", "/api/v1/auth/me", token).status_code == 401
    assert admin("SELECT count(*) AS n FROM sessions WHERE user_id = $1", MEM)[0]["n"] == 0
    assert admin("SELECT count(*) AS n FROM auth_tokens WHERE user_id = $1", MEM)[0]["n"] == 0
    assert call("GET", "/api/v1/auth/me", "a2").status_code == 200  # nobody else is affected
    [row] = audit()
    assert row["event_type"] == "user_suspended" and row["actor_user_id"] == A1
    assert '"sessions_revoked": 2' in row["metadata"]


def test_suspend_and_reactivate_are_idempotent() -> None:
    assert call("POST", users_url(user=MEM, action="suspend")).json()["status"] == "suspended"
    assert call("POST", users_url(user=MEM, action="suspend")).json()["status"] == "suspended"
    assert call("POST", users_url(user=MEM, action="reactivate")).json()["status"] == "active"
    assert call("POST", users_url(user=MEM, action="reactivate")).json()["status"] == "active"
    assert [r["event_type"] for r in audit()] == ["user_suspended", "user_reactivated"]
    # Reactivation does not bring sessions back.
    assert call("GET", "/api/v1/auth/me", "mem").status_code == 401


def test_reactivating_someone_who_never_accepted_their_invite_puts_them_back_to_invited() -> None:
    assert call("POST", users_url(user=INV, action="suspend")).json()["status"] == "suspended"
    assert admin("SELECT count(*) AS n FROM auth_tokens WHERE user_id = $1", INV)[0]["n"] == 0
    assert call("POST", users_url(user=INV, action="reactivate")).json()["status"] == "invited"


def test_an_admin_cannot_suspend_themselves() -> None:
    response = call("POST", users_url(user=A1, action="suspend"))
    assert response.status_code == 409 and response.json()["detail"] == "You cannot suspend yourself"
    assert status_of(A1) == ("org_admin", "active")


def test_the_last_active_admin_cannot_be_suspended() -> None:
    assert call("POST", users_url(user=A2, action="suspend")).status_code == 200
    response = call("POST", users_url(user=A1, action="suspend"), "provider")
    assert response.status_code == 409
    assert status_of(A1) == ("org_admin", "active")
    assert call("GET", "/api/v1/auth/me", "a1").status_code == 200


def test_another_admin_can_be_suspended() -> None:
    assert call("POST", users_url(user=A2, action="suspend")).json()["status"] == "suspended"
    assert call("GET", "/api/v1/auth/me", "a2").status_code == 401


# --- sessions of suspended users / orgs (get_current_user) -------------------------

def test_a_session_of_a_non_active_user_is_refused() -> None:
    # Even if a session row survived (it should not), a suspended user is not authenticated.
    admin("UPDATE users SET status = 'suspended' WHERE id = $1", MEM)
    assert call("GET", "/api/v1/auth/me", "mem").status_code == 401


def test_a_session_in_a_suspended_org_is_refused() -> None:
    admin("UPDATE organizations SET status = 'suspended' WHERE id = $1", ORG_B)
    assert call("GET", "/api/v1/auth/me", "b_admin").status_code == 401
    assert call("GET", "/api/v1/auth/me", "provider").status_code == 200
