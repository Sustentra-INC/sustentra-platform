"""Per-calculation-line recalculation: ``calculation_lines`` in the recalculation response."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.engagement_recalculation_service import (
    EngagementRecalculationService,
    validate_recalculation_settings,
)
from backend.tests.services.test_calculation_lines import ELEC_KC, ELEC_STL, GAS_KC, GAS_STL, KC, STL
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase, _own

REGIONS = {"Kansas City Plant": "NYUP", "St Louis Plant": "RFCE"}


def _service(store: FakeStore) -> EngagementRecalculationService:
    return EngagementRecalculationService(store, store, store)


def _engagement(**settings: Any) -> dict:
    settings.setdefault("facilities", [KC, STL])
    return {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
            "settings": settings}


def _run(store: FakeStore, decisions: dict | None = None, **recalculation: Any) -> dict:
    return _service(store).recalculate(_engagement(recalculation=recalculation), _own, decisions)


def _by_key(result: dict) -> dict[str, dict]:
    return {line["key"]: line for line in result["calculation_lines"]}


def _gas_store() -> FakeStore:
    store = FakeStore()
    store.add_document("GAS-KC-1", "CT-S1-FUELQTY", [_gas_record(30000, "2025-01-01", "2025-01-31")])
    store.add_document("GAS-KC-2", "CT-S1-FUELQTY", [_gas_record(35000, "2025-02-01", "2025-02-28")])
    store.add_document("GAS-STL", "CT-S1-FUELQTY", [_gas_record(500, "2025-01-01", "2025-01-31", plant="St Louis Plant")])
    return store


def test_stationary_lines_per_facility_add_up_to_the_category() -> None:
    result = _run(_gas_store())
    lines = _by_key(result)
    assert set(lines) == {GAS_KC, GAS_STL}
    kc = lines[GAS_KC]
    assert (kc["scope"], kc["category"], kc["level2"], kc["label"], kc["facility_id"]) == (
        "s1", "stationary", "Natural Gas", "Kansas City Plant", "fac-kc01")
    assert [(r["document_id"], r["quantity"], r["share_in_period"], r["period_start"], r["review"])
            for r in kc["step1"]["rows"]] == [("GAS-KC-1", 30000, 1, "2025-01-01", "accepted"),
                                              ("GAS-KC-2", 35000, 1, "2025-02-01", "accepted")]
    assert kc["step1"]["total"] == {"quantity": 65000, "unit": "MMBtu"}
    assert kc["step2"]["factor"] == 1 and kc["step2"]["result"] == {"quantity": 65000, "unit": "MMBtu"}
    assert kc["method"]["equations"]["CO2"] == "Eq. 1"
    co2 = next(g for g in kc["step3"]["gases"] if g["gas"] == "CO2")
    assert co2["ef"]["value"] == 53.06 and co2["mass_t"] == pytest.approx(65000 * 53.06 / 1000)
    assert co2["gwp"]["value"] == 1 and co2["co2e_t"] == pytest.approx(co2["mass_t"])
    category = result["categories"]["stationary_combustion"]
    assert sum(ln["results"]["total_co2e_t"] for ln in lines.values()) == pytest.approx(category["total_co2e"])
    for gas in ("CO2", "CH4", "N2O"):
        assert sum(ln["results"]["mass_t"][gas] for ln in lines.values()) == pytest.approx(category["total_mass_t"][gas])
    assert result["calculation_unplaced"] == []


def test_company_side_runs_its_activity_through_the_same_steps() -> None:
    """Kent Cannery board: 650,000 therms x 0.1 = 65,000 MMBtu x 53.06 kg/MMBtu = 3,448.9 t CO2."""

    result = _run(_gas_store(), reported_activity={GAS_KC: {"quantity": 650000, "unit": "therms"}},
                  reported_lines={GAS_KC: 3300})
    kc = _by_key(result)[GAS_KC]
    company = kc["company"]
    assert company["activity"] == {"quantity": 650000, "unit": "therms"}
    assert company["step2"]["factor"] == pytest.approx(0.1)
    assert company["step2"]["result"] == {"quantity": pytest.approx(65000), "unit": "MMBtu"}
    co2 = next(g for g in company["step3"]["gases"] if g["gas"] == "CO2")
    assert co2["mass_t"] == pytest.approx(3448.9)
    assert company["results"]["total_co2e_t"] == pytest.approx(kc["results"]["total_co2e_t"])
    assert kc["reported_total_co2e_t"] == 3300
    assert kc["difference_t"] == pytest.approx(kc["results"]["total_co2e_t"] - 3300)
    row = next(g for g in kc["step3"]["gases"] if g["gas"] == "CO2")
    assert row["company_co2e_t"] == pytest.approx(3448.9) and row["difference_t"] == pytest.approx(0, abs=1e-9)
    assert kc["results"]["company_total_co2e_t"] == pytest.approx(company["results"]["total_co2e_t"])
    assert result["needs_input"] == []
    # A line with no company figures has no company side.
    assert _by_key(result)[GAS_STL]["company"] is None


def test_line_status_is_judged_against_the_reported_base_with_the_materiality_tolerance() -> None:
    within = _by_key(_run(_gas_store(), reported_lines={GAS_KC: 3440}))[GAS_KC]
    assert within["status"] == "within" and abs(within["difference_pct_of_base"]) < 5
    above = _by_key(_run(_gas_store(), reported_lines={GAS_KC: 3000}))[GAS_KC]
    assert above["status"] == "above" and above["difference_pct_of_base"] > 5
    none = _by_key(_run(_gas_store()))[GAS_KC]
    assert (none["status"], none["difference_t"], none["reported_total_co2e_t"]) == ("not_reported", None, None)


def test_a_company_unit_that_cannot_convert_is_asked_about_and_unknown_keys_are_flagged() -> None:
    result = _run(_gas_store(), reported_activity={GAS_KC: {"quantity": 5, "unit": "gal"},
                                                   "s1:stationary:coal:nowhere": {"quantity": 1, "unit": "ton"}},
                  reported_lines={"s1:stationary:coal:nowhere": 10})
    assert _by_key(result)[GAS_KC]["company"] is None
    asks = [i for i in result["needs_input"] if i["kind"] == "company_activity"]
    assert len(asks) == 1 and asks[0]["key"] == GAS_KC and "gal" in asks[0]["message"]
    assert result["calculation_line_inputs"]["unknown_line_keys"] == [
        {"setting": "reported_activity", "key": "s1:stationary:coal:nowhere"},
        {"setting": "reported_lines", "key": "s1:stationary:coal:nowhere"}]


def test_consolidated_share_scales_the_line_total_only() -> None:
    full = _by_key(_run(_gas_store()))[GAS_KC]
    half_result = _service(_gas_store()).recalculate(
        _engagement(recalculation={"consolidated_shares": {"fac-kc01": 50}}), _own)
    half = _by_key(half_result)[GAS_KC]
    assert half["consolidated_share_pct"] == 50
    assert half["results"]["sum_co2e_t"] == pytest.approx(full["results"]["sum_co2e_t"])
    assert half["results"]["total_co2e_t"] == pytest.approx(full["results"]["sum_co2e_t"] / 2)
    assert half_result["categories"]["stationary_combustion"]["total_co2e"] == pytest.approx(
        _run(_gas_store())["categories"]["stationary_combustion"]["total_co2e"])


def test_prorated_records_show_their_share_and_counted_quantity() -> None:
    store = FakeStore()
    store.add_document("GAS-CROSS", "CT-S1-FUELQTY", [_gas_record(1000, "2024-12-22", "2025-01-10")])
    row = _by_key(_run(store))[GAS_KC]["step1"]["rows"][0]
    assert row["share_in_period"] == pytest.approx(10 / 20)
    assert row["counted_quantity"] == pytest.approx(500) and row["quantity"] == 1000


def test_therm_bills_convert_in_step_two() -> None:
    store = FakeStore()
    store.add_document("GAS-THERM", "CT-S1-FUELQTY", [{**_gas_record(1000), "activity_quantity": (1000, "therm")}])
    line = _by_key(_run(store))[GAS_KC]
    assert line["step1"]["total"] == {"quantity": 1000, "unit": "therm"}
    assert line["step2"]["from_unit"] == "therm" and line["step2"]["to_unit"] == "MMBtu"
    assert line["step2"]["factor"] == pytest.approx(0.1) and line["step2"]["result"]["quantity"] == pytest.approx(100)


def test_gwp_set_changes_only_the_gwp_dependent_numbers() -> None:
    by_set = {name: _by_key(_run(_gas_store(), gwp_set=name))[GAS_KC] for name in ("AR4", "AR5", "AR6")}
    assert {n: [g["gwp"]["value"] for g in ln["step3"]["gases"]] for n, ln in by_set.items()} == {
        "AR4": [1, 25, 298], "AR5": [1, 28, 265], "AR6": [1, 27.0, 273]}
    assert "AR4 WG1 Table 2.14" in by_set["AR4"]["step3"]["gases"][1]["gwp"]["source"]
    masses = [ln["results"]["mass_t"] for ln in by_set.values()]
    assert masses[0] == masses[1] == masses[2]
    ef = [[g["ef"]["value"] for g in ln["step3"]["gases"]] for ln in by_set.values()]
    assert ef[0] == ef[1] == ef[2]
    totals = [ln["results"]["sum_co2e_t"] for ln in by_set.values()]
    assert len(set(totals)) == 3
    assert _run(_gas_store(), gwp_set="AR4")["gwp_set"] == "AR4"
    ch4 = by_set["AR4"]["results"]["mass_t"]["CH4"]
    assert by_set["AR4"]["results"]["gas_co2e_t"]["CH4"] == pytest.approx(ch4 * 25)


def test_a_record_with_no_line_is_reported_unplaced_and_the_totals_still_reconcile() -> None:
    store = _gas_store()
    store.add_document("GAS-ELSEWHERE", "CT-S1-FUELQTY", [_gas_record(200, plant="Somewhere Else Ltd")])
    result = _run(store)
    unplaced = result["calculation_unplaced"]
    assert len(unplaced) == 1 and unplaced[0]["key"] is None
    assert unplaced[0]["step1"]["rows"][0]["document_id"] == "GAS-ELSEWHERE"
    assert unplaced[0]["step1"]["total"] == {"quantity": 200, "unit": "MMBtu"}
    category = result["categories"]["stationary_combustion"]
    everything = [*result["calculation_lines"], *unplaced]
    assert sum(ln["results"]["total_co2e_t"] for ln in everything) == pytest.approx(category["total_co2e"])


def test_a_reviewer_move_puts_the_document_on_the_other_line() -> None:
    decisions = {"GAS-STL": {"placements": [{"from": GAS_STL, "to": GAS_KC}]}}
    result = _run(_gas_store(), decisions)
    lines = _by_key(result)
    assert GAS_STL not in lines
    assert [r["document_id"] for r in lines[GAS_KC]["step1"]["rows"]] == ["GAS-KC-1", "GAS-STL", "GAS-KC-2"]
    assert lines[GAS_KC]["results"]["total_co2e_t"] == pytest.approx(
        result["categories"]["stationary_combustion"]["total_co2e"])


def test_electricity_lines_per_facility_add_up_to_the_location_based_category() -> None:
    store = FakeStore()
    store.add_document("E-KC", "CT-S2-ELEC", [{**_elec_record(1200, start="2025-01-01", end="2025-12-31"),
                                               "activity_quantity": (1200000, "kWh")}])
    store.add_document("E-STL", "CT-S2-ELEC", [_elec_record(800, plant="St Louis Plant", start="2025-01-01",
                                                            end="2025-12-31")])
    result = _run(store, grid_regions=REGIONS)
    lines = _by_key(result)
    assert set(lines) == {ELEC_KC, ELEC_STL}
    kc = lines[ELEC_KC]
    assert kc["step1"]["total"] == {"quantity": 1200000, "unit": "kWh"}
    assert kc["step2"]["factor"] == pytest.approx(0.001) and kc["step2"]["result"]["quantity"] == pytest.approx(1200)
    co2 = next(g for g in kc["step3"]["gases"] if g["gas"] == "CO2")
    assert co2["activity"] == {"value": pytest.approx(1200), "unit": "MWh"}
    assert co2["unit_conversion"] == pytest.approx(1 / 2204.62)
    assert co2["mass_t"] == pytest.approx(co2["activity"]["value"] * co2["ef"]["value"] / 2204.62)
    category = result["categories"]["purchased_electricity_location_based"]
    assert sum(ln["results"]["total_co2e_t"] for ln in lines.values()) == pytest.approx(category["total_co2e"])
    # Company side: kWh -> MWh through fuel_units.
    with_company = _by_key(_run(store, grid_regions=REGIONS,
                                reported_activity={ELEC_KC: {"quantity": 1000000, "unit": "kWh"}}))[ELEC_KC]
    assert with_company["company"]["step2"]["result"]["quantity"] == pytest.approx(1000)
    assert with_company["company"]["results"]["total_co2e_t"] < kc["results"]["total_co2e_t"]


GROUP_ROAD = {"fuel": "Diesel Fuel", "vehicle_type": "Medium- and Heavy-Duty Vehicles", "factor_fuel_type": "Diesel",
              "on_road": True, "model_year": 2018, "distance": 10000, "distance_unit": "mi", "label": "Heavy trucks"}
GROUP_OFF = {"fuel": "Diesel Fuel", "vehicle_type": "Industrial/Commercial Equipment", "factor_fuel_type": "Diesel",
             "on_road": False, "fuel_quantity": 200, "fuel_unit": "gal", "label": "Forklifts"}


def _mobile_store() -> FakeStore:
    store = FakeStore()
    store.add_document("FLEET", "CT-S1-MOBFUEL", [_diesel_purchase(600), _diesel_purchase(400, "2025-09-01")])
    return store


def test_a_mobile_fuel_with_one_vehicle_group_is_one_line() -> None:
    result = _run(_mobile_store(), vehicle_groups=[GROUP_ROAD])
    (line,) = result["calculation_lines"]
    assert line["key"] == "s1:mobile:diesel-fuel:vg-heavy-trucks"
    assert (line["category"], line["label"], line["facility_id"], line["consolidated_share_pct"]) == (
        "mobile", "Heavy trucks", None, 100)
    assert line["step1"]["total"] == {"quantity": 1000, "unit": "gal"}
    assert line["step1"]["rows"][0]["period_start"] == line["step1"]["rows"][0]["period_end"] == "2025-05-01"
    by_gas = {g["gas"]: g for g in line["step3"]["gases"]}
    assert by_gas["CO2"]["activity"] == {"value": 1000, "unit": "gal"}
    assert by_gas["CH4"]["activity"] == {"value": 10000, "unit": "mi"}  # distance, Eq 4
    assert line["method"]["equations"] == {"CO2": "Eq. 1", "CH4": "Eq. 4", "N2O": "Eq. 4"}
    distance = line["step2"]["distance"]
    assert (distance["fuel_economy"]["value"], distance["fuel_economy"]["unit"]) == (10, "mi/gal")
    assert distance["result"] == {"quantity": 10000, "unit": "mi"}
    assert line["step2"]["source"] is None  # gal needs no conversion
    assert _by_key(_run(_gas_store()))[GAS_KC]["step2"]["distance"] is None
    category = result["categories"]["mobile_combustion"]
    assert line["results"]["total_co2e_t"] == pytest.approx(category["total_co2e"])
    # Company fuel drives CO2; the group's CH4 and N2O stay as entered.
    company = _by_key(_run(_mobile_store(), vehicle_groups=[GROUP_ROAD],
                           reported_activity={line["key"]: {"quantity": 2000, "unit": "gal"}}))[line["key"]]
    assert next(g for g in company["company"]["step3"]["gases"] if g["gas"] == "CO2")["mass_t"] == pytest.approx(
        2 * by_gas["CO2"]["mass_t"])
    assert "company_ch4_n2o_use_vehicle_group" in company["flags"]


def test_two_vehicle_groups_are_two_lines_and_unplaced_fuel_keeps_the_total_whole() -> None:
    result = _run(_mobile_store(), vehicle_groups=[GROUP_ROAD, GROUP_OFF])
    lines = _by_key(result)
    assert set(lines) == {"s1:mobile:diesel-fuel:vg-heavy-trucks", "s1:mobile:diesel-fuel:vg-forklifts"}
    ch4 = {k: next(g for g in ln["step3"]["gases"] if g["gas"] == "CH4") for k, ln in lines.items()}
    assert ch4["s1:mobile:diesel-fuel:vg-heavy-trucks"]["activity"]["unit"] == "mi"  # Eq 4 on-road
    assert ch4["s1:mobile:diesel-fuel:vg-forklifts"]["activity"] == {"value": 200, "unit": "gal"}  # Eq 5 non-road
    assert lines["s1:mobile:diesel-fuel:vg-forklifts"]["method"]["equations"]["CH4"] == "Eq. 5"
    # Two groups use the fuel, so its records cannot pick one: they are listed, not dropped.
    (unplaced,) = result["calculation_unplaced"]
    assert unplaced["step1"]["total"] == {"quantity": 1000, "unit": "gal"}
    category = result["categories"]["mobile_combustion"]
    everything = [*lines.values(), unplaced]
    assert sum(ln["results"]["total_co2e_t"] for ln in everything) == pytest.approx(category["total_co2e"])
    # A reviewer files the document on a group: then it is whole.
    moved = _run(_mobile_store(), {"FLEET": {"placements": [
        {"from": "supporting:unassigned", "to": "s1:mobile:diesel-fuel:vg-heavy-trucks"}]}},
        vehicle_groups=[GROUP_ROAD, GROUP_OFF])
    assert moved["calculation_unplaced"] == []
    assert sum(ln["results"]["total_co2e_t"] for ln in moved["calculation_lines"]) == pytest.approx(
        category["total_co2e"])


def test_biomass_lines_show_biogenic_co2_and_count_ch4_n2o_toward_their_category() -> None:
    store = FakeStore()
    store.add_document("WOOD", "CT-S1-FUELQTY", [{**_gas_record(100, fuel="biomass"),
                                                   "activity_quantity": (100, "short_ton")}])
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas_record(1000)])
    result = _run(store, fuel_choices={"stationary:biomass": "Wood and Wood Residuals"})
    wood = next(ln for ln in result["calculation_lines"] if ln["category"] == "biogenic")
    assert wood["scope"] == "biogenic" and wood["counts_toward"] == "stationary"
    assert wood["results"]["biogenic_co2_t"] > 0 and wood["results"]["mass_t"]["CO2"] == 0
    assert "biogenic_co2_reported_separately" in wood["flags"]
    category = result["categories"]["stationary_combustion"]
    counted = [ln for ln in result["calculation_lines"] if ln["counts_toward"] == "stationary"]
    assert sum(ln["results"]["total_co2e_t"] for ln in counted) == pytest.approx(category["total_co2e"])
    assert sum(ln["results"]["biogenic_co2_t"] for ln in counted) == pytest.approx(category["biogenic_co2_t"])


def test_existing_response_keys_are_unchanged_and_new_ones_added() -> None:
    result = _run(_gas_store())
    assert {"categories", "scope_totals", "comparisons", "needs_input", "rollup", "excluded"} <= set(result)
    assert {"calculation_lines", "calculation_unplaced", "calculation_line_inputs"} <= set(result)
    assert result["gwp_set"] == "AR5"


def test_line_inputs_are_validated() -> None:
    validate_recalculation_settings({
        "gwp_set": "AR4", "reported_lines": {GAS_KC: 12.5},
        "reported_activity": {GAS_KC: {"quantity": 650000, "unit": "therms"}},
        "consolidated_shares": {"fac-kc01": 80}})
    for bad in ({"reported_lines": {GAS_KC: -1}}, {"reported_lines": [1]}, {"reported_lines": {GAS_KC: "x"}},
                {"reported_activity": {GAS_KC: {"quantity": 1}}},
                {"reported_activity": {GAS_KC: {"quantity": 1, "unit": ""}}},
                {"reported_activity": {GAS_KC: {"quantity": -1, "unit": "gal"}}},
                {"reported_activity": {GAS_KC: {"quantity": 1, "unit": "gal", "extra": 1}}},
                {"consolidated_shares": {"fac-kc01": 101}}, {"consolidated_shares": {"fac-kc01": -1}}):
        with pytest.raises(ValueError):
            validate_recalculation_settings(bad)
