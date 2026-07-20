from pathlib import Path

import pytest

from backend.app.repositories.review_repository import (
    InMemoryReviewDecisionRepository,
    JsonlReviewDecisionRepository,
)


def _decision(review_decision_id, candidate_id, evidence_id="EV-1", document_id="DOC-1", field_name="fuel_type"):
    return {
        "review_decision_id": review_decision_id,
        "candidate_id": candidate_id,
        "evidence_id": evidence_id,
        "document_id": document_id,
        "field_name": field_name,
        "decision": "accepted",
        "reviewed_value": "Natural Gas",
        "reviewed_unit": None,
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "reviewer_note": None,
        "candidate_snapshot": {"candidate_id": candidate_id},
        "source_reference": {"document_id": document_id},
    }


@pytest.fixture(params=["memory", "jsonl"])
def repository(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryReviewDecisionRepository()
    return JsonlReviewDecisionRepository(tmp_path / "review_decisions.jsonl")


def test_save_and_list_all(repository):
    repository.save(_decision("r1", "c1"))
    repository.save(_decision("r2", "c2"))
    assert len(repository.list_all()) == 2


def test_list_by_evidence(repository):
    repository.save(_decision("r1", "c1", evidence_id="EV-1"))
    repository.save(_decision("r2", "c2", evidence_id="EV-2"))
    assert len(repository.list_by_evidence("EV-1")) == 1


def test_list_by_document(repository):
    repository.save(_decision("r1", "c1", document_id="DOC-1"))
    repository.save(_decision("r2", "c2", document_id="DOC-2"))
    assert len(repository.list_by_document("DOC-2")) == 1


def test_list_by_candidate(repository):
    repository.save(_decision("r1", "c1"))
    repository.save(_decision("r2", "c1"))
    repository.save(_decision("r3", "c2"))
    assert len(repository.list_by_candidate("c1")) == 2


def test_get_latest_by_candidate(repository):
    repository.save(_decision("r1", "c1"))
    repository.save(_decision("r2", "c1"))
    latest = repository.get_latest_by_candidate("c1")
    assert latest["review_decision_id"] == "r2"


def test_get_latest_by_field(repository):
    repository.save(_decision("r1", "c1", field_name="fuel_type"))
    repository.save(_decision("r2", "c2", field_name="fuel_type"))
    latest = repository.get_latest_by_field("EV-1", "fuel_type")
    assert latest["review_decision_id"] == "r2"


def test_get_latest_returns_none_when_absent(repository):
    assert repository.get_latest_by_candidate("missing") is None
    assert repository.get_latest_by_field("EV-1", "missing") is None


def test_jsonl_persistence_survives_reinstantiation(tmp_path: Path):
    path = tmp_path / "review_decisions.jsonl"
    first = JsonlReviewDecisionRepository(path)
    first.save(_decision("r1", "c1"))
    first.save(_decision("r2", "c1"))

    second = JsonlReviewDecisionRepository(path)
    assert len(second.list_all()) == 2
    assert second.get_latest_by_candidate("c1")["review_decision_id"] == "r2"


def test_jsonl_uses_provided_path(tmp_path: Path):
    path = tmp_path / "nested" / "review_decisions.jsonl"
    repository = JsonlReviewDecisionRepository(path)
    repository.save(_decision("r1", "c1"))
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip()
