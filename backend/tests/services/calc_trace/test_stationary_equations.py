"""Stationary combustion: the equation picker (C1). Eq. 1, Eq. 2 and Eq. 3 per gas, each worked from decided inputs
only, checked against the calculator's own Eq. 2 / Eq. 3, and moving the line's category by exactly the decided
difference. With no decision every number is today's."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.services import calc_line_review as review
from backend.app.services import emissions_calculator as calc
from backend.app.services import line_totals
from backend.app.services.calc_trace import stationary
from backend.app.services.request_service import Actor
from backend.app.services.review_field import ReviewConflict
from backend.tests.services.calc_trace.recalc_scenarios import run
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, gas_store, line_of
from backend.tests.services.test_calculation_lines import GAS_KC
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore

SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())
PROPANE = "s1:stationary:propane:fac-kc01"
COAL = "s1:stationary:bituminous:fac-kc01"
COAL_KW = {"fuel_choices": {"stationary:coal": "Bituminous", "stationary:wood": "Wood and Wood Residuals"}}
ACTOR = Actor(user_id="u1", name="Ann Reviewer", login="ann@acme.test")
NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
HHV = "input|hhv|recomputed"
CC = "input|cc|recomputed"
HHV_UNIT, CC_UNIT = "MMBtu/short_ton", "% by mass"


def solid_store(fuel: str, short_tons: float) -> FakeStore:
    store = FakeStore()
    store.add_document("S", "CT-S1-FUELQTY", [{**_gas_record(short_tons, fuel=fuel),
                                               "activity_quantity": (short_tons, "short_ton"),
                                               "activity_unit": ("short_ton", None)}])
    return store


def coal_store(short_tons: float = 1000) -> FakeStore:
    return solid_store("coal", short_tons)


def propane_store(gallons: float = 2350) -> FakeStore:
    store = FakeStore()
    store.add_document("P", "CT-S1-FUELQTY", [{**_gas_record(gallons, fuel="propane"),
                                               "activity_quantity": (gallons, "gal"),
                                               "activity_unit": ("gal", None)}])
    return store


def hhv(value: Any = 25.50, unit: str = HHV_UNIT, key: str = COAL) -> dict[str, Any]:
    return event(key, HHV, "edited", value, unit)


def cc(value: Any = 75, key: str = COAL) -> dict[str, Any]:
    return event(key, CC, "edited", value, CC_UNIT)


def pick(gas: str, option: str, key: str = COAL) -> dict[str, Any]:
    return event(key, f"choice|equation:{gas}|", "edited", option)


def worked(store: FakeStore, key: str, events: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return run(store, line_decisions=events, **{**COAL_KW, **kw})


def mass(trace: dict[str, Any], gas: str) -> float:
    return float(block(trace, f"emissions.{gas}")["recomputed"]["result"]["value"])


def reasons(line: dict[str, Any]) -> list[str]:
    return [n["reason"] for n in line["decisions"]["not_applied"]]


def calculator(fuel: str, quantity: float, unit: str, **given: calc.Measure) -> calc.LineResult:
    return calc.stationary_combustion([calc.StationaryFuel(fuel, calc.Measure(quantity, unit), **given)]).lines[0]


# --- the plan's numbers, exactly ---------------------------------------------------------------------------------
def test_propane_2350_gal_eq1_is_the_plans_number() -> None:
    line = line_of(run(propane_store()), PROPANE)
    trace = line["trace"]
    assert [trace["choices"][i]["chosen"] for i in (1, 2, 3)] == ["eq_1"] * 3
    assert mass(trace, "CO2") == pytest.approx(13.442, rel=1e-12)
    assert mass(trace, "CH4") == pytest.approx(0.0006345, rel=1e-12)
    assert mass(trace, "N2O") == pytest.approx(0.0001175, rel=1e-12)
    gwp = {gas: block(trace, f"gwp.{gas}")["recomputed"]["result"]["value"] for gas in ("CH4", "N2O")}
    assert gwp["CH4"] == pytest.approx(0.017766, rel=1e-12) and gwp["N2O"] == pytest.approx(0.0311375, rel=1e-12)
    assert trace["result"]["recomputed"] == pytest.approx(13.4909035, rel=1e-12)
    jsonschema.validate(trace, SCHEMA)


def test_bituminous_1000_short_tons_eq1_2_and_3_are_the_plans_numbers() -> None:
    store = coal_store()
    eq1 = line_of(run(store, **COAL_KW), COAL)["trace"]
    assert mass(eq1, "CO2") == pytest.approx(2325.0, rel=1e-12)

    eq2 = line_of(worked(store, COAL, [hhv(), pick("CO2", "eq_2")]), COAL)["trace"]
    assert mass(eq2, "CO2") == pytest.approx(2378.64, rel=1e-12)
    assert eq2["choices"][1]["chosen"] == "eq_2" and eq2["choices"][1]["chosen_by"] == "reviewer"
    assert [t["operand"]["value"] for t in block(eq2, "emissions.CO2")["recomputed"]["terms"]][:3] == [
        1000, 25.5, 93.28]

    eq3 = line_of(worked(store, COAL, [cc(), pick("CO2", "eq_3")]), COAL)["trace"]
    assert mass(eq3, "CO2") == pytest.approx(1000 * 0.90718474 * 0.75 * 44 / 12, rel=1e-12)  # 2,494.758035
    assert mass(eq3, "CO2") == pytest.approx(2494.758035, abs=1e-9)
    for trace in (eq1, eq2, eq3):
        jsonschema.validate(trace, SCHEMA)


def test_eq2_and_eq3_agree_with_the_calculators_own_equations_to_1e12() -> None:
    store = coal_store()
    by2 = calculator("Bituminous", 1000, "short_ton", heat_content=calc.Measure(25.5, "MMBtu per short_ton"))
    by3 = calculator("Bituminous", 1000, "short_ton", carbon_content=calc.Measure(75, calc.PERCENT_BY_MASS))
    both = worked(store, COAL, [hhv(), pick("CO2", "eq_2"), pick("CH4", "eq_2"), pick("N2O", "eq_2")])
    trace = line_of(both, COAL)["trace"]
    for gas in calc.GASES:
        assert mass(trace, gas) == pytest.approx(by2.mass_t[gas], rel=1e-12)
    three = line_of(worked(store, COAL, [cc(), pick("CO2", "eq_3")]), COAL)["trace"]
    assert mass(three, "CO2") == pytest.approx(by3.mass_t["CO2"], rel=1e-12)


def test_ch4_and_n2o_on_eq2_use_the_per_energy_factors() -> None:
    trace = line_of(worked(coal_store(), COAL, [hhv(), pick("CH4", "eq_2"), pick("N2O", "eq_2")]), COAL)["trace"]
    assert mass(trace, "CO2") == pytest.approx(2325.0, rel=1e-12)  # CO2 stays on Eq. 1
    assert mass(trace, "CH4") == pytest.approx(25500 * 11 / 1e6, rel=1e-12)  # Hub: 11 g CH4 per MMBtu
    assert mass(trace, "N2O") == pytest.approx(25500 * 1.6 / 1e6, rel=1e-12)  # 1.6 g N2O per MMBtu


# --- availability ----------------------------------------------------------------------------------------------
def test_without_an_accepted_hhv_eq2_is_unavailable_and_says_why() -> None:
    trace = line_of(run(coal_store(), **COAL_KW), COAL)["trace"]
    options = {o["id"]: o for o in trace["choices"][1]["options"]}
    assert options["eq_1"]["available"] is True
    assert options["eq_2"]["available"] is False and "heat content" in options["eq_2"]["why_unavailable"]
    assert options["eq_3"]["available"] is False and "carbon content" in options["eq_3"]["why_unavailable"]
    assert options["eq_2"]["required_inputs"] == ["hhv"] and options["eq_3"]["required_inputs"] == ["cc"]
    ch4 = {o["id"]: o for o in trace["choices"][2]["options"]}
    assert ch4["eq_3"]["available"] is False and "CO₂ only" in ch4["eq_3"]["why_unavailable"]
    for input_id in ("hhv", "cc"):
        assert trace["inputs"][input_id]["decidable"] is True
        assert trace["inputs"][input_id]["recomputed"]["status"] == "awaiting_review"
        assert trace["inputs"][input_id]["recomputed"]["value"] is None


def test_choosing_eq2_with_no_hhv_changes_nothing() -> None:
    default = run(coal_store(), **COAL_KW)
    after = worked(coal_store(), COAL, [pick("CO2", "eq_2")])
    line = line_of(after, COAL)
    assert reasons(line) == ["option_not_available"]
    assert line["trace"]["result"] == line_of(default, COAL)["trace"]["result"]
    assert after["categories"] == default["categories"]


def test_eq3_is_not_offered_for_ch4_and_n2o() -> None:
    line = line_of(worked(coal_store(), COAL, [cc(), pick("CH4", "eq_3"), pick("N2O", "eq_3")]), COAL)
    assert reasons(line) == ["option_not_available"] * 2
    assert mass(line["trace"], "CH4") == pytest.approx(0.274, rel=1e-12)  # still on Eq. 1 (274 g CH4 per 1,000 short tons)


def test_a_fuel_measured_in_energy_has_no_eq2_or_eq3() -> None:
    trace = line_of(run(gas_store()), GAS_KC)["trace"]
    for choice in trace["choices"][1:]:
        by_id = {o["id"]: o for o in choice["options"]}
        assert by_id["eq_1"]["available"] and not by_id["eq_2"]["available"] and not by_id["eq_3"]["available"]
    assert "hhv" not in trace["inputs"] and "cc" not in trace["inputs"]
    line = line_of(run(gas_store(), line_decisions=[
        event(GAS_KC, HHV, "edited", 0.1, "MMBtu/MMBtu"), event(GAS_KC, "choice|equation:CO2|", "edited", "eq_2")]),
        GAS_KC)
    assert sorted(reasons(line)) == ["not_on_this_line", "option_not_available"]
    assert line["trace"]["result"] == trace["result"]


def test_eq3_needs_a_fuel_measured_in_mass() -> None:
    trace = line_of(run(propane_store()), PROPANE)["trace"]
    co2 = {o["id"]: o for o in trace["choices"][1]["options"]}
    assert "mass" in co2["eq_3"]["why_unavailable"] and "cc" not in trace["inputs"]
    assert "hhv" in trace["inputs"] and trace["inputs"]["hhv"]["recomputed"]["unit"] == "MMBtu/gal"


def test_a_decided_hhv_opens_eq2_for_the_next_run_of_the_line() -> None:
    plain = run(coal_store(), line_decisions=[hhv()], **COAL_KW)
    trace = line_of(plain, COAL)["trace"]
    options = {o["id"]: o for o in trace["choices"][1]["options"]}
    assert options["eq_2"]["available"] is True and options["eq_3"]["available"] is False
    assert stationary.site_decided({"input|hhv|recomputed": hhv()["record"]}) == ["hhv"]
    assert stationary.site_decided({"input|hhv|recomputed": event(COAL, HHV, "pending", None)["record"]}) == []
    assert stationary.site_decided(None) == []


# --- the totals move by exactly the decided difference ---------------------------------------------------------------
def test_the_category_moves_by_exactly_the_decided_difference() -> None:
    store = coal_store()
    default = run(store, **COAL_KW)
    after = worked(store, COAL, [hhv(), pick("CO2", "eq_2")])
    name = "stationary_combustion"
    before_cat, after_cat = default["categories"][name], after["categories"][name]
    assert after_cat["total_mass_t"]["CO2"] - before_cat["total_mass_t"]["CO2"] == pytest.approx(2378.64 - 2325.0,
                                                                                                  rel=1e-9)
    assert after_cat["total_mass_t"]["CH4"] == pytest.approx(before_cat["total_mass_t"]["CH4"], rel=1e-12)
    line = line_of(after, COAL)
    assert after_cat["total_co2e"] == pytest.approx(line["results"]["total_co2e_t"], rel=1e-12)
    assert line["results"]["mass_t"]["CO2"] == pytest.approx(2378.64, rel=1e-12)
    assert line["results"]["total_co2e_t"] == line["trace"]["result"]["recomputed"]
    assert line_totals.adds_up(line_totals.line_sums([*after["calculation_lines"], *after["calculation_unplaced"]],
                                                     "stationary"), after_cat)
    assert "reviewer_decisions_applied" in after_cat["flags"] and "reviewer_decisions_applied" in line["flags"]


def test_the_legacy_step3_row_carries_the_routed_gas_in_its_own_units() -> None:
    line = line_of(worked(coal_store(), COAL, [hhv(), pick("CO2", "eq_2")]), COAL)
    row = next(r for r in line["step3"]["gases"] if r["gas"] == "CO2")
    assert (row["activity"]["value"], row["activity"]["unit"]) == (25500.0, "MMBtu")
    assert (row["ef"]["value"], row["ef"]["unit"]) == (93.28, "kg/MMBtu") and row["ef"]["source"]
    assert row["mass_t"] == pytest.approx(2378.64, rel=1e-12)
    assert row["activity"]["value"] * row["ef"]["value"] * row["unit_conversion"] == pytest.approx(row["mass_t"])
    eq3 = line_of(worked(coal_store(), COAL, [cc(), pick("CO2", "eq_3")]), COAL)
    row3 = next(r for r in eq3["step3"]["gases"] if r["gas"] == "CO2")
    assert (row3["activity"]["unit"], row3["ef"]["unit"]) == ("kg", "kg CO2/kg") and row3["ef"]["source"]
    assert row3["activity"]["value"] * row3["ef"]["value"] * row3["unit_conversion"] == pytest.approx(row3["mass_t"])


def test_a_decided_activity_flows_into_the_chosen_equation() -> None:
    edit = event(COAL, "input|activity.total|recomputed", "edited", 500, "short_ton")
    trace = line_of(worked(coal_store(), COAL, [edit, hhv(), pick("CO2", "eq_2")]), COAL)["trace"]
    assert mass(trace, "CO2") == pytest.approx(500 * 25.5 * 93.28 / 1000, rel=1e-12)
    three = line_of(worked(coal_store(), COAL, [edit, cc(), pick("CO2", "eq_3")]), COAL)["trace"]
    assert mass(three, "CO2") == pytest.approx(500 * 0.90718474 * 0.75 * 44 / 12, rel=1e-12)


def test_eq2_works_a_fuel_sold_by_volume() -> None:
    events = [event(PROPANE, HHV, "edited", 0.091, "MMBtu/gal"), pick("CO2", "eq_2", PROPANE)]
    trace = line_of(run(propane_store(), line_decisions=events), PROPANE)["trace"]
    assert mass(trace, "CO2") == pytest.approx(2350 * 0.091 * 62.87 / 1000, rel=1e-12)
    by = calculator("Propane", 2350, "gal", heat_content=calc.Measure(0.091, "MMBtu per gal"))
    assert mass(trace, "CO2") == pytest.approx(by.mass_t["CO2"], rel=1e-12)


def test_a_biogenic_fuels_co2_on_eq2_is_reported_apart_and_counts_zero() -> None:
    store = solid_store("wood", 100)
    default = run(store, **COAL_KW)
    wood = default["calculation_lines"][0]["key"]
    events = [event(wood, HHV, "edited", 17.48, HHV_UNIT), pick("CO2", "eq_2", wood)]
    after = run(store, line_decisions=events, **COAL_KW)
    line = line_of(after, wood)
    assert line["results"]["biogenic_co2_t"] == pytest.approx(100 * 17.48 * 93.8 / 1000, rel=1e-12)
    assert line["results"]["mass_t"]["CO2"] == 0.0 and line["results"]["gas_co2e_t"]["CO2"] == 0.0
    assert line["results"]["total_co2e_t"] == line_of(default, wood)["results"]["total_co2e_t"]
    assert after["categories"]["stationary_combustion"]["biogenic_co2_t"] == pytest.approx(
        line["results"]["biogenic_co2_t"], rel=1e-12)


# --- with no decision, byte-identical ------------------------------------------------------------------------------
def test_with_no_decision_that_changes_a_number_every_total_is_todays() -> None:
    store = coal_store()
    plain = run(store, **COAL_KW)
    for events in ([], [hhv()], [cc()], [hhv(), cc()], [pick("CO2", "eq_1")], [hhv(), pick("CO2", "eq_1")]):
        after = worked(store, COAL, events)
        assert after["categories"] == plain["categories"], events
        assert line_of(after, COAL)["results"] == line_of(plain, COAL)["results"], events
        assert line_of(after, COAL)["trace"]["result"] == line_of(plain, COAL)["trace"]["result"], events


def test_a_site_value_with_no_equation_using_it_is_held_not_applied() -> None:
    line = line_of(worked(coal_store(), COAL, [hhv()]), COAL)
    assert line["decisions"]["not_applied"] == []
    assert line["decisions"]["applied"][0]["uses"].startswith("held")
    assert line["trace"]["inputs"]["hhv"]["recomputed"]["value"] == 25.5
    assert line["trace"]["inputs"]["hhv"]["recomputed"]["status"] == "edited"
    assert "reviewer_decisions_applied" not in line["flags"]


def test_a_pending_suggestion_or_a_rejection_never_opens_an_equation() -> None:
    default = run(coal_store(), **COAL_KW)
    pending = event(COAL, HHV, "pending", None, suggestion=25.5)
    rejected = event(COAL, HHV, "rejected", None, suggestion=25.5)
    for events in ([pending, pick("CO2", "eq_2")], [rejected, pick("CO2", "eq_2")]):
        after = worked(coal_store(), COAL, events)
        assert after["categories"] == default["categories"]
        assert reasons(line_of(after, COAL)) == ["option_not_available"]


def test_the_same_decisions_twice_give_the_same_response() -> None:
    events = [hhv(), pick("CO2", "eq_2")]
    assert worked(coal_store(), COAL, events) == worked(coal_store(), COAL, events)
    assert worked(coal_store(), COAL, events) == worked(coal_store(), COAL, list(reversed(events)))


# --- hostile data ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", [0, -25.5, float("nan"), float("inf"), "25.5", True, None, 1e16, 25_500_000, 0.001])
def test_a_site_hhv_that_is_not_a_plausible_number_never_reaches_the_math(value: Any) -> None:
    default = run(coal_store(), **COAL_KW)
    after = worked(coal_store(), COAL, [hhv(value), pick("CO2", "eq_2")])
    line = line_of(after, COAL)
    assert after["categories"] == default["categories"]
    assert sorted(reasons(line)) == ["invalid_value", "no_route_for_option"]
    assert line["trace"]["result"] == line_of(default, COAL)["trace"]["result"]


@pytest.mark.parametrize("value", [0, -1, 100.5, 150, 0.75, 1e16, float("nan"), "75", True])
def test_a_carbon_content_that_is_not_a_percent_never_reaches_the_math(value: Any) -> None:
    default = run(coal_store(), **COAL_KW)
    after = worked(coal_store(), COAL, [cc(value), pick("CO2", "eq_3")])
    assert after["categories"] == default["categories"]
    assert "invalid_value" in reasons(line_of(after, COAL))


def test_a_btu_for_mmbtu_slip_is_refused_with_the_typical_value() -> None:
    line = line_of(worked(coal_store(), COAL, [hhv(25_500_000), pick("CO2", "eq_2")]), COAL)
    message = next(n["message"] for n in line["decisions"]["not_applied"] if n["id"] == "hhv")
    assert "24.93" in message and "MMBtu" in message


def test_a_fraction_for_a_percent_is_refused() -> None:
    line = line_of(worked(coal_store(), COAL, [cc(0.75), pick("CO2", "eq_3")]), COAL)
    message = next(n["message"] for n in line["decisions"]["not_applied"] if n["id"] == "cc")
    assert "75 for 75%" in message


@pytest.mark.parametrize("unit", ["Btu/short_ton", "MMBtu/gal", "MMBtu", "MMBtu/short ton", "kWh/short_ton", "☃"])
def test_a_site_hhv_in_another_unit_is_refused_not_converted(unit: str) -> None:
    default = run(coal_store(), **COAL_KW)
    after = worked(coal_store(), COAL, [hhv(25.5, unit), pick("CO2", "eq_2")])
    assert "unit_mismatch" in reasons(line_of(after, COAL))
    assert after["categories"] == default["categories"]


def test_a_factor_decided_for_a_gas_on_another_equation_is_not_used() -> None:
    ef = event(COAL, "input|ef.CO2|recomputed", "edited", 50.0, "kg/short_ton")
    default = run(coal_store(), **COAL_KW)
    with_ef = worked(coal_store(), COAL, [ef, hhv(), pick("CO2", "eq_2")])
    only = worked(coal_store(), COAL, [hhv(), pick("CO2", "eq_2")])
    assert line_of(with_ef, COAL)["trace"]["result"] == line_of(only, COAL)["trace"]["result"]
    assert "equation_not_used" in reasons(line_of(with_ef, COAL))
    assert with_ef["categories"]["stationary_combustion"]["total_mass_t"] == pytest.approx(
        only["categories"]["stationary_combustion"]["total_mass_t"], rel=1e-12)
    assert line_of(default, COAL)["trace"]["result"] != line_of(only, COAL)["trace"]["result"]


def test_a_factor_decided_for_a_gas_still_on_eq1_is_used_beside_a_routed_gas() -> None:
    ef = event(COAL, "input|ef.CH4|recomputed", "edited", 22.0, "g/short_ton")
    trace = line_of(worked(coal_store(), COAL, [ef, hhv(), pick("CO2", "eq_2")]), COAL)["trace"]
    assert mass(trace, "CH4") == pytest.approx(1000 * 22.0 / 1e6, rel=1e-12)
    assert mass(trace, "CO2") == pytest.approx(2378.64, rel=1e-12)


def test_a_huge_or_tiny_quantity_stays_exact() -> None:
    for tons in (1e-6, 1e9):
        trace = line_of(worked(coal_store(tons), COAL, [hhv(), pick("CO2", "eq_2")]), COAL)["trace"]
        assert mass(trace, "CO2") == pytest.approx(tons * 25.5 * 93.28 / 1000, rel=1e-12)


def test_unicode_and_control_characters_in_a_choice_value_are_not_an_option() -> None:
    for value in ("eq_₂", "eq_2\x00", "EQ_2", "", " eq_2", "eq_2; DROP TABLE", None, 2, ["eq_2"]):
        after = worked(coal_store(), COAL, [hhv(), pick("CO2", value)])  # type: ignore[arg-type]
        assert reasons(line_of(after, COAL)) == ["option_not_available"], repr(value)


def test_a_line_that_mixes_units_offers_no_equation_but_eq1() -> None:
    store = FakeStore()
    store.add_document("S1", "CT-S1-FUELQTY", [{**_gas_record(100, fuel="coal"), "activity_quantity": (100, "short_ton"),
                                                "activity_unit": ("short_ton", None)}])
    store.add_document("S2", "CT-S1-FUELQTY", [{**_gas_record(50, fuel="coal"), "activity_quantity": (50, "MMBtu"),
                                                "activity_unit": ("MMBtu", None)}])
    plain = line_of(run(store, **COAL_KW), COAL)
    assert "mixed_units_or_fuels" in plain["flags"]
    trace = plain["trace"]
    if trace is None:
        pytest.skip("this mix is not traced")
    for choice in trace["choices"][1:]:
        assert [o["available"] for o in choice["options"]] == [True, False, False]
    assert "hhv" not in trace["inputs"]
    after = line_of(worked(store, COAL, [hhv(), pick("CO2", "eq_2")]), COAL)
    assert after["trace"]["result"] == trace["result"]


def test_a_line_with_no_evidence_offers_no_equation_but_eq1() -> None:
    store = FakeStore()
    plain = run(store, reported_activity={GAS_KC: {"quantity": 650000, "unit": "therms"}})
    for line in plain["calculation_lines"]:
        trace = line.get("trace")
        if trace and trace["panel"] == "stationary":
            for choice in trace["choices"][1:]:
                assert [o["available"] for o in choice["options"]] == [True, False, False]


# --- the reviewer's actions on it (rules, no database) ------------------------------------------------------------
def test_choose_eq2_is_refused_until_the_hhv_is_decided_then_taken() -> None:
    store = coal_store()
    before = line_of(run(store, **COAL_KW), COAL)["trace"]
    choice = next(c for c in before["choices"] if c["id"] == "equation:CO2")
    with pytest.raises(ReviewConflict, match="heat content"):
        review.decide_choice(review.new_record("s"), choice, "choose", option_id="eq_2", reason="Site HHV from the "
                             "supplier", actor=ACTOR, now=NOW, basis=review.basis_of(before, choice=choice))
    after = line_of(run(store, line_decisions=[hhv()], **COAL_KW), COAL)["trace"]
    choice = next(c for c in after["choices"] if c["id"] == "equation:CO2")
    record = review.decide_choice(review.new_record("s"), choice, "choose", option_id="eq_2",
                                  reason="Site HHV from the supplier", actor=ACTOR, now=NOW,
                                  basis=review.basis_of(after, choice=choice))
    assert record["decision"]["value"] == "eq_2" and json.loads(record["decision"]["basis"]) == {"chosen": "eq_1"}


def test_the_hhv_input_takes_an_edit_with_a_reason_and_its_unit() -> None:
    trace = line_of(run(coal_store(), **COAL_KW), COAL)["trace"]
    item = trace["inputs"]["hhv"]
    record = review.decide_input(review.new_record("s"), item, None, "recomputed", "edit", value=25.5,
                                 unit=HHV_UNIT, reason="Supplier certificate", actor=ACTOR, now=NOW,
                                 basis=review.basis_of(trace, item))
    assert record["decision"]["value"] == 25.5 and record["decision"]["unit"] == HHV_UNIT
    with pytest.raises(Exception, match="enter the value in"):
        review.decide_input(review.new_record("s"), item, None, "recomputed", "edit", value=25.5,
                            unit="Btu/short_ton", reason="x", actor=ACTOR, now=NOW)
    with pytest.raises(Exception, match="reason"):
        review.decide_input(review.new_record("s"), item, None, "recomputed", "edit", value=25.5, unit=HHV_UNIT,
                            actor=ACTOR, now=NOW)


def test_a_stale_hhv_after_the_unit_of_the_line_changed_is_not_applied() -> None:
    stale = hhv()
    stale["record"]["decision"]["basis"] = json.dumps({"value": None, "unit": "MMBtu/gal", "source": None,
                                                        "grid_region": None})
    after = worked(coal_store(), COAL, [stale, pick("CO2", "eq_2")])
    assert "stale" in reasons(line_of(after, COAL))
    assert after["categories"] == run(coal_store(), **COAL_KW)["categories"]


def test_the_equation_choice_is_a_choice_with_a_stable_id_per_gas() -> None:
    trace = line_of(run(coal_store(), **COAL_KW), COAL)["trace"]
    assert [c["id"] for c in trace["choices"]] == ["method", "equation:CO2", "equation:CH4", "equation:N2O"]
    assert all([o["id"] for o in c["options"]] == ["eq_1", "eq_2", "eq_3"] for c in trace["choices"][1:])
    assert [b["choice_id"] for b in next(s for s in trace["steps"] if s["id"] == "emissions")["blocks"]] == [
        "equation:CO2", "equation:CH4", "equation:N2O"]
    assert math.isfinite(trace["result"]["recomputed"])
