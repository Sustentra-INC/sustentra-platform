"""Processing runs through the real app (sessions, S1 scope binding, the sync engine) with the
queue in Postgres (migration 0015): a read is recorded under the caller's organization and
RLS keeps it there. The documents and the pipeline stay in memory.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.core import db
from backend.app.core.config import Settings
from backend.app.core.db import to_sync_url
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_token
from backend.app.main import create_app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import ProcessingRunRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000015e1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000015e1")
TOKENS = {
    "a_member": (uuid.UUID("aaaaaaaa-2222-0000-0000-0000000015e1"), ORG_A, "member@acme.test", "org_member"),
    "b_member": (uuid.UUID("bbbbbbbb-2222-0000-0000-0000000015e1"), ORG_B, "member@beta.test", "org_member"),
    "provider": (uuid.UUID("cccccccc-3333-0000-0000-0000000015e1"), None, "ops@sustentra.test", "provider_admin"),
}
BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    await _admin("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
    await _admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'runs-acme'), "
                 "($2, 'Beta', 'runs-beta')", ORG_A, ORG_B)
    now = datetime.now(UTC)
    for token, (user_id, org_id, email, role) in TOKENS.items():
        await _admin("INSERT INTO users (id, org_id, email, role) VALUES ($1, $2, $3, $4)", user_id, org_id, email, role)
        await _admin("INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                     "VALUES ($1, $2, $3, $4, $5, $4)", user_id, org_id, hash_token(token), now, now + timedelta(days=1))


@pytest.fixture
def document(tmp_path: Path) -> Iterator[dict]:
    """An org-A document whose run queue is the real Postgres table."""

    limiter.reset()
    asyncio.run(_seed())
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository())
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=2, max_overflow=0)
    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service,
                documents_api.current_run_repository())
    documents_api.configure_services(upload_service=uploads, pipeline_service=pipeline, storage_service=storage,
                                     run_repository=ProcessingRunRepository(engine))
    try:
        yield uploads.upload_document(engagement_id="ENG-RUNS", file_name="bill.txt", content=BILL,
                                      mime_type="text/plain", document_role="source_evidence",
                                      uploaded_by="member@acme.test", org_id=str(ORG_A))
    finally:
        documents_api.configure_services(upload_service=original[0], pipeline_service=original[1],
                                         storage_service=original[2], run_repository=original[3])
        engine.dispose()


async def _call(method: str, path: str, token: str, body: Any = None) -> Any:
    engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]
    sessionmaker = db.build_sessionmaker(engine)

    async def session_dep() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session, session.begin():
            yield session

    app.dependency_overrides[db.get_db_session] = session_dep
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            return await client.request(method, path, cookies={SESSION_COOKIE: token}, json=body,
                                        headers={"Origin": ORIGIN})
    finally:
        await engine.dispose()


def call(method: str, path: str, token: str = "a_member", body: Any = None) -> Any:
    return asyncio.run(_call(method, path, token, body))


def test_a_read_is_recorded_under_the_callers_organization(document: dict) -> None:
    response = call("POST", f"/api/v1/documents/{document['document_id']}/processing-runs",
                    body={"canonical_type_id_override": "CT-S1-FUELQTY"})
    assert response.status_code == 200, response.text
    run = response.json()
    assert (run["status"], run["attempt"], run["requested_by"]) == ("completed", 1, "member@acme.test")

    [row] = asyncio.run(_admin("SELECT * FROM s1_processing_runs"))
    assert (row["run_id"], row["org_id"], row["status"]) == (run["run_id"], ORG_A, "completed")
    assert row["pipeline_run_id"] == run["pipeline_run_id"] and row["worker_id"].startswith("inline:")
    assert row["lease_expires_at"] is None

    path = f"/api/v1/processing-runs/{run['run_id']}"
    assert call("GET", path).json() == run
    assert call("GET", path, "b_member").status_code == 404  # RLS: another organization sees nothing
    assert call("GET", path, "provider").status_code == 200
    listed = "/api/v1/engagements/ENG-RUNS/processing-runs"
    assert [r["run_id"] for r in call("GET", listed).json()["items"]] == [run["run_id"]]
    assert call("GET", listed, "b_member").json()["items"] == []


def test_the_older_endpoint_records_its_read_too(document: dict) -> None:
    response = call("POST", f"/api/v1/documents/{document['document_id']}/pipeline/process",
                    body={"canonical_type_id_override": "CT-S1-FUELQTY", "persist_run": True})
    assert response.status_code == 200, response.text
    pipeline_run = response.json()["pipeline_run"]
    [row] = asyncio.run(_admin("SELECT * FROM s1_processing_runs"))
    assert (row["run_id"], row["status"], row["pipeline_run_id"]) == (
        pipeline_run["processing_run_id"], "completed", pipeline_run["pipeline_run_id"])
