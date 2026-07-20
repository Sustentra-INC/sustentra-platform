import copy

import pytest

from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.review_decision_service import ReviewDecisionService


def _candidate(**overrides):
    base = {
        "candidate_id": "candidate::EV-1::DOC-1::activity_quantity",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "field_name": "activity_quantity",
        "display_label": "Activity quantity",
        "raw_value": "28,100 MMBtu",
        "normalized_value": 28100,
        "unit": "MMBtu",
        "confidence": 0.9,
        "source_reference": {"document_id": "DOC-1", "text_snippet": "Total Usage 28,100 MMBtu"},
        "validation_flags": [],
    }
    base.update(overrides)
    return base


def _service():
    return ReviewDecisionService(
        repository=InMemoryReviewDecisionRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda candidate: "review-test-001",
    )


def test_accepted_uses_candidate_value_and_unit():
    record = _service().submit_decision(_candidate(), "accepted", "reviewer-1")
    assert record["decision"] == "accepted"
    assert record["reviewed_value"] == 28100
    assert record["reviewed_unit"] == "MMBtu"
    assert record["reviewed_at"] == "2026-01-01T00:00:00+00:00"


def test_accepted_allows_matching_value():
    record = _service().submit_decision(
        _candidate(), "accepted", "reviewer-1", reviewed_value=28100, reviewed_unit="MMBtu"
    )
    assert record["reviewed_value"] == 28100


def test_accepted_rejects_modified_value():
    with pytest.raises(ValueError):
        _service().submit_decision(_candidate(), "accepted", "reviewer-1", reviewed_value=999)


def test_edited_requires_reviewed_value():
    with pytest.raises(ValueError):
        _service().submit_decision(_candidate(), "edited", "reviewer-1")


def test_edited_stores_reviewer_value_and_unit():
    record = _service().submit_decision(
        _candidate(), "edited", "reviewer-1", reviewed_value=30000, reviewed_unit="MMBtu"
    )
    assert record["decision"] == "edited"
    assert record["reviewed_value"] == 30000
    assert record["reviewed_unit"] == "MMBtu"


def test_rejected_stores_no_value_or_unit():
    record = _service().submit_decision(_candidate(), "rejected", "reviewer-1")
    assert record["reviewed_value"] is None
    assert record["reviewed_unit"] is None


def test_rejected_with_value_raises():
    with pytest.raises(ValueError):
        _service().submit_decision(_candidate(), "rejected", "reviewer-1", reviewed_value=1)


def test_needs_more_evidence_stores_no_value_or_unit():
    record = _service().submit_decision(_candidate(), "needs_more_evidence", "reviewer-1")
    assert record["decision"] == "needs_more_evidence"
    assert record["reviewed_value"] is None
    assert record["reviewed_unit"] is None


def test_candidate_snapshot_and_source_reference_preserved():
    candidate = _candidate()
    record = _service().submit_decision(candidate, "accepted", "reviewer-1")
    assert record["candidate_snapshot"]["candidate_id"] == candidate["candidate_id"]
    assert record["source_reference"]["text_snippet"] == "Total Usage 28,100 MMBtu"


def test_input_candidate_is_not_mutated():
    candidate = _candidate()
    snapshot = copy.deepcopy(candidate)
    _service().submit_decision(candidate, "accepted", "reviewer-1")
    assert candidate == snapshot


def test_missing_required_candidate_field_raises():
    candidate = _candidate()
    del candidate["normalized_value"]
    with pytest.raises(ValueError):
        _service().submit_decision(candidate, "accepted", "reviewer-1")


def test_invalid_decision_raises():
    with pytest.raises(ValueError):
        _service().submit_decision(_candidate(), "approved", "reviewer-1")


def test_missing_reviewer_id_raises():
    with pytest.raises(ValueError):
        _service().submit_decision(_candidate(), "accepted", "")


def test_latest_decision_retrieval():
    service = ReviewDecisionService(
        repository=InMemoryReviewDecisionRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda candidate: "review-latest",
    )
    candidate = _candidate()
    service.submit_decision(candidate, "needs_more_evidence", "reviewer-1")
    service.submit_decision(candidate, "accepted", "reviewer-2")

    latest = service.get_latest_by_candidate(candidate["candidate_id"])
    assert latest["decision"] == "accepted"
    latest_field = service.get_latest_by_field("EV-1", "activity_quantity")
    assert latest_field["decision"] == "accepted"


def test_default_id_factory_is_deterministic_prefix():
    service = ReviewDecisionService(repository=InMemoryReviewDecisionRepository())
    record = service.submit_decision(_candidate(), "accepted", "reviewer-1")
    assert record["review_decision_id"].startswith("review::candidate::EV-1::DOC-1::activity_quantity::")
