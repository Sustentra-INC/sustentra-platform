import pytest
from fastapi.testclient import TestClient

from backend.app.api import reviews
from backend.app.main import app
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.review_decision_service import ReviewDecisionService
from backend.tests.api.conftest import ORG_A, make_user


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
    # the reviewer is the signed-in user, not the client-supplied reviewer_id (SEC-001)
    assert body["reviewer_id"] == make_user().email
    assert body["org_id"] == str(ORG_A)


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
    assert body["reviewer_id"] == make_user().email
    assert "reviewed_by" not in body


def test_put_review_adds_one_audit_event_with_ids_only():
    events = []
    original = reviews._service
    reviews.configure_service(
        ReviewDecisionService(repository=InMemoryReviewDecisionRepository(), audit_writer=events.append)
    )
    try:
        response = TestClient(app).put(
            "/v1/evidence/EV-1/fields/activity_quantity/review",
            json={"candidate": _candidate(), "decision": "edited", "reviewed_value": 31337, "reviewed_unit": "kWh",
                  "reviewer_note": "secret note"},
        )
    finally:
        reviews.configure_service(original)
    assert response.status_code == 200
    assert len(events) == 1
    event = events[0]
    user = make_user()
    assert event["event_type"] == "review_value_edited"
    assert (event["org_id"], event["actor_user_id"], event["actor_role"]) == (str(ORG_A), user.id, "org_member")
    assert (event["target_type"], event["target_id"]) == ("engagement", "ENG-1")
    assert event["metadata"]["document_id"] == "DOC-1" and event["metadata"]["decision"] == "edited"
    flat = str(event)
    assert "31337" not in flat and "kWh" not in flat and "secret note" not in flat and "bill.pdf" not in flat


def _reject(client, note, **extra):
    return client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "rejected", "reviewer_note": note, **extra},
    )


def test_reject_stores_the_reason_who_and_when(client):
    response = _reject(client, "  Wrong meter: this is the neighbour's bill  ")
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "rejected"
    assert body["reviewed_value"] is None and body["reviewed_unit"] is None
    assert body["reviewer_note"] == "Wrong meter: this is the neighbour's bill"
    assert body["reviewer_id"] == make_user().email
    assert body["reviewed_at"] == "2026-01-01T00:00:00+00:00"
    # and it reads back, with the reason, from the document's decisions
    listed = client.get("/v1/documents/DOC-1/reviews").json()
    assert listed[-1]["decision"] == "rejected" and listed[-1]["reviewer_note"].startswith("Wrong meter")


@pytest.mark.parametrize("note", [None, "", "   ", "\n\t"])
def test_reject_without_a_reason_is_refused_and_nothing_is_stored(client, note):
    response = _reject(client, note)
    assert response.status_code == 400
    assert "reason" in response.json()["detail"].lower()
    assert client.get("/v1/evidence/EV-1/reviews").json() == []


def test_reject_reason_is_capped_at_500_characters(client):
    assert _reject(client, "x" * 500).status_code == 200
    assert _reject(client, "x" * 501).status_code == 422


def test_a_rejected_value_can_be_put_back_by_a_later_accept(client):
    assert _reject(client, "Not this one").status_code == 200
    again = client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted"},
    )
    assert again.status_code == 200
    latest = client.get("/v1/candidates/candidate::EV-1::DOC-1::activity_quantity/reviews/latest").json()
    assert latest["decision"] == "accepted"


def test_reject_with_a_value_is_refused(client):
    assert _reject(client, "no", reviewed_value=5).status_code == 400


def test_accept_does_not_need_a_reason(client):
    response = client.put(
        "/v1/evidence/EV-1/fields/activity_quantity/review",
        json={"candidate": _candidate(), "decision": "accepted"},
    )
    assert response.status_code == 200 and response.json()["reviewer_note"] is None
