"""Migration 0026 and kept workpaper copies, through the real app and Postgres.

Add-only tables for app_user, org isolation (RLS), the copy and its audit event in one transaction, one copy
for two downloads at once, a damaged copy, a storage failure that sends nothing, an archived engagement.
Needs TEST_DATABASE_URL (owner) and TEST_APP_DATABASE_URL (app_user); skipped locally without them.
The downgrade test runs alembic and always leaves head.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from backend.app.core import db
from backend.app.core.config import Settings, get_settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

BACKEND = Path(__file__).resolve().parents[2]
ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000002601")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000002602")
A_MEMBER = uuid.UUID("aaaaaaaa-0002-0000-0000-000000002601")
A_ADMIN = uuid.UUID("aaaaaaaa-0001-0000-0000-000000002601")
B_MEMBER = uuid.UUID("bbbbbbbb-0002-0000-0000-000000002602")
PROVIDER = uuid.UUID("cccccccc-0001-0000-0000-000000002601")
ENG = uuid.UUID("aaaaaaaa-1111-0000-0000-000000002601")
ENG_CLOSED = uuid.UUID("aaaaaaaa-2222-0000-0000-000000002601")
TOKENS = {"a_member": (A_MEMBER, ORG_A), "a_admin": (A_ADMIN, ORG_A), "b_member": (B_MEMBER, ORG_B),
          "provider": (PROVIDER, None)}
COPIES, DOWNLOADS = "workpaper_copies", "workpaper_downloads"
PREVIOUS = "0025_review_decisions_add_only"
DENIED = (ProgrammingError, DBAPIError)


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
        await conn.execute("TRUNCATE audit_logs")
        await conn.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'wp-a'), ($2, 'Beta', 'wp-b')",
                           ORG_A, ORG_B)
        await conn.execute(
            "INSERT INTO users (id, org_id, email, first_name, last_name, role, status) VALUES "
            "($1, $2, 'member@acme.test', 'Meg', 'Member', 'org_member', 'active'),"
            "($3, $2, 'admin@acme.test', 'Ann', 'Admin', 'org_admin', 'active'),"
            "($4, $5, 'member@beta.test', 'Ben', 'Beta', 'org_member', 'active'),"
            "($6, NULL, 'ops@sustentra.test', 'Op', 'Erator', 'provider_admin', 'active')",
            A_MEMBER, ORG_A, A_ADMIN, B_MEMBER, ORG_B, PROVIDER)
        await conn.execute(
            "INSERT INTO engagements (id, org_id, name, status) VALUES ($1, $2, 'FY2025 =SUM(A1)', 'active'), "
            "($3, $2, 'Closed year', 'archived')", ENG, ORG_A, ENG_CLOSED)
        now = datetime.now(UTC)
        for token, (user_id, org_id) in TOKENS.items():
            await conn.execute(
                "INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                "VALUES ($1, $2, $3, $4, $5, $4)", user_id, org_id, hash_token(token), now, now + timedelta(days=1))
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    asyncio.run(_seed())


@pytest.fixture(scope="module")
def admin() -> Any:
    engine = create_engine(db.to_sync_url(ADMIN_URL or ""), pool_size=1, max_overflow=0)
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine() -> Any:
    engine = create_engine(db.to_sync_url(APP_URL or ""), pool_size=2, max_overflow=0)
    yield engine
    engine.dispose()


def _as_app(engine: Any, tenant: uuid.UUID | None, sql: str, **params: Any) -> Any:
    with engine.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true), set_config('app.is_provider', :p, true)"),
                  {"t": str(tenant or ""), "p": "false" if tenant else "true"})
        return c.execute(text(sql), params)


def _insert_copy(engine: Any, org: uuid.UUID = ORG_A, engagement: uuid.UUID = ENG, content: bytes = b"PK-bytes",
                 scope: uuid.UUID | None = ORG_A) -> Any:
    sha = hashlib.sha256(content).hexdigest()
    return _as_app(engine, scope, f"INSERT INTO {COPIES} (org_id, engagement_id, file_name, size_bytes, sha256, "
                   "content_fingerprint, app_version, content) VALUES (:org, :e, 'f.xlsx', :size, :sha, :sha, 'v', :c) "
                   "RETURNING id", org=org, e=engagement, size=len(content), sha=sha, c=content).scalar_one()


# --- the schema ---------------------------------------------------------------

def test_the_app_role_can_only_insert_and_select_on_both_tables(admin: Any, app_engine: Any) -> None:
    copy_id = _insert_copy(app_engine)
    _as_app(app_engine, ORG_A, f"INSERT INTO {DOWNLOADS} (org_id, engagement_id, copy_id, kind) "
            "VALUES (:org, :e, :c, 'prepared')", org=ORG_A, e=ENG, c=copy_id)
    with admin.connect() as c:
        for table in (COPIES, DOWNLOADS):
            privileges = {p: c.execute(text("SELECT has_table_privilege('app_user', :t, :p)"), {"t": table, "p": p}).scalar()
                          for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")}
            assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False,
                                  "TRUNCATE": False}, table
            policies = {r.policyname: r.cmd for r in c.execute(
                text("SELECT policyname, cmd FROM pg_policies WHERE tablename = :t"), {"t": table})}
            assert sorted(policies.values()) == ["INSERT", "SELECT"], table
            assert c.execute(text("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname = :t"),
                             {"t": table}).scalar()
    for sql in (f"UPDATE {COPIES} SET file_name = 'x'", f"UPDATE {COPIES} SET content = 'x'::bytea",
                f"DELETE FROM {COPIES}", f"TRUNCATE {COPIES}", f"SELECT 1 FROM {COPIES} FOR UPDATE",
                f"UPDATE {DOWNLOADS} SET kind = 'saved'", f"DELETE FROM {DOWNLOADS}", f"TRUNCATE {DOWNLOADS}"):
        with pytest.raises(DENIED, match="permission denied"):
            _as_app(app_engine, ORG_A, sql)


def test_foreign_keys_restrict_and_nothing_cascades(admin: Any, app_engine: Any) -> None:
    copy_id = _insert_copy(app_engine)
    with admin.connect() as c:
        for table, expected in ((COPIES, {("organizations", "r"), ("engagements", "r")}),
                                (DOWNLOADS, {("organizations", "r"), ("engagements", "r"), (COPIES, "r")})):
            rows = c.execute(text("SELECT confrelid::regclass::text AS ref, confdeltype FROM pg_constraint "
                                  "WHERE contype = 'f' AND conrelid = CAST(:t AS regclass)"), {"t": table}).all()
            assert {(r.ref, r.confdeltype) for r in rows} == expected, table
    # like audit history: an engagement or organization that has kept copies cannot be deleted
    with admin.begin() as c, pytest.raises(IntegrityError):
        c.execute(text("DELETE FROM engagements WHERE id = :e"), {"e": ENG})
    with admin.begin() as c, pytest.raises(IntegrityError):
        c.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": ORG_A})
    assert copy_id


def test_one_organization_cannot_see_or_write_another_organizations_copies(app_engine: Any) -> None:
    _insert_copy(app_engine)
    assert _as_app(app_engine, ORG_B, f"SELECT count(*) FROM {COPIES}").scalar_one() == 0
    assert _as_app(app_engine, ORG_A, f"SELECT count(*) FROM {COPIES}").scalar_one() == 1
    assert _as_app(app_engine, None, f"SELECT count(*) FROM {COPIES}").scalar_one() == 1  # provider scope
    with pytest.raises(DENIED, match="row-level security"):
        _insert_copy(app_engine, org=ORG_A, scope=ORG_B)  # B writing a row for A
    copy_id = _as_app(app_engine, ORG_A, f"SELECT id FROM {COPIES}").scalar_one()
    with pytest.raises(DENIED, match="row-level security"):
        _as_app(app_engine, ORG_B, f"INSERT INTO {DOWNLOADS} (org_id, engagement_id, copy_id, kind) "
                "VALUES (:o, :e, :c, 'saved')", o=ORG_A, e=ENG, c=copy_id)
    with pytest.raises(IntegrityError):  # the size and checksum are checked by the table itself
        _as_app(app_engine, ORG_A, f"INSERT INTO {COPIES} (org_id, engagement_id, file_name, size_bytes, sha256, "
                "content_fingerprint, app_version, content) VALUES (:o, :e, 'f', 99, :s, :s, 'v', 'abc')",
                o=ORG_A, e=ENG, s="0" * 64)


# --- through the app ----------------------------------------------------------

def _app(engine: Any) -> Any:
    app = create_app(Settings(environment="test", git_sha="rel-1", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    return app


def calls(*requests: tuple[str, str]) -> list[Any]:
    """Requests (token, path) sent at the same time, to one app on one pool."""

    async def main() -> list[Any]:
        engine = db.create_engine(APP_URL or "", pool_size=4, max_overflow=0)
        try:
            transport = httpx.ASGITransport(app=_app(engine))

            async def one(token: str, path: str) -> Any:
                async with httpx.AsyncClient(transport=transport, base_url="https://testserver",
                                             headers={"Origin": ORIGIN}) as client:
                    client.cookies.set(SESSION_COOKIE, token)
                    return await client.get(path)

            return list(await asyncio.gather(*(one(t, p) for t, p in requests)))
        finally:
            await engine.dispose()

    return asyncio.run(main())


def call(token: str, path: str) -> Any:
    return calls((token, path))[0]


EXPORT = f"/api/v1/engagements/{ENG}/export"
LIST = f"/api/v1/engagements/{ENG}/workpaper-copies"


def rows(admin: Any, sql: str, **params: Any) -> list[Any]:
    with admin.connect() as c:
        return list(c.execute(text(sql), params).all())


def test_a_download_keeps_its_bytes_a_download_record_and_an_audit_event_together(admin: Any) -> None:
    response = call("a_member", EXPORT)
    assert response.status_code == 200, response.text
    (copy,) = rows(admin, f"SELECT *, octet_length(content) AS n FROM {COPIES}")
    assert bytes(copy.content) == response.content and copy.n == len(response.content)
    assert copy.sha256 == hashlib.sha256(response.content).hexdigest() == response.headers["etag"].strip('"')
    assert (copy.org_id, copy.engagement_id, copy.prepared_by_user_id, copy.prepared_by_email, copy.app_version) == (
        ORG_A, ENG, A_MEMBER, "member@acme.test", get_settings().git_sha)
    assert copy.request_id and copy.file_name.startswith("FY2025 SUMA1 workpaper ")
    (download,) = rows(admin, f"SELECT * FROM {DOWNLOADS}")
    assert (download.copy_id, download.kind, download.downloaded_by_email) == (copy.id, "prepared", "member@acme.test")
    (event,) = rows(admin, "SELECT * FROM audit_logs WHERE event_type = 'workpaper_exported'")
    assert event.metadata == {"format": "xlsx", "copy_id": str(copy.id), "sha256": copy.sha256,
                              "size_bytes": copy.size_bytes, "copy_reused": False}
    assert (event.org_id, event.actor_user_id, event.target_id, event.request_id) == (
        ORG_A, A_MEMBER, str(ENG), copy.request_id)


def test_two_downloads_at_once_keep_one_copy_and_two_download_records(admin: Any) -> None:
    first, second = calls(("a_member", EXPORT), ("a_member", EXPORT))
    assert first.status_code == second.status_code == 200
    assert first.content == second.content  # both hold the one kept file
    assert rows(admin, f"SELECT count(*) FROM {COPIES}")[0][0] == 1
    assert rows(admin, f"SELECT count(*) FROM {DOWNLOADS}")[0][0] == 2
    assert sorted(e.metadata["copy_reused"] for e in rows(admin, "SELECT metadata FROM audit_logs "
                                                          "WHERE event_type = 'workpaper_exported'")) == [False, True]


def test_the_list_and_a_kept_copy_download(admin: Any) -> None:
    live = call("a_member", EXPORT)
    call("a_admin", EXPORT)  # another preparer: a second copy
    listed = call("a_member", LIST)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2 and [i["prepared_by"] for i in body["items"]] == ["admin@acme.test", "member@acme.test"]
    assert [i["downloads"] for i in body["items"]] == [1, 1] and "content" not in body["items"][0]
    older = body["items"][1]
    kept = call("a_admin", f"{LIST}/{older['id']}/download")
    assert kept.status_code == 200 and kept.content == live.content
    assert hashlib.sha256(kept.content).hexdigest() == older["sha256"]
    assert call("a_member", LIST).json()["items"][1]["downloads"] == 2
    (event,) = rows(admin, "SELECT * FROM audit_logs WHERE event_type = 'workpaper_copy_downloaded'")
    assert event.actor_user_id == A_ADMIN
    assert event.metadata == {"copy_id": older["id"], "sha256": older["sha256"], "size_bytes": older["size_bytes"]}
    assert rows(admin, f"SELECT kind FROM {DOWNLOADS} ORDER BY created_at")[-1][0] == "saved"
    page = call("a_member", LIST + "?limit=1&offset=1").json()
    assert page["total"] == 2 and [i["id"] for i in page["items"]] == [older["id"]]
    assert call("a_member", LIST + "?limit=101").status_code == 422


def test_other_organizations_and_signed_out_callers_get_nothing(admin: Any) -> None:
    call("a_member", EXPORT)
    (copy_id,) = [r[0] for r in rows(admin, f"SELECT id FROM {COPIES}")]
    for path in (EXPORT, LIST, f"{LIST}/{copy_id}/download"):
        assert call("b_member", path).status_code == 404, path
        assert call("not-a-session", path).status_code == 401, path
    assert call("a_member", f"{LIST}/{uuid.uuid4()}/download").status_code == 404
    assert call("a_member", f"{LIST}/not-a-uuid/download").status_code == 404
    other = f"/api/v1/engagements/{ENG_CLOSED}/workpaper-copies/{copy_id}/download"
    assert call("a_member", other).status_code == 404  # a copy of another engagement is not served under this one
    assert rows(admin, f"SELECT count(*) FROM {DOWNLOADS}")[0][0] == 1
    # support (provider) reads across organizations, as on the live download
    assert call("provider", LIST).json()["total"] == 1
    assert call("provider", f"{LIST}/{copy_id}/download").status_code == 200


def test_an_archived_engagement_can_still_be_downloaded(admin: Any) -> None:
    response = call("a_member", f"/api/v1/engagements/{ENG_CLOSED}/export")
    assert response.status_code == 200
    assert rows(admin, f"SELECT count(*) FROM {COPIES} WHERE engagement_id = :e", e=ENG_CLOSED)[0][0] == 1


def test_a_damaged_copy_is_not_sent_and_the_next_download_keeps_a_fresh_one(admin: Any) -> None:
    live = call("a_member", EXPORT)
    (copy_id,) = [r[0] for r in rows(admin, f"SELECT id FROM {COPIES}")]
    with admin.begin() as c:  # the owner changes one byte, keeping the size (the table's own checks pass)
        c.execute(text(f"UPDATE {COPIES} SET content = set_byte(content, 40, get_byte(content, 40) # 1)"))
    damaged = call("a_member", f"{LIST}/{copy_id}/download")
    assert damaged.status_code == 500 and "no longer matches its checksum" in damaged.json()["detail"]
    assert rows(admin, f"SELECT count(*) FROM {DOWNLOADS} WHERE kind = 'saved'")[0][0] == 0
    again = call("a_member", EXPORT)
    assert again.status_code == 200 and again.content != b"" and again.content[:2] == b"PK"
    assert rows(admin, f"SELECT count(*) FROM {COPIES}")[0][0] == 2
    assert live.status_code == 200


def test_if_the_copy_cannot_be_saved_nothing_is_sent_and_no_event_is_written(admin: Any) -> None:
    with admin.begin() as c:
        c.execute(text(f"ALTER TABLE {COPIES} RENAME TO {COPIES}_away"))
    try:
        response = call("a_member", EXPORT)
    finally:
        with admin.begin() as c:
            c.execute(text(f"ALTER TABLE {COPIES}_away RENAME TO {COPIES}"))
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert rows(admin, "SELECT count(*) FROM audit_logs WHERE event_type = 'workpaper_exported'")[0][0] == 0
    assert rows(admin, f"SELECT count(*) FROM {DOWNLOADS}")[0][0] == 0
    assert call("a_member", EXPORT).status_code == 200  # and a retry works


# --- deploy order ---------------------------------------------------------------

def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_downgrade_drops_the_tables_and_upgrade_brings_them_back(admin: Any, app_engine: Any) -> None:
    try:
        _alembic("downgrade", PREVIOUS)
        with admin.connect() as c:
            assert c.execute(text("SELECT to_regclass('workpaper_copies')")).scalar() is None
            assert c.execute(text("SELECT to_regclass('workpaper_downloads')")).scalar() is None
            # the previous release's schema (0025) is intact
            assert not c.execute(text("SELECT has_table_privilege('app_user', 's1_review_decisions', 'UPDATE')")).scalar()
    finally:
        _alembic("upgrade", "head")
    _insert_copy(app_engine)
    assert _as_app(app_engine, ORG_A, f"SELECT count(*) FROM {COPIES}").scalar_one() == 1
