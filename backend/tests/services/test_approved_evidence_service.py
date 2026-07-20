import copy

import pytest

from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService


class StubReviewRepository:
    def __init__(self, decisions: list[dict]) -> None:
        self._decisions = [copy.deepcopy(item) for item in decisions]
        self.calls: list[str] = []

    def list_by_evidence(self, evidence_id: str) -> list[dict]:
        self.calls.append(evidence_id)
        return [
            copy.deepcopy(item)
            for item in self._decisions
            if item.get("evidence_id") == evidence_id
        ]



def _make_service(review_repository=None) -> ApprovedEvidenceService:
    counter = {"n": 0}

    def id_factory(engagement_id: str, evidence_id: str) -> str:
        counter["n"] += 1
        return f"approved::{engagement_id}::{evidence_id}::{counter['n']:02d}"

    return ApprovedEvidenceService(
        review_repository=review_repository,
        approved_repository=InMemoryApprovedEvidenceRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )



def _review_decision(
    review_decision_id: str,
    field_name: str,
    *,
    decision: str = "accepted",
    reviewed_at: str = "2026-01-01T00:00:00+00:00",
    reviewed_value=28100,
    reviewed_unit: str | None = "MMBtu",
    evidence_id: str = "EV-1",
    document_id: str = "DOC-1",
    display_label: str = "Activity Quantity",
    raw_value: str = "28,100 MMBtu",
    confidence: float | None = 0.91,
    validation_flags: list[str] | None = None,
) -> dict:
    if validation_flags is None:
        validation_flags = []

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
            "display_label": display_label,
            "raw_value": raw_value,
            "confidence": confidence,
            "validation_flags": validation_flags,
        },
        "source_reference": {
            "document_id": document_id,
            "text_snippet": "Total Usage 28,100 MMBtu",
        },
    }



