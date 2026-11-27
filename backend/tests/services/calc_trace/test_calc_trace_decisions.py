"""Reviewer decisions read into a line's trace (F3b): accepted and edited values and chosen options are worked in, a
pending suggestion never is, a rejected input keeps the automatic value, and nothing hostile reaches the arithmetic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.tests.services.calc_trace.recalc_scenarios import GROUP_ROAD, REGIONS, mixed_store, run
from backend.tests.services.test_calculation_lines import ELEC_KC, GAS_KC
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase

SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())
DIESEL = "s1:mobile:diesel-fuel:vg-heavy-trucks"
# Natural gas per MMBtu (EPA Hub Table 1, AR5): 53.06 kg CO2 + 1 g CH4 x 28 + 0.1 g N2O x 265, in t CO2e.
NG_T_PER_MMBTU = 0.05306 + 0.001e-3 * 28 + 0.0001e-3 * 265


def event(line_key: str, stream: str, status: str, value: Any = None, unit: str | None = None,
          suggestion: Any = None) -> dict[str, Any]:
    """One stored decision event (``calc_line_review.append``'s shape), as ``current`` returns it."""

    target, target_id, side = stream.split("|")
    decision = None if status == "none" else {
        "status": status, "value": value, "by": {"name": "Rev Iewer", "login": "rev@example.com"},
        "at": "2026-11-26T10:00:00Z", **({"unit": unit} if unit else {}),
        **({"reason": "Corrected from the invoice"} if status in ("edited", "rejected") else {})}
    return {"line_key": line_key, "stream": stream, "target": target, "target_id": target_id, "side": side or None,
            "seq": 1, "record": {"field_id": stream, "decision": decision, "history": [],
                                 "suggestion": {"value": suggestion, "reason": "Read from page 2"} if suggestion
                                 else None}}


def gas_store(therms: float = 650000) -> FakeStore:
    store = FakeStore()
    store.add_document("G", "CT-S1-FUELQTY", [{**_gas_record(therms), "activity_quantity": (therms, "therm")}])
    return store


def line_of(response: dict, key: str) -> dict:
    return next(ln for ln in response["calculation_lines"] if ln["key"] == key)


def block(trace: dict, block_id: str) -> dict:
    return next(b for s in trace["steps"] for b in s["blocks"] if b["id"] == block_id)


def test_no_decisions_and_an_empty_list_leave_the_response_exactly_as_it_was() -> None:
    plain = run(mixed_store(), grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD])
    assert run(mixed_store(), line_decisions=[], grid_regions=REGIONS, vehicle_groups=[GROUP_ROAD]) == plain
    assert "calculation_line_decisions" not in plain
    assert all("decisions" not in line for line in plain["calculation_lines"])


