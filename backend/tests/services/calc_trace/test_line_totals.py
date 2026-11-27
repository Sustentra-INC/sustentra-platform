"""Category totals from the calculation lines (F3b): with no decision every total is the calculators' own; a decision
on a line moves its line, its category, its scope, the comparisons, the roll-up and the Excel workpaper by exactly the
decided difference, and a revert puts every one of them back."""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

import pytest
from openpyxl import load_workbook

from backend.app.services import emissions_calculator as calc
from backend.app.services import line_totals
from backend.app.services.workpaper_export_service import build_workbook
from backend.tests.services.calc_trace import fixture_replay
from backend.tests.services.calc_trace.recalc_scenarios import GROUP_ROAD, REGIONS, mixed_store, run, scenarios
from backend.tests.services.calc_trace.test_calc_trace_decisions import (
    DIESEL, NG_T_PER_MMBTU, event, gas_store, line_of,
)
from backend.tests.services.test_calculation_lines import ELEC_STL, GAS_KC, GAS_STL
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase

FAMILIES = {"stationary": "stationary_combustion", "mobile": "mobile_combustion",
            "purchased_energy": "purchased_electricity_location_based"}
TOL = 1e-9


def _every_line(response: dict) -> list[dict]:
    return [*response["calculation_lines"], *response["calculation_unplaced"]]


def _assert_lines_add_up(response: dict) -> int:
    """Σ lines + unplaced = each family's category (mass by gas and biogenic CO2, and CO2e from the line traces)."""

    checked = 0
    for counts_toward, name in FAMILIES.items():
        category = response["categories"].get(name)
        sums = line_totals.line_sums(_every_line(response), counts_toward)
        assert line_totals.adds_up(sums, category), (name, sums, category and category["total_mass_t"])
        traced = [ln for ln in response["calculation_lines"] if ln["counts_toward"] == counts_toward]
        if category is not None and all(ln.get("trace") for ln in traced):
            from_traces = sum(next(b for s in ln["trace"]["steps"] for b in s["blocks"]
                                   if b["id"] == "results.sum")["recomputed"]["result"]["value"] for ln in traced)
            unplaced = sum(u["results"]["sum_co2e_t"] for u in response["calculation_unplaced"]
                           if u["counts_toward"] == counts_toward)
            assert math.isclose(from_traces + unplaced, category["total_co2e"], rel_tol=TOL, abs_tol=TOL), name
        checked += category is not None
    return checked


# --- the guard: with no decisions, every total is today's ------------------------------------------------------------
@pytest.mark.parametrize("name", fixture_replay.NAMES, ids=fixture_replay.slug)
def test_every_recorded_fixture_adds_up_line_by_line_and_matches_its_recorded_totals(name: str) -> None:
    recorded = fixture_replay.load(name)
    response = fixture_replay.replay(name, with_traces=True)
    for category in fixture_replay.FAMILIES:
        want, got = recorded["categories"].get(category), response["categories"].get(category)
        assert (want is None) == (got is None), category
        if want is None:
            continue
        assert math.isclose(got["total_co2e"], want["total_co2e"], rel_tol=TOL), category
        for gas in calc.GASES:
            assert math.isclose(got["total_mass_t"][gas], want["total_mass_t"][gas], rel_tol=TOL, abs_tol=1e-12)
    _assert_lines_add_up(response)
    store, engagement = fixture_replay.rebuild(recorded)
    no_decisions = fixture_replay.SetupFromStoreService(store).recalculate(engagement, fixture_replay._own, None,
                                                                          line_decisions=[])
    assert no_decisions == fixture_replay.replay(name)


@pytest.mark.parametrize("name", ["plain", "company", "share", "no_regions"])
def test_every_backend_scenario_adds_up_line_by_line(name: str) -> None:
    assert _assert_lines_add_up(scenarios()[name]) >= 1 or name == "no_regions"


def test_decisions_that_change_no_number_leave_every_total_exactly_as_it_was() -> None:
    plain = run(mixed_store(), with_traces=False, grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD])
    method = line_of(run(mixed_store(), grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD]), GAS_KC)["trace"]["choices"][0]
    quiet = [event(GAS_KC, "input|activity.total|recomputed", "pending", suggestion=1.0),
             event(GAS_KC, "input|ef.CO2|recomputed", "rejected"),
             event(GAS_KC, f"choice|{method['id']}|", "edited", method["chosen"]),
             event(GAS_KC, "input|activity.total|company", "edited", 5.0),
             event("s1:stationary:natural-gas:fac-gone", "input|activity.total|recomputed", "edited", 5.0)]
    decided = run(mixed_store(), with_traces=False, line_decisions=quiet, grid_regions=REGIONS,
                  vehicle_groups=[GROUP_ROAD])
    for key in ("categories", "scope_totals", "comparisons", "rollup"):
        assert decided[key] == plain[key], key


