"""S1-BE-002: engagements in Postgres - API through the real app, and RLS on the table.

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
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000e1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000e1")
A_ADMIN = uuid.UUID("aaaaaaaa-1111-0000-0000-0000000000e1")
A_MEMBER = uuid.UUID("aaaaaaaa-2222-0000-0000-0000000000e1")
B_MEMBER = uuid.UUID("bbbbbbbb-2222-0000-0000-0000000000e1")
PROVIDER = uuid.UUID("cccccccc-3333-0000-0000-0000000000e1")
TOKENS = {"a_admin": (A_ADMIN, ORG_A), "a_member": (A_MEMBER, ORG_A), "b_member": (B_MEMBER, ORG_B),
          "provider": (PROVIDER, None)}


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, engagements, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme'), ($2, 'Beta', 'beta')",
            ORG_A, ORG_B,
        )
        await conn.execute(
            """
            INSERT INTO users (id, org_id, email, role) VALUES
              ($1, $2, 'admin@acme.test', 'org_admin'),
              ($3, $2, 'member@acme.test', 'org_member'),
              ($4, $5, 'member@beta.test', 'org_member'),
              ($6, NULL, 'ops@sustentra.test', 'provider_admin')
            """,
            A_ADMIN, ORG_A, A_MEMBER, B_MEMBER, ORG_B, PROVIDER,
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


async def _call(method: str, path: str, token: str | None, body: Any = None) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        transport = httpx.ASGITransport(app=_app(engine))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            cookies = {SESSION_COOKIE: token} if token else None
            return await client.request(method, path, cookies=cookies, json=body, headers={"Origin": ORIGIN})
    finally:
        await engine.dispose()


def call(method: str, path: str, token: str | None = "a_member", body: Any = None) -> Any:
    return asyncio.run(_call(method, path, token, body))


BASE = "/api/v1/engagements"
SETUP = {"facilities": [{"facilityId": "F1", "name": "Kent Cannery"}], "assuranceLevel": "Limited"}


def create(token: str = "a_member", **fields: Any) -> dict:
    body = {"name": "FY2024 GHG verification", "client_name": "Acme Foods",
            "reporting_period_start": "2024-01-01", "reporting_period_end": "2024-12-31", "settings": SETUP,
            **fields}
    response = call("POST", BASE, token, body)
    assert response.status_code == 201, response.text
    return response.json()


# --- create / read / update --------------------------------------------------------

def test_create_stores_the_engagement_in_the_callers_org() -> None:
    created = create()
    assert created["org_id"] == str(ORG_A)
    assert created["created_by"] == str(A_MEMBER)
    assert created["status"] == "active"
    assert created["settings"] == SETUP
    assert created["reporting_period_start"] == "2024-01-01"
    rows = asyncio.run(_admin("SELECT org_id, name FROM engagements"))
    assert [(r["org_id"], r["name"]) for r in rows] == [(ORG_A, "FY2024 GHG verification")]


def test_list_get_and_update() -> None:
    first = create(name="First")
    second = create(name="Second")
    listed = call("GET", BASE).json()["items"]
    assert [e["name"] for e in listed] == ["Second", "First"]  # most recently updated first

    assert call("GET", f"{BASE}/{first['id']}").json()["name"] == "First"

    updated = call("PATCH", f"{BASE}/{first['id']}", body={"client_name": "Acme Foods Ltd",
                                                           "settings": {"dataScope": "Scope 1 & 2"}})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["client_name"] == "Acme Foods Ltd"
    assert body["settings"] == {"dataScope": "Scope 1 & 2"}  # settings are replaced as a whole
    assert body["name"] == "First" and body["updated_at"] > first["updated_at"]
    assert [e["id"] for e in call("GET", BASE).json()["items"]] == [first["id"], second["id"]]


def test_archived_engagements_leave_the_default_list() -> None:
    created = create()
    archived = call("PATCH", f"{BASE}/{created['id']}", body={"status": "archived"})
    assert archived.json()["status"] == "archived"
    assert call("GET", BASE).json()["items"] == []
    assert [e["id"] for e in call("GET", f"{BASE}?include_archived=true").json()["items"]] == [created["id"]]


def test_create_and_update_are_audited_without_values() -> None:
    created = create()
    call("PATCH", f"{BASE}/{created['id']}", body={"name": "Renamed"})
    call("PATCH", f"{BASE}/{created['id']}", body={"status": "archived"})
    rows = asyncio.run(_admin(
        "SELECT event_type, org_id, actor_user_id, target_id, metadata FROM audit_logs "
        "WHERE target_type = 'engagement' ORDER BY created_at"))
    assert [r["event_type"] for r in rows] == ["engagement_created", "engagement_updated", "engagement_archived"]
    assert all(r["org_id"] == ORG_A and r["actor_user_id"] == A_MEMBER for r in rows)
    assert all(r["target_id"] == created["id"] for r in rows)
    assert "Renamed" not in str(rows[1]["metadata"]) and "name" in str(rows[1]["metadata"])


# --- validation -----------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"name": "   "},
    {"name": "x" * 201},
    {"name": "Ok", "settings": {"password": "nope"}},
    {"name": "Ok", "settings": {"facilities": "x" * (70 * 1024)}},
    {"name": "Ok", "reporting_period_start": "2024-12-31", "reporting_period_end": "2024-01-01"},
    {"name": "Ok", "org_id": str(ORG_B)},  # ignored field must not choose the owner
])
def test_create_validation(body: dict) -> None:
    response = call("POST", BASE, body=body)
    if "org_id" in body:
        assert response.status_code == 201 and response.json()["org_id"] == str(ORG_A)
    else:
        assert response.status_code == 422, body


def test_update_validation_considers_the_stored_period() -> None:
    created = create()
    response = call("PATCH", f"{BASE}/{created['id']}", body={"reporting_period_end": "2023-06-30"})
    assert response.status_code == 422
    for body in ({"name": None}, {"status": None}, {"status": "deleted"}, {"settings": None}):
        assert call("PATCH", f"{BASE}/{created['id']}", body=body).status_code == 422, body


def test_unknown_or_malformed_ids_are_404() -> None:
    assert call("GET", f"{BASE}/{uuid.uuid4()}").status_code == 404
    assert call("GET", f"{BASE}/not-a-uuid").status_code == 404
    assert call("PATCH", f"{BASE}/not-a-uuid", body={"name": "x"}).status_code == 404


# --- access ---------------------------------------------------------------------------

def test_signed_out_is_401() -> None:
    assert call("GET", BASE, token=None).status_code == 401
    assert call("POST", BASE, token=None, body={"name": "x"}).status_code == 401


def test_other_org_cannot_see_or_change_it() -> None:
    created = create()
    assert call("GET", BASE, "b_member").json()["items"] == []
    assert call("GET", f"{BASE}/{created['id']}", "b_member").status_code == 404
    assert call("PATCH", f"{BASE}/{created['id']}", "b_member", {"name": "Mine now"}).status_code == 404
    assert call("GET", f"{BASE}/{created['id']}").json()["name"] == "FY2024 GHG verification"


def test_org_admin_and_member_share_their_orgs_engagements() -> None:
    created = create("a_admin")
    assert call("PATCH", f"{BASE}/{created['id']}", "a_member", {"name": "Edited"}).status_code == 200


def test_provider_admin_reads_every_org_but_cannot_write() -> None:
    a = create()
    b = create("b_member", name="Beta engagement")
    assert {e["id"] for e in call("GET", BASE, "provider").json()["items"]} == {a["id"], b["id"]}
    assert [e["id"] for e in call("GET", f"{BASE}?org_id={ORG_B}", "provider").json()["items"]] == [b["id"]]
    assert call("GET", f"{BASE}/{a['id']}", "provider").status_code == 200
    assert call("POST", BASE, "provider", {"name": "x"}).status_code == 403
    assert call("PATCH", f"{BASE}/{a['id']}", "provider", {"name": "x"}).status_code == 403


def test_org_users_cannot_widen_the_list_with_org_id() -> None:
    create("b_member", name="Beta engagement")
    assert call("GET", f"{BASE}?org_id={ORG_B}").json()["items"] == []


# --- RLS on the table itself ------------------------------------------------------------

async def _as_app(tenant: uuid.UUID | None, sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(APP_URL)
    try:
        async with conn.transaction():
            if tenant is not None:
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def test_rls_isolates_rows_by_tenant() -> None:
    create()
    assert len(asyncio.run(_as_app(ORG_A, "SELECT id FROM engagements"))) == 1
    assert asyncio.run(_as_app(ORG_B, "SELECT id FROM engagements")) == []
    assert asyncio.run(_as_app(None, "SELECT id FROM engagements")) == []
    # B cannot update A's row (matches nothing) or insert a row for A.
    assert asyncio.run(_as_app(ORG_B, "UPDATE engagements SET name = 'x' RETURNING id")) == []
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        asyncio.run(_as_app(ORG_B, "INSERT INTO engagements (org_id, name) VALUES ($1, 'x')", ORG_A))


def test_the_app_cannot_delete_engagements() -> None:
    create()
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        asyncio.run(_as_app(ORG_A, "DELETE FROM engagements"))


# --- uploads need an existing, active engagement of the caller's org ---------------------

@pytest.fixture
def temp_uploads(tmp_path: Any) -> Any:
    from backend.app.api import documents as documents_api
    from backend.app.repositories.document_repository import InMemoryDocumentRepository
    from backend.app.services.document_upload_service import DocumentUploadService
    from backend.app.services.local_storage_service import LocalStorageService

    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    service = DocumentUploadService(storage_service=LocalStorageService(tmp_path / "uploads"),
                                    document_repository=InMemoryDocumentRepository())
    documents_api.configure_services(upload_service=service)
    yield
    documents_api.configure_services(upload_service=original[0], pipeline_service=original[1],
                                     storage_service=original[2])


async def _upload(engagement_id: str, token: str) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        transport = httpx.ASGITransport(app=_app(engine))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            return await client.post(
                f"/api/v1/engagements/{engagement_id}/documents/upload",
                cookies={SESSION_COOKIE: token}, headers={"Origin": ORIGIN},
                files={"file": ("bill.pdf", b"%PDF-1.4 test", "application/pdf")},
            )
    finally:
        await engine.dispose()


def upload(engagement_id: str, token: str = "a_member") -> Any:
    return asyncio.run(_upload(engagement_id, token))


def test_upload_to_an_active_engagement_of_my_org(temp_uploads: None) -> None:
    created = create()
    response = upload(created["id"])
    assert response.status_code == 200, response.text
    assert response.json()["engagement_id"] == created["id"]


def test_upload_to_an_unknown_or_foreign_engagement_is_404(temp_uploads: None) -> None:
    created = create()
    for engagement_id, token in ((str(uuid.uuid4()), "a_member"), ("ENG-1", "a_member"), (created["id"], "b_member")):
        response = upload(engagement_id, token)
        assert response.status_code == 404, (engagement_id, token)
        assert response.json()["detail"] == "Engagement not found."


def test_upload_to_an_archived_engagement_is_409(temp_uploads: None) -> None:
    created = create()
    call("PATCH", f"{BASE}/{created['id']}", body={"status": "archived"})
    response = upload(created["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "Engagement is archived."


def test_provider_admin_cannot_upload(temp_uploads: None) -> None:
    assert upload(create()["id"], "provider").status_code == 403
