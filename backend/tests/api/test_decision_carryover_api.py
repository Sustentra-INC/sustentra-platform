"""S1-BE-014 at the API: the review screen's two reads and the methodology run honour a re-read."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.api import methodology as methodology_api
from backend.app.api import reviews as reviews_api
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.review_decision_service import ReviewDecisionService
from backend.tests.api.conftest import ORG_A, make_user
from backend.tests.services.test_decision_carryover import DOC, _decide, _read, FEB, JAN, MAR

QTY = f"candidate::EV-1::{DOC}::activity_quantity"


@pytest.fixture
def env(tmp_path: Path, act_as) -> Iterator[dict]:
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository(),
                                    clock=lambda: "2026-01-01T00:00:00+00:00")
    results = InMemoryExtractionResultRepository()
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=results)
    decisions = InMemoryReviewDecisionRepository()
    originals = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service,
                 reviews_api._service)
    documents_api.configure_services(upload_service=uploads, pipeline_service=pipeline, storage_service=storage)
    reviews_api.configure_service(ReviewDecisionService(repository=decisions))
    act_as("org_member", ORG_A)
    document = uploads.upload_document(engagement_id="ENG-1", file_name="Zürich Rechnung – Käserei.txt",
                                       content=b"Gas 58.92 MMBtu", mime_type="text/plain",
                                       document_role="source_evidence", uploaded_by="dev@example.com",
                                       org_id=str(ORG_A))

    def read(items: list[dict]) -> None:
        results.save({"document_id": document["document_id"], "evidence_id": "EV-1",
                      "canonical_type_id": "CT-S1-FUELQTY", "org_id": str(ORG_A), "candidate_count": len(items),
                      "items": items, "created_at": "2026-01-01T00:00:00+00:00"})

    def review(rows: list[dict]) -> None:
        for row in rows:
            decisions.save({**row, "document_id": document["document_id"], "org_id": str(ORG_A)})

    try:
        yield {"client": TestClient(app), "doc": document["document_id"], "read": read, "review": review}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])
        reviews_api.configure_service(originals[3])


def _remap(items: list[dict], doc_id: str) -> list[dict]:
    return [{**i, "document_id": doc_id} for i in items]


def test_the_review_screen_reads_say_review_it_again(env: dict) -> None:
    doc = env["doc"]
    env["review"](_remap(_decide(_read(JAN, MAR)), doc))
    env["read"](_remap(_read(MAR, FEB), doc))  # a re-read: March moved up, January became February
    client = env["client"]
    items = {i["candidate_id"]: i for i in client.get(f"/v1/documents/{doc}/extraction-result/latest").json()["items"]}
    assert items[f"{QTY}::r2"]["review_reread_changed"] is True  # February must be reviewed again
    assert "review_reread_changed" not in items[f"{QTY}::r1"]
    reviews = client.get(f"/v1/documents/{doc}/reviews").json()
    assert len(reviews) == 12  # the old decisions are all still there
    by_id = {r["candidate_id"]: r for r in reviews}
    assert by_id[f"{QTY}::r2"]["applies_to_candidate_id"] == f"{QTY}::r1"  # March's accept follows March
    assert by_id[f"{QTY}::r1"]["applies_to_candidate_id"] is None  # January's matches nothing now


def test_a_read_nobody_redid_answers_exactly_as_before(env: dict) -> None:
    doc = env["doc"]
    stored = _remap(_decide(_read(JAN, MAR)), doc)
    items = _remap(_read(JAN, MAR), doc)
    env["review"](stored)
    env["read"](items)
    client = env["client"]
    assert client.get(f"/v1/documents/{doc}/extraction-result/latest").json()["items"] == items
    returned = client.get(f"/v1/documents/{doc}/reviews").json()
    assert all("applies_to_candidate_id" not in r for r in returned) and len(returned) == len(stored)


def test_reviews_of_a_document_with_no_read_are_returned_as_stored(env: dict) -> None:
    env["review"](_remap(_decide(_read(JAN)), env["doc"]))
    assert len(env["client"].get(f"/v1/documents/{env['doc']}/reviews").json()) == 6


def test_methodology_persist_drops_fields_whose_decision_no_longer_applies(env: dict) -> None:
    doc = env["doc"]
    stored = _remap(_decide(_read(JAN, MAR)), doc)
    env["review"](stored)
    env["read"](_remap(_read(MAR, FEB), doc))
    january = next(d for d in stored if d["candidate_id"] == f"{QTY}::r1")
    march = next(d for d in stored if d["candidate_id"] == f"{QTY}::r2")
    approved = {"evidence_id": "EV-1", "fields": [
        {"field_name": "activity_quantity", "review_decision_id": january["review_decision_id"]},
        {"field_name": "activity_quantity", "review_decision_id": march["review_decision_id"]},
        {"field_name": "fuel_type", "review_decision_id": "rd-of-another-system"}]}
    kept = methodology_api._without_stale_fields(approved, make_user())["fields"]
    assert [f["review_decision_id"] for f in kept] == [march["review_decision_id"], "rd-of-another-system"]
