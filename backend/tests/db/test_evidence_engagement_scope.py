"""SEC-004: a client-supplied evidence id must belong to the engagement in the path, not just to the org.

Through the real app with the Postgres S1 stores as ``app_user`` (RLS on). Same org other engagement, another
org, a malformed id and non-ASCII ids all answer 404 "Evidence not found." and store nothing.

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
from backend.app.repositories.document_repository import PostgresDocumentRepository
from backend.app.repositories.extraction_result_repository import PostgresExtractionResultRepository
from backend.app.repositories.pipeline_repository import PostgresPipelineRunRepository
from backend.app.repositories.processing_run_repository import ProcessingRunRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.postgres_file_store import PostgresFileStore
from backend.app.services.sessions import SESSION_COOKIE

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORIGIN = "https://app.sustentra.test"
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000164e1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000164e1")
TOKENS = {
    "a_member": (uuid.UUID("aaaaaaaa-2222-0000-0000-0000000164e1"), ORG_A, "member@acme.test", "org_member"),
    "b_member": (uuid.UUID("bbbbbbbb-2222-0000-0000-0000000164e1"), ORG_B, "member@beta.test", "org_member"),
}
BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"
NON_ASCII_NAME = "Müller Käserei – Zürich 電気 CO₂ 90°F.txt"


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    await _admin("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
    await _admin("TRUNCATE s1_documents, s1_document_files, s1_pipeline_runs, s1_extraction_results, "
                 "s1_processing_runs")
    await _admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'evslot-acme'), "
                 "($2, 'Beta', 'evslot-beta')", ORG_A, ORG_B)
    now = datetime.now(UTC)
    for token, (user_id, org_id, email, role) in TOKENS.items():
        await _admin("INSERT INTO users (id, org_id, email, role) VALUES ($1, $2, $3, $4)", user_id, org_id, email, role)
        await _admin("INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at) "
                     "VALUES ($1, $2, $3, $4, $5, $4)", user_id, org_id, hash_token(token), now, now + timedelta(days=1))


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[Any]:
    limiter.reset()
    asyncio.run(_seed())
    engine = create_engine(to_sync_url(APP_URL or ""), pool_size=4, max_overflow=0)
    files = PostgresFileStore(cache_dir=tmp_path / "cache", engine=engine)
    uploads = DocumentUploadService(storage_service=files, document_repository=PostgresDocumentRepository(engine))
    pipeline = PipelineOrchestrationService(pipeline_repository=PostgresPipelineRunRepository(engine),
                                            extraction_result_repository=PostgresExtractionResultRepository(engine))
    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service,
                documents_api.current_run_repository())
    documents_api.configure_services(upload_service=uploads, pipeline_service=pipeline, storage_service=files,
                                     run_repository=ProcessingRunRepository(engine))
    try:
        yield files
    finally:
        documents_api.configure_services(upload_service=original[0], pipeline_service=original[1],
                                         storage_service=original[2], run_repository=original[3])
        engine.dispose()


async def _call(method: str, path: str, token: str, **kwargs: Any) -> Any:
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
            return await client.request(method, path, cookies={SESSION_COOKIE: token},
                                        headers={"Origin": ORIGIN}, **kwargs)
    finally:
        await engine.dispose()


def call(method: str, path: str, token: str = "a_member", **kwargs: Any) -> Any:
    return asyncio.run(_call(method, path, token, **kwargs))


def engagement(token: str, name: str) -> str:
    response = call("POST", "/api/v1/engagements", token, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(token: str, engagement_id: str, evidence_id: str | None = None, name: str = "bill.txt") -> Any:
    return call("POST", f"/api/v1/engagements/{engagement_id}/documents/upload", token,
                files={"file": (name, BILL, "text/plain")}, data={"evidence_id": evidence_id} if evidence_id else {})


def register(token: str, engagement_id: str, storage_uri: str, evidence_id: str | None) -> Any:
    return call("POST", f"/api/v1/engagements/{engagement_id}/documents", token,
                json={"file_name": "bill.txt", "mime_type": "text/plain", "storage_uri": storage_uri,
                      "document_role": "source_evidence", "evidence_id": evidence_id})


def stored(engagement_id: str, token: str = "a_member") -> int:
    return len(call("GET", f"/api/v1/engagements/{engagement_id}/documents", token).json()["items"])


def test_evidence_of_another_engagement_of_the_same_org_is_refused_and_nothing_is_stored(stores: Any) -> None:
    first, second = engagement("a_member", "FY24 first"), engagement("a_member", "FY24 second")
    seed = upload("a_member", first).json()
    refused = upload("a_member", second, seed["evidence_id"])
    assert (refused.status_code, refused.json()["detail"]) == (404, "Evidence not found.")
    assert stored(second) == 0 and stored(first) == 1
    registered = register("a_member", second, seed["storage_uri"], seed["evidence_id"])
    assert (registered.status_code, registered.json()["detail"]) == (404, "Evidence not found.")
    assert stored(second) == 0
    assert asyncio.run(_admin("SELECT count(*) AS n FROM s1_document_files"))[0]["n"] == 1  # no file was written


def test_the_engagements_own_evidence_id_still_attaches(stores: Any) -> None:
    eng = engagement("a_member", "FY24")
    seed = upload("a_member", eng).json()
    again = upload("a_member", eng, seed["evidence_id"])
    assert again.status_code == 200 and again.json()["evidence_id"] == seed["evidence_id"]
    registered = register("a_member", eng, seed["storage_uri"], seed["evidence_id"])
    assert registered.status_code == 200, registered.text
    assert stored(eng) == 3


def test_another_orgs_evidence_id_gives_the_same_answer(stores: Any) -> None:
    eng_a, eng_b = engagement("a_member", "Acme"), engagement("b_member", "Beta")
    seed = upload("a_member", eng_a).json()
    other_org = upload("b_member", eng_b, seed["evidence_id"])
    same_org = upload("a_member", engagement("a_member", "Acme two"), seed["evidence_id"])
    assert (other_org.status_code, other_org.json()) == (same_org.status_code, same_org.json())
    assert other_org.status_code == 404 and stored(eng_b, "b_member") == 0


@pytest.mark.parametrize("evidence_id", ["evidence::nope", "x" * 5000, "'; DROP TABLE s1_documents; --",
                                         "証拠::Müller Käserei – Zürich CO₂ 90°F", "a b\tc"])
def test_a_malformed_or_non_ascii_evidence_id_is_a_plain_404(stores: Any, evidence_id: str) -> None:
    eng = engagement("a_member", "FY24")
    response = upload("a_member", eng, evidence_id)
    assert (response.status_code, response.json()["detail"]) == (404, "Evidence not found.")
    assert stored(eng) == 0


def test_approved_evidence_projection_is_for_the_evidences_own_engagement(stores: Any) -> None:
    first, second = engagement("a_member", "FY24 first"), engagement("a_member", "FY24 second")
    seed = upload("a_member", first).json()
    path = f"/api/v1/evidence/{seed['evidence_id']}/approved-evidence/project"
    wrong = call("POST", path, "a_member", json={"engagement_id": second, "evidence_type": "utility_bill"})
    assert (wrong.status_code, wrong.json()["detail"]) == (404, "Evidence not found.")
    foreign = call("POST", path, "b_member", json={"engagement_id": first, "evidence_type": "utility_bill"})
    assert foreign.status_code == 404
