import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.domain.pipeline import PipelineRun, PipelineStageStatuses

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "pipeline_run.schema.json"


def _run_payload(**overrides) -> dict:
    payload = {
        "pipeline_run_id": "pipeline::EV-1::abc123",
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
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
    payload.update(overrides)
    return payload


def test_pipeline_schema_is_valid_json():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["title"] == "PipelineRun"
    assert schema["additionalProperties"] is False


def test_pipeline_run_model_accepts_valid_summary():
    model = PipelineRun(**_run_payload())
    assert model.status == "completed"
    assert isinstance(model.stage_statuses, PipelineStageStatuses)


def test_pipeline_run_model_invalid_status_fails():
    with pytest.raises(ValidationError):
        PipelineRun(**_run_payload(status="in_progress"))


def test_pipeline_run_model_invalid_stage_status_fails():
    invalid = _run_payload()
    invalid["stage_statuses"]["target_plan"] = "done"
    with pytest.raises(ValidationError):
        PipelineRun(**invalid)


def test_pipeline_run_model_required_fields_are_enforced():
    payload = _run_payload()
    del payload["pipeline_run_id"]
    with pytest.raises(ValidationError):
        PipelineRun(**payload)
