from pathlib import Path

import pytest

from backend.app.repositories.evidence_repository import (
    InMemoryApprovedEvidenceRepository,
    JsonlApprovedEvidenceRepository,
)


def _approved_field(review_decision_id: str) -> dict:
    return {
        "field_name": "activity_quantity",
        "display_label": "Activity Quantity",
        "extracted_value": "28,100 MMBtu",
        "approved_value": 28100,
        "approved_unit": "MMBtu",
        "decision": "accepted",
        "source_reference": {"document_id": "DOC-1", "text_snippet": "Total Usage"},
        "review_decision_id": review_decision_id,
        "candidate_id": f"candidate-{review_decision_id}",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "confidence": 0.91,
        "validation_flags": [],
    }


def _record(
    approved_evidence_id: str,
    evidence_id: str = "EV-1",
    engagement_id: str = "ENG-1",
    document_id: str = "DOC-1",
) -> dict:
    return {
        "approved_evidence_id": approved_evidence_id,
        "evidence_id": evidence_id,
        "engagement_id": engagement_id,
        "document_id": document_id,
        "evidence_type": "CT-S1-FUELQTY",
        "review_status": "approved",
        "field_count": 1,
        "approved_field_count": 1,
        "fields": [_approved_field(f"review-{approved_evidence_id}")],
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_review_decision_ids": [f"review-{approved_evidence_id}"],
    }


@pytest.fixture(params=["memory", "jsonl"])
def repository(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryApprovedEvidenceRepository()
    return JsonlApprovedEvidenceRepository(tmp_path / "approved_evidence.jsonl")


def test_save_and_list_all(repository):
    repository.save(_record("approved-001"))
    repository.save(_record("approved-002", evidence_id="EV-2"))
    assert len(repository.list_all()) == 2


def test_list_by_engagement(repository):
    repository.save(_record("approved-001", engagement_id="ENG-1"))
    repository.save(_record("approved-002", engagement_id="ENG-2"))
    assert len(repository.list_by_engagement("ENG-2")) == 1


def test_list_by_evidence(repository):
    repository.save(_record("approved-001", evidence_id="EV-1"))
    repository.save(_record("approved-002", evidence_id="EV-2"))
    assert len(repository.list_by_evidence("EV-1")) == 1


def test_list_by_document(repository):
    repository.save(_record("approved-001", document_id="DOC-1"))
    repository.save(_record("approved-002", document_id="DOC-2"))
    assert len(repository.list_by_document("DOC-2")) == 1


def test_get_latest_by_evidence(repository):
    repository.save(_record("approved-001", evidence_id="EV-1"))
    repository.save(_record("approved-002", evidence_id="EV-1"))
    latest = repository.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["approved_evidence_id"] == "approved-002"


def test_get_by_id(repository):
    repository.save(_record("approved-001"))
    assert repository.get_by_id("approved-001") is not None
    assert repository.get_by_id("missing") is None


def test_jsonl_persistence_survives_reinstantiation(tmp_path: Path):
    path = tmp_path / "approved_evidence.jsonl"
    first = JsonlApprovedEvidenceRepository(path)
    first.save(_record("approved-001", evidence_id="EV-1"))
    first.save(_record("approved-002", evidence_id="EV-1"))

    second = JsonlApprovedEvidenceRepository(path)
    assert len(second.list_all()) == 2
    latest = second.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["approved_evidence_id"] == "approved-002"


def test_jsonl_uses_temporary_provided_path(tmp_path: Path):
    path = tmp_path / "nested" / "approved_evidence.jsonl"
    repository = JsonlApprovedEvidenceRepository(path)
    repository.save(_record("approved-001"))
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip()