def test_accepted_review_decision_becomes_approved_field():
    service = _make_service()
    result = service.project_from_review_decisions(
        [_review_decision("review-001", "activity_quantity", decision="accepted")],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["approved_field_count"] == 1
    assert result["fields"][0]["decision"] == "accepted"
    assert result["fields"][0]["approved_value"] == 28100



def test_edited_review_decision_becomes_approved_field():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision(
                "review-001",
                "activity_quantity",
                decision="edited",
                reviewed_value=30000,
            )
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["approved_field_count"] == 1
    assert result["fields"][0]["decision"] == "edited"
    assert result["fields"][0]["approved_value"] == 30000



def test_rejected_latest_decision_is_excluded_from_fields():
    service = _make_service()
    result = service.project_from_review_decisions(
        [_review_decision("review-001", "activity_quantity", decision="rejected")],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["approved_field_count"] == 0
    assert result["fields"] == []



def test_needs_more_evidence_latest_decision_is_excluded_from_fields():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision(
                "review-001", "activity_quantity", decision="needs_more_evidence"
            )
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["approved_field_count"] == 0
    assert result["fields"] == []



def test_latest_decision_per_field_wins_by_timestamp_and_input_order():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision(
                "review-001",
                "activity_quantity",
                decision="accepted",
                reviewed_value=28100,
                reviewed_at="2026-01-01T00:00:00+00:00",
            ),
            _review_decision(
                "review-002",
                "activity_quantity",
                decision="edited",
                reviewed_value=30000,
                reviewed_at="2026-01-01T00:00:00+00:00",
            ),
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["field_count"] == 1
    assert result["approved_field_count"] == 1
    assert result["fields"][0]["review_decision_id"] == "review-002"
    assert result["fields"][0]["approved_value"] == 30000



def test_later_rejected_removes_earlier_accepted_field():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision(
                "review-001",
                "activity_quantity",
                decision="accepted",
                reviewed_at="2026-01-01T00:00:00+00:00",
            ),
            _review_decision(
                "review-002",
                "activity_quantity",
                decision="rejected",
                reviewed_at="2026-01-02T00:00:00+00:00",
            ),
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["field_count"] == 1
    assert result["approved_field_count"] == 0
    assert result["fields"] == []
    assert result["review_status"] == "no_approved_fields"



def test_mixed_accepted_and_rejected_latest_decisions_are_partially_approved():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision("review-001", "activity_quantity", decision="accepted"),
            _review_decision("review-002", "fuel_type", decision="rejected"),
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["review_status"] == "partially_approved"
    assert result["field_count"] == 2
    assert result["approved_field_count"] == 1



def test_all_accepted_or_edited_latest_decisions_are_approved():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision("review-001", "activity_quantity", decision="accepted"),
            _review_decision("review-002", "fuel_type", decision="edited", reviewed_value="Natural Gas"),
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["review_status"] == "approved"
    assert result["approved_field_count"] == 2



def test_zero_approved_fields_status_becomes_no_approved_fields():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision("review-001", "activity_quantity", decision="rejected"),
            _review_decision("review-002", "fuel_type", decision="needs_more_evidence"),
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["review_status"] == "no_approved_fields"
    assert result["approved_field_count"] == 0



def test_empty_review_decision_list_status_becomes_in_review():
    service = _make_service()
    result = service.project_from_review_decisions(
        [],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["review_status"] == "in_review"
    assert result["field_count"] == 0
    assert result["approved_field_count"] == 0



def test_source_reference_is_preserved():
    service = _make_service()
    source_reference = {
        "document_id": "DOC-1",
        "text_snippet": "Total Usage 28,100 MMBtu",
        "page_number": 3,
    }
    decision = _review_decision("review-001", "activity_quantity")
    decision["source_reference"] = source_reference

    result = service.project_from_review_decisions(
        [decision],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["fields"][0]["source_reference"] == source_reference



def test_candidate_snapshot_values_are_carried_to_output():
    service = _make_service()
    result = service.project_from_review_decisions(
        [
            _review_decision(
                "review-001",
                "activity_quantity",
                display_label="Metered Activity Quantity",
                raw_value="28,100 MMBtu",
                confidence=0.77,
                validation_flags=["normalized_from_comma_value"],
            )
        ],
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    field = result["fields"][0]
    assert field["display_label"] == "Metered Activity Quantity"
    assert field["extracted_value"] == "28,100 MMBtu"
    assert field["confidence"] == 0.77
    assert field["validation_flags"] == ["normalized_from_comma_value"]



def test_input_review_decisions_are_not_mutated():
    service = _make_service()
    decisions = [_review_decision("review-001", "activity_quantity", decision="accepted")]
    snapshot = copy.deepcopy(decisions)

    service.project_from_review_decisions(
        decisions,
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert decisions == snapshot



def test_mixed_evidence_id_raises_value_error():
    service = _make_service()
    with pytest.raises(ValueError):
        service.project_from_review_decisions(
            [
                _review_decision("review-001", "activity_quantity", evidence_id="EV-1"),
                _review_decision("review-002", "fuel_type", evidence_id="EV-2"),
            ],
            engagement_id="ENG-1",
            evidence_type="CT-S1-FUELQTY",
        )



def test_mixed_document_id_raises_value_error():
    service = _make_service()
    with pytest.raises(ValueError):
        service.project_from_review_decisions(
            [
                _review_decision("review-001", "activity_quantity", document_id="DOC-1"),
                _review_decision("review-002", "fuel_type", document_id="DOC-2"),
            ],
            engagement_id="ENG-1",
            evidence_type="CT-S1-FUELQTY",
        )



def test_project_by_evidence_reads_from_review_repository():
    decisions = [_review_decision("review-001", "activity_quantity", evidence_id="EV-1")]
    review_repo = StubReviewRepository(decisions)
    service = _make_service(review_repository=review_repo)

    result = service.project_by_evidence(
        evidence_id="EV-1",
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert review_repo.calls == ["EV-1"]
    assert result["evidence_id"] == "EV-1"
    assert result["approved_field_count"] == 1



def test_project_by_evidence_without_reviews_returns_in_review_aggregate():
    review_repo = StubReviewRepository([])
    service = _make_service(review_repository=review_repo)

    result = service.project_by_evidence(
        evidence_id="EV-404",
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    assert result["review_status"] == "in_review"
    assert result["field_count"] == 0
    assert result["approved_field_count"] == 0
    assert result["fields"] == []
