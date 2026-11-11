from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api import evidence_tree as tree_api
from backend.app.main import app
from backend.tests.api.conftest import ORG_A, ORG_B
from backend.tests.services.test_calculation_lines import GAS_KC, KC, STL, _gas
from backend.tests.services.test_engagement_recalculation_service import FakeStore

ENGAGEMENT = {"id": "ENG-1", "org_id": ORG_A, "name": "FY2025 GHG", "reporting_period_start": "2025-01-01",
              "reporting_period_end": "2025-03-31", "settings": {"facilities": [KC, STL]}}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas(310, "2025-01-16", "2025-02-15")], org_id=str(ORG_A))
    store.reviews["G1"] = [{**r, "reviewer_id": "ana@example.com", "reviewed_at": "2025-04-02T10:00:00Z"}
                           for r in store.reviews["G1"]]
    store.add_document("OTHER", "CT-S1-FUELQTY", [_gas()], org_id=str(ORG_B))  # another org's: never visible to A

    async def visible(db, engagement_id, user):  # noqa: ANN001, ANN202 - stands in for the Postgres lookup
        if engagement_id != "ENG-1" or (not user.is_provider and user.org_id != ORG_A):
            raise HTTPException(status_code=404, detail="Engagement not found.")
        return ENGAGEMENT

    async def decisions(db, engagement):  # noqa: ANN001, ANN202
        return {}

    async def names(db, org_id):  # noqa: ANN001, ANN202
        return {"ana@example.com": "Ana Reyes"}

    async def no_db():  # noqa: ANN202
        yield None

    from backend.app.core.db import get_db_session
    from backend.app.services.evidence_tree_service import EvidenceTreeService

    monkeypatch.setattr(tree_api, "_visible", visible)
    monkeypatch.setattr(tree_api, "document_decisions", decisions)
    monkeypatch.setattr(tree_api, "reviewer_names", names)
    monkeypatch.setattr(tree_api, "_service", lambda: EvidenceTreeService(store, store, store))
    app.dependency_overrides[get_db_session] = no_db
    yield store
    app.dependency_overrides.pop(get_db_session, None)


def test_a_reader_gets_the_tree(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        response = client.get("/v1/engagements/ENG-1/evidence-tree")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"blocks", "facilities", "lines", "set_aside", "vehicle_groups", "anchors_for_contractual"}
    assert body["anchors_for_contractual"] == "company" and body["vehicle_groups"] == []
    assert set(body["blocks"]) == {"summary", "summary_counts", "unassigned", "unassigned_counts", "supporting"}
    assert [ln["key"] for ln in body["lines"]] == [GAS_KC, "s1:stationary:natural-gas:fac-stl2"]
    stationary = body["blocks"]["supporting"]["scopes"][0]["categories"][0]
    row = stationary["level2s"][0]["lines"][0]["documents"][0]
    assert row["document_id"] == "G1" and row["file_name"] == "G1.pdf" and row["facility_id"] == "fac-kc01"
    assert set(row) == {"document_id", "file_name", "period_start", "period_end", "facility_id", "facility_name",
                        "processing_status", "detected_type", "also_in", "values", "accepted", "flags",
                        "placement_from"}


def test_the_facility_query_filters_the_tree(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        kc = client.get("/v1/engagements/ENG-1/evidence-tree?facility_id=fac-kc01").json()
        stl = client.get("/v1/engagements/ENG-1/evidence-tree?facility_id=fac-stl2").json()
    assert [ln["key"] for ln in kc["lines"]] == [GAS_KC] and stl["lines"][0]["facility_id"] == "fac-stl2"
    assert kc["blocks"]["supporting"]["scopes"][0]["counts"]["documents"] == 1
    assert stl["blocks"]["supporting"]["scopes"][0]["counts"]["documents"] == 0


def test_a_reader_gets_a_schedule_with_names(act_as, wired: FakeStore) -> None:
    act_as("org_admin", ORG_A)
    with TestClient(app) as client:
        response = client.get(f"/v1/engagements/ENG-1/calculation-lines/{GAS_KC}/schedule")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"line", "reporting_period", "coverage", "identifiers", "values", "history", "rows",
                         "columns", "activity_quantity_note", "identifier_groups"}
    assert body["rows"][0]["saved_by"]["name"] == "Ana Reyes" and body["rows"][0]["accepted"] is True
    assert body["line"]["key"] == GAS_KC and body["values"][0]["decided_by"] == "Ana Reyes"
    assert [m["status"] for m in body["coverage"]] == ["counted_in_part", "counted_in_part", "no_document"]
    assert body["history"][0]["text"].startswith("Ana Reyes accepted 310 MMBtu from G1.pdf")


def test_provider_support_can_read(act_as, wired: FakeStore) -> None:
    act_as("provider_admin")
    with TestClient(app) as client:
        assert client.get("/v1/engagements/ENG-1/evidence-tree").status_code == 200


def test_an_unknown_line_is_a_plain_404(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        response = client.get("/v1/engagements/ENG-1/calculation-lines/s1:stationary:coal:fac-nowhere/schedule")
    assert response.status_code == 404
    assert response.json()["detail"] == "This calculation line does not exist in this engagement."


def test_another_orgs_engagement_is_404_and_signed_out_is_401(act_as, wired: FakeStore) -> None:
    act_as("org_member", ORG_B)
    with TestClient(app) as client:
        assert client.get("/v1/engagements/ENG-1/evidence-tree").status_code == 404
        assert client.get(f"/v1/engagements/ENG-1/calculation-lines/{GAS_KC}/schedule").status_code == 404
    act_as(None)
    with TestClient(app) as client:
        assert client.get("/v1/engagements/ENG-1/evidence-tree").status_code == 401
        assert client.get(f"/v1/engagements/ENG-1/calculation-lines/{GAS_KC}/schedule").status_code == 401
