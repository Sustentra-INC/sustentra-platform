"""S1-BE-014 at the API: the review screen's two reads and the methodology run honour a re-read."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.api import evidence as evidence_api
from backend.app.api import methodology as methodology_api
from backend.app.api import reviews as reviews_api
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
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
    original_approved = evidence_api._service
    evidence_api.configure_service(ApprovedEvidenceService(
        review_repository=decisions, approved_repository=InMemoryApprovedEvidenceRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00"))
    act_as("org_member", ORG_A)
    document = uploads.upload_document(engagement_id="ENG-1", file_name="Zürich Rechnung – Käserei.txt",
                                       content=b"Gas 58.92 MMBtu", mime_type="text/plain",
                                       document_role="source_evidence", uploaded_by="dev@example.com",
                                       org_id=str(ORG_A))

    def read(items: list[dict], type_id: str | None = "CT-S1-FUELQTY", at: str = "2026-01-01T00:00:00+00:00") -> None:
        results.save({"document_id": document["document_id"], "evidence_id": "EV-1",
                      "canonical_type_id": type_id, "org_id": str(ORG_A), "candidate_count": len(items),
                      "items": items, "created_at": at})

    def review(rows: list[dict]) -> None:
        for row in rows:
            decisions.save({**row, "document_id": document["document_id"], "org_id": str(ORG_A)})

    try:
        yield {"client": TestClient(app), "doc": document["document_id"], "read": read, "review": review}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])
        reviews_api.configure_service(originals[3])
        evidence_api.configure_service(original_approved)


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


# --- a read as another document type: earlier decisions do not apply to its values -------------------------------
def _summary_then_stationary(env: dict, first_type: str | None = "CT-GHG-WORKBOOK") -> list[dict]:
    """The document was read as a summary document and its values accepted (January 1st); a move onto a stationary
    line then had it read as stationary fuel (February 1st): the very same fields, record indexes and values."""

    doc = env["doc"]
    stored = [{**d, "reviewed_at": "2026-01-01T00:00:00+00:00"} for d in _remap(_decide(_read(JAN, MAR)), doc)]
    env["read"](_remap(_read(JAN, MAR), doc), first_type, "2026-01-01T00:00:00+00:00")
    env["review"](stored)
    env["read"](_remap(_read(JAN, MAR), doc), "CT-S1-FUELQTY", "2026-02-01T00:00:00+00:00")
    return stored


def test_the_reviews_list_keeps_every_decision_but_none_applies_to_the_values_of_the_new_type(env: dict) -> None:
    stored = _summary_then_stationary(env)
    client, doc = env["client"], env["doc"]
    reviews = client.get(f"/v1/documents/{doc}/reviews").json()
    assert len(reviews) == len(stored)  # none removed
    assert all(r["applies_to_candidate_id"] is None for r in reviews)
    assert client.get(f"/v1/documents/{doc}/extraction-result/latest").status_code == 200


def test_a_decision_made_after_the_read_as_the_new_type_applies_as_usual(env: dict) -> None:
    _summary_then_stationary(env)
    doc = env["doc"]
    later = [{**d, "reviewed_at": "2026-03-01T00:00:00+00:00", "review_decision_id": d["review_decision_id"] + "-later"}
             for d in _remap(_decide(_read(JAN, MAR)), doc)]
    env["review"](later)
    reviews = env["client"].get(f"/v1/documents/{doc}/reviews").json()
    by_id = {r["review_decision_id"]: r for r in reviews}
    assert all(by_id[d["review_decision_id"]].get("applies_to_candidate_id", d["candidate_id"]) == d["candidate_id"]
               for d in later)  # a decision that applies to its own candidate is returned as stored
    assert all(by_id[k]["applies_to_candidate_id"] is None for k in by_id if not k.endswith("-later"))


def test_projecting_approved_evidence_ignores_decisions_made_before_the_read_as_another_type(env: dict) -> None:
    stored = _summary_then_stationary(env)
    projected = env["client"].post("/v1/evidence/EV-1/approved-evidence/project",
                                   json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"})
    assert projected.status_code == 200, projected.text
    assert projected.json()["approved_field_count"] == 0 and projected.json()["fields"] == []
    assert stored  # they are all still stored


def test_a_first_read_with_no_type_is_not_a_type_change(env: dict) -> None:
    _summary_then_stationary(env, first_type=None)
    reviews = env["client"].get(f"/v1/documents/{env['doc']}/reviews").json()
    assert all(r.get("applies_to_candidate_id", r["candidate_id"]) is not None for r in reviews)  # they still apply
    projected = env["client"].post("/v1/evidence/EV-1/approved-evidence/project",
                                   json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"})
    assert projected.status_code == 200 and projected.json()["approved_field_count"] > 0


def test_methodology_persist_drops_fields_decided_before_the_read_as_another_type(env: dict) -> None:
    stored = _summary_then_stationary(env)
    kept_id = stored[0]["review_decision_id"]
    approved = {"evidence_id": "EV-1", "fields": [
        {"field_name": "activity_quantity", "review_decision_id": kept_id},
        {"field_name": "fuel_type", "review_decision_id": "rd-of-another-system"}]}
    kept = methodology_api._without_stale_fields(approved, make_user())["fields"]
    assert [f["review_decision_id"] for f in kept] == ["rd-of-another-system"]