def test_an_edited_activity_is_worked_through_every_step() -> None:
    edit = event(GAS_KC, "input|activity.total|recomputed", "edited", 700000, "therm")
    trace = line_of(run(gas_store(), line_decisions=[edit]), GAS_KC)["trace"]
    jsonschema.validate(trace, SCHEMA)
    side = trace["inputs"]["activity.total"]["recomputed"]
    assert side["value"] == 700000 and side["status"] == "edited"
    assert side["source"] == {"kind": "entered", "by": "Rev Iewer", "at": "2026-11-26T10:00:00Z",
                              "reason": "Corrected from the invoice"}
    assert block(trace, "conversion")["recomputed"]["result"]["value"] == pytest.approx(70000, rel=1e-12)
    assert block(trace, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(3714.2, rel=1e-12)
    assert trace["result"]["recomputed"] == pytest.approx(70000 * NG_T_PER_MMBTU, rel=1e-12)  # 3,718.015
    assert "reviewer_decisions_applied" in trace["flags"]


def test_the_default_line_is_the_plans_kent_cannery_number() -> None:
    trace = line_of(run(gas_store()), GAS_KC)["trace"]
    assert trace["result"]["recomputed"] == pytest.approx(3452.4425, abs=1e-9)


def test_a_pending_suggestion_never_reaches_the_recomputed_side() -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    pending = event(GAS_KC, "input|activity.total|recomputed", "pending", None, suggestion=900000)
    none = event(GAS_KC, "input|ef.CO2|recomputed", "none", suggestion=99.0)
    after = line_of(run(gas_store(), line_decisions=[pending, none]), GAS_KC)
    assert after["trace"]["steps"] == before["steps"] and after["trace"]["result"] == before["result"]
    assert after["decisions"] == {"applied": [], "not_applied": []}


def test_a_rejected_input_falls_back_to_the_automatic_value_with_a_flag() -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    rejected = event(GAS_KC, "input|ef.CO2|recomputed", "rejected", suggestion=60.0)
    after = line_of(run(gas_store(), line_decisions=[rejected]), GAS_KC)
    trace = after["trace"]
    assert trace["result"] == before["result"] and trace["steps"] == before["steps"]
    assert trace["inputs"]["ef.CO2"]["recomputed"]["value"] == 53.06
    assert trace["inputs"]["ef.CO2"]["recomputed"]["status"] == "rejected"
    assert "reviewer_rejected_input" in trace["flags"] and "reviewer_decisions_applied" not in trace["flags"]
    assert after["decisions"]["applied"] == [{"target": "input", "id": "ef.CO2", "side": "recomputed",
                                              "status": "rejected", "uses": "automatic value"}]


def test_an_accepted_suggestion_is_used_and_sourced() -> None:
    accepted = event(GAS_KC, "input|ef.CO2|recomputed", "accepted", 50.0, suggestion=50.0)
    trace = line_of(run(gas_store(), line_decisions=[accepted]), GAS_KC)["trace"]
    side = trace["inputs"]["ef.CO2"]["recomputed"]
    assert side["status"] == "accepted" and side["value"] == 50.0 and side["source"]["reason"] == "Read from page 2"
    assert block(trace, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(65000 * 50.0 / 1000)
    jsonschema.validate(trace, SCHEMA)


def test_a_row_edit_changes_the_sum_and_everything_after_it() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas_record(30000, "2025-01-01", "2025-01-31")])
    store.add_document("G2", "CT-S1-FUELQTY", [_gas_record(35000, "2025-02-01", "2025-02-28")])
    default = line_of(run(store), GAS_KC)["trace"]
    row = default["inputs"]["activity.total"]["rows"][1]["id"]
    edit = event(GAS_KC, f"input|activity.total/{row}|recomputed", "edited", 36000, "MMBtu")
    trace = line_of(run(store, line_decisions=[edit]), GAS_KC)["trace"]
    assert block(trace, "activity")["recomputed"]["result"]["value"] == 66000
    assert trace["inputs"]["activity.total"]["recomputed"]["value"] == 66000
    assert trace["inputs"]["activity.total"]["rows"][1]["recomputed"]["value"] == 36000
    assert trace["inputs"]["activity.total"]["rows"][0]["recomputed"]["value"] == 30000
    assert trace["result"]["recomputed"] == pytest.approx(66000 * NG_T_PER_MMBTU, rel=1e-12)


def test_a_total_decided_outright_wins_over_its_rows() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas_record(30000)])
    row = line_of(run(store), GAS_KC)["trace"]["inputs"]["activity.total"]["rows"][0]["id"]
    decided = run(store, line_decisions=[event(GAS_KC, f"input|activity.total/{row}|recomputed", "edited", 1, "MMBtu"),
                                         event(GAS_KC, "input|activity.total|recomputed", "edited", 40000, "MMBtu")])
    line = line_of(decided, GAS_KC)
    assert line["trace"]["result"]["recomputed"] == pytest.approx(40000 * NG_T_PER_MMBTU, rel=1e-12)
    assert [(n["id"], n["reason"]) for n in line["decisions"]["not_applied"]] == [
        (f"activity.total/{row}", "total_decided")]


