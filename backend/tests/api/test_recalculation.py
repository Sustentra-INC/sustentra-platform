from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api import recalculation as recalculation_api
from backend.app.api.engagements import EngagementUpdate
from backend.app.main import app
from backend.tests.api.conftest import ORG_A, ORG_B
from backend.tests.services.test_engagement_recalculation_service import (
    FakeStore,
    _elec,
    _service,
)

ENGAGEMENT = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
              "settings": {"recalculation": {"grid_regions": {"Facility A": "NYUP"}}}}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S2-ELEC", [_elec(1200, "Facility A", "Albany, NY")], org_id=str(ORG_A))

    async def visible(db, engagement_id, user):  # noqa: ANN001, ANN202 - stands in for the Postgres lookup
        if engagement_id != "ENG-1" or user.org_id != ORG_A:
            raise HTTPException(status_code=404, detail="Engagement not found.")
        return ENGAGEMENT

    async def no_db():  # noqa: ANN202
        yield None

    from backend.app.core.db import get_db_session

    monkeypatch.setattr(recalculation_api, "_visible", visible)
    monkeypatch.setattr(recalculation_api, "_service", lambda: _service(store))

    async def no_decisions(db, engagement_id, kind=None):  # noqa: ANN001, ANN202
        return []

    monkeypatch.setattr(recalculation_api.workpaper_item_service, "list_items", no_decisions)
    app.dependency_overrides[get_db_session] = no_db
    yield store
    app.dependency_overrides.pop(get_db_session, None)


def test_recalculation_for_my_engagement(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        response = client.get("/v1/engagements/ENG-1/recalculation")
    assert response.status_code == 200
    body = response.json()
    location = body["categories"]["purchased_electricity_location_based"]
    assert location["lines"][0]["key"] == "Facility A"
    assert round(location["total_co2e"], 2) == round(1200 * (240.99 + 0.011 * 28 + 0.001 * 265) / 2204.62, 2)
    assert body["gwp_set"] == "AR5" and body["tolerance_pct"] == 5.0


def test_other_org_and_signed_out_cannot_read(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_B)
    with TestClient(app) as client:
        assert client.get("/v1/engagements/ENG-1/recalculation").status_code == 404
    act_as(None)
    with TestClient(app) as client:
        assert client.get("/v1/engagements/ENG-1/recalculation").status_code == 401


def test_reference_lists_the_input_choices(act_as) -> None:
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        body = client.get("/v1/reference/recalculation").json()
    assert body["gwp_sets"] == ["AR5", "AR6"] and body["default_gwp_set"] == "AR5"
    assert len(body["egrid_subregions"]) == 28 and len(body["stationary_fuels"]) == 63
    assert {"key": "scope1_total", "label": "Scope 1 (Total)", "workbook_row": 22, "unit": "t CO2e"} in \
        body["reported_data_points"]


def test_engagement_settings_validate_recalculation_inputs() -> None:
    EngagementUpdate(settings={"recalculation": {"gwp_set": "AR6", "grid_regions": {"Facility A": "NYUP"}}})
    with pytest.raises(ValueError):
        EngagementUpdate(settings={"recalculation": {"gwp_set": "AR4"}})
