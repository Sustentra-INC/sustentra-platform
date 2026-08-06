from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.api import engagements as engagements_api
from backend.app.main import app
from backend.app.repositories.engagement_repository import InMemoryEngagementRepository


def test_get_default_s1_engagement_seeds_repository():
    original_repository = engagements_api._repository
    repository = InMemoryEngagementRepository()
    engagements_api.configure_repository(repository)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/engagements/ENG-S1-2025")
    finally:
        engagements_api.configure_repository(original_repository)

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "ENG-S1-2025"
    assert body["client_name"] == "SCE Manufacturing"
    assert body["facilities"][0]["name"] == "Riverside Plant"
    assert repository.get_by_id("ENG-S1-2025") is not None


def test_create_engagement_persists_project_metadata():
    original_repository = engagements_api._repository
    repository = InMemoryEngagementRepository()
    engagements_api.configure_repository(repository)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/engagements",
                json={
                    "engagement_name": "Local Validation",
                    "client_name": "Validation Client",
                    "created_by": "dev@example.com",
                    "facilities": [{"facility_id": "facility-1", "name": "Facility 1"}],
                },
            )
    finally:
        engagements_api.configure_repository(original_repository)

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "engagement::local-validation"
    assert repository.get_by_id("engagement::local-validation")["client_name"] == "Validation Client"
