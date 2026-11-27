"""Mobile combustion panel (C3): a vehicle group's distance as fuel x fuel economy, the distance-source rule (Q5), and
non-road equipment. Every expected number is the plan's (calc-panels-plan.md, C3), as an exact test."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.tests.services.calc_trace.recalc_scenarios import GROUP_ROAD, REGIONS, mixed_store, run, scenarios
from backend.tests.services.calc_trace.test_calc_trace_decisions import DIESEL, SCHEMA, block, event, gas_store, line_of
from backend.tests.services.calc_trace.test_line_totals import _assert_lines_add_up
from backend.tests.services.test_calculation_lines import GAS_KC
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase

COMPANY = {DIESEL: {"quantity": 380000, "unit": "gal"}}
GROUP_7MPG = {**GROUP_ROAD, "distance": 2_660_000}  # 380,000 gal at 7.00 mpg
NON_ROAD = {"fuel": "Diesel Fuel", "vehicle_type": "Industrial/Commercial Equipment", "factor_fuel_type": "Diesel",
            "on_road": False, "label": "Yard loaders"}
LOADERS = "s1:mobile:diesel-fuel:vg-yard-loaders"
ECONOMY = "input|fuel_economy|recomputed"
ABS = 1e-9


def diesel_store(gallons: float = 380000) -> FakeStore:
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(gallons)])
    return store


def trace_of(response: dict, key: str = DIESEL) -> dict:
    trace = line_of(response, key)["trace"]
    jsonschema.validate(trace, SCHEMA)
    return trace


def mass(trace: dict, gas: str) -> float:
    return float(block(trace, f"emissions.{gas}")["recomputed"]["result"]["value"])


def mobile_total(response: dict) -> float:
    return float(response["categories"]["mobile_combustion"]["total_co2e"])


# --- the plan's numbers ------------------------------------------------------------------------------------------------
def test_diesel_380000_gal_at_7_mpg_is_the_plans_line() -> None:
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY)
    trace = trace_of(response)
    assert trace["inputs"]["fuel_economy"]["recomputed"]["value"] == pytest.approx(7.0, abs=ABS)
    distance = block(trace, "distance")["recomputed"]
    assert distance["result"]["value"] == pytest.approx(2_660_000, abs=ABS)
    assert distance["result"]["unit"] == "mi"
    assert mass(trace, "CH4") == pytest.approx(0.02527, abs=ABS)
    assert mass(trace, "N2O") == pytest.approx(0.114646, abs=ABS)
    assert trace["result"]["recomputed"] == pytest.approx(3910.88875, abs=ABS)
    assert trace["result"]["company"] == pytest.approx(3910.88875, abs=ABS) and trace["result"]["difference"] == 0
    assert mobile_total(response) == pytest.approx(3910.88875, abs=ABS)


def test_a_verifier_fuel_economy_of_6_55_gives_2_489_000_mi_and_the_plans_difference() -> None:
    base = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY)
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY,
                   line_decisions=[event(DIESEL, ECONOMY, "edited", 6.55, "mi/gal")])
    trace = trace_of(response)
    jsonschema.validate(trace, SCHEMA)
    distance = block(trace, "distance")["recomputed"]["result"]
    assert distance["value"] == pytest.approx(2_489_000, abs=ABS) and distance["difference"] == pytest.approx(-171_000, abs=ABS)
    assert mass(trace, "CH4") == pytest.approx(0.0236455, abs=ABS)
    assert mass(trace, "N2O") == pytest.approx(0.1072759, abs=ABS)
    assert trace["result"]["recomputed"] == pytest.approx(3908.8901875, abs=ABS)
    assert trace["result"]["difference"] == pytest.approx(-1.9985625, abs=ABS)  # Claire's "3,909 (-2)"
    economy = trace["inputs"]["fuel_economy"]
    assert economy["recomputed"]["value"] == 6.55 and economy["recomputed"]["status"] == "edited"
    assert economy["company"]["value"] == pytest.approx(7.0, abs=ABS) and economy["difference"] == pytest.approx(-0.45)
    assert trace["inputs"]["distance"]["recomputed"]["status"] == "derived"
    assert trace["inputs"]["distance"]["recomputed"]["source"]["from"] == ["activity.total", "fuel_economy"]
    assert "distance_from_fuel_economy" in trace["flags"] and "reviewer_decisions_applied" in trace["flags"]
    # the CO2 follows the fuel, which did not move; the Step 3 operand is the derived distance
    assert block(trace, "emissions.CO2")["recomputed"] == block(
        trace_of(base), "emissions.CO2")["recomputed"]
    assert block(trace, "emissions.CH4")["recomputed"]["terms"][0]["operand"]["value"] == pytest.approx(2_489_000)
    # ... and it is the category's number too, with the lines still adding up to it
    assert mobile_total(response) == pytest.approx(3908.8901875, abs=ABS)
    _assert_lines_add_up(response)
    assert line_of(response, DIESEL)["results"]["total_co2e_t"] == pytest.approx(3908.8901875, abs=ABS)
    assert line_of(response, DIESEL)["decisions"]["applied"][0]["value"] == 6.55


def test_non_road_industrial_diesel_12000_gal() -> None:
    response = run(diesel_store(12000), vehicle_groups=[NON_ROAD])
    trace = trace_of(response, LOADERS)
    assert mass(trace, "CO2") == pytest.approx(122.52, abs=ABS)
    assert mass(trace, "CH4") == pytest.approx(0.00516, abs=ABS)
    assert mass(trace, "N2O") == pytest.approx(0.00744, abs=ABS)
    assert trace["result"]["recomputed"] == pytest.approx(124.63608, abs=ABS)
    assert mobile_total(response) == pytest.approx(124.63608, abs=ABS)
    assert "fuel_economy" not in trace["inputs"] and all(b["id"] != "distance" for s in trace["steps"] for b in s["blocks"])
    assert "Eq. 5" in trace["choices"][0]["options"][0]["label"]
    # fuel x Table 5's per-gallon factors, not a distance
    assert block(trace, "emissions.CH4")["recomputed"]["terms"][0]["operand"]["unit"] == "gal"


# --- the fuel economy is an input a reviewer decides, from the line's action menus ----------------------------------
def test_the_fuel_economy_is_offered_as_a_decidable_mi_per_gal_input() -> None:
    trace = trace_of(run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY))
    item = trace["inputs"]["fuel_economy"]
    assert item["decidable"] is True and item["recomputed"]["unit"] == "mi/gal" and item["id"] == "fuel_economy"
    assert item["recomputed"]["status"] == "derived" and item["company"]["status"] == "derived"
    operands = [t["operand"] for t in block(trace, "distance")["recomputed"]["terms"]]
    assert [o.get("input_id") for o in operands] == [None, "fuel_economy"]  # the cell the panel puts its menu on
    assert [(o["column"], o["unit"]) for o in operands] == [("fuel", "gal"), ("economy", "mi/gal")]


def test_without_a_company_figure_there_is_no_company_fuel_economy() -> None:
    trace = trace_of(run(diesel_store(), vehicle_groups=[GROUP_7MPG]))
    assert "company" not in trace["inputs"]["fuel_economy"] and "company" not in block(trace, "distance")
    moved = trace_of(run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=[event(DIESEL, ECONOMY, "edited", 5.0)]))
    assert moved["result"]["company"] is None and moved["result"]["difference"] is None


def test_a_decided_fuel_economy_follows_a_decided_fuel() -> None:
    fuel = event(DIESEL, "input|activity.total|recomputed", "edited", 400000, "gal")
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=[fuel, event(DIESEL, ECONOMY, "edited", 6.0)])
    trace = trace_of(response)
    assert block(trace, "distance")["recomputed"]["result"]["value"] == pytest.approx(2_400_000)
    assert mass(trace, "CH4") == pytest.approx(2_400_000 * 0.0095 / 1e6, abs=ABS)
    assert mass(trace, "CO2") == pytest.approx(400000 * 10.21 / 1000, abs=ABS)
    _assert_lines_add_up(response)


def test_a_decided_fuel_alone_keeps_the_entered_distance_and_the_fuel_economy_it_implies_follows() -> None:
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG],
                   line_decisions=[event(DIESEL, "input|activity.total|recomputed", "edited", 400000, "gal")])
    trace = trace_of(response)
    assert mass(trace, "CH4") == pytest.approx(0.02527, abs=ABS)  # by distance: the fuel does not move it
    assert trace["inputs"]["fuel_economy"]["recomputed"]["value"] == pytest.approx(2_660_000 / 400000)
    assert block(trace, "distance")["recomputed"]["result"]["value"] == pytest.approx(2_660_000)
    assert "distance_from_fuel_economy" not in trace["flags"]


def test_a_decided_distance_alone_stands_and_the_fuel_economy_follows() -> None:
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY,
                   line_decisions=[event(DIESEL, "input|distance|recomputed", "edited", 2_489_000, "mi")])
    trace = trace_of(response)
    assert trace["inputs"]["fuel_economy"]["recomputed"]["value"] == pytest.approx(6.55)
    assert trace["inputs"]["fuel_economy"]["recomputed"]["status"] == "derived"
    assert trace["inputs"]["distance"]["recomputed"]["status"] == "edited"
    assert trace["result"]["recomputed"] == pytest.approx(3908.8901875, abs=ABS)
    assert block(trace, "distance")["recomputed"]["result"]["difference"] == pytest.approx(-171_000)


def test_the_fuel_economy_wins_over_a_decided_distance_and_the_distance_decision_is_reported() -> None:
    both = [event(DIESEL, "input|distance|recomputed", "edited", 1_000_000, "mi"),
            event(DIESEL, ECONOMY, "edited", 6.55, "mi/gal")]
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=both)
    only = run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=[both[1]])
    assert mobile_total(response) == mobile_total(only)
    line = line_of(response, DIESEL)
    assert [(n["id"], n["reason"]) for n in line["decisions"]["not_applied"]] == [("distance", "fuel_economy_decided")]
    assert trace_of(response)["inputs"]["distance"]["recomputed"]["value"] == pytest.approx(2_489_000)


def test_a_pending_suggestion_a_rejection_and_a_company_side_edit_move_nothing() -> None:
    plain = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY)
    quiet = [event(DIESEL, ECONOMY, "pending", suggestion=5.0), event(DIESEL, "input|fuel_economy|company", "edited", 9.0, "mi/gal")]
    after = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY, line_decisions=quiet)
    assert after["categories"] == plain["categories"]
    assert trace_of(after)["steps"] == trace_of(plain)["steps"]
    rejected = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY,
                   line_decisions=[event(DIESEL, ECONOMY, "rejected")])
    assert rejected["categories"] == plain["categories"]
    assert trace_of(rejected)["inputs"]["fuel_economy"]["recomputed"]["status"] == "rejected"


def test_a_decided_fuel_economy_is_reverted_by_removing_it() -> None:
    plain = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY)
    reverted = run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY,
                   line_decisions=[event(DIESEL, ECONOMY, "pending")])
    assert reverted["categories"] == plain["categories"] and reverted["scope_totals"] == plain["scope_totals"]


# --- hostile values never reach the arithmetic ------------------------------------------------------------------------
@pytest.mark.parametrize("value, unit", [
    (0, "mi/gal"), (-7, "mi/gal"), (float("nan"), "mi/gal"), (float("inf"), "mi/gal"), (1e16, "mi/gal"),
    ("seven", "mi/gal"), (True, "mi/gal"), (None, "mi/gal"), ("٧", "mi/gal"), (6.55, "km/L"), (6.55, "mpg"),
])
def test_a_hostile_fuel_economy_is_reported_and_never_used(value: Any, unit: str) -> None:
    plain = run(diesel_store(), vehicle_groups=[GROUP_7MPG])
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=[event(DIESEL, ECONOMY, "edited", value, unit)])
    assert response["categories"] == plain["categories"]
    line = line_of(response, DIESEL)
    assert line["decisions"]["applied"] == [] and [n["id"] for n in line["decisions"]["not_applied"]] == ["fuel_economy"]
    assert trace_of(response)["steps"] == trace_of(plain)["steps"]


@pytest.mark.parametrize("value", [1e15, 1e-300])
def test_an_extreme_but_valid_fuel_economy_leaves_a_finite_whole_response(value: float) -> None:
    response = run(diesel_store(), vehicle_groups=[GROUP_7MPG], line_decisions=[event(DIESEL, ECONOMY, "edited", value, "mi/gal")])
    assert math.isfinite(mobile_total(response)) and trace_of(response) is not None
    json.dumps(response, allow_nan=False)


def test_a_fuel_economy_decision_on_a_line_without_one_is_reported_on_that_line_only() -> None:
    stray = [event(GAS_KC, ECONOMY, "edited", 7.0, "mi/gal"), event(LOADERS, ECONOMY, "edited", 7.0, "mi/gal"),
             event("s1:mobile:diesel-fuel:vg-someone-elses", ECONOMY, "edited", 7.0, "mi/gal")]
    plain = run(mixed_store(), grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD, NON_ROAD])
    response = run(mixed_store(), grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD, NON_ROAD], line_decisions=stray)
    for key in ("categories", "scope_totals", "comparisons", "rollup"):
        assert response[key] == plain[key], key
    assert [n["reason"] for n in line_of(response, GAS_KC)["decisions"]["not_applied"]] == ["not_on_this_line"]


# --- where there is no fuel economy ---------------------------------------------------------------------------------
def test_no_fuel_economy_without_a_distance_or_when_the_line_does_not_hold_all_its_fuel() -> None:
    no_distance = {k: v for k, v in GROUP_ROAD.items() if k != "distance"}
    assert "fuel_economy" not in trace_of(run(diesel_store(), vehicle_groups=[no_distance]))["inputs"]
    second = {**GROUP_ROAD, "label": "Vans", "distance": 5000}
    for line in run(diesel_store(), vehicle_groups=[GROUP_ROAD, second])["calculation_lines"]:
        if line["trace"]:
            assert "fuel_economy" not in line["trace"]["inputs"]
    assert "fuel_economy" not in trace_of(run(gas_store()), GAS_KC)["inputs"]


def test_litres_and_gallons_on_one_line_are_one_fuel_in_gallons() -> None:
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(300), {**_diesel_purchase(100), "activity_quantity": (100, "L"),
                                                                       "activity_unit": ("L", None)}])
    gallons = 300 + 100 / 3.785411784
    trace = trace_of(run(store, vehicle_groups=[GROUP_7MPG]))
    assert trace["inputs"]["fuel_economy"]["recomputed"]["value"] == pytest.approx(2_660_000 / gallons, rel=1e-9)
    assert block(trace, "distance")["recomputed"]["result"]["value"] == pytest.approx(2_660_000, rel=1e-9)


def test_a_line_with_no_evidence_is_still_a_line_with_no_fuel_economy() -> None:
    response = run(FakeStore(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY)
    for line in response["calculation_lines"]:
        assert not line.get("trace") or "fuel_economy" not in line["trace"]["inputs"]


# --- with no decision nothing moves -----------------------------------------------------------------------------------
def test_with_no_fuel_economy_decision_every_total_is_the_calculators_own() -> None:
    # the calculator by itself: 380,000 gal at 10.21 kg/gal, 2,660,000 mi at Table 4's 2007-2022 row
    plain = run(diesel_store(), with_traces=False, vehicle_groups=[GROUP_7MPG])
    with_traces = run(diesel_store(), with_traces=True, vehicle_groups=[GROUP_7MPG])
    assert plain["categories"] == with_traces["categories"] and plain["scope_totals"] == with_traces["scope_totals"]
    assert plain["categories"]["mobile_combustion"]["total_co2e"] == pytest.approx(
        380000 * 10.21 / 1000 + (2_660_000 * 0.0095 / 1e6) * 28 + (2_660_000 * 0.0431 / 1e6) * 265, abs=ABS)
    for name, response in scenarios().items():
        _assert_lines_add_up(response)
        assert response["categories"] == scenarios(with_traces=False)[name]["categories"], name


def test_every_mobile_trace_in_the_backend_scenarios_checks_out() -> None:
    for response in scenarios().values():
        for line in response["calculation_lines"]:
            if line["counts_toward"] == "mobile" and line["trace"]:
                jsonschema.validate(line["trace"], SCHEMA)


def test_the_frontend_fixture_is_the_backends_current_trace() -> None:
    """``calcTraceMobile.json`` (read by the TypeScript contract test) is Claire's diesel line as the backend builds it."""

    live = trace_of(run(diesel_store(), vehicle_groups=[GROUP_7MPG], reported_activity=COMPANY))
    path = Path(__file__).parents[4] / "frontend" / "features" / "s1" / "api" / "__fixtures__" / "calcTraceMobile.json"
    assert json.loads(path.read_text()) == live