@pytest.mark.parametrize("value", [0, -5, float("nan"), float("inf"), "NaN", "12", True, None, 1e16])
def test_a_stored_value_that_is_not_a_number_above_zero_never_reaches_the_math(value: Any) -> None:
    """A row stored before this rule, or written by hand: reported, not used."""

    before = line_of(run(gas_store()), GAS_KC)["trace"]
    line = line_of(run(gas_store(), line_decisions=[
        event(GAS_KC, "input|activity.total|recomputed", "edited", value, "therm")]), GAS_KC)
    assert line["trace"]["result"] == before["result"] and line["trace"]["steps"] == before["steps"]
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["invalid_value"]


def test_a_value_in_another_unit_is_refused_not_converted() -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    line = line_of(run(gas_store(), line_decisions=[
        event(GAS_KC, "input|activity.total|recomputed", "edited", 65000, "MMBtu")]), GAS_KC)
    assert line["trace"]["result"] == before["result"]
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["unit_mismatch"]


@pytest.mark.parametrize("input_id", ["gwp.CH4", "share", "unit_conversion"])
def test_engagement_wide_inputs_are_not_decided_per_line(input_id: str) -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    line = line_of(run(gas_store(), line_decisions=[
        event(GAS_KC, f"input|{input_id}|recomputed", "edited", 50.0)]), GAS_KC)
    assert line["trace"]["result"] == before["result"]
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["set_elsewhere"]


def test_the_company_side_is_shown_never_an_operand() -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    line = line_of(run(gas_store(), line_decisions=[
        event(GAS_KC, "input|activity.total|company", "edited", 1.0, "therm")]), GAS_KC)
    assert line["trace"]["result"] == before["result"] and line["decisions"] == {"applied": [], "not_applied": []}


def test_a_decision_on_an_input_or_line_that_is_gone_is_reported_never_applied() -> None:
    before = run(gas_store())
    after = run(gas_store(), line_decisions=[
        event(GAS_KC, "input|ef.SF6|recomputed", "edited", 1.0),
        event(GAS_KC, "input|activity.total/GONE/x|recomputed", "edited", 1.0),
        event(GAS_KC, "choice|equation:SF6|", "edited", "eq1"),
        event("s1:stationary:natural-gas:fac-renamed", "input|activity.total|recomputed", "edited", 1.0, "therm")])
    line = line_of(after, GAS_KC)
    assert line["trace"]["result"] == line_of(before, GAS_KC)["trace"]["result"]
    assert sorted(n["reason"] for n in line["decisions"]["not_applied"]) == ["not_on_this_line"] * 3
    report = after["calculation_line_decisions"]
    assert report["orphaned"] == [{"line_key": "s1:stationary:natural-gas:fac-renamed", "target": "input",
                                   "id": "activity.total", "side": "recomputed", "status": "edited"}]
    assert len(report["not_applied"]) == 3 and report["lines_with_decisions"] == 0


def test_choosing_the_default_route_is_recorded_and_changes_no_number() -> None:
    before = line_of(run(gas_store()), GAS_KC)["trace"]
    method = before["choices"][0]
    line = line_of(run(gas_store(), line_decisions=[event(GAS_KC, f"choice|{method['id']}|", "edited",
                                                          method["chosen"])]), GAS_KC)
    assert line["trace"]["choices"][0]["chosen_by"] == "reviewer"
    assert line["trace"]["result"] == before["result"] and line["trace"]["steps"] == before["steps"]
    stale = line_of(run(gas_store(), line_decisions=[event(GAS_KC, f"choice|{method['id']}|", "edited", "eq9")]),
                    GAS_KC)
    assert [n["reason"] for n in stale["decisions"]["not_applied"]] == ["option_not_available"]