# --- the plan's exact numbers, as category totals ------------------------------------------------------------------
def test_plan_numbers_are_the_category_totals() -> None:
    gas = run(gas_store())["categories"]["stationary_combustion"]
    assert gas["total_co2e"] == pytest.approx(3452.4425, abs=1e-9)
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(380000)])
    mobile = run(store, vehicle_groups=[{**GROUP_ROAD, "distance": 100000}])["categories"]["mobile_combustion"]
    assert mobile["total_mass_t"]["CO2"] == pytest.approx(3879.8, abs=1e-9)
    store = FakeStore()
    store.add_document("E", "CT-S2-ELEC", [_elec_record(2747, start="2025-01-01", end="2025-12-31")])
    electricity = run(store, grid_regions={**REGIONS, "Kansas City Plant": "CAMX"})["categories"][
        "purchased_electricity_location_based"]
    assert electricity["total_co2e"] == pytest.approx(545.9435, abs=5e-4)


# --- a decision moves every total by exactly its difference, and a revert puts it back -------------------------------
def _scope1(response: dict) -> float:
    return float(response["scope_totals"]["scope1"]["total_co2e"])


def _comparison(response: dict, key: str) -> float:
    return float(next(c for c in response["comparisons"] if c["key"] == key)["recalculated"])


def _summary(response: dict) -> dict[str, Any]:
    book = build_workbook(engagement={"name": "E", "settings": {}}, recalculation=response, register={}, items=[],
                          exported_by="x")
    return {r[0]: r[1] for r in load_workbook(BytesIO(book))["Summary"].iter_rows(min_row=2, values_only=True)}


def test_an_edit_moves_line_category_scope_comparison_rollup_and_excel_by_the_recomputed_delta() -> None:
    settings: dict[str, Any] = {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD],
                                "reported": {"scope1_total": 3000.0}}
    before = run(mixed_store(), **settings)
    old_line = line_of(before, GAS_KC)
    old_mmbtu = old_line["step2"]["result"]["quantity"]
    edit = event(GAS_KC, "input|activity.total|recomputed", "edited", old_mmbtu + 1000, "MMBtu")
    after = run(mixed_store(), line_decisions=[edit], **settings)
    delta = 1000 * NG_T_PER_MMBTU  # 53.1145 t CO2e
    line = line_of(after, GAS_KC)
    assert line["results"]["total_co2e_t"] - old_line["results"]["total_co2e_t"] == pytest.approx(delta, rel=1e-9)
    assert line["trace"]["result"]["recomputed"] == line["results"]["total_co2e_t"]
    assert line["step1"]["total"]["quantity"] == old_mmbtu + 1000
    assert line["step1"]["rows"] == old_line["step1"]["rows"]  # the evidence stays as read
    assert "reviewer_decisions_applied" in line["flags"]
    stationary = after["categories"]["stationary_combustion"]
    assert stationary["total_co2e"] - before["categories"]["stationary_combustion"]["total_co2e"] == pytest.approx(
        delta, rel=1e-9)
    assert stationary["total_mass_t"]["CO2"] - before["categories"]["stationary_combustion"]["total_mass_t"]["CO2"] \
        == pytest.approx(1000 * 0.05306, rel=1e-9)
    assert "reviewer_decisions_applied" in stationary["flags"]
    assert any(s["label"].startswith("CO2 after reviewer decisions") for s in stationary["lines"][0]["steps"])
    assert _scope1(after) - _scope1(before) == pytest.approx(delta, rel=1e-9)
    assert _comparison(after, "scope1_total") - _comparison(before, "scope1_total") == pytest.approx(delta, rel=1e-9)
    assert _comparison(after, "stationary_combustion_total") - _comparison(before, "stationary_combustion_total") == \
        pytest.approx(delta, rel=1e-9)
    assert after["scope_totals"]["scope1"]["mass_t"]["CO2"] - before["scope_totals"]["scope1"]["mass_t"]["CO2"] == \
        pytest.approx(1000 * 0.05306, rel=1e-9)  # the By-gas table
    nodes_before, nodes_after = before["rollup"]["nodes"], after["rollup"]["nodes"]
    assert nodes_after["inventory_location_total"]["co2e_t"] - nodes_before["inventory_location_total"]["co2e_t"] == \
        pytest.approx(delta, rel=1e-9)
    excel_before, excel_after = _summary(before), _summary(after)
    assert excel_after["Scope 1 recalculated (t CO2e)"] - excel_before["Scope 1 recalculated (t CO2e)"] == \
        pytest.approx(delta, rel=1e-9)
    # nothing else moved: the other lines, the other categories, scope 2
    assert line_of(after, GAS_STL)["results"] == line_of(before, GAS_STL)["results"]
    for name in ("mobile_combustion", "purchased_electricity_location_based", "purchased_electricity_market_based"):
        assert after["categories"][name] == before["categories"][name]
    assert after["scope_totals"]["scope2_location"] == before["scope_totals"]["scope2_location"]
    _assert_lines_add_up(after)

    # a revert (the decision back to pending) returns every number to the original exactly
    reverted = run(mixed_store(), line_decisions=[event(GAS_KC, "input|activity.total|recomputed", "pending")],
                   **settings)
    for key in ("categories", "scope_totals", "comparisons", "rollup", "calculation_unplaced"):
        assert reverted[key] == before[key], key
    assert line_of(reverted, GAS_KC)["results"] == old_line["results"]


