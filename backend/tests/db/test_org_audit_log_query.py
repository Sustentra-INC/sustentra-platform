"""COMP-002 integration tests for GET /api/v1/orgs/{org_id}/audit-logs.

Runs against real Postgres with RLS using:
- TEST_DATABASE_URL (owner credentials, for setup)
- TEST_APP_DATABASE_URL (app_user credentials, for API requests)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

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

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000021")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000021")

ADMIN_A_ID = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000021")
MEMBER_A_ID = uuid.UUID("aaaaaaaa-2222-0000-0000-000000000021")
ADMIN_B_ID = uuid.UUID("bbbbbbbb-1111-0000-0000-000000000021")
PROVIDER_ID = uuid.UUID("cccccccc-3333-0000-0000-000000000021")

TOKEN_ADMIN_A = "tok-admin-a"
TOKEN_MEMBER_A = "tok-member-a"
TOKEN_ADMIN_B = "tok-admin-b"
TOKEN_PROVIDER = "tok-provider"

T = TypeVar("T")


def run(fn: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
    return asyncio.run(fn(*args, **kwargs))


async def _admin_execute(sql: str, *args: Any) -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _admin_fetch(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _add_session(
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    token: str,
    *,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> None:
    created = created_at or (datetime.now(UTC) - timedelta(minutes=5))
    expires = expires_at or (created + timedelta(days=7))
    await _admin_execute(
        """
        INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at)
        VALUES ($1, $2, $3, $4, $5, $4)
        """,
        user_id,
        org_id,
        hash_token(token),
        created,
        expires,
    )


async def _reset_seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, audit_logs, users, organizations CASCADE")
        await conn.execute(
            """
            INSERT INTO organizations (id, name, slug) VALUES
              ($1, 'Alpha Org', 'alpha-org'),
              ($2, 'Beta Org',  'beta-org')
            """,
            ORG_A,
            ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, role, status, first_name, last_name, full_name) VALUES
              ($1, $2, 'admin.alpha@test',  'org_admin',      'active', 'Ada',  'Admin',    'Ada Admin'),
              ($3, $2, 'member.alpha@test', 'org_member',     'active', 'Mia',  'Member',   'Mia Member'),
              ($4, $5, 'admin.beta@test',   'org_admin',      'active', 'Ben',  'Beta',     'Ben Beta'),
              ($6, NULL, 'ops@test',        'provider_admin', 'active', 'Pia',  'Provider', 'Pia Provider')
            """,
            ADMIN_A_ID,
            ORG_A,
            MEMBER_A_ID,
            ADMIN_B_ID,
            ORG_B,
            PROVIDER_ID,
        )
    finally:
        await conn.close()

    await _add_session(ADMIN_A_ID, ORG_A, TOKEN_ADMIN_A)
    await _add_session(MEMBER_A_ID, ORG_A, TOKEN_MEMBER_A)
    await _add_session(ADMIN_B_ID, ORG_B, TOKEN_ADMIN_B)
    await _add_session(PROVIDER_ID, None, TOKEN_PROVIDER)


