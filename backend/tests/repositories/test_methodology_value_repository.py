from pathlib import Path

import pytest

from backend.app.repositories.methodology_value_repository import (
    InMemoryMethodologyValueRepository,
    JsonlMethodologyValueRepository,
)


@pytest.fixture(params=["memory", "jsonl"])
def repository(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryMethodologyValueRepository()
    return JsonlMethodologyValueRepository(tmp_path / "methodology_values.jsonl")


def test_save_and_list_all(repository):
    repository.save(_record("mv-001"))
    repository.save(_record("mv-002", evidence_id="EV-2"))
    assert len(repository.list_all()) == 2


def test_list_by_engagement(repository):
    repository.save(_record("mv-001", engagement_id="ENG-1"))
    repository.save(_record("mv-002", engagement_id="ENG-2"))
    assert len(repository.list_by_engagement("ENG-2")) == 1


def test_list_by_evidence(repository):
    repository.save(_record("mv-001", evidence_id="EV-1"))
    repository.save(_record("mv-002", evidence_id="EV-2"))
    assert len(repository.list_by_evidence("EV-1")) == 1


def test_list_by_approved_evidence(repository):
    repository.save(_record("mv-001", approved_evidence_id="approved-001"))
    repository.save(_record("mv-002", approved_evidence_id="approved-002"))
    assert len(repository.list_by_approved_evidence("approved-001")) == 1


def test_list_by_methodology_field(repository):
    repository.save(_record("mv-001", methodology_field_id="S1-STC-010"))
    repository.save(_record("mv-002", methodology_field_id="S1-MOB-010"))
    assert len(repository.list_by_methodology_field("S1-MOB-010")) == 1


def test_get_by_id(repository):
    repository.save(_record("mv-001"))
    assert repository.get_by_id("mv-001") is not None
    assert repository.get_by_id("missing") is None


def test_replace_for_approved_evidence(repository):
    repository.save(_record("mv-old", approved_evidence_id="approved-001"))
    repository.save(_record("mv-other", approved_evidence_id="approved-002"))

    saved = repository.replace_for_approved_evidence(
        "approved-001",
        [_record("mv-new", approved_evidence_id="approved-001")],
    )

    assert [record["methodology_value_id"] for record in saved] == ["mv-new"]
    assert {
        record["methodology_value_id"] for record in repository.list_all()
    } == {"mv-new", "mv-other"}


def test_jsonl_persistence_survives_reinstantiation(tmp_path: Path):
    path = tmp_path / "methodology_values.jsonl"
    first = JsonlMethodologyValueRepository(path)
    first.save(_record("mv-001"))
    first.save(_record("mv-002"))

    second = JsonlMethodologyValueRepository(path)
    assert len(second.list_all()) == 2
    assert second.get_by_id("mv-002") is not None


def _record(
    methodology_value_id: str,
    *,
    engagement_id: str = "ENG-1",
    evidence_id: str = "EV-1",
    approved_evidence_id: str = "approved-001",
    methodology_field_id: str = "S1-STC-010",
) -> dict:
    return {
        "methodology_value_id": methodology_value_id,
        "engagement_id": engagement_id,
        "evidence_id": evidence_id,
        "document_id": "DOC-1",
        "methodology_field_id": methodology_field_id,
        "data_schema_field": "quantity_combusted",
        "grain": "fuel_record",
        "record_key": "EV-1::DOC-1::activity_quantity",
        "approved_value": 28100,
        "approved_unit": "MMBtu",
        "source_reference": {"text_snippet": "Total Usage"},
        "approved_evidence_id": approved_evidence_id,
        "review_decision_id": "review-001",
        "value_origin": "approved_evidence",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
