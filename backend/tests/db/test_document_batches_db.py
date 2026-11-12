"""Migration 0018 on the real database, as ``app_user``: the batch table isolated per organization by
RLS (and never updated or deleted by the app), ``s1_documents.batch_id`` kept equal to the record's
own, a batch's documents listed in the caller's scope only, and the migration down and up.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from backend.app.core.db import tenant_transaction, to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.document_batch_repository import DocumentBatchRepository
from backend.app.repositories.document_repository import PostgresDocumentRepository
from sqlalchemy import text

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

BACKEND = Path(__file__).resolve().parents[2]
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000019a1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000019b2")


def admin(sql: str, *args: Any) -> list[Any]:
    async def go() -> list[Any]:
        conn = await asyncpg.connect(ADMIN_URL)
        try:
            return list(await conn.fetch(sql, *args))
        finally:
            await conn.close()

    return asyncio.run(go())


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def seeded() -> None:
    admin("TRUNCATE s1_document_batches")
    admin("TRUNCATE s1_documents")
    admin("TRUNCATE users, organizations CASCADE")
    admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 'batch-org-a'), "
          "($2, 'Org B', 'batch-org-b')", ORG_A, ORG_B)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=4, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def document(document_id: str, org: uuid.UUID, batch_id: str | None) -> dict[str, Any]:
    return {"document_id": document_id, "engagement_id": "ENG-1", "evidence_id": f"EV-{document_id}",
            "file_name": "bill.pdf", "mime_type": "application/pdf", "storage_uri": "x/bill.pdf",
            "document_role": "source_evidence", "document_type": None, "uploaded_by": "u@example.com",
            "uploaded_at": "2026-01-01T00:00:00+00:00", "processing_status": "not_started", "org_id": str(org),
            "batch_id": batch_id}


def test_a_batch_is_visible_only_to_its_organization(engine: Engine) -> None:
    batches = DocumentBatchRepository(engine)
    with scoped(S1Scope.tenant(ORG_A)):
        mine = batches.create(org_id=str(ORG_A), engagement_id="ENG-1", created_by="a@example.com", label="March")
        assert batches.get(mine.id) == mine
        assert (mine.label, mine.engagement_id, mine.org_id) == ("March", "ENG-1", str(ORG_A))
    with scoped(S1Scope.tenant(ORG_B)):
        assert batches.get(mine.id) is None
    with scoped(S1Scope.platform()):
        assert batches.get(mine.id) == mine


def test_a_batch_cannot_be_created_for_another_organization(engine: Engine) -> None:
    batches = DocumentBatchRepository(engine)
    with scoped(S1Scope.tenant(ORG_A)), pytest.raises(DBAPIError):
        batches.create(org_id=str(ORG_B), engagement_id="ENG-1", created_by="a@example.com")


def test_the_app_can_neither_change_nor_delete_a_batch(engine: Engine) -> None:
    batches = DocumentBatchRepository(engine)
    with scoped(S1Scope.tenant(ORG_A)):
        mine = batches.create(org_id=str(ORG_A), engagement_id="ENG-1", created_by="a@example.com")
        for statement in ("UPDATE s1_document_batches SET label = 'x'", "DELETE FROM s1_document_batches"):
            with pytest.raises(DBAPIError), tenant_transaction(S1Scope.tenant(ORG_A), engine) as connection:
                connection.execute(text(statement))
        assert batches.get(mine.id) == mine


def test_a_batchs_documents_are_listed_in_the_callers_scope_only(engine: Engine) -> None:
    documents = PostgresDocumentRepository(engine)
    with scoped(S1Scope.tenant(ORG_A)):
        documents.save(document("D1", ORG_A, "B1"))
        documents.save(document("D2", ORG_A, "B1"))
        documents.save(document("D3", ORG_A, None))
        assert [d["document_id"] for d in documents.list_by_batch("B1")] == ["D1", "D2"]
        assert documents.get_by_id("D3")["batch_id"] is None
    with scoped(S1Scope.tenant(ORG_B)):
        assert documents.list_by_batch("B1") == []


def test_the_batch_id_column_must_equal_the_records(engine: Engine) -> None:
    admin("INSERT INTO s1_documents (document_id, record) VALUES ('ok', '{\"document_id\": \"ok\"}'::jsonb)")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        admin("INSERT INTO s1_documents (document_id, batch_id, record) "
              "VALUES ('bad', 'B1', '{\"document_id\": \"bad\", \"batch_id\": \"B2\"}'::jsonb)")


def test_0019_down_and_up() -> None:
    try:
        assert admin("SELECT 1 FROM pg_class WHERE relname = 's1_document_batches'")
        alembic("downgrade", "0018_s1_document_chunks")
        assert not admin("SELECT 1 FROM pg_class WHERE relname = 's1_document_batches'")
        assert not admin("SELECT 1 FROM information_schema.columns "
                         "WHERE table_name = 's1_documents' AND column_name = 'batch_id'")
        alembic("upgrade", "head")
        assert admin("SELECT 1 FROM pg_class WHERE relname = 's1_document_batches'")
        assert admin("SELECT 1 FROM information_schema.columns "
                     "WHERE table_name = 's1_documents' AND column_name = 'batch_id'")
    finally:
        alembic("upgrade", "head")
