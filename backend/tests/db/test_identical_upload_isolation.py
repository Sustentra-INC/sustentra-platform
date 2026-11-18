"""The same bytes uploaded again never bring an earlier read, date or file with them (N39).

Everything runs through the real app with the Postgres S1 stores (documents, files, pipeline runs,
extraction results, processing runs) as ``app_user``, so RLS applies. Two organizations, three
engagements (two in org A, one in org B), one set of bytes uploaded to all of them, and twice into
one engagement. Each document must have its own id, its own upload time, its own evidence and its
own read; another organization sees none of it, even though the files share a cache folder (named
by the checksum) on this server.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import time
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
from backend.app.core.s1_scope import S1Scope, scoped
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
ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000039e1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000039e1")
TOKENS = {
    "a_member": (uuid.UUID("aaaaaaaa-2222-0000-0000-0000000039e1"), ORG_A, "member@acme.test", "org_member"),
    "b_member": (uuid.UUID("bbbbbbbb-2222-0000-0000-0000000039e1"), ORG_B, "member@beta.test", "org_member"),
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
    await _admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'ident-acme'), "
                 "($2, 'Beta', 'ident-beta')", ORG_A, ORG_B)
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


def upload(token: str, engagement_id: str, name: str = "bill.txt", content: bytes = BILL) -> dict:
    response = call("POST", f"/api/v1/engagements/{engagement_id}/documents/upload", token,
                    files={"file": (name, content, "text/plain")})
    assert response.status_code == 200, response.text
    time.sleep(0.01)  # distinct upload times
    return response.json()


def read(token: str, document_id: str) -> dict:
    response = call("POST", f"/api/v1/documents/{document_id}/processing-runs", token,
                    json={"canonical_type_id_override": "CT-S1-FUELQTY"})
    assert response.status_code in (200, 202), response.text
    assert response.json()["status"] == "completed", response.text
    latest = call("GET", f"/api/v1/documents/{document_id}/extraction-result/latest", token)
    assert latest.status_code == 200, latest.text
    return latest.json()


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def test_identical_bytes_in_two_engagements_of_one_org_get_their_own_reads(stores: Any) -> None:
    first, second = engagement("a_member", "FY24 first"), engagement("a_member", "FY24 second")
    doc1, doc2 = upload("a_member", first), upload("a_member", second)
    assert doc1["document_id"] != doc2["document_id"] and doc1["evidence_id"] != doc2["evidence_id"]
    assert (doc1["engagement_id"], doc2["engagement_id"]) == (first, second)
    assert parse(doc2["uploaded_at"]) > parse(doc1["uploaded_at"])
    assert doc1["storage_uri"] != doc2["storage_uri"]

    read1 = read("a_member", doc1["document_id"])
    read2 = read("a_member", doc2["document_id"])  # the same bytes, read later
    assert read1["document_id"] == doc1["document_id"] and read2["document_id"] == doc2["document_id"]
    assert read1["evidence_id"] == doc1["evidence_id"] and read2["evidence_id"] == doc2["evidence_id"]
    assert read1["pipeline_run_id"] != read2["pipeline_run_id"]
    assert parse(read2["created_at"]) > parse(read1["created_at"])
    # Every read happened after its own upload: nothing carries an earlier date.
    assert parse(read1["created_at"]) >= parse(doc1["uploaded_at"])
    assert parse(read2["created_at"]) >= parse(doc2["uploaded_at"])
    assert read1["items"] and len(read1["items"]) == len(read2["items"])
    for one, two in zip(read1["items"], read2["items"], strict=True):
        assert one["candidate_id"] != two["candidate_id"] if "candidate_id" in one else True
        assert doc1["document_id"] not in str(two) and doc2["document_id"] not in str(one)

    # Each engagement lists only its own document, with its own upload time.
    for engagement_id, doc in ((first, doc1), (second, doc2)):
        listed = call("GET", f"/api/v1/engagements/{engagement_id}/documents").json()["items"]
        assert [(d["document_id"], d["uploaded_at"]) for d in listed] == [(doc["document_id"], doc["uploaded_at"])]


def test_the_same_bytes_twice_in_one_engagement_are_two_documents_with_two_reads(stores: Any) -> None:
    eng = engagement("a_member", "FY24 twice")
    one, two = upload("a_member", eng), upload("a_member", eng)
    assert one["document_id"] != two["document_id"] and one["evidence_id"] != two["evidence_id"]
    assert one["storage_uri"] != two["storage_uri"]  # one folder per document
    read_one, read_two = read("a_member", one["document_id"]), read("a_member", two["document_id"])
    assert read_one["pipeline_run_id"] != read_two["pipeline_run_id"]
    assert parse(read_two["created_at"]) > parse(read_one["created_at"]) >= parse(one["uploaded_at"])
    listed = call("GET", f"/api/v1/engagements/{eng}/documents").json()["items"]
    assert {d["document_id"]: d["uploaded_at"] for d in listed} == {
        one["document_id"]: one["uploaded_at"], two["document_id"]: two["uploaded_at"]}


def test_another_org_cannot_see_or_reuse_a_read_of_identical_bytes(stores: Any) -> None:
    eng_a, eng_b = engagement("a_member", "Acme FY24"), engagement("b_member", "Beta FY24")
    doc_a = upload("a_member", eng_a)
    read_a = read("a_member", doc_a["document_id"])
    doc_b = upload("b_member", eng_b)  # the same bytes, to org B, after org A's read exists
    assert doc_b["document_id"] != doc_a["document_id"] and doc_b["org_id"] == str(ORG_B)
    assert parse(doc_b["uploaded_at"]) > parse(read_a["created_at"])

    # Org B has no read yet: org A's read of the same bytes is not reused.
    assert call("GET", f"/api/v1/documents/{doc_b['document_id']}/extraction-result/latest", "b_member").status_code == 404
    read_b = read("b_member", doc_b["document_id"])
    assert read_b["pipeline_run_id"] != read_a["pipeline_run_id"]
    assert parse(read_b["created_at"]) >= parse(doc_b["uploaded_at"]) > parse(read_a["created_at"])

    # Neither org can reach the other's document, read, file, run or engagement.
    for token, other in (("b_member", doc_a), ("a_member", doc_b)):
        d = other["document_id"]
        assert call("GET", f"/api/v1/documents/{d}", token).status_code == 404
        assert call("GET", f"/api/v1/documents/{d}/extraction-result/latest", token).status_code == 404
        assert call("GET", f"/api/v1/documents/{d}/download", token).status_code == 404
        assert call("GET", f"/api/v1/documents/{d}/content", token).status_code == 404
        assert call("POST", f"/api/v1/documents/{d}/processing-runs", token, json={}).status_code == 404
    assert call("GET", f"/api/v1/engagements/{eng_a}/documents", "b_member").json()["items"] == []
    assert call("GET", f"/api/v1/engagements/{eng_b}/documents", "a_member").json()["items"] == []
    for token, engagement_id in (("b_member", eng_a), ("a_member", eng_b)):  # nor can it add to it
        response = call("POST", f"/api/v1/engagements/{engagement_id}/documents/upload", token,
                        files={"file": ("bill.txt", BILL, "text/plain")})
        assert response.status_code == 404


def test_a_warm_file_cache_never_serves_one_org_the_others_file(stores: Any) -> None:
    eng_a, eng_b = engagement("a_member", "Acme FY24"), engagement("b_member", "Beta FY24")
    doc_a, doc_b = upload("a_member", eng_a), upload("b_member", eng_b)
    # Org A's file is cached on this server (named by checksum); org B's identical bytes share the folder.
    with scoped(S1Scope.tenant(ORG_A)):
        cached_a = stores.resolve_storage_uri(doc_a["storage_uri"])
    with scoped(S1Scope.tenant(ORG_B)):
        assert stores.resolve_storage_uri(doc_b["storage_uri"]).read_bytes() == BILL
        with pytest.raises(ValueError):  # a warm cache is not a way in: the row is looked up under RLS first
            stores.resolve_storage_uri(doc_a["storage_uri"])
    assert cached_a.read_bytes() == BILL
    assert call("GET", f"/api/v1/documents/{doc_a['document_id']}/download", "b_member").status_code == 404
    assert call("GET", f"/api/v1/documents/{doc_b['document_id']}/download", "b_member").content == BILL


def test_a_non_ascii_file_name_keeps_its_own_read_and_time(stores: Any) -> None:
    eng_a, eng_b = engagement("a_member", "Acme Zürich"), engagement("a_member", "Acme München")
    plain = upload("a_member", eng_a)
    first, second = upload("a_member", eng_a, NON_ASCII_NAME), upload("a_member", eng_b, NON_ASCII_NAME)
    assert first["document_id"] != second["document_id"] and first["storage_uri"] != second["storage_uri"]
    read_first, read_second = read("a_member", first["document_id"]), read("a_member", second["document_id"])
    assert read_first["pipeline_run_id"] != read_second["pipeline_run_id"]
    assert parse(second["uploaded_at"]) > parse(first["uploaded_at"])
    assert parse(read_first["created_at"]) >= parse(first["uploaded_at"])
    assert parse(read_second["created_at"]) >= parse(second["uploaded_at"])
    shown = call("GET", f"/api/v1/documents/{first['document_id']}").json()
    assert shown["uploaded_at"] == first["uploaded_at"] and shown["uploaded_at"] != plain["uploaded_at"]
    assert call("GET", f"/api/v1/documents/{second['document_id']}/download").content == BILL