def test_a_consolidated_share_scales_the_line_total_never_the_category() -> None:
    settings: dict[str, Any] = {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD],
                                "consolidated_shares": {"fac-kc01": 60.0}}
    before = run(mixed_store(), **settings)
    old = line_of(before, GAS_KC)
    edit = event(GAS_KC, "input|activity.total|recomputed", "edited", old["step2"]["result"]["quantity"] + 1000,
                 "MMBtu")
    after = run(mixed_store(), line_decisions=[edit], **settings)
    delta = 1000 * NG_T_PER_MMBTU
    assert line_of(after, GAS_KC)["results"]["sum_co2e_t"] - old["results"]["sum_co2e_t"] == pytest.approx(delta)
    assert line_of(after, GAS_KC)["results"]["total_co2e_t"] - old["results"]["total_co2e_t"] == pytest.approx(
        0.6 * delta)
    assert after["categories"]["stationary_combustion"]["total_co2e"] - \
        before["categories"]["stationary_combustion"]["total_co2e"] == pytest.approx(delta, rel=1e-9)
    _assert_lines_add_up(after)


def test_the_reported_line_status_follows_the_decided_total() -> None:
    reported = {GAS_KC: 3452.4425}
    before = run(gas_store(), reported_lines=reported)
    assert line_of(before, GAS_KC)["status"] == "within"
    after = run(gas_store(), reported_lines=reported,
                line_decisions=[event(GAS_KC, "input|activity.total|recomputed", "edited", 900000, "therm")])
    line = line_of(after, GAS_KC)
    assert line["status"] == "above"
    assert line["difference_t"] == pytest.approx(250000 * 0.1 * NG_T_PER_MMBTU, rel=1e-9)


def test_an_electricity_factor_and_mwh_move_location_and_market_based() -> None:
    certificates = [{"label": "RECs", "mwh": 600}]
    settings: dict[str, Any] = {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD], "certificates": certificates}
    before = run(mixed_store(), **settings)
    location0 = before["categories"]["purchased_electricity_location_based"]
    market0 = before["categories"]["purchased_electricity_market_based"]
    stl = line_of(before, ELEC_STL)
    mwh = stl["step2"]["result"]["quantity"]
    ef = event(ELEC_STL, "input|ef.CO2|recomputed", "edited", 500.0, "lb/MWh")
    after = run(mixed_store(), line_decisions=[ef], **settings)
    rfce = stl["step3"]["gases"][0]["ef"]["value"]
    delta_co2 = mwh * (500.0 - rfce) / calc.LB_PER_METRIC_TON
    location = after["categories"]["purchased_electricity_location_based"]
    assert location["total_mass_t"]["CO2"] - location0["total_mass_t"]["CO2"] == pytest.approx(delta_co2, rel=1e-9)
    coverage = market0["details"]["coverage"]
    market = after["categories"]["purchased_electricity_market_based"]
    assert market["details"]["coverage"] == pytest.approx(coverage)
    assert market["total_mass_t"]["CO2"] - market0["total_mass_t"]["CO2"] == pytest.approx(
        delta_co2 * (1 - coverage), rel=1e-9)
    assert after["scope_totals"]["scope2_market"]["total_co2e"] - before["scope_totals"]["scope2_market"][
        "total_co2e"] == pytest.approx(delta_co2 * (1 - coverage), rel=1e-9)
    _assert_lines_add_up(after)

    # more MWh: location-based by MWh x factor, market-based with the certificate coverage moved
    more = event(ELEC_STL, "input|activity.total|recomputed", "edited", mwh + 200, "MWh")
    moved = run(mixed_store(), line_decisions=[more], **settings)
    total_mwh = market0["details"]["total_mwh"] + 200
    market = moved["categories"]["purchased_electricity_market_based"]
    assert market["details"]["total_mwh"] == pytest.approx(total_mwh)
    assert market["details"]["coverage"] == pytest.approx(600 / total_mwh)
    expected = calc.electricity_market_based(
        [calc.FacilityElectricity("Kansas City Plant", calc.Measure(1200, "MWh"), "NYUP"),
         calc.FacilityElectricity("St Louis Plant", calc.Measure(mwh + 200, "MWh"), "RFCE")],
        [calc.Certificate("RECs", 600)])
    assert market["total_co2e"] == pytest.approx(expected.total_co2e, rel=1e-9)
    assert moved["categories"]["purchased_electricity_location_based"]["total_co2e"] - location0["total_co2e"] == \
        pytest.approx(200 * sum(g["ef"]["value"] * g["gwp"]["value"] for g in stl["step3"]["gases"])
                      / calc.LB_PER_METRIC_TON, rel=1e-9)
    _assert_lines_add_up(moved)


