"""COMP-002: an org's audit log - access, filters and cursor pagination, through the real app and Postgres.

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
from backend.app.core.config import Settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.services.audit_query import encode_cursor
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000c2")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000c2")
A_ADMIN = uuid.UUID("aaaaaaaa-0001-0000-0000-0000000000c2")
A_MEMBER = uuid.UUID("aaaaaaaa-0002-0000-0000-0000000000c2")
A_GONE = uuid.UUID("aaaaaaaa-0003-0000-0000-0000000000c2")
B_ADMIN = uuid.UUID("bbbbbbbb-0001-0000-0000-0000000000c2")
PROVIDER = uuid.UUID("cccccccc-0001-0000-0000-0000000000c2")
TOKENS = {"a_admin": (A_ADMIN, ORG_A), "a_member": (A_MEMBER, ORG_A), "b_admin": (B_ADMIN, ORG_B),
          "provider": (PROVIDER, None)}
URL = f"/api/v1/orgs/{ORG_A}/audit-logs"
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SAME = 5  # events sharing one timestamp


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme'), "
                           "($2, 'Beta', 'beta')", ORG_A, ORG_B)
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, first_name, last_name, role, status) VALUES
              ($1, $2, 'admin@acme.test', 'Ann', 'Admin', 'org_admin', 'active'),
              ($3, $2, 'member@acme.test', 'Meg', 'Member', 'org_member', 'active'),
              ($4, $2, 'deleted_x@deleted', 'Deleted', 'User', 'org_member', 'deleted'),
              ($5, $6, 'admin@beta.test', 'Ben', 'Beta', 'org_admin', 'active'),
              ($7, NULL, 'ops@sustentra.test', 'Op', 'Erator', 'provider_admin', 'active')
            """,
            A_ADMIN, ORG_A, A_MEMBER, A_GONE, B_ADMIN, ORG_B, PROVIDER,
        )
        # Clear the full_name the app keeps in sync so display names come from first/last.
        await conn.execute("UPDATE users SET full_name = NULL")
        events = [
            # (org, actor, role, event, target user, when)
            (ORG_A, PROVIDER, "provider_admin", "org_created", None, T0 - timedelta(days=3)),
            (ORG_A, A_ADMIN, "org_admin", "user_invited", A_MEMBER, T0 - timedelta(days=2)),
            (ORG_A, A_MEMBER, "org_member", "login_success", None, T0 - timedelta(days=1)),
            (ORG_A, A_ADMIN, "org_admin", "user_deleted", A_GONE, T0 - timedelta(hours=1)),
            (ORG_B, B_ADMIN, "org_admin", "user_invited", B_ADMIN, T0),
            (None, None, None, "login_fail", None, T0),
        ] + [(ORG_A, A_ADMIN, "org_admin", "user_role_changed", A_MEMBER, T0) for _ in range(SAME)]
        for org, actor, role, event, target, when in events:
            await conn.execute(
                "INSERT INTO audit_logs (org_id, actor_user_id, actor_role, event_type, target_type, target_id, "
                "ip_address, user_agent, metadata, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, '10.0.0.1', 'UA', '{\"k\": 1}', $7)",
                org, actor, role, event, "user" if target else ("organization" if event == "org_created" else None),
                str(target) if target else (str(org) if event == "org_created" else None), when,
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
    asyncio.run(_seed())


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    return app


def call(path: str = URL, token: str | None = "a_admin", **params: Any) -> Any:
    async def main() -> Any:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            transport = httpx.ASGITransport(app=_app(engine))
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                         headers={"Origin": ORIGIN}) as client:
                if token:
                    client.cookies.set(SESSION_COOKIE, token)
                return await client.get(path, params={k: v for k, v in params.items() if v is not None})
        finally:
            await engine.dispose()

    return asyncio.run(main())


