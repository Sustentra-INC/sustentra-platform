from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.app.core import db as core_db
from backend.tests.db._db_contract import (
    DatabaseContractError,
    TEST_DATABASE_DISPOSABLE_ENV,
    validate_required_database_setup,
)

pytestmark = pytest.mark.requires_test_db


@pytest.mark.asyncio
async def test_runtime_requests_and_db_assertions_connect_as_app_user(
    seeded_identities,
    db_test_client,
    as_app_user,
) -> None:
    await db_test_client.login_with_otp(
        email="admin.a@org-a.test",
        password=seeded_identities.password,
        org_slug="org-a",
    )

    me = await db_test_client.client.get("/api/v1/auth/me", headers=db_test_client.headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin.a@org-a.test"

    async def role_row(conn):
        return await conn.fetchrow(
            "SELECT current_user, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
            "FROM pg_roles WHERE rolname = current_user"
        )

    row = await as_app_user(role_row, tenant_id=seeded_identities.org_a_id)
    assert row["current_user"] == "app_user"
    assert not any((row["rolsuper"], row["rolbypassrls"], row["rolcreatedb"], row["rolcreaterole"]))


@pytest.mark.asyncio
async def test_org_a_and_org_b_are_isolated_by_tenant_context(
    seeded_identities,
    as_app_user,
) -> None:
    async def list_emails(conn):
        rows = await conn.fetch("SELECT email FROM users ORDER BY email")
        return {row["email"] for row in rows}

    org_a_emails = await as_app_user(list_emails, tenant_id=seeded_identities.org_a_id)
    org_b_emails = await as_app_user(list_emails, tenant_id=seeded_identities.org_b_id)

    assert org_a_emails == {"admin.a@org-a.test", "member.a@org-a.test"}
    assert org_b_emails == {"admin.b@org-b.test", "member.b@org-b.test"}


@pytest.mark.asyncio
async def test_missing_tenant_context_sees_no_tenant_scoped_rows(as_app_user) -> None:
    count = await as_app_user(lambda conn: conn.fetchval("SELECT count(*) FROM users"))
    assert count == 0


@pytest.mark.asyncio
async def test_tenant_state_does_not_leak_when_pool_reuses_connection(
    seeded_identities,
    single_pool_sessionmaker,
) -> None:
    async with single_pool_sessionmaker() as session, session.begin():
        await core_db.set_tenant(session, seeded_identities.org_a_id)
        org_a_emails = list((await session.execute(text("SELECT email FROM users ORDER BY email"))).scalars())

    async with single_pool_sessionmaker() as session, session.begin():
        no_tenant_emails = list((await session.execute(text("SELECT email FROM users ORDER BY email"))).scalars())
        tenant_setting = (await session.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()

    assert org_a_emails == ["admin.a@org-a.test", "member.a@org-a.test"]
    assert no_tenant_emails == []
    assert tenant_setting in (None, "")


@pytest.mark.asyncio
async def test_login_helper_returns_cookie_accepted_by_authenticated_endpoint(
    seeded_identities,
    db_test_client,
) -> None:
    cookie = await db_test_client.login_with_otp(
        email="admin.a@org-a.test",
        password=seeded_identities.password,
        org_slug="org-a",
    )
    assert cookie

    response = await db_test_client.client.get("/api/v1/auth/me", headers=db_test_client.headers)
    assert response.status_code == 200
    assert response.json()["role"] == "org_admin"


@pytest.mark.asyncio
async def test_email_capture_uses_sender_seams_without_transport_calls(
    seeded_identities,
    db_test_client,
    transport_guard,
) -> None:
    assert db_test_client.email_capture.otp_codes == []

    response = await db_test_client.client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin.a@org-a.test",
            "password": seeded_identities.password,
            "org_slug": "org-a",
        },
        headers=db_test_client.headers,
    )

    assert response.status_code == 200
    assert len(db_test_client.email_capture.otp_codes) == 1
    assert transport_guard.smtp_calls == 0
    assert transport_guard.ses_calls == 0


@pytest.mark.asyncio
async def test_email_capture_is_isolated_between_tests(db_test_client) -> None:
    assert db_test_client.email_capture.otp_codes == []
    assert db_test_client.email_capture.reset_links == []


@pytest.mark.asyncio
async def test_clock_advance_exercises_real_lockout_boundary(
    seeded_identities,
    db_test_client,
    controlled_clock,
) -> None:
    for _ in range(5):
        bad = await db_test_client.client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin.a@org-a.test",
                "password": "wrong password",
                "org_slug": "org-a",
            },
            headers=db_test_client.headers,
        )
        assert bad.status_code == 401

    locked = await db_test_client.client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin.a@org-a.test",
            "password": seeded_identities.password,
            "org_slug": "org-a",
        },
        headers=db_test_client.headers,
    )
    assert locked.status_code == 429

    controlled_clock.advance(timedelta(minutes=15, seconds=1))
    unlocked = await db_test_client.client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin.a@org-a.test",
            "password": seeded_identities.password,
            "org_slug": "org-a",
        },
        headers=db_test_client.headers,
    )
    assert unlocked.status_code == 200


def test_required_database_mode_rejects_invalid_setup_before_destructive_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TEST_DATABASE_DISPOSABLE_ENV, raising=False)
    with pytest.raises(DatabaseContractError, match="TEST_DB_DISPOSABLE"):
        validate_required_database_setup(required=True)


@pytest.mark.asyncio
async def test_invite_emails_are_captured_not_sent(
    seeded_identities,
    db_test_client,
    transport_guard,
) -> None:
    await db_test_client.login_with_otp(
        email="admin.a@org-a.test",
        password=seeded_identities.password,
        org_slug="org-a",
    )
    response = await db_test_client.client.post(
        f"/api/v1/orgs/{seeded_identities.org_a_id}/invites",
        json={"email": "new@org-a.test", "role": "org_member", "first_name": "New", "last_name": "Person"},
        headers=db_test_client.headers,
    )
    assert response.status_code == 201, response.text
    link = db_test_client.email_capture.latest_invite_link("new@org-a.test")
    assert "/invite/accept?token=" in link
    assert transport_guard.smtp_calls == 0 and transport_guard.ses_calls == 0