async def _insert_audit_event(
    *,
    org_id: uuid.UUID,
    event_type: str,
    created_at: datetime,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    row_id = event_id or uuid.uuid4()
    await _admin_execute(
        """
        INSERT INTO audit_logs (
            id, org_id, actor_user_id, actor_role, event_type,
            target_type, target_id, request_id, ip_address, user_agent, metadata, created_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CAST($9 AS inet), $10, $11::jsonb, $12)
        """,
        row_id,
        org_id,
        actor_user_id,
        actor_role,
        event_type,
        target_type,
        target_id,
        request_id,
        ip_address,
        user_agent,
        json.dumps(metadata or {}),
        created_at,
    )
    return row_id


async def _as_app(
    work: Callable[[Any], Coroutine[Any, Any, Any]],
    *,
    tenant: uuid.UUID | None = None,
    provider: bool = False,
) -> Any:
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


async def _expected_ids_for_org(org_id: uuid.UUID) -> list[uuid.UUID]:
    async def work(conn: Any) -> list[uuid.UUID]:
        rows = await conn.fetch(
            "SELECT id FROM audit_logs WHERE org_id = $1 ORDER BY created_at DESC, id DESC",
            org_id,
        )
        return [row["id"] for row in rows]

    return await _as_app(work, tenant=org_id)


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    run(_reset_seed)


def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    return app


async def _request(path: str, *, token: str | None = None, params: dict[str, str] | None = None) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        transport = httpx.ASGITransport(app=_app(engine))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            cookies = {SESSION_COOKIE: token} if token else None
            return await client.get(path, params=params, cookies=cookies, headers={"Origin": ORIGIN})
    finally:
        await engine.dispose()


def request(path: str, *, token: str | None = None, params: dict[str, str] | None = None) -> Any:
    return run(_request, path, token=token, params=params)


def _path(org_id: uuid.UUID) -> str:
    return f"/api/v1/orgs/{org_id}/audit-logs"


def _ids(body: dict[str, Any]) -> list[uuid.UUID]:
    return [uuid.UUID(item["id"]) for item in body["items"]]


def _encode_cursor_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


# --- role and scope enforcement -------------------------------------------------

def test_role_enforcement_and_cross_org_semantics() -> None:
    run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 1, 12, 0, tzinfo=UTC),
    )

    assert request(_path(ORG_A)).status_code == 401
    assert request(_path(ORG_A), token=TOKEN_MEMBER_A).status_code == 403
    assert request(_path(ORG_B), token=TOKEN_ADMIN_A).status_code == 404

    own_org = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    assert own_org.status_code == 200

    provider_any_org = request(_path(ORG_B), token=TOKEN_PROVIDER)
    assert provider_any_org.status_code == 200


def test_provider_admin_queries_each_org_without_cross_leakage() -> None:
    a_older = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 10, 10, 0, tzinfo=UTC),
    )
    a_newer = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="logout",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 10, 11, 0, tzinfo=UTC),
    )
    b_older = run(
        _insert_audit_event,
        org_id=ORG_B,
        event_type="login_success",
        actor_user_id=ADMIN_B_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 10, 12, 0, tzinfo=UTC),
    )
    b_newer = run(
        _insert_audit_event,
        org_id=ORG_B,
        event_type="org_updated",
        actor_user_id=ADMIN_B_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 10, 13, 0, tzinfo=UTC),
    )

    response_a = request(_path(ORG_A), token=TOKEN_PROVIDER)
    assert response_a.status_code == 200
    ids_a = _ids(response_a.json())
    assert ids_a == [a_newer, a_older]
    assert b_newer not in ids_a and b_older not in ids_a

    response_b = request(_path(ORG_B), token=TOKEN_PROVIDER)
    assert response_b.status_code == 200
    ids_b = _ids(response_b.json())
    assert ids_b == [b_newer, b_older]
    assert a_newer not in ids_b and a_older not in ids_b


# --- filters and date boundaries ------------------------------------------------

def test_filters_event_type_user_and_utc_date_bounds() -> None:
    before = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 1, 23, 59, 59, 999999, tzinfo=UTC),
    )
    start = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="logout",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 2, 0, 0, 0, 0, tzinfo=UTC),
    )
    mid = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 2, 12, 0, 0, 0, tzinfo=UTC),
    )
    end = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 2, 23, 59, 59, 999999, tzinfo=UTC),
    )
    after = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 3, 0, 0, 0, 0, tzinfo=UTC),
    )
    run(
        _insert_audit_event,
        org_id=ORG_B,
        event_type="login_success",
        actor_user_id=ADMIN_B_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 2, 8, 0, 0, 0, tzinfo=UTC),
    )

    by_event = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"event_type": "logout"})
    assert by_event.status_code == 200
    assert _ids(by_event.json()) == [start]

    by_user = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"user_id": str(MEMBER_A_ID)})
    assert by_user.status_code == 200
    assert _ids(by_user.json()) == [after, end, mid, start]

    by_date = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={"from_date": "2026-02-02", "to_date": "2026-02-02"},
    )
    assert by_date.status_code == 200
    assert _ids(by_date.json()) == [end, mid, start]

    combined = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={
            "event_type": "login_success",
            "user_id": str(MEMBER_A_ID),
            "from_date": "2026-02-02",
            "to_date": "2026-02-02",
        },
    )
    assert combined.status_code == 200
    assert _ids(combined.json()) == [end, mid]

    assert before not in _ids(by_date.json())