def all_pages(token: str = "a_admin", **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(50):
        response = call(token=token, cursor=cursor, **params)
        assert response.status_code == 200, response.text
        body = response.json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("pagination did not end")


# --- access ------------------------------------------------------------------------

def test_org_admin_sees_only_their_org_newest_first() -> None:
    response = call()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    events = [e["event_type"] for e in body["items"]]
    assert events == ["user_role_changed"] * SAME + ["user_deleted", "login_success", "user_invited", "org_created"]
    # Beta's event and the org-less login_fail are never included.
    assert all(e["target_id"] != str(B_ADMIN) for e in body["items"])


def test_another_orgs_admin_gets_404_member_403_anonymous_401() -> None:
    assert call(token="b_admin").status_code == 404
    assert call(token="a_member").status_code == 403
    assert call(token=None).status_code == 401
    assert call(f"/api/v1/orgs/{uuid.uuid4()}/audit-logs", "provider").status_code == 404
    assert call("/api/v1/orgs/not-a-uuid/audit-logs", "provider").status_code == 404


def test_provider_admin_can_read_any_org() -> None:
    a = call(token="provider").json()["items"]
    b = call(f"/api/v1/orgs/{ORG_B}/audit-logs", "provider").json()["items"]
    assert len(a) == SAME + 4
    assert [e["event_type"] for e in b] == ["user_invited"]


def test_display_names_and_no_ip_or_user_agent() -> None:
    items = call().json()["items"]
    by_type = {e["event_type"]: e for e in items}
    assert by_type["user_role_changed"]["actor"] == "Ann Admin"
    assert by_type["user_role_changed"]["target"] == "Meg Member"
    assert by_type["user_deleted"]["target"] == "Deleted User"
    # An org admin cannot see provider admins (RLS): shown as the provider.
    assert by_type["org_created"]["actor"] == "Sustentra"
    assert by_type["org_created"]["target"] is None
    assert by_type["login_success"]["metadata"] == {"k": 1}
    assert "ip_address" not in items[0] and "user_agent" not in items[0]
    # A provider admin sees the real name.
    provider_view = {e["event_type"]: e for e in call(token="provider").json()["items"]}
    assert provider_view["org_created"]["actor"] == "Op Erator"


# --- pagination --------------------------------------------------------------------

@pytest.mark.parametrize("limit", [1, 2, 3, 4, 100])
def test_pages_never_skip_or_repeat_even_with_equal_timestamps(limit: int) -> None:
    every = call(limit=100).json()["items"]
    paged = all_pages(limit=limit)
    assert [e["id"] for e in paged] == [e["id"] for e in every]
    assert len({e["id"] for e in paged}) == SAME + 4


def test_next_cursor_returns_the_correct_next_page() -> None:
    first = call(limit=3).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    second = call(limit=3, cursor=first["next_cursor"]).json()
    every = call(limit=100).json()["items"]
    assert [e["id"] for e in second["items"]] == [e["id"] for e in every[3:6]]


def test_limit_bounds_and_default() -> None:
    assert call(limit=0).status_code == 422
    assert call(limit=101).status_code == 422
    assert len(call().json()["items"]) == SAME + 4  # default 50


@pytest.mark.parametrize("cursor", ["garbage", "!!!", encode_cursor(T0, uuid.uuid4())[:-3] + "zzz", "fA"])
def test_a_bad_cursor_is_400(cursor: str) -> None:
    response = call(cursor=cursor)
    assert response.status_code == 400 and response.json()["detail"] == "Invalid cursor"


# --- filters -----------------------------------------------------------------------

def test_filter_by_event_type() -> None:
    items = all_pages(limit=2, event_type="user_role_changed")
    assert len(items) == SAME and {e["event_type"] for e in items} == {"user_role_changed"}
    assert call(event_type="Bad Type").status_code == 422


def test_filter_by_user_matches_actor_or_target() -> None:
    member = [e["event_type"] for e in call(user_id=str(A_MEMBER)).json()["items"]]
    assert member == ["user_role_changed"] * SAME + ["login_success", "user_invited"]
    assert [e["event_type"] for e in call(user_id=str(PROVIDER)).json()["items"]] == ["org_created"]
    assert call(user_id="nope").status_code == 422


def test_filter_by_dates_inclusive() -> None:
    day = (T0 - timedelta(days=1)).date().isoformat()
    assert [e["event_type"] for e in call(from_date=day, to_date=day).json()["items"]] == ["login_success"]
    since = [e["event_type"] for e in call(from_date=T0.date().isoformat()).json()["items"]]
    assert since == ["user_role_changed"] * SAME + ["user_deleted"]
    assert call(from_date="2026-10-02", to_date="2026-10-01").status_code == 422


def test_filters_combine_with_the_cursor() -> None:
    items = all_pages(limit=1, user_id=str(A_MEMBER), from_date=(T0 - timedelta(days=1)).date().isoformat())
    assert [e["event_type"] for e in items] == ["user_role_changed"] * SAME + ["login_success"]
