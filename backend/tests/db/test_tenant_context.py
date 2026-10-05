"""AUTH-002 integration tests: requests through FastAPI as app_user with RLS.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
Uses httpx.AsyncClient + ASGITransport so the app and the asyncpg pool share
one event loop.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core import db

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000c1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000c2")


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE users, organizations CASCADE")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'A', 'ctx-a'), ($2, 'B', 'ctx-b')", ORG_A, ORG_B
        )
        await conn.execute(
            "INSERT INTO users (org_id, email, role) VALUES ($1, 'a1@a.test', 'org_admin'), "
            "($1, 'a2@a.test', 'org_member'), ($2, 'b1@b.test', 'org_admin')",
            ORG_A,
            ORG_B,
        )
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    asyncio.run(_seed())


def _build_app(sessionmaker: Any) -> FastAPI:
    """Mini app: tenant comes from a stand-in for the authenticated session."""
    app = FastAPI()

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            async with session.begin():
                yield session

    # Stand-in for AUTH-004's get_current_user; tests override it per request.
    async def authenticated_org() -> uuid.UUID | None:
        return None

    app.state.authenticated_org = authenticated_org

    @app.get("/users")
    async def list_users(
        session: AsyncSession = Depends(session_dep),
        org: uuid.UUID | None = Depends(authenticated_org),
    ) -> dict[str, Any]:
        if org is not None:
            await db.set_tenant(session, org)
        emails = (await session.execute(text("SELECT email FROM users ORDER BY email"))).scalars().all()
        setting = (await session.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
        return {"emails": list(emails), "tenant_setting": setting}

    return app


def _fixed_org(org: uuid.UUID | None) -> Any:
    # Zero-parameter dependency, so FastAPI doesn't turn anything into a query param.
    async def current() -> uuid.UUID | None:
        return org

    return current


async def _requests(sequence: list[uuid.UUID | None], *, pool_size: int = 1) -> list[dict[str, Any]]:
    # pool_size=1, max_overflow=0: every request reuses the SAME pooled connection.
    engine = db.create_engine(APP_URL or "", pool_size=pool_size, max_overflow=0)
    app = _build_app(db.build_sessionmaker(engine))
    dep = app.state.authenticated_org
    results = []
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for org in sequence:
                app.dependency_overrides[dep] = _fixed_org(org)
                response = await client.get("/users")
                assert response.status_code == 200
                results.append(response.json())
    finally:
        await engine.dispose()
    return results


def test_request_authenticated_as_org_a_sees_only_org_a() -> None:
    [result] = asyncio.run(_requests([ORG_A]))
    assert result["emails"] == ["a1@a.test", "a2@a.test"]


def test_unauthenticated_request_sees_zero_users() -> None:
    [result] = asyncio.run(_requests([None]))
    assert result["emails"] == []


def test_tenant_does_not_leak_between_requests_on_a_pooled_connection() -> None:
    first, second, third = asyncio.run(_requests([ORG_A, None, ORG_B]))
    assert first["emails"] == ["a1@a.test", "a2@a.test"]
    assert second["emails"] == []  # same connection, previous tenant is gone
    assert second["tenant_setting"] in (None, "")
    assert third["emails"] == ["b1@b.test"]


def test_provider_context_sees_all_orgs() -> None:
    async def run() -> list[str]:
        engine = db.create_engine(APP_URL or "", pool_size=1, max_overflow=0)
        try:
            async with db.build_sessionmaker(engine)() as session, session.begin():
                await db.set_provider(session)
                return list((await session.execute(text("SELECT email FROM users ORDER BY email"))).scalars())
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == ["a1@a.test", "a2@a.test", "b1@b.test"]


def test_runtime_connection_is_app_user() -> None:
    async def run() -> tuple[str, bool]:
        engine = db.create_engine(APP_URL or "", pool_size=1, max_overflow=0)
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user"))).one()
                return row[0], row[1]
        finally:
            await engine.dispose()

    user, bypass = asyncio.run(run())
    assert user == "app_user"
    assert bypass is False
