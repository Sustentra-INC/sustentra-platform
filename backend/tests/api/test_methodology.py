from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import methodology as methodology_api
from backend.app.main import app
from backend.tests.services.test_s2_orchestration_service import (
    _approved_evidence,
    _service,
)


def test_post_s2_run_returns_summary() -> None:
    original = methodology_api._service
    methodology_api.configure_service(_service())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/methodology/s2/run",
                json={"approved_evidence": _approved_evidence()},
            )
    finally:
        methodology_api.configure_service(original)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["engagement_id"] == "ENG-1"
    assert body["summary"]["field_value_count"] == 3


def test_post_s2_run_returns_400_for_invalid_approved_evidence() -> None:
    original = methodology_api._service
    methodology_api.configure_service(_service())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/methodology/s2/run",
                json={"approved_evidence": {"approved_evidence_id": "bad"}},
            )
    finally:
        methodology_api.configure_service(original)

    assert response.status_code == 400
    assert "approved_evidence missing" in response.json()["detail"]
