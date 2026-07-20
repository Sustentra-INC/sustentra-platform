import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.domain.evidence import ApprovedEvidence

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "approved_evidence.schema.json"


def _field(**overrides) -> dict:
    base = {
        "field_name": "activity_quantity",
        "display_label": "Activity Quantity",
        "extracted_value": "28,100 MMBtu",
        "approved_value": 28100,
        "approved_unit": "MMBtu",
        "decision": "accepted",
        "source_reference": {"document_id": "DOC-1", "text_snippet": "Total Usage"},
        "review_decision_id": "review-001",
        "candidate_id": "candidate-001",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "confidence": 0.91,
        "validation_flags": [],
    }
    base.update(overrides)
    return base


def _approved_evidence(**overrides) -> dict:
    base = {
        "approved_evidence_id": "approved::ENG-1::EV-1::abc123",
        "evidence_id": "EV-1",
        "engagement_id": "ENG-1",
        "document_id": "DOC-1",
        "evidence_type": "CT-S1-FUELQTY",
        "review_status": "approved",
        "field_count": 1,
        "approved_field_count": 1,
        "fields": [_field()],
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_review_decision_ids": ["review-001"],
    }
    base.update(overrides)
    return base


def test_schema_is_valid_json():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == "ApprovedEvidence"
    assert schema["additionalProperties"] is False


def test_schema_decision_enum_is_accepted_or_edited_only():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    item_props = schema["properties"]["fields"]["items"]["properties"]
    assert set(item_props["decision"]["enum"]) == {"accepted", "edited"}


def test_model_accepts_valid_approved_evidence():
    model = ApprovedEvidence(**_approved_evidence())
    assert model.review_status == "approved"
    assert model.approved_field_count == 1
    assert model.fields[0].approved_value == 28100


def test_invalid_review_status_fails():
    with pytest.raises(ValidationError):
        ApprovedEvidence(**_approved_evidence(review_status="review_complete"))


def test_invalid_field_decision_fails():
    with pytest.raises(ValidationError):
        ApprovedEvidence(**_approved_evidence(fields=[_field(decision="invalid")]))


def test_rejected_and_needs_more_evidence_are_not_valid_field_decisions():
    with pytest.raises(ValidationError):
        ApprovedEvidence(**_approved_evidence(fields=[_field(decision="rejected")]))

    with pytest.raises(ValidationError):
        ApprovedEvidence(
            **_approved_evidence(fields=[_field(decision="needs_more_evidence")])
        )


def test_required_fields_are_enforced():
    payload = _approved_evidence()
    del payload["created_at"]

    with pytest.raises(ValidationError):
        ApprovedEvidence(**payload)
