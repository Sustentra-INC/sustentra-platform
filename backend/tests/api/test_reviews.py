import pytest
from fastapi.testclient import TestClient

from backend.app.api import reviews
from backend.app.main import app
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.review_decision_service import ReviewDecisionService


@pytest.fixture
def client():
    original = reviews._service
    reviews.configure_service(
        ReviewDecisionService(
            repository=InMemoryReviewDecisionRepository(),
            clock=lambda: "2026-01-01T00:00:00+00:00",
        )
    )
    try:
        yield TestClient(app)
    finally:
        reviews.configure_service(original)


def _candidate(evidence_id="EV-1", field_name="activity_quantity"):
    return {
        "candidate_id": f"candidate::{evidence_id}::DOC-1::{field_name}",
        "evidence_id": evidence_id,
        "document_id": "DOC-1",
        "field_name": field_name,
        "display_label": "Activity quantity",
        "raw_value": "28,100 MMBtu",
        "normalized_value": 28100,
        "unit": "MMBtu",
        "confidence": 0.9,
        "source_reference": {"document_id": "DOC-1", "text_snippet": "Total Usage 28,100 MMBtu"},
        "validation_flags": [],
    }


def test_put_review_stores_accepted_decision(client):
    response = client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewer_id": "reviewer-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "accepted"
    assert body["reviewed_value"] == 28100
    assert body["reviewed_unit"] == "MMBtu"
    assert "approved_value" not in body
    assert "approved_unit" not in body
    assert body["reviewer_id"] == "reviewer-1"


def test_put_review_stores_edited_decision(client):
    response = client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={
            "candidate": _candidate(),
            "decision": "edited",
            "reviewer_id": "reviewer-1",
            "reviewed_value": 30000,
            "reviewed_unit": "MMBtu",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "edited"
    assert body["reviewed_value"] == 30000


def test_evidence_id_mismatch_returns_400(client):
    response = client.put(
        "/v1/evidence/OTHER/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewer_id": "reviewer-1"},
    )
    assert response.status_code == 400


def test_field_name_mismatch_returns_400(client):
    response = client.put(
        "/v1/evidence/EV-1/fields/other_field/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewer_id": "reviewer-1"},
    )
    assert response.status_code == 400


def test_get_evidence_reviews(client):
    client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewer_id": "reviewer-1"},
    )
    response = client.get("/v1/evidence/EV-1/reviews")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_document_reviews(client):
    client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewer_id": "reviewer-1"},
    )
    response = client.get("/v1/documents/DOC-1/reviews")
    assert response.status_code == 200
    assert response.json()[0]["document_id"] == "DOC-1"


def test_get_latest_candidate_review(client):
    candidate = _candidate()
    client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": candidate, "decision": "needs_more_evidence", "reviewer_id": "r1"},
    )
    client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": candidate, "decision": "accepted", "reviewer_id": "r2"},
    )
    response = client.get(f"/v1/candidates/{candidate['candidate_id']}/reviews/latest")
    assert response.status_code == 200
    assert response.json()["decision"] == "accepted"


def test_get_latest_candidate_review_not_found(client):
    response = client.get("/v1/candidates/does-not-exist/reviews/latest")
    assert response.status_code == 404


def test_backward_compatible_aliases(client):
    response = client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted", "reviewed_by": "legacy-reviewer"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reviewer_id"] == "legacy-reviewer"
    assert "reviewed_by" not in body
