from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.api import pipeline as pipeline_api
from backend.app.main import app
from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.review_decision_service import ReviewDecisionService


@pytest.fixture
def client_context(tmp_path):
    original = pipeline_api._service

    pipeline_repo = InMemoryPipelineRunRepository()
    review_repo = InMemoryReviewDecisionRepository()
    approved_repo = InMemoryApprovedEvidenceRepository()

    review_service = ReviewDecisionService(
        repository=review_repo,
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )
    approved_service = ApprovedEvidenceService(
        review_repository=review_repo,
        approved_repository=approved_repo,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda engagement_id, evidence_id: f"approved::{engagement_id}::{evidence_id}::01",
    )

    counter = {"n": 0}

    def id_factory(prefix: str, seed: str) -> str:
        counter["n"] += 1
        return f"{prefix}::{seed}::{counter['n']:02d}"

    service = PipelineOrchestrationService(
        pipeline_repository=pipeline_repo,
        review_service=review_service,
        approved_evidence_service=approved_service,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )

    pipeline_api.configure_service(service)

    local_file = tmp_path / "sample.txt"
    local_file.write_text(
        "\n".join(
            [
                "Facility Name: Demo Plant",
                "Fuel Type: Natural Gas",
                "Total Usage: 28,100 MMBtu",
                "Service Period: 10/01/2023 - 10/31/2023",
                "Supplier: Demo Utility",
                "Account Number: 123456",
            ]
        ),
        encoding="utf-8",
    )

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "local_file": str(local_file),
            }
    finally:
        pipeline_api.configure_service(original)



def _request(local_file_path: str) -> dict:
    return {
        "local_file_path": local_file_path,
        "engagement_id": "ENG-1",
        "canonical_type_id_override": "CT-S1-FUELQTY",
        "persist_run": True,
    }



def test_post_process_document_works(client_context):
    client = client_context["client"]
    response = client.post(
        "/v1/pipeline/local/process-document",
        json=_request(client_context["local_file"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert "pipeline_run" in body
    assert "parser_output" in body
    assert "classification_result" in body
    assert "extraction_targets" in body
    assert "extraction_result" in body



def test_get_pipeline_run_returns_persisted_run(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/pipeline/local/process-document",
        json=_request(client_context["local_file"]),
    )
    run_id = created.json()["pipeline_run"]["pipeline_run_id"]

    fetched = client.get(f"/v1/pipeline/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["pipeline_run_id"] == run_id



def test_get_latest_run_by_evidence_returns_latest(client_context):
    client = client_context["client"]
    payload = _request(client_context["local_file"])
    payload["evidence_id"] = "EV-1"

    created = client.post("/v1/pipeline/local/process-document", json=payload)
    assert created.status_code == 200

    latest = client.get("/v1/pipeline/evidence/EV-1/latest-run")
    assert latest.status_code == 200
    assert latest.json()["evidence_id"] == "EV-1"



def test_get_evidence_status_returns_status_object(client_context):
    client = client_context["client"]
    payload = _request(client_context["local_file"])
    payload["evidence_id"] = "EV-STATUS"

    created = client.post("/v1/pipeline/local/process-document", json=payload)
    assert created.status_code == 200

    status = client.get("/v1/pipeline/evidence/EV-STATUS/status")
    assert status.status_code == 200
    body = status.json()
    assert body["evidence_id"] == "EV-STATUS"
    assert "latest_pipeline_run" in body
    assert "review_decision_count" in body
    assert "latest_approved_evidence" in body
    assert "approved_field_count" in body
    assert "review_status" in body



def test_missing_file_returns_non_2xx(client_context):
    client = client_context["client"]
    response = client.post(
        "/v1/pipeline/local/process-document",
        json=_request("missing-file.txt"),
    )
    assert response.status_code == 400



def test_unknown_pipeline_run_id_returns_404(client_context):
    client = client_context["client"]
    response = client.get("/v1/pipeline/runs/unknown-run")
    assert response.status_code == 404
