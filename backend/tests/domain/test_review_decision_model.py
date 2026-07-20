import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.domain.review import ReviewDecision

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "review_decision.schema.json"


def _valid_decision(**overrides) -> dict:
    base = {
        "review_decision_id": "review-test-001",
        "candidate_id": "candidate::EV-1::DOC-1::fuel_type",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "field_name": "fuel_type",
        "decision": "accepted",
        "reviewed_value": "Natural Gas",
        "reviewed_unit": None,
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "reviewer_note": None,
        "candidate_snapshot": {"candidate_id": "candidate::EV-1::DOC-1::fuel_type"},
        "source_reference": {"document_id": "DOC-1"},
    }
    base.update(overrides)
    return base


def test_schema_is_valid_json():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == "ReviewDecision"
    assert schema["additionalProperties"] is False


def test_schema_uses_reviewed_value_not_approved_value():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    required = set(schema["required"])
    assert "reviewed_value" in required
    assert "reviewed_unit" in required
    assert "reviewer_id" in required
    assert "approved_value" not in schema["properties"]
    assert "approved_unit" not in schema["properties"]


def test_schema_decision_enum():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["properties"]["decision"]["enum"]) == {
        "accepted",
        "rejected",
        "edited",
        "needs_more_evidence",
    }


def test_model_accepts_valid_decision():
    model = ReviewDecision(**_valid_decision())
    assert model.decision == "accepted"
    assert model.reviewer_id == "reviewer-1"


def test_model_rejects_invalid_decision_enum():
    with pytest.raises(ValidationError):
        ReviewDecision(**_valid_decision(decision="approved"))


def test_model_has_no_approved_value_field():
    fields = ReviewDecision.model_fields
    assert "reviewed_value" in fields
    assert "reviewed_unit" in fields
    assert "approved_value" not in fields
    assert "approved_unit" not in fields