def test_single_ended_date_filters_use_utc_day_boundaries() -> None:
    before = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 1, 23, 59, 59, 999999, tzinfo=UTC),
    )
    at_start = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="logout",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 2, 0, 0, 0, 0, tzinfo=UTC),
    )
    at_end = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 2, 23, 59, 59, 999999, tzinfo=UTC),
    )
    after = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=MEMBER_A_ID,
        actor_role="org_member",
        created_at=datetime(2026, 2, 3, 0, 0, 0, 0, tzinfo=UTC),
    )

    from_only = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"from_date": "2026-02-02"})
    assert from_only.status_code == 200
    assert _ids(from_only.json()) == [after, at_end, at_start]

    to_only = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"to_date": "2026-02-02"})
    assert to_only.status_code == 200
    assert _ids(to_only.json()) == [at_end, at_start, before]


def test_to_date_max_value_is_safe_and_returns_200() -> None:
    event_id = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 2, 20, 12, 0, tzinfo=UTC),
    )

    response = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"to_date": "9999-12-31"})
    assert response.status_code == 200
    assert event_id in _ids(response.json())


# --- pagination ----------------------------------------------------------------

def test_pagination_limits_to_100_and_sets_final_page_cursor_to_null() -> None:
    base = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

    for i in range(99):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=base - timedelta(minutes=i),
        )

    tie_time = base - timedelta(minutes=99)
    tie_ids = [
        uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
        uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
        uuid.UUID("00000000-0000-0000-0000-0000000000a3"),
        uuid.UUID("00000000-0000-0000-0000-0000000000a4"),
    ]
    for row_id in tie_ids:
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=tie_time,
            event_id=row_id,
        )

    first = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    assert first.status_code == 200
    body_1 = first.json()
    ids_1 = _ids(body_1)

    assert len(ids_1) == 100
    assert body_1["next_cursor"] is not None

    second = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": body_1["next_cursor"]})
    assert second.status_code == 200
    body_2 = second.json()
    ids_2 = _ids(body_2)

    assert len(ids_2) == 3
    assert body_2["next_cursor"] is None

    all_ids = ids_1 + ids_2
    expected = run(_expected_ids_for_org, ORG_A)
    assert all_ids == expected

    tie_order = [row_id for row_id in all_ids if row_id in set(tie_ids)]
    assert tie_order == sorted(tie_ids, reverse=True)


def test_full_cursor_traversal_has_no_duplicates_or_gaps() -> None:
    base = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)
    for i in range(135):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="user_invited",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=base - timedelta(minutes=i),
            metadata={"ordinal": i},
        )

    seen: list[uuid.UUID] = []
    cursor: str | None = None

    while True:
        params = {"cursor": cursor} if cursor else None
        response = request(_path(ORG_A), token=TOKEN_ADMIN_A, params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(_ids(body))
        cursor = body["next_cursor"]
        if cursor is None:
            break

    expected = run(_expected_ids_for_org, ORG_A)
    assert seen == expected
    assert len(seen) == len(set(seen))


def test_empty_result_has_null_cursor() -> None:
    run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
    )

    response = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"event_type": "password_reset"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


# --- cursor integrity and validation --------------------------------------------

def test_invalid_cursor_and_cursor_scope_changes_are_rejected() -> None:
    base = datetime(2026, 4, 10, 9, 0, tzinfo=UTC)
    for i in range(101):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=base - timedelta(minutes=i),
        )

    first = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    cursor = first.json()["next_cursor"]
    assert cursor

    malformed = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": "not-base64"})
    assert malformed.status_code == 422

    changed_filter = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={"cursor": cursor, "event_type": "logout"},
    )
    assert changed_filter.status_code == 400

    changed_org = request(_path(ORG_B), token=TOKEN_PROVIDER, params={"cursor": cursor})
    assert changed_org.status_code == 400


def test_cursor_timestamp_overflow_to_utc_is_422() -> None:
    overflow_cursor = _encode_cursor_payload(
        {
            "v": 1,
            "org_id": str(ORG_A),
            "event_type": None,
            "user_id": None,
            "from_date": None,
            "to_date": None,
            "created_at": "9999-12-31T23:59:59.999999-14:00",
            "id": str(uuid.uuid4()),
        }
    )

    response = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": overflow_cursor})
    assert response.status_code == 422


def test_generated_cursor_with_suffix_empty_and_oversized_are_rejected() -> None:
    base = datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    for i in range(101):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=base - timedelta(minutes=i),
        )

    first = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    valid_followup = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": cursor})
    assert valid_followup.status_code == 200

    appended = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": cursor + "!!!"})
    assert appended.status_code == 422

    empty = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": ""})
    assert empty.status_code == 422

    oversized = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": "A" * 5000})
    assert oversized.status_code == 422


