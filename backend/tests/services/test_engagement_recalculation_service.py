"""Engagement recalculation: reviewed evidence in, workbook-checked numbers out."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.engagement_recalculation_service import (
    EngagementRecalculationService,
    materiality_tolerance,
    validate_recalculation_settings,
)

ORG = "org-a"


class FakeStore:
    """documents / extraction results / review decisions, as the S1 services return them."""

    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.results: dict[str, list[dict]] = {}
        self.reviews: dict[str, list[dict]] = {}

    def add_document(self, document_id: str, canonical_type_id: str, records: list[dict[str, tuple]],
                     engagement_id: str = "ENG-1", org_id: str = ORG, decision: str | None = "accepted") -> None:
        """``records``: one dict per record of field_name -> (normalized_value, unit)."""

        self.documents.append({"document_id": document_id, "engagement_id": engagement_id, "org_id": org_id,
                               "file_name": f"{document_id}.pdf"})
        items, reviews = [], []
        multi = len(records) > 1
        for index, record in enumerate(records, start=1):
            for field_name, (value, unit) in record.items():
                candidate_id = f"{document_id}:{index}:{field_name}"
                items.append({"candidate_id": candidate_id, "field_name": field_name, "normalized_value": value,
                              "unit": unit, "record_index": index if multi else None,
                              "source_reference": {"document_id": document_id, "page_number": 1}})
                if decision:
                    reviews.append({"candidate_id": candidate_id, "decision": decision, "org_id": org_id,
                                    "reviewed_value": value if decision == "accepted" else None,
                                    "reviewed_unit": unit if decision == "accepted" else None})
        self.results[document_id] = [{"document_id": document_id, "org_id": org_id,
                                      "canonical_type_id": canonical_type_id, "items": items}]
        self.reviews[document_id] = reviews

    # the three service seams
    def list_documents(self, engagement_id: str) -> list[dict]:
        return [d for d in self.documents if d["engagement_id"] == engagement_id]

    def list_extraction_results_by_document(self, document_id: str) -> list[dict]:
        return self.results.get(document_id, [])

    def list_by_document(self, document_id: str) -> list[dict]:
        return self.reviews.get(document_id, [])


def _service(store: FakeStore) -> EngagementRecalculationService:
    return EngagementRecalculationService(store, store, store)


def _engagement(**settings: Any) -> dict:
    return {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
            "settings": settings}


def _own(record: dict) -> bool:
    return record.get("org_id") == ORG


def _elec(mwh: float, facility: str, address: str, start: str = "2025-01-01", end: str = "2025-12-31") -> dict:
    return {"activity_quantity": (mwh, "MWh"), "activity_unit": ("MWh", None), "energy_type": ("electricity", None),
            "facility_name": (facility, None), "service_address": (address, None),
            "service_period_start": (start, None), "service_period_end": (end, None)}


def _by_key(result: dict) -> dict[str, dict]:
    return {c["key"]: c for c in result["comparisons"]}


# --- the workbook's two-facility example, as reviewed utility bills -----------------------
def _workbook_example_store() -> FakeStore:
    store = FakeStore()
    # Facility A 1,200,000 kWh and Facility B 800,000 kWh for the year, split over bills.
    store.add_document("BILL-A1", "CT-S2-ELEC", [_elec(700, "Facility A", "Albany, NY", "2025-01-01", "2025-06-30")])
    store.add_document("BILL-A2", "CT-S2-ELEC", [_elec(500, "Facility A", "Albany, NY", "2025-07-01", "2025-12-31")])
    store.add_document("BILL-B1", "CT-S2-ELEC", [_elec(800, "Facility B", "Philadelphia, PA")])
    return store


def test_grid_region_is_required_and_never_defaulted() -> None:
    result = _service(_workbook_example_store()).recalculate(_engagement(), _own)
    assert result["categories"]["purchased_electricity_location_based"] is None
    asks = {item["key"]: item for item in result["needs_input"] if item["kind"] == "grid_region"}
    assert set(asks) == {"Facility A", "Facility B"}
    assert "NYUP" in asks["Facility A"]["options"] and "Albany, NY" in asks["Facility A"]["message"]
    assert _by_key(result)["scope2_location_total"]["status"] == "no_evidence"


def test_workbook_example_end_to_end_location_and_market_based() -> None:
    settings = {"recalculation": {
        "grid_regions": {"Facility A": "NYUP", "Facility B": "RFCE"},
        "certificates": [{"label": "REC retirement report 1", "mwh": 400},
                         {"label": "REC retirement report 2", "mwh": 200}],
        "reported": {"scope2_location_total": 348.14, "scope2_market_total": 243.70},
    }}
    result = _service(_workbook_example_store()).recalculate(_engagement(**settings), _own)
    location = result["categories"]["purchased_electricity_location_based"]
    assert [round(line["mass_t"]["CO2"], 2) for line in location["lines"]] == [131.17, 215.82]  # exact EPA factors
    assert round(location["total_co2e"], 2) == 348.15  # workbook: 348.14 with factors rounded to 241.0 / 594.7
    assert round(result["categories"]["purchased_electricity_market_based"]["total_co2e"], 2) == 243.70
    comparisons = _by_key(result)
    assert comparisons["scope2_location_total"]["status"] == "within_tolerance"
    assert comparisons["scope2_market_total"]["status"] == "within_tolerance"
    assert comparisons["scope2_location_total"]["workbook_row"] == 30
    assert result["needs_input"] == [] and result["awaiting_review"] == []
    # Each facility's MWh names the reviewed bills it came from.
    facility_a = next(i for i in location["details"]["inputs"] if i["fuel"] == "Facility A")
    assert facility_a["quantity"] == 1200 and [d["document_id"] for d in facility_a["documents"]] == ["BILL-A1", "BILL-A2"]


# --- reviewed values only ------------------------------------------------------------------
def _gas(quantity: float, unit: str = "MMBtu", start: str = "2025-01-01", end: str = "2025-01-31",
         fuel: str = "natural_gas") -> dict:
    return {"fuel_type": (fuel, None), "activity_quantity": (quantity, unit), "activity_unit": (unit, None),
            "service_period_start": (start, None), "service_period_end": (end, None),
            "facility_name": ("Plant 1", None)}


def test_unreviewed_and_rejected_values_never_reach_a_number() -> None:
    store = FakeStore()
    store.add_document("GAS-OK", "CT-S1-FUELQTY", [_gas(1000)])
    store.add_document("GAS-PENDING", "CT-S1-FUELQTY", [_gas(5000)], decision=None)
    store.add_document("GAS-REJECTED", "CT-S1-FUELQTY", [_gas(9000)], decision="rejected")
    result = _service(store).recalculate(_engagement(), _own)
    stationary = result["categories"]["stationary_combustion"]
    assert stationary["lines"][0]["mass_t"]["CO2"] == pytest.approx(1000 * 53.06 / 1000)
    pending = {item["document_id"] for item in result["awaiting_review"]}
    assert pending == {"GAS-PENDING", "GAS-REJECTED"}
    assert _by_key(result)["scope1_total"]["inputs_incomplete"] is True


def test_edited_value_is_used() -> None:
    store = FakeStore()
    store.add_document("GAS-1", "CT-S1-FUELQTY", [_gas(1000)])
    store.reviews["GAS-1"] = [
        {**r, "decision": "edited", "reviewed_value": "1,250", "reviewed_unit": None}
        if r["candidate_id"].endswith("activity_quantity") else r for r in store.reviews["GAS-1"]
    ]
    result = _service(store).recalculate(_engagement(), _own)
    assert result["categories"]["stationary_combustion"]["lines"][0]["mass_t"]["CO2"] == pytest.approx(
        1250 * 53.06 / 1000)


def test_other_organizations_are_invisible() -> None:
    store = FakeStore()
    store.add_document("MINE", "CT-S1-FUELQTY", [_gas(1000)])
    store.add_document("THEIRS", "CT-S1-FUELQTY", [_gas(999_999)], org_id="org-b")
    result = _service(store).recalculate(_engagement(), _own)
    assert result["documents_considered"] == 1
    assert result["categories"]["stationary_combustion"]["total_co2e"] < 100


# --- documents read vs documents fully reviewed -------------------------------------------------
def test_documents_reviewed_counts_only_documents_with_nothing_awaiting_review() -> None:
    # As on staging: one electricity bill accepted; two scanned bills and a diesel CSV not reviewed yet.
    store = FakeStore()
    store.add_document("ELEC-OK", "CT-S2-ELEC", [_elec(1200, "Facility A", "Albany, NY")])
    store.add_document("SCAN-1", "CT-S2-ELEC", [_elec(300, "Facility A", "Albany, NY")], decision=None)
    store.add_document("SCAN-2", "CT-S2-ELEC", [_elec(400, "Facility A", "Albany, NY")], decision=None)
    store.add_document("DIESEL-CSV", "CT-S1-FUELQTY",
                       [_gas(100, "gal", fuel="diesel"), _gas(200, "gal", "2025-02-01", "2025-02-28", "diesel")],
                       decision=None)
    result = _service(store).recalculate(_engagement(recalculation={"grid_regions": {"Facility A": "NYUP"}}), _own)
    assert {item["document_id"] for item in result["awaiting_review"]} == {"SCAN-1", "SCAN-2", "DIESEL-CSV"}
    assert result["documents_considered"] == 4  # documents read
    assert result["documents_reviewed"] == 1


def test_documents_reviewed_is_decided_per_document() -> None:
    store = FakeStore()
    store.add_document("ELEC-OK", "CT-S2-ELEC", [_elec(1200, "Facility A", "Albany, NY")])
    # A CSV with one record still pending: its other, reviewed record does not make it reviewed.
    store.add_document("DIESEL-CSV", "CT-S1-FUELQTY",
                       [_gas(100, "gal", fuel="diesel"), _gas(200, "gal", "2025-02-01", "2025-02-28", "diesel")])
    store.reviews["DIESEL-CSV"] = [r for r in store.reviews["DIESEL-CSV"] if ":2:" not in r["candidate_id"]]
    # Reviewed, but the amount is not usable as electricity: a question about this document's value.
    store.add_document("ELEC-THERM", "CT-S2-ELEC", [{**_elec(50, "Facility A", "Albany, NY"),
                                                     "activity_quantity": (50, "therm")}])
    # Reviewed; what is missing is the engagement's eGRID subregion for Facility B, not a review.
    store.add_document("ELEC-B", "CT-S2-ELEC", [_elec(800, "Facility B", "Philadelphia, PA")])
    # Withdrawn by the reviewer: not read into the recalculation at all.
    store.add_document("WITHDRAWN", "CT-S2-ELEC", [_elec(900, "Facility A", "Albany, NY")])
    result = _service(store).recalculate(_engagement(recalculation={"grid_regions": {"Facility A": "NYUP"}}), _own,
                                         decisions={"WITHDRAWN": {"disposition": "withdrawn"}})
    assert [item["document_id"] for item in result["awaiting_review"]] == ["DIESEL-CSV"]
    quantity = next(item for item in result["needs_input"] if item["kind"] == "quantity")
    assert quantity["document_id"] == "ELEC-THERM"
    region = next(item for item in result["needs_input"] if item["kind"] == "grid_region")
    assert region["key"] == "Facility B" and "document_id" not in region
    assert result["documents_considered"] == 4
    assert result["documents_reviewed"] == 2  # fully reviewed: ELEC-OK and ELEC-B
    # The partly reviewed CSV is not fully reviewed, yet its reviewed record feeds the totals.
    [diesel] = result["categories"]["stationary_combustion"]["details"]["inputs"]
    assert diesel["quantity"] == 100 and [d["document_id"] for d in diesel["documents"]] == ["DIESEL-CSV"]


# --- grouping and proration ----------------------------------------------------------------
def test_one_total_per_fuel_type_across_bills_and_units() -> None:
    store = FakeStore()
    store.add_document("JAN", "CT-S1-FUELQTY", [_gas(1000)])  # 1,000 MMBtu
    store.add_document("FEB", "CT-S1-FUELQTY", [_gas(5000, "therm", "2025-02-01", "2025-02-28")])  # 500 MMBtu
    result = _service(store).recalculate(_engagement(), _own)
    lines = result["categories"]["stationary_combustion"]["lines"]
    assert len(lines) == 1 and lines[0]["key"] == "Natural Gas"
    assert lines[0]["mass_t"]["CO2"] == pytest.approx(1500 * 53.06 / 1000)


def test_bills_spanning_the_reporting_period_are_prorated() -> None:
    store = FakeStore()
    # 31-day bill (Dec 19 - Jan 18), 18 days of it in the reporting year
    store.add_document("DEC-JAN", "CT-S1-FUELQTY", [_gas(3100, start="2024-12-19", end="2025-01-18")])
    result = _service(store).recalculate(_engagement(), _own)
    line = result["categories"]["stationary_combustion"]["lines"][0]
    assert line["mass_t"]["CO2"] == pytest.approx(3100 * 18 / 31 * 53.06 / 1000)
    assert "prorated_to_reporting_period" in line["flags"]


# --- fuel matching -------------------------------------------------------------------------
def test_ambiguous_fuel_asks_and_the_reviewer_choice_is_used() -> None:
    store = FakeStore()
    store.add_document("OIL", "CT-S1-FUELQTY", [_gas(1000, "gal", fuel="fuel_oil")])
    asked = _service(store).recalculate(_engagement(), _own)
    choice = next(item for item in asked["needs_input"] if item["kind"] == "fuel_choice")
    assert choice["key"] == "stationary:fuel_oil"
    assert "Distillate Fuel Oil No. 2" in choice["options"] and "Residual Fuel Oil No. 6" in choice["options"]
    assert asked["categories"]["stationary_combustion"] is None

    chosen = _service(store).recalculate(
        _engagement(recalculation={"fuel_choices": {"stationary:fuel_oil": "Residual Fuel Oil No. 6"}}), _own)
    line = chosen["categories"]["stationary_combustion"]["lines"][0]
    assert line["key"] == "Residual Fuel Oil No. 6"
    assert line["mass_t"]["CO2"] == pytest.approx(1000 * 11.27 / 1000)  # Table 1: 11.27 kg CO2 per gallon


def test_diesel_auto_match_is_flagged_for_the_reviewer() -> None:
    store = FakeStore()
    store.add_document("GEN", "CT-S1-FUELQTY", [_gas(100, "gal", fuel="diesel")])
    line = _service(store).recalculate(_engagement(), _own)["categories"]["stationary_combustion"]["lines"][0]
    assert line["key"] == "Distillate Fuel Oil No. 2"
    assert "diesel_matched_to_distillate_fuel_oil_no_2" in line["flags"]


# --- mobile combustion ---------------------------------------------------------------------
def _fill(gallons: float, day: str, fuel: str = "diesel") -> dict:
    return {"fuel_type": (fuel, None), "activity_quantity": (gallons, "gal"), "activity_unit": ("gal", None),
            "transaction_date": (day, None)}


def test_mobile_fuel_receipts_sum_per_fuel_and_skip_other_years() -> None:
    store = FakeStore()
    store.add_document("CARD-STMT", "CT-S1-MOBFUEL", [_fill(40, "2025-03-02"), _fill(60, "2025-03-09"),
                                                      _fill(15, "2025-03-04", "gasoline"),
                                                      _fill(500, "2024-12-30")])  # last year: excluded
    result = _service(store).recalculate(_engagement(), _own)
    lines = {line["key"]: line for line in result["categories"]["mobile_combustion"]["lines"]}
    assert lines["Diesel Fuel"]["mass_t"]["CO2"] == pytest.approx(100 * 10.21 / 1000)  # Table 2
    assert lines["Motor Gasoline"]["mass_t"]["CO2"] == pytest.approx(15 * 8.78 / 1000)
    # receipts carry no vehicle type / model year / distance: CH4 and N2O need vehicle groups
    assert "ch4_n2o_need_vehicle_groups" in result["categories"]["mobile_combustion"]["flags"]
    assert _by_key(result)["mobile_combustion_total"]["recalculated"] == pytest.approx(
        result["categories"]["mobile_combustion"]["total_co2e"])


def test_unclear_mobile_fuel_asks() -> None:
    store = FakeStore()
    store.add_document("E85", "CT-S1-MOBFUEL", [_fill(30, "2025-05-01", "e85")])
    result = _service(store).recalculate(_engagement(), _own)
    choice = next(item for item in result["needs_input"] if item["kind"] == "fuel_choice")
    assert choice["key"] == "mobile:e85" and "Ethanol (100%)" in choice["options"]
    assert result["categories"]["mobile_combustion"] is None


# --- comparison tolerance ------------------------------------------------------------------
def test_comparison_uses_the_engagement_materiality_threshold() -> None:
    store = FakeStore()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas(1000)])
    recalculated = 1000 * 53.06 / 1000 + 1000 / 1e6 * 28 + 100 / 1e6 * 265
    reported = recalculated * 0.92  # 8.7% below
    five = _service(store).recalculate(
        _engagement(recalculation={"reported": {"scope1_total": reported}}), _own)
    ten = _service(store).recalculate(
        _engagement(materialityThreshold="10%", recalculation={"reported": {"scope1_total": reported}}), _own)
    assert _by_key(five)["scope1_total"]["status"] == "exceeds_tolerance"
    assert _by_key(ten)["scope1_total"]["status"] == "within_tolerance"
    assert (materiality_tolerance({}), materiality_tolerance({"materialityThreshold": "10%"})) == (5.0, 10.0)


def test_settings_validation() -> None:
    validate_recalculation_settings({"gwp_set": "AR6", "reported": {"scope1_total": 1.0}})
    for bad in ({"gwp_set": "AR4"}, {"surprise": 1}, {"reported": {"not_a_point": 1}},
                {"certificates": [{"mwh": -1}]}, {"grid_regions": {"A": 1}}):
        with pytest.raises(ValueError):
            validate_recalculation_settings(bad)


def test_records_outside_the_reporting_period_are_listed_not_silently_dropped() -> None:
    store = FakeStore()
    store.add_document("GAS-2024", "CT-S1-FUELQTY", [_gas(500, start="2024-01-01", end="2024-01-31")])
    store.add_document("BILL-2024", "CT-S2-ELEC", [_elec(90, "Facility Z", "Albany, NY", "2024-03-01", "2024-03-31")])
    store.add_document("GAS-2025", "CT-S1-FUELQTY", [_gas(1000)])
    result = _service(store).recalculate(_engagement(), _own)
    excluded = {item["document_id"]: item for item in result["excluded"]}
    assert set(excluded) == {"GAS-2024", "BILL-2024"}
    assert excluded["GAS-2024"]["period"] == "2024-01-01 to 2024-01-31"
    # The out-of-period bill neither counts nor asks for a grid region.
    assert not any(item["kind"] == "grid_region" for item in result["needs_input"])
    assert result["categories"]["stationary_combustion"]["lines"][0]["mass_t"]["CO2"] == pytest.approx(1000 * 53.06 / 1000)


# --- the reviewer's document decisions and Setup facilities ----------------------------------
def test_withdrawn_duplicate_and_superseded_documents_are_left_out_and_listed() -> None:
    store = FakeStore()
    for doc in ("GAS-KEEP", "GAS-WITHDRAWN", "GAS-DUP", "GAS-OLD", "GAS-NEW"):
        store.add_document(doc, "CT-S1-FUELQTY", [_gas(100)])
    decisions = {
        "GAS-WITHDRAWN": {"documentId": "GAS-WITHDRAWN", "disposition": "withdrawn"},
        "GAS-DUP": {"documentId": "GAS-DUP", "relationships": [{"kind": "duplicate", "otherDocumentId": "GAS-KEEP"}]},
        "GAS-NEW": {"documentId": "GAS-NEW", "relationships": [{"kind": "supersedes", "otherDocumentId": "GAS-OLD"}]},
    }
    result = _service(store).recalculate(_engagement(), _own, decisions)
    reasons = {item["document_id"]: item["reason"] for item in result["excluded"]}
    assert reasons == {"GAS-WITHDRAWN": "withdrawn", "GAS-DUP": "duplicate", "GAS-OLD": "superseded"}
    stationary = result["categories"]["stationary_combustion"]
    assert stationary["lines"][0]["mass_t"]["CO2"] == pytest.approx(2 * 100 * 53.06 / 1000)  # GAS-KEEP + GAS-NEW


def test_bills_take_their_setup_facility_and_its_grid_region() -> None:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S2-ELEC", [_elec(1200, "HVP Account 1001", "15 State Street, Albany, NY 12207")])
    store.add_document("BILL-B", "CT-S2-ELEC", [_elec(800, "Facility B", "Philadelphia, PA")])
    facilities = [
        {"facilityId": "F1", "name": "Albany Plant", "address": "15 State Street", "gridRegion": "NYUP"},
        {"facilityId": "F2", "name": "Philly Warehouse", "gridRegion": "RFCE"},
    ]
    engagement = _engagement(facilities=facilities, recalculation={"grid_regions": {"Philly Warehouse": "RFCE"}})
    # BILL-A matches by address; BILL-B only through the reviewer's facility decision.
    result = _service(store).recalculate(engagement, _own, {"BILL-B": {"documentId": "BILL-B", "facilityId": "F2"}})
    location = result["categories"]["purchased_electricity_location_based"]
    assert [line["key"] for line in location["lines"]] == ["Albany Plant", "Philly Warehouse"]
    assert round(location["total_co2e"], 2) == 348.15  # Claire's worked example, regions from Setup
    assert not [n for n in result["needs_input"] if n["kind"] == "grid_region"]


def test_match_facility_needs_a_clear_name_or_address() -> None:
    from backend.app.services.engagement_recalculation_service import match_facility

    facilities = [{"facilityId": "F1", "name": "Kent Cannery", "address": "88 Mill Road, Kent, WA"}]
    assert match_facility("KENT CANNERY", None, facilities)["facilityId"] == "F1"
    assert match_facility(None, "88 Mill Road", facilities)["facilityId"] == "F1"
    assert match_facility("Kent", "Kent", facilities) is None  # too short to be sure
    assert match_facility("Other site", "1 Elm St, Kent", facilities) is None


def test_setup_facilities_reject_an_unknown_grid_region() -> None:
    from backend.app.services.engagement_recalculation_service import validate_facilities

    validate_facilities([{"facilityId": "F1", "name": "A", "gridRegion": "NYUP"}, {"facilityId": "F2", "name": "B"}])
    with pytest.raises(ValueError):
        validate_facilities([{"facilityId": "F1", "name": "A", "gridRegion": "MOON"}])


# --- Scope 1 fugitive: refrigerants (Simplified Material Balance) --------------------------
LB = 0.45359237 / 1000  # metric tons per lb


def _refrigerant(gas: str, day: str, service_type: str | None = "service", added: float | None = None,
                 recovered: float | None = None, capacity: float | None = None, unit: str = "lb") -> dict:
    record: dict[str, tuple] = {"refrigerant_type": (gas, None), "service_date": (day, None),
                                "equipment_id": ("RTU-1", None)}
    if service_type is not None:
        record["service_type"] = (service_type, None)
    for name, value in (("refrigerant_added", added), ("refrigerant_recovered", recovered),
                        ("equipment_capacity", capacity)):
        if value is not None:
            record[name] = (value, unit)
    return record


def test_refrigerants_follow_the_simplified_material_balance_per_gas() -> None:
    store = FakeStore()
    store.add_document("REFRIG-LOG", "CT-S1-REFRSVC", [
        _refrigerant("HFC-134a", "2025-01-22", added=45, capacity=650),  # P_S 45
        _refrigerant("R-410A", "2025-04-09", added=4.5),  # P_S 4.5
        _refrigerant("R-410A", "2025-08-18", "installation", added=21, capacity=20),  # P_N 21, C_N 20
        _refrigerant("HFC-134a", "2025-12-05", "disposal", added=0, recovered=580, capacity=600),  # C_D 600, R_D 580
    ])
    result = _service(store).recalculate(_engagement(), _own)
    fugitive = result["categories"]["fugitive_refrigerants"]
    lines = {line["key"]: line for line in fugitive["lines"]}
    assert lines["HFC-134a"]["steps"][0]["result"] == pytest.approx(65)  # 45 + (600 - 580)
    assert lines["R-410A"]["steps"][0]["result"] == pytest.approx(5.5)  # (21 - 20) + 4.5
    assert lines["HFC-134a"]["mass_t"]["HFC-134a"] == pytest.approx(65 * LB)
    assert fugitive["gwp"]["R-410A"]["value"] == 1924 and "Table 12" in fugitive["gwp"]["R-410A"]["source"]
    expected = 65 * LB * 1300 + 5.5 * LB * 1924
    assert fugitive["total_co2e"] == pytest.approx(expected)
    # Fugitive emissions are part of Scope 1 and have their own reported data point (row 45).
    assert result["scope_totals"]["scope1"]["total_co2e"] == pytest.approx(expected)
    fugitive_row = _by_key(result)["fugitive_total"]
    assert fugitive_row["recalculated"] == pytest.approx(expected) and fugitive_row["workbook_row"] == 46
    assert result["needs_input"] == [] and result["awaiting_review"] == []


def test_hcfcs_are_listed_not_counted_and_unknown_gases_ask_for_a_gwp() -> None:
    store = FakeStore()
    store.add_document("R22", "CT-S1-REFRSVC", [_refrigerant("R-22", "2025-03-01", added=10)])
    store.add_document("R454B", "CT-S1-REFRSVC", [_refrigerant("R-454B", "2025-03-02", added=8)])
    result = _service(store).recalculate(_engagement(), _own)
    assert result["categories"]["fugitive_refrigerants"] is None
    left_out = [e for e in result["excluded"] if e["reason"] == "montreal_protocol_gas"]
    assert [(e["document_id"], e["gas"]) for e in left_out] == [("R22", "HCFC-22")]
    asks = [n for n in result["needs_input"] if n["kind"] == "refrigerant_gwp"]
    assert [a["key"] for a in asks] == ["R-454B"] and "safety data sheet" in asks[0]["message"]

    entered = {"recalculation": {"refrigerant_gwps": {"R-454B": 466}}}
    result = _service(store).recalculate(_engagement(**entered), _own)
    fugitive = result["categories"]["fugitive_refrigerants"]
    assert fugitive["total_co2e"] == pytest.approx(8 * LB * 466)
    assert fugitive["gwp"]["R-454B"]["source"] == "entered by the reviewer (safety data sheet)"


def test_refrigerant_records_need_the_reviewed_amounts_their_service_type_uses() -> None:
    store = FakeStore()
    # A disposal needs the retired equipment's full charge and what was recovered.
    store.add_document("RETIRE", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-05-01", "disposal", recovered=9)])
    store.add_document("OLD", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2024-11-01", added=3)])
    store.add_document("OZ", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-06-01", added=72, unit="oz")])
    result = _service(store).recalculate(_engagement(), _own)
    waiting = {a["document_id"]: a["fields"] for a in result["awaiting_review"]}
    assert waiting == {"RETIRE": ["equipment_capacity"]}
    assert [e["document_id"] for e in result["excluded"]] == ["OLD"]  # outside the reporting period
    fugitive = result["categories"]["fugitive_refrigerants"]
    assert fugitive["lines"][0]["steps"][0]["result"] == pytest.approx(4.5)  # 72 oz


def test_refrigerant_gwps_are_validated() -> None:
    validate_recalculation_settings({"refrigerant_gwps": {"R-454B": 466}})
    with pytest.raises(ValueError, match="refrigerant_gwps"):
        validate_recalculation_settings({"refrigerant_gwps": {"R-454B": "high"}})
    with pytest.raises(ValueError, match="refrigerant_gwps"):
        validate_recalculation_settings({"refrigerant_gwps": {"R-454B": -1}})


# --- Mobile CH4 / N2O by vehicle group (workbook Eq 4 / Eq 5) ------------------------------
def _diesel_purchase(gallons: float, day: str = "2025-05-01") -> dict:
    return {"fuel_type": ("diesel", None), "activity_quantity": (gallons, "gal"), "activity_unit": ("gal", None),
            "transaction_date": (day, None)}


def _mobile_store() -> FakeStore:
    store = FakeStore()
    store.add_document("FLEET", "CT-S1-MOBFUEL", [_diesel_purchase(600), _diesel_purchase(400, "2025-09-01")])
    return store


def test_vehicle_groups_add_ch4_and_n2o_by_distance_and_by_fuel() -> None:
    groups = [
        {"fuel": "Diesel Fuel", "vehicle_type": "Medium- and Heavy-Duty Vehicles", "factor_fuel_type": "Diesel",
         "on_road": True, "model_year": 2018, "distance": 10000, "distance_unit": "mi", "label": "4 heavy trucks"},
        {"fuel": "Diesel Fuel", "vehicle_type": "Industrial/Commercial Equipment", "factor_fuel_type": "Diesel",
         "on_road": False, "fuel_quantity": 200, "fuel_unit": "gal", "label": "3 forklifts"},
    ]
    service = _service(_mobile_store())
    result = service.recalculate(_engagement(recalculation={"vehicle_groups": groups}), _own)
    mobile = result["categories"]["mobile_combustion"]
    line = mobile["lines"][0]
    on_road = service.reference.on_road("Medium- and Heavy-Duty Vehicles", "Diesel", 2018)
    non_road = service.reference.non_road("Industrial/Commercial Equipment", "Diesel")
    expected_ch4 = (10000 * on_road["ch4_g_per_mile"] + 200 * non_road["ch4_g_per_gallon"]) / 1e6
    assert line["mass_t"]["CH4"] == pytest.approx(expected_ch4)
    assert line["mass_t"]["N2O"] == pytest.approx(
        (10000 * on_road["n2o_g_per_mile"] + 200 * non_road["n2o_g_per_gallon"]) / 1e6)
    assert "ch4_n2o_need_vehicle_groups" not in mobile["flags"]
    assert any("vehicle group: 4 heavy trucks" == s["inputs"]["distance"]["source"]
               for s in line["steps"] if "distance" in s["inputs"])
    assert result["needs_input"] == []


def test_vehicle_group_gaps_are_asked_and_a_lone_non_road_group_uses_all_the_fuel() -> None:
    service = _service(_mobile_store())
    lone = [{"fuel": "Diesel Fuel", "vehicle_type": "Construction/Mining Equipment",
             "factor_fuel_type": "Diesel Equipment", "on_road": False}]
    line = service.recalculate(_engagement(recalculation={"vehicle_groups": lone}), _own)[
        "categories"]["mobile_combustion"]["lines"][0]
    ef5 = service.reference.non_road("Construction/Mining Equipment", "Diesel Equipment")["ch4_g_per_gallon"]
    assert line["mass_t"]["CH4"] == pytest.approx(1000 * ef5 / 1e6)  # all 1,000 gal

    gaps = [
        {"fuel": "Diesel Fuel", "vehicle_type": "Passenger Cars", "factor_fuel_type": "Diesel", "on_road": True,
         "distance": 5000},  # no model year
        {"fuel": "Diesel Fuel", "vehicle_type": "Light-Duty Trucks", "factor_fuel_type": "Diesel", "on_road": True,
         "model_year": 2025, "distance": 8000},  # newer than the table: newest year's factor
        {"fuel": "Diesel Fuel", "vehicle_type": "Rocket", "factor_fuel_type": "Diesel", "on_road": True,
         "model_year": 2020, "distance": 1},
    ]
    result = service.recalculate(_engagement(recalculation={"vehicle_groups": gaps}), _own)
    asks = [n["message"] for n in result["needs_input"] if n["kind"] == "vehicle_group"]
    assert len(asks) == 2 and "model year" in asks[0] and "no on-road CH4/N2O factor" in asks[1]
    mobile = result["categories"]["mobile_combustion"]
    newest = service.reference.on_road("Light-Duty Trucks", "Diesel", 2022)
    assert mobile["lines"][0]["mass_t"]["CH4"] == pytest.approx(8000 * newest["ch4_g_per_mile"] / 1e6)
    assert "model_year_newer_than_table" in mobile["flags"]


def test_vehicle_groups_are_validated() -> None:
    good = {"fuel": "Diesel Fuel", "vehicle_type": "Buses", "factor_fuel_type": "CNG", "on_road": True}
    validate_recalculation_settings({"vehicle_groups": [good]})
    for bad in ({**good, "on_road": "yes"}, {**good, "model_year": 25}, {**good, "distance": -3},
                {**good, "distance_unit": "furlong"}, {**good, "colour": "red"}, {"fuel": "Diesel Fuel"}):
        with pytest.raises(ValueError):
            validate_recalculation_settings({"vehicle_groups": [bad]})


# --- Setup's in-scope data points -----------------------------------------------------------
def test_data_points_set_out_of_scope_are_shown_but_never_judged() -> None:
    from backend.app.services.engagement_recalculation_service import CATALOGUE_KEYS, DATA_POINT_KEYS

    assert DATA_POINT_KEYS <= CATALOGUE_KEYS  # every compared data point can be scoped
    settings = {"recalculation": {"grid_regions": {"Facility A": "NYUP", "Facility B": "RFCE"},
                                  "reported": {"scope2_market_total": 999.0}},
                "outOfScopeDataPoints": ["scope2_market_total"]}
    rows = _by_key(_service(_workbook_example_store()).recalculate(_engagement(**settings), _own))
    market = rows["scope2_market_total"]
    assert market["status"] == "not_in_scope" and market["recalculated"] == pytest.approx(348.15, abs=0.01)
    assert market["inputs_incomplete"] is False
    assert rows["scope2_location_total"]["status"] == "not_reported"


def test_out_of_scope_keys_are_validated() -> None:
    from backend.app.services.engagement_recalculation_service import validate_out_of_scope

    validate_out_of_scope(["process_total", "scope2_nf3"])
    with pytest.raises(ValueError, match="unknown data points"):
        validate_out_of_scope(["scope9_total"])
    with pytest.raises(ValueError):
        validate_out_of_scope("scope1_total")


# --- grid region from the facility's ZIP code (EPA Power Profiler) --------------------------
def test_a_single_subregion_zip_sets_the_grid_region_and_says_so() -> None:
    store = FakeStore()
    store.add_document("BILL-A", "CT-S2-ELEC", [_elec(1200, "Facility A", "15 State Street, Albany, NY 12207")])
    result = _service(store).recalculate(_engagement(), _own)
    location = result["categories"]["purchased_electricity_location_based"]
    assert location["lines"][0]["key"] == "Facility A" and "grid_region_from_zip" in location["flags"]
    facility = location["details"]["inputs"][0]
    assert facility["grid_region"] == "NYUP" and facility["grid_region_source"].startswith("ZIP 12207")
    assert result["needs_input"] == []


def test_a_street_number_is_not_taken_for_a_zip_code() -> None:
    store = FakeStore()
    store.add_document("BILL-D", "CT-S2-ELEC", [_elec(300, "Dallas Office", "12345 Main St")])
    result = _service(store).recalculate(_engagement(), _own)
    assert result["categories"]["purchased_electricity_location_based"] is None
    ask = result["needs_input"][0]
    assert ask["kind"] == "grid_region" and len(ask["options"]) == 28  # every subregion: nothing guessed


def test_a_zip_with_several_subregions_asks_with_just_those() -> None:
    store = FakeStore()
    store.add_document("BILL-C", "CT-S2-ELEC", [_elec(500, "Facility C", "1 Main St, Ardsley, NY 10501")])
    ask = _service(store).recalculate(_engagement(), _own)["needs_input"][0]
    assert ask["kind"] == "grid_region" and ask["options"] == ["NYCW", "NYUP"]
    assert "ZIP 10501 is served by NYCW or NYUP" in ask["message"]
    # A reviewer's choice still wins over the ZIP code.
    chosen = {"recalculation": {"grid_regions": {"Facility C": "NYUP"}}}
    result = _service(store).recalculate(_engagement(**chosen), _own)
    assert result["needs_input"] == []
    source = result["categories"]["purchased_electricity_location_based"]["details"]["inputs"][0]["grid_region_source"]
    assert source == "chosen under Recalculation inputs"


# --- review findings: records that would net a negative or vanish silently --------------------
def test_refrigerant_records_that_cannot_be_right_are_asked_about_not_netted() -> None:
    store = FakeStore()
    store.add_document("PRECHARGED", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-03-01", "installation",
                                                                    added=8, capacity=10)])
    store.add_document("OVER", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-04-01", "disposal", recovered=12,
                                                              capacity=10)])
    store.add_document("BLANK", "CT-S1-REFRSVC", [_refrigerant("", "2025-05-01", added=3)])
    store.add_document("OK", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-06-01", added=4)])
    result = _service(store).recalculate(_engagement(), _own)
    asks = {n["key"]: n["message"] for n in result["needs_input"] if n["kind"] == "refrigerant_record"}
    assert set(asks) == {"PRECHARGED.pdf:installation", "OVER.pdf:disposal", "BLANK.pdf:refrigerant_type"}
    assert "pre-charged" in asks["PRECHARGED.pdf:installation"]
    line = result["categories"]["fugitive_refrigerants"]["lines"][0]
    assert line["steps"][0]["result"] == pytest.approx(4)  # only the usable record, nothing negative


def test_a_vehicle_group_for_a_fuel_without_records_is_reported() -> None:
    groups = [{"fuel": "Motor Gasoline", "vehicle_type": "Gasoline Passenger Cars", "factor_fuel_type": "Gasoline",
               "on_road": True, "model_year": 2020, "distance": 5000, "label": "pool cars"}]
    result = _service(_mobile_store()).recalculate(_engagement(recalculation={"vehicle_groups": groups}), _own)
    asks = [n["message"] for n in result["needs_input"] if n["kind"] == "vehicle_group"]
    assert asks == ["Motor Gasoline, pool cars: there are no reviewed Motor Gasoline records in the reporting "
                    "period, so this vehicle group is not used."]


def test_an_open_ended_oldest_model_year_band_is_used_as_is() -> None:
    groups = [{"fuel": "Diesel Fuel", "vehicle_type": "Medium- and Heavy-Duty Vehicles", "factor_fuel_type": "Diesel",
               "on_road": True, "model_year": 1955, "distance": 1000}]
    service = _service(_mobile_store())
    mobile = service.recalculate(_engagement(recalculation={"vehicle_groups": groups}), _own)["categories"][
        "mobile_combustion"]
    # Diesel trucks start at 1960 in Table 4: a 1955 truck uses the oldest band, with a note.
    assert "model_year_older_than_table" in mobile["flags"]
    hdv = next(t for t in service.reference.vehicle_types() if t["vehicle_type"] == "Gasoline Heavy-Duty Vehicles")
    assert hdv["first_model_year"] is None  # "1980 and earlier" covers any older year: nothing is moved


# --- the emissions roll-up ----------------------------------------------------------------
def test_open_items_name_their_roll_up_category() -> None:
    store = _workbook_example_store()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas(1000)], decision=None)
    result = _service(store).recalculate(_engagement(), _own)
    assert {item["category"] for item in result["needs_input"]} == {"purchased_electricity"}
    assert {item["category"] for item in result["awaiting_review"]} == {"stationary_combustion"}
    categories = result["rollup"]["categories"]
    assert (categories["purchased_electricity"]["status"], categories["purchased_electricity"]["open_items"]) == (
        "awaiting_inputs", 2)
    assert categories["stationary_combustion"]["status"] == "awaiting_inputs"


def test_roll_up_agrees_with_the_legacy_comparisons() -> None:
    store = _workbook_example_store()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas(1000)])
    store.add_document("REFRIG-LOG", "CT-S1-REFRSVC", [_refrigerant("R-410A", "2025-04-09", added=100)])
    settings = {"recalculation": {"grid_regions": {"Facility A": "NYUP", "Facility B": "RFCE"},
                                  "certificates": [{"label": "REC", "mwh": 600}]}}
    result = _service(store).recalculate(_engagement(**settings), _own)
    outputs = {o["key"]: o for o in result["rollup"]["final_outputs"]}
    for comparison in result["comparisons"]:
        if comparison["recalculated"] is not None and comparison["key"] != "biogenic_co2":
            assert outputs[comparison["key"]]["recalculated"] == pytest.approx(comparison["recalculated"]), \
                comparison["key"]
    nodes = result["rollup"]["nodes"]
    assert nodes["scope1_total"]["co2e_t"] == pytest.approx(result["scope_totals"]["scope1"]["total_co2e"])
    assert nodes["inventory_location_total"]["co2e_t"] == pytest.approx(
        result["scope_totals"]["scope1"]["total_co2e"] + result["scope_totals"]["scope2_location"]["total_co2e"])
    # Mobile has no evidence and process etc. aren't built: counted as 0, so the total is complete
    # and names them (Claire, Q5).
    assert nodes["scope1_total"]["status"] == "complete"
    assert {m["source"] for m in nodes["scope1_total"]["counted_as_zero"]} >= {"mobile_combustion", "process_sources"}


def test_absent_sources_complete_the_totals() -> None:
    store = FakeStore()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas(1000)])
    absent = {key: "None at this company (site visit)" for key in (
        "mobile_combustion", "process_sources", "fugitive_refrigerants", "fugitive_purchased_gases",
        "agricultural_sources")}
    result = _service(store).recalculate(_engagement(recalculation={
        "absent_sources": absent, "reported": {"scope1_total": 53.17}}), _own)
    scope1 = next(o for o in result["rollup"]["final_outputs"] if o["key"] == "scope1_total")
    assert (scope1["status"], scope1["completeness"]) == ("within_tolerance", "complete")
    assert result["rollup"]["categories"]["process_sources"]["absent_reason"] == "None at this company (site visit)"


def test_roll_up_settings_are_validated() -> None:
    validate_recalculation_settings({
        "absent_sources": {"process_sources": "No industrial processes"},
        "reported_units": {"scope1_hfcs": "t CO2e", "scope1_co2": "t"},
        "reported": {"purchased_cooling_total": 0, "scope2_nf3": 0.0, "scope1_total": None},
    })
    for bad in ({"absent_sources": {"not_a_source": "x"}}, {"absent_sources": {"process_sources": ""}},
                {"absent_sources": {"process_sources": "x" * 501}}, {"absent_sources": []},
                {"reported_units": {"scope1_total": "t"}}, {"reported_units": {"scope1_hfcs": "kg"}},
                {"reported": {"scope1_total": -1}}, {"reported": {"scope1_total": True}}):
        with pytest.raises(ValueError):
            validate_recalculation_settings(bad)


# --- data quality checks ---------------------------------------------------------------------
def test_quality_checks_name_the_documents_a_reviewer_should_look_at() -> None:
    store = _workbook_example_store()  # Facility A: two half-year bills; Facility B: one annual bill
    store.add_document("BILL-B-Q1", "CT-S2-ELEC", [_elec(96, "Facility B", "Philadelphia, PA", "2025-01-01", "2025-03-31")])
    store.add_document("GAS-JAN", "CT-S1-FUELQTY", [_gas(1000)])
    store.add_document("GAS-JAN-COPY", "CT-S1-FUELQTY", [_gas(1000)])
    result = _service(store).recalculate(_engagement(), _own)
    found = {(c["check"], c["trigger"]): c for c in result["quality_checks"]}
    overlap = found[("Q-004", "overlap_same_source_different_document_id")]
    assert overlap["documents"] == ["BILL-B1", "BILL-B-Q1"] and overlap["facility"] == "Facility B"
    assert found[("Q-003", "same_document_reuploaded_with_different_file_name")]["documents"] == ["GAS-JAN", "GAS-JAN-COPY"]
    gas_gap = found[("Q-001", "missing_month")]
    assert gas_gap["category"] == "stationary_combustion" and gas_gap["detail"]["missing_months"][0] == "Feb 2025"
    assert not any(c["facility"] == "Facility A" for c in result["quality_checks"])  # two half-year bills: complete
    # Marking the copy as a duplicate takes it out of the numbers and out of the checks.
    decided = _service(store).recalculate(_engagement(), _own, decisions={"GAS-JAN-COPY": {"relationships": [{"kind": "duplicate", "otherDocumentId": "GAS-JAN"}]}})
    assert not any(c["check"] == "Q-003" for c in decided["quality_checks"])