def test_a_vehicle_group_distance_moves_the_mobile_category() -> None:
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(380000)])
    groups = [{**GROUP_ROAD, "distance": 100000}]
    before = run(store, vehicle_groups=groups)
    after = run(store, vehicle_groups=groups,
                line_decisions=[event(DIESEL, "input|distance|recomputed", "edited", 150000, "mi")])
    for gas in ("CH4", "N2O"):
        assert after["categories"]["mobile_combustion"]["total_mass_t"][gas] == pytest.approx(
            1.5 * before["categories"]["mobile_combustion"]["total_mass_t"][gas], rel=1e-9)
    assert after["categories"]["mobile_combustion"]["total_mass_t"]["CO2"] == \
        before["categories"]["mobile_combustion"]["total_mass_t"]["CO2"]
    _assert_lines_add_up(after)


def test_when_the_lines_do_not_add_up_no_decision_is_half_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    before = run(gas_store())
    monkeypatch.setattr(line_totals, "adds_up", lambda sums, category: False)
    after = run(gas_store(), line_decisions=[event(GAS_KC, "input|activity.total|recomputed", "edited", 700000,
                                                   "therm")])
    line = line_of(after, GAS_KC)
    assert after["categories"] == before["categories"] and after["scope_totals"] == before["scope_totals"]
    assert line["results"] == line_of(before, GAS_KC)["results"]
    assert line["trace"]["result"] == line_of(before, GAS_KC)["trace"]["result"]  # the working shown is counted
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["category_does_not_add_up"]
    assert line["decisions"]["applied"] == []


def test_a_failure_while_counting_restores_every_number(monkeypatch: pytest.MonkeyPatch) -> None:
    before = run(gas_store())

    def broken(categories: dict, decided: list, lines: list, *args: Any, **kw: Any) -> None:
        decided[0].write(0.0)  # half way: a line written, then a failure
        categories["stationary_combustion"] = None
        raise RuntimeError("boom")

    monkeypatch.setattr(line_totals, "apply", broken)
    after = run(gas_store(), line_decisions=[event(GAS_KC, "input|activity.total|recomputed", "edited", 700000,
                                                   "therm")])
    assert after["categories"] == before["categories"] and after["scope_totals"] == before["scope_totals"]
    line = line_of(after, GAS_KC)
    assert line["results"] == line_of(before, GAS_KC)["results"]
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["could_not_count"]


def test_two_lines_of_one_fuel_each_move_their_own_share_of_the_category() -> None:
    settings: dict[str, Any] = {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD]}
    before = run(mixed_store(), **settings)
    kc, stl = line_of(before, GAS_KC), line_of(before, GAS_STL)
    decided = run(mixed_store(), line_decisions=[
        event(GAS_KC, "input|activity.total|recomputed", "edited", kc["step2"]["result"]["quantity"] * 2, "MMBtu"),
        event(GAS_STL, "input|ef.CO2|recomputed", "edited", 60.0, "kg/MMBtu")], **settings)
    delta = kc["step2"]["result"]["quantity"] * NG_T_PER_MMBTU + stl["step2"]["result"]["quantity"] * (60 - 53.06) / 1000
    assert decided["categories"]["stationary_combustion"]["total_co2e"] - \
        before["categories"]["stationary_combustion"]["total_co2e"] == pytest.approx(delta, rel=1e-9)
    assert decided["calculation_line_decisions"]["lines_with_decisions"] == 2
    _assert_lines_add_up(decided)