def test_cursor_rejects_changed_user_or_date_filters() -> None:
    base = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)
    for i in range(101):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=MEMBER_A_ID,
            actor_role="org_member",
            created_at=base - timedelta(minutes=i),
        )

    first = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={
            "user_id": str(MEMBER_A_ID),
            "from_date": "2026-08-01",
            "to_date": "2026-08-01",
        },
    )
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    changed_user = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={
            "cursor": cursor,
            "user_id": str(ADMIN_A_ID),
            "from_date": "2026-08-01",
            "to_date": "2026-08-01",
        },
    )
    assert changed_user.status_code == 400

    changed_from = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={
            "cursor": cursor,
            "user_id": str(MEMBER_A_ID),
            "from_date": "2026-07-31",
            "to_date": "2026-08-01",
        },
    )
    assert changed_from.status_code == 400

    changed_to = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={
            "cursor": cursor,
            "user_id": str(MEMBER_A_ID),
            "from_date": "2026-08-01",
            "to_date": "2026-08-02",
        },
    )
    assert changed_to.status_code == 400


def test_cursor_rejects_empty_optional_fields() -> None:
    run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    bad_cursor = _encode_cursor_payload(
        {
            "v": 1,
            "org_id": str(ORG_A),
            "event_type": "login_success",
            "user_id": "",
            "from_date": None,
            "to_date": None,
            "created_at": "2026-08-10T12:00:00+00:00",
            "id": str(uuid.uuid4()),
        }
    )

    response = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": bad_cursor})
    assert response.status_code == 422


def test_invalid_uuid_and_invalid_date_range_are_422() -> None:
    bad_user = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"user_id": "not-a-uuid"})
    assert bad_user.status_code == 422

    bad_dates = request(
        _path(ORG_A),
        token=TOKEN_ADMIN_A,
        params={"from_date": "2026-05-03", "to_date": "2026-05-01"},
    )
    assert bad_dates.status_code == 422


# --- consistency with concurrent inserts ----------------------------------------

def test_newer_insert_between_pages_does_not_corrupt_cursor_walk() -> None:
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    for i in range(120):
        run(
            _insert_audit_event,
            org_id=ORG_A,
            event_type="login_success",
            actor_user_id=ADMIN_A_ID,
            actor_role="org_admin",
            created_at=base - timedelta(minutes=i),
        )

    expected_before = run(_expected_ids_for_org, ORG_A)

    page_1 = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    assert page_1.status_code == 200
    body_1 = page_1.json()
    ids_1 = _ids(body_1)
    assert len(ids_1) == 100

    new_id = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_success",
        actor_user_id=ADMIN_A_ID,
        actor_role="org_admin",
        created_at=base + timedelta(minutes=1),
    )

    page_2 = request(_path(ORG_A), token=TOKEN_ADMIN_A, params={"cursor": body_1["next_cursor"]})
    assert page_2.status_code == 200
    body_2 = page_2.json()
    ids_2 = _ids(body_2)

    assert body_2["next_cursor"] is None
    assert new_id not in ids_2

    walked = ids_1 + ids_2
    assert walked == expected_before
    assert new_id not in walked


# --- historical actor handling ---------------------------------------------------

def test_historical_events_with_missing_or_null_actor_are_returned() -> None:
    deleted_actor = uuid.UUID("dddddddd-4444-0000-0000-000000000021")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    missing_actor_event = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="org_updated",
        actor_user_id=deleted_actor,
        actor_role="org_admin",
        created_at=now,
    )
    null_actor_event = run(
        _insert_audit_event,
        org_id=ORG_A,
        event_type="login_fail",
        actor_user_id=None,
        actor_role=None,
        created_at=now - timedelta(minutes=1),
    )

    response = request(_path(ORG_A), token=TOKEN_ADMIN_A)
    assert response.status_code == 200

    rows = {uuid.UUID(item["id"]): item for item in response.json()["items"]}

    assert rows[missing_actor_event]["actor_user_id"] == str(deleted_actor)
    assert rows[missing_actor_event]["actor_email"] is None

    assert rows[null_actor_event]["actor_user_id"] is None
    assert rows[null_actor_event]["actor_email"] is None
