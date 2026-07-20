from pathlib import Path

import pytest

from backend.app.repositories.pipeline_repository import (
    InMemoryPipelineRunRepository,
    JsonlPipelineRunRepository,
)


def _run(
    pipeline_run_id: str,
    engagement_id: str = "ENG-1",
    evidence_id: str = "EV-1",
) -> dict:
    return {
        "pipeline_run_id": pipeline_run_id,
        "engagement_id": engagement_id,
        "evidence_id": evidence_id,
        "document_id": "DOC-1",
        "processing_run_id": "PROC-1",
        "status": "completed",
        "stage_statuses": {
            "parse": "completed",
            "classify": "completed",
            "target_plan": "completed",
            "candidate_generation": "completed",
        },
        "input_file_name": "sample.txt",
        "canonical_type_id": "CT-S1-FUELQTY",
        "canonical_type_source": "override",
        "classification_status": "classified",
        "parser_status": "parsed",
        "target_count": 2,
        "candidate_count": 2,
        "found_candidate_count": 1,
        "missing_candidate_count": 1,
        "low_confidence_candidate_count": 1,
        "warnings": [],
        "errors": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:01+00:00",
        "artifacts": {
            "parser_output_path": None,
            "candidate_output_path": None,
            "approved_evidence_id": None,
        },
    }


@pytest.fixture(params=["memory", "jsonl"])
def repository(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryPipelineRunRepository()
    return JsonlPipelineRunRepository(tmp_path / "pipeline_runs.jsonl")


def test_save_and_list_all(repository):
    repository.save(_run("run-001"))
    repository.save(_run("run-002", evidence_id="EV-2"))
    assert len(repository.list_all()) == 2


def test_list_by_engagement(repository):
    repository.save(_run("run-001", engagement_id="ENG-1"))
    repository.save(_run("run-002", engagement_id="ENG-2"))
    assert len(repository.list_by_engagement("ENG-1")) == 1


def test_list_by_evidence(repository):
    repository.save(_run("run-001", evidence_id="EV-1"))
    repository.save(_run("run-002", evidence_id="EV-2"))
    assert len(repository.list_by_evidence("EV-2")) == 1


def test_get_by_id(repository):
    repository.save(_run("run-001"))
    assert repository.get_by_id("run-001") is not None
    assert repository.get_by_id("does-not-exist") is None


def test_get_latest_by_evidence(repository):
    repository.save(_run("run-001", evidence_id="EV-1"))
    repository.save(_run("run-002", evidence_id="EV-1"))
    latest = repository.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["pipeline_run_id"] == "run-002"


def test_jsonl_persistence_survives_reinstantiation(tmp_path: Path):
    path = tmp_path / "pipeline_runs.jsonl"
    first = JsonlPipelineRunRepository(path)
    first.save(_run("run-001", evidence_id="EV-1"))
    first.save(_run("run-002", evidence_id="EV-1"))

    second = JsonlPipelineRunRepository(path)
    assert len(second.list_all()) == 2
    latest = second.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["pipeline_run_id"] == "run-002"


def test_jsonl_uses_temporary_path(tmp_path: Path):
    path = tmp_path / "nested" / "pipeline_runs.jsonl"
    repository = JsonlPipelineRunRepository(path)
    repository.save(_run("run-001"))
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip()
