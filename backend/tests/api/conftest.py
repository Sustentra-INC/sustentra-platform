"""Shared API-test helpers for SEC-001 (session + org scoping on the S1 routes).

``act_as(role, org_id)`` signs the TestClient in as a user by overriding
``get_current_user``; the S1 route modules listed in ``_S1_MODULES`` are signed in
as an org-A member by default, with the evidence ids they use owned by org A.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import pytest

from backend.app.api import documents as documents_api
from backend.app.api.engagements import require_open_engagement
from backend.app.core.auth import CurrentUser, get_current_user
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService

ORG_A = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
ORG_B = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")

# Existing S1 route tests that predate SEC-001: signed in as an org-A member.
_S1_MODULES = {"test_documents", "test_evidence", "test_methodology", "test_pipeline", "test_reviews"}
# Evidence ids those tests use, owned by org A.
_SEEDED_EVIDENCE = ("EV-1", "EV-2", "EV-9", "EV-123", "EV-PIPE", "EV-STATUS", "EV-EMPTY")


def make_user(role: str = "org_member", org_id: uuid.UUID | None = ORG_A) -> CurrentUser:
    if role == "provider_admin":
        org_id = None
    label = role if org_id is None else f"{role}.{str(org_id)[:8]}"
    return CurrentUser(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"user:{label}"),
        email=f"{label}@example.com",
        first_name=None,
        last_name=None,
        full_name=None,
        role=role,
        org_id=org_id,
        org_slug=None if org_id is None else f"org-{str(org_id)[:8]}",
        session_id=uuid.uuid4(),
    )


@pytest.fixture
def act_as() -> Iterator[Callable[..., CurrentUser]]:
    """Sign requests in as ``make_user(role, org_id)``; ``act_as(None)`` signs out."""

    def sign_in(role: str | None = "org_member", org_id: uuid.UUID | None = ORG_A) -> CurrentUser | None:
        if role is None:
            app.dependency_overrides.pop(get_current_user, None)
            return None
        user = make_user(role, org_id)
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    try:
        yield sign_in  # type: ignore[misc]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def owned_upload_service(tmp_path, documents: list[dict] | None = None) -> DocumentUploadService:
    repository = InMemoryDocumentRepository()
    for document in documents or []:
        repository.save(document)
    return DocumentUploadService(
        storage_service=LocalStorageService(tmp_path / "uploads"),
        document_repository=repository,
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )


def seeded_document(evidence_id: str, org_id: uuid.UUID | None = ORG_A, document_id: str = "DOC-1") -> dict:
    return {
        "document_id": document_id,
        "engagement_id": "ENG-1",
        "evidence_id": evidence_id,
        "file_name": "bill.pdf",
        "mime_type": "application/pdf",
        "storage_uri": f"local-data/uploads/{org_id}/ENG-1/{evidence_id}/bill.pdf",
        "document_role": "source_evidence",
        "document_type": None,
        "uploaded_by": "seed@example.com",
        "uploaded_at": "2026-01-01T00:00:00+00:00",
        "processing_status": "completed",
        "org_id": str(org_id) if org_id else None,
    }


@pytest.fixture(autouse=True)
def _s1_signed_in(request: pytest.FixtureRequest, tmp_path) -> Iterator[None]:
    module = request.module.__name__.rsplit(".", 1)[-1]
    if module not in _S1_MODULES:
        yield
        return
    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    service = owned_upload_service(tmp_path, [seeded_document(ev) for ev in _SEEDED_EVIDENCE])
    documents_api.configure_services(upload_service=service)
    app.dependency_overrides[get_current_user] = lambda: make_user("org_member", ORG_A)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        documents_api.configure_services(
            upload_service=original[0], pipeline_service=original[1], storage_service=original[2]
        )


@pytest.fixture(autouse=True)
def _engagements_exist() -> Iterator[None]:
    """API tests use engagement ids like ENG-1 that are not rows in Postgres: treat
    every engagement as an existing, active one of the caller's org. The real check
    (require_open_engagement) is covered against the database in tests/db."""

    app.dependency_overrides[require_open_engagement] = lambda: {"status": "active"}
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_open_engagement, None)
