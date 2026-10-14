"""Migration 0013: the S1 document stores in Postgres, isolated per organization by RLS.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user), like
test_rls_users.py; skipped locally without them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b2")
RECORD_TABLES = {
    "s1_documents": "document_id",
    "s1_pipeline_runs": "pipeline_run_id",
    "s1_extraction_results": "pipeline_run_id",
    "s1_review_decisions": "review_decision_id",
    "s1_approved_evidence": "approved_evidence_id",
}


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


def _record(table: str, org: uuid.UUID | None, key: str) -> dict[str, Any]:
    record: dict[str, Any] = {RECORD_TABLES[table]: key, "org_id": str(org) if org else None, "note": "x"}
    if table == "s1_documents":
        record["processing_status"] = "uploaded"
    return record


async def _insert(conn: Any, table: str, record: dict[str, Any]) -> None:
    column = RECORD_TABLES[table]
    extra = ", processing_status" if table == "s1_documents" else ""
    extra_value = ", $4" if table == "s1_documents" else ""
    args = [record.get("org_id") and uuid.UUID(record["org_id"]), record[column], json.dumps(record)]
    if table == "s1_documents":
        args.append(record["processing_status"])
    await conn.execute(
        f"INSERT INTO {table} (org_id, {column}, record{extra}) VALUES ($1, $2, $3::jsonb{extra_value})", *args)


async def _insert_file(conn: Any, uri: str, org: uuid.UUID | None, content: bytes = b"%PDF-1.4 bill") -> None:
    await conn.execute(
        "INSERT INTO s1_document_files (storage_uri, org_id, file_name, size_bytes, sha256, content) "
        "VALUES ($1, $2, 'bill.pdf', $3, $4, $5)",
        uri, org, len(content), hashlib.sha256(content).hexdigest(), content)


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE users, organizations CASCADE")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 's1-org-a'), ($2, 'Org B', 's1-org-b')",
            ORG_A, ORG_B)
        for table in RECORD_TABLES:
            await conn.execute(f"TRUNCATE {table}")
            for org, key in ((ORG_A, "a"), (ORG_B, "b"), (None, "legacy")):
                await _insert(conn, table, _record(table, org, key))
        await conn.execute("TRUNCATE s1_document_files")
        for org, uri in ((ORG_A, "uploads/a/bill.pdf"), (ORG_B, "uploads/b/bill.pdf"), (None, "uploads/legacy.pdf")):
            await _insert_file(conn, uri, org)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    run(_seed)


async def _as_app(work: Callable[[Any], Awaitable[Any]], *, tenant: uuid.UUID | None = None,
                  provider: bool = False) -> Any:
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


def _keys(table: str, **scope: Any) -> set[str]:
    column = RECORD_TABLES.get(table, "storage_uri")

    async def work(conn: Any) -> set[str]:
        return {r[column] for r in await conn.fetch(f"SELECT {column} FROM {table}")}

    return run(lambda: _as_app(work, **scope))


@pytest.mark.parametrize("table", [*RECORD_TABLES, "s1_document_files"])
def test_each_org_sees_only_its_own_rows_and_provider_sees_all(table: str) -> None:
    a, b, legacy = ("uploads/a/bill.pdf", "uploads/b/bill.pdf", "uploads/legacy.pdf") \
        if table == "s1_document_files" else ("a", "b", "legacy")
    assert _keys(table, tenant=ORG_A) == {a}
    assert _keys(table, tenant=ORG_B) == {b}
    assert _keys(table, provider=True) == {a, b, legacy}  # unowned (pre-SEC-001) rows: provider only
    assert _keys(table) == set()  # no tenant context: nothing


@pytest.mark.parametrize("table", list(RECORD_TABLES))
def test_writes_are_held_to_the_callers_org_and_nothing_is_deleted(table: str) -> None:
    async def write_other_org(conn: Any) -> None:
        await _insert(conn, table, _record(table, ORG_B, "sneaky"))

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):  # RLS WITH CHECK
        run(lambda: _as_app(write_other_org, tenant=ORG_A))

    async def write_own(conn: Any) -> None:
        await _insert(conn, table, _record(table, ORG_A, "mine"))

    run(lambda: _as_app(write_own, tenant=ORG_A))
    assert "mine" in _keys(table, tenant=ORG_A)

    async def update_other(conn: Any) -> str:
        return await conn.execute(f"UPDATE {table} SET updated_at = now() WHERE org_id = $1", ORG_B)

    assert run(lambda: _as_app(update_other, tenant=ORG_A)) == "UPDATE 0"

    async def delete_own(conn: Any) -> None:
        await conn.execute(f"DELETE FROM {table} WHERE org_id = $1", ORG_A)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        run(lambda: _as_app(delete_own, tenant=ORG_A))


def test_filter_columns_and_ownership_must_match_the_record() -> None:
    async def mismatched_org(conn: Any) -> None:
        record = _record("s1_review_decisions", ORG_B, "x")
        await conn.execute("INSERT INTO s1_review_decisions (org_id, review_decision_id, record) VALUES ($1, 'x', $2)",
                           ORG_A, json.dumps(record))

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(lambda: _as_app(mismatched_org, provider=True))

    async def mismatched_id(conn: Any) -> None:
        await conn.execute("INSERT INTO s1_documents (org_id, document_id, record) VALUES ($1, 'doc-1', $2)",
                           ORG_A, json.dumps({"document_id": "doc-2", "org_id": str(ORG_A)}))

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(lambda: _as_app(mismatched_id, tenant=ORG_A))

    async def duplicate_document(conn: Any) -> None:
        await _insert(conn, "s1_documents", _record("s1_documents", ORG_A, "a"))

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):  # one row per document
        run(lambda: _as_app(duplicate_document, tenant=ORG_A))


def test_a_file_row_must_hold_the_bytes_it_describes() -> None:
    async def wrong_size(conn: Any) -> None:
        await conn.execute(
            "INSERT INTO s1_document_files (storage_uri, org_id, file_name, size_bytes, sha256, content) "
            "VALUES ('uploads/a/x.pdf', $1, 'x.pdf', 99, $2, $3)", ORG_A, "0" * 64, b"abc")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        run(lambda: _as_app(wrong_size, tenant=ORG_A))

    async def read_back(conn: Any) -> bytes:
        return await conn.fetchval("SELECT content FROM s1_document_files WHERE storage_uri = 'uploads/a/bill.pdf'")

    assert run(lambda: _as_app(read_back, tenant=ORG_A)) == b"%PDF-1.4 bill"


def test_tenant_settings_do_not_outlive_their_transaction() -> None:
    async def two_transactions() -> tuple[int, int]:
        conn = await asyncpg.connect(APP_URL)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(ORG_A))
                inside = await conn.fetchval("SELECT count(*) FROM s1_documents")
            async with conn.transaction():
                after = await conn.fetchval("SELECT count(*) FROM s1_documents")
            return inside, after
        finally:
            await conn.close()

    assert run(two_transactions) == (1, 0)