def test_electricity_2747_mwh_camx_then_an_edited_co2_factor() -> None:
    store = FakeStore()
    store.add_document("E", "CT-S2-ELEC", [_elec_record(2747, start="2025-01-01", end="2025-12-31")])
    regions = {**REGIONS, "Kansas City Plant": "CAMX"}
    default = line_of(run(store, grid_regions=regions), ELEC_KC)["trace"]
    assert default["result"]["recomputed"] == pytest.approx(545.9435, abs=5e-4)
    edit = event(ELEC_KC, "input|ef.CO2|recomputed", "edited", 400.0, "lb/MWh")
    trace = line_of(run(store, grid_regions=regions, line_decisions=[edit]), ELEC_KC)["trace"]
    co2 = block(trace, "emissions.CO2")["recomputed"]["result"]["value"]
    assert co2 == pytest.approx(2747 * 400.0 / 2204.62, rel=1e-12)
    delta = trace["result"]["recomputed"] - default["result"]["recomputed"]
    assert delta == pytest.approx(2747 * (400.0 - 436.655) / 2204.62, rel=1e-9)
    jsonschema.validate(trace, SCHEMA)


def test_diesel_380000_gal_then_an_edited_fuel_and_distance() -> None:
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(380000)])
    groups = [{**GROUP_ROAD, "distance": 100000}]
    default = line_of(run(store, vehicle_groups=groups), DIESEL)["trace"]
    assert block(default, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(3879.8, abs=1e-9)
    fuel = event(DIESEL, "input|activity.total|recomputed", "edited", 400000, "gal")
    trace = line_of(run(store, vehicle_groups=groups, line_decisions=[fuel]), DIESEL)["trace"]
    assert block(trace, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(4084.0, rel=1e-12)
    for gas in ("CH4", "N2O"):  # by distance (Eq. 4): the fuel does not move them
        assert block(trace, f"emissions.{gas}")["recomputed"] == block(default, f"emissions.{gas}")["recomputed"]
    distance = event(DIESEL, "input|distance|recomputed", "edited", 200000, "mi")
    moved = line_of(run(store, vehicle_groups=groups, line_decisions=[distance]), DIESEL)["trace"]
    for gas in ("CH4", "N2O"):
        assert block(moved, f"emissions.{gas}")["recomputed"]["result"]["value"] == pytest.approx(
            2 * block(default, f"emissions.{gas}")["recomputed"]["result"]["value"], rel=1e-12)
    assert block(moved, "emissions.CO2")["recomputed"] == block(default, "emissions.CO2")["recomputed"]


def test_the_company_side_difference_follows_the_decided_value() -> None:
    company = {GAS_KC: {"quantity": 650000, "unit": "therm"}}
    edit = event(GAS_KC, "input|activity.total|recomputed", "edited", 700000, "therm")
    trace = line_of(run(gas_store(), reported_activity=company, line_decisions=[edit]), GAS_KC)["trace"]
    assert trace["inputs"]["activity.total"]["difference"] == pytest.approx(50000)
    assert trace["result"]["difference"] == pytest.approx(5000 * NG_T_PER_MMBTU, rel=1e-9)
    assert block(trace, "results.total")["recomputed"]["result"]["difference"] == pytest.approx(
        5000 * NG_T_PER_MMBTU, rel=1e-9)


def test_a_line_that_mixes_runs_takes_no_decision_on_a_number() -> None:
    store = FakeStore()
    store.add_document("G1", "CT-S1-FUELQTY", [_gas_record(100)])
    store.add_document("G2", "CT-S1-FUELQTY", [{**_gas_record(100), "activity_quantity": (1000, "scf"),
                                               "activity_unit": ("scf", None)}])
    plain = line_of(run(store), GAS_KC)
    assert "mixed_units_or_fuels" in plain["flags"]
    if plain["trace"] is None:
        pytest.skip("this mix is not traced")
    line = line_of(run(store, line_decisions=[event(GAS_KC, "input|ef.CO2|recomputed", "edited", 50.0)]), GAS_KC)
    assert line["trace"]["result"] == plain["trace"]["result"]
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["line_mixes_runs"]
