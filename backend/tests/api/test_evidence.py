import pytest
from fastapi.testclient import TestClient

from backend.app.api import evidence as evidence_api
from backend.app.main import app
from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService


@pytest.fixture
def api_context():
    original = evidence_api._service
    review_repo = InMemoryReviewDecisionRepository()
    approved_repo = InMemoryApprovedEvidenceRepository()
    counter = {"n": 0}

    def id_factory(engagement_id: str, evidence_id: str) -> str:
        counter["n"] += 1
        return f"approved::{engagement_id}::{evidence_id}::{counter['n']:02d}"

    service = ApprovedEvidenceService(
        review_repository=review_repo,
        approved_repository=approved_repo,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )

    evidence_api.configure_service(service)
    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "review_repo": review_repo,
            }
    finally:
        evidence_api.configure_service(original)



def _review_decision(
    review_decision_id: str,
    field_name: str,
    *,
    decision: str = "accepted",
    evidence_id: str = "EV-1",
    document_id: str = "DOC-1",
    reviewed_at: str = "2026-01-01T00:00:00+00:00",
) -> dict:
    reviewed_value = 28100
    reviewed_unit = "MMBtu"
    if decision in {"rejected", "needs_more_evidence"}:
        reviewed_value = None
        reviewed_unit = None

    return {
        "review_decision_id": review_decision_id,
        "candidate_id": f"candidate::{evidence_id}::{document_id}::{field_name}",
        "evidence_id": evidence_id,
        "document_id": document_id,
        "field_name": field_name,
        "decision": decision,
        "reviewed_value": reviewed_value,
        "reviewed_unit": reviewed_unit,
        "reviewer_id": "reviewer-1",
        "reviewed_at": reviewed_at,
        "reviewer_note": None,
        "candidate_snapshot": {
            "candidate_id": f"candidate::{evidence_id}::{document_id}::{field_name}",
            "display_label": "Activity Quantity",
            "raw_value": "28,100 MMBtu",
            "confidence": 0.9,
            "validation_flags": [],
        },
        "source_reference": {
            "document_id": document_id,
            "text_snippet": "Total Usage 28,100 MMBtu",
        },
    }



def test_post_project_creates_approved_evidence_from_existing_reviews(api_context):
    client = api_context["client"]
    review_repo = api_context["review_repo"]
    review_repo.save(_review_decision("review-001", "activity_quantity", decision="accepted"))

    response = client.post(
        "/v1/evidence/EV-1/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"] == "EV-1"
    assert body["approved_field_count"] == 1
    field = body["fields"][0]
    assert field["approved_value"] == 28100
    assert field["approved_unit"] == "MMBtu"
    assert "reviewed_value" not in field
    assert "reviewed_unit" not in field



def test_get_latest_by_evidence_returns_latest_record(api_context):
    client = api_context["client"]
    review_repo = api_context["review_repo"]
    review_repo.save(_review_decision("review-001", "activity_quantity", decision="accepted"))

    projected = client.post(
        "/v1/evidence/EV-1/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    ).json()

    latest = client.get("/v1/evidence/EV-1/approved-evidence/latest")
    assert latest.status_code == 200
    assert latest.json()["approved_evidence_id"] == projected["approved_evidence_id"]



def test_get_latest_by_evidence_returns_404_when_none_exists(api_context):
    client = api_context["client"]
    response = client.get("/v1/evidence/EV-404/approved-evidence/latest")
    assert response.status_code == 404



def test_get_by_approved_evidence_id_works(api_context):
    client = api_context["client"]
    review_repo = api_context["review_repo"]
    review_repo.save(_review_decision("review-001", "activity_quantity", decision="accepted"))

    projected = client.post(
        "/v1/evidence/EV-1/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    ).json()

    response = client.get(f"/v1/approved-evidence/{projected['approved_evidence_id']}")
    assert response.status_code == 200
    assert response.json()["approved_evidence_id"] == projected["approved_evidence_id"]



def test_get_by_engagement_returns_projected_records(api_context):
    client = api_context["client"]
    review_repo = api_context["review_repo"]
    review_repo.save(
        _review_decision("review-001", "activity_quantity", decision="accepted", evidence_id="EV-1")
    )
    review_repo.save(
        _review_decision("review-002", "activity_quantity", decision="edited", evidence_id="EV-2")
    )

    client.post(
        "/v1/evidence/EV-1/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    )
    client.post(
        "/v1/evidence/EV-2/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-MOBFUEL"},
    )

    response = client.get("/v1/engagements/ENG-1/approved-evidence")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert all(item["engagement_id"] == "ENG-1" for item in body)



def test_post_project_returns_in_review_when_no_review_decisions_exist(api_context):
    client = api_context["client"]

    response = client.post(
        "/v1/evidence/EV-EMPTY/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "in_review"
    assert body["field_count"] == 0
    assert body["approved_field_count"] == 0



def test_post_project_returns_no_approved_fields_when_latest_are_non_approved(api_context):
    client = api_context["client"]
    review_repo = api_context["review_repo"]
    review_repo.save(_review_decision("review-001", "activity_quantity", decision="rejected"))

    response = client.post(
        "/v1/evidence/EV-1/approved-evidence/project",
        json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_status"] == "no_approved_fields"
    assert body["approved_field_count"] == 0
