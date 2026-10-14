"""Emissions roll-up: category results -> Scope 1, Scope 2 and inventory totals -> final outputs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import emissions_calculator as calc
from backend.app.services.emissions_rollup import (
    FINAL_OUTPUT_KEYS,
    FINAL_OUTPUTS,
    LAYOUT,
    NODE_BY_KEY,
    NODES,
    OUTPUT_STATUSES,
    SOURCE_KEYS,
    SOURCES,
    UNIT_KEYS,
    build_rollup,
    rollup_layout,
)
from backend.app.services.engagement_recalculation_service import CATALOGUE_KEYS

REF = default_emission_factor_reference()
LB_T = 0.00045359237
NOT_BUILT = ("process_sources", "fugitive_purchased_gases", "agricultural_sources", "purchased_steam",
             "purchased_heating", "purchased_cooling")


def _stationary(mmbtu: float = 1000, fuel: str = "Natural Gas") -> calc.CategoryResult:
    return calc.stationary_combustion([calc.StationaryFuel(fuel, calc.Measure(mmbtu, "MMBtu"))], REF)


def _refrigerants(*uses: calc.RefrigerantUse, gwp_set: str = "AR5") -> calc.CategoryResult:
    return calc.refrigerants(list(uses), REF, gwp_set=gwp_set)


def _electricity(certificates: float = 600) -> tuple[calc.CategoryResult, calc.CategoryResult]:
    facilities = [calc.FacilityElectricity("Facility A", calc.Measure(1200, "MWh"), "NYUP"),
                  calc.FacilityElectricity("Facility B", calc.Measure(800, "MWh"), "RFCE")]
    return (calc.electricity_location_based(facilities, REF),
            calc.electricity_market_based(facilities, [calc.Certificate("REC", certificates)], REF))


def _scenario_a() -> dict[str, calc.CategoryResult | None]:
    location, market = _electricity()
    return {
        "stationary_combustion": _stationary(),
        "mobile_combustion": None,
        "fugitive_refrigerants": _refrigerants(calc.RefrigerantUse("R-410A", "lb", serviced=100),
                                               calc.RefrigerantUse("HFC-227ea", "lb", serviced=20)),
        "purchased_electricity_location_based": location,
        "purchased_electricity_market_based": market,
    }


ABSENT_A = {key: "Site visit: none at this company" for key in ("mobile_combustion", *NOT_BUILT)}


def _rollup(categories: dict[str, calc.CategoryResult | None], *, open_items: dict[str, int] | None = None,
            absent: dict[str, str] | None = None, reported: dict[str, float] | None = None,
            units: dict[str, str] | None = None, out_of_scope: set[str] | None = None, tolerance: float = 5.0,
            gwp_set: str = "AR5") -> dict[str, Any]:
    return build_rollup(categories, open_items=open_items or {}, absent=absent or {}, reported=reported or {},
                        reported_units=units or {}, out_of_scope=out_of_scope or set(), tolerance=tolerance,
                        gwp_set=gwp_set, ref=REF)


def _out(result: dict[str, Any], key: str) -> dict[str, Any]:
    return next(o for o in result["final_outputs"] if o["key"] == key)


# --- Scenario A: everything built is calculated, everything else confirmed absent ------------
def test_scenario_a_rolls_categories_up_to_scope_and_inventory_totals() -> None:
    result = _rollup(_scenario_a(), absent=ABSENT_A)
    nodes = result["nodes"]
    expected = {
        "stationary_combustion_total": 53.1145,
        "fugitive_total": 87.271171988 + 30.39068879,
        "scope1_total": 170.776360778,
        "scope2_location_total": 348.1479801507743,
        "scope2_market_total": 243.70358610554203,
        "inventory_location_total": 518.9243409287743,
        "inventory_market_total": 414.479946883542,
    }
    for key, value in expected.items():
        assert nodes[key]["co2e_t"] == pytest.approx(value, rel=1e-12), key
        assert nodes[key]["status"] == "complete" and nodes[key]["missing"] == [], key
    assert nodes["mobile_combustion_total"]["co2e_t"] == 0.0  # confirmed absent: a true 0
    assert nodes["scope1_co2"]["mass_t"] == pytest.approx(53.06)
    assert (nodes["scope1_ch4"]["mass_t"], nodes["scope1_ch4"]["co2e_t"]) == pytest.approx((0.001, 0.028))
    assert (nodes["scope1_n2o"]["mass_t"], nodes["scope1_n2o"]["co2e_t"]) == pytest.approx((0.0001, 0.0265))
    assert nodes["scope1_hfcs"]["mass_t"] == pytest.approx(120 * LB_T)
    assert nodes["scope1_hfcs"]["co2e_t"] == pytest.approx(117.661860778)
    for gas in ("pfcs", "sf6", "nf3", "other_gases"):
        assert (nodes[f"scope1_{gas}"]["co2e_t"], nodes[f"scope1_{gas}"]["status"]) == (0.0, "complete")
    assert nodes["scope2_co2"]["mass_t"] == pytest.approx(346.9895038600757)
    assert all(check["ok"] for check in result["checks"]) and len(result["checks"]) == 5
    # The fugitive line split is published, so the HFC row can show its working.
    split = result["categories"]["fugitive_refrigerants"]["gas_split"]
    assert split["R-410A"]["groups"]["HFCs"]["co2e_t"] == pytest.approx(87.271171988)
    json.dumps(result)  # the API returns it as is


def test_reported_totals_are_compared_against_the_materiality_threshold() -> None:
    within = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_total": 175}), "scope1_total")
    assert within["status"] == "within_tolerance" and within["within_threshold"] is True
    assert within["difference_pct"] == pytest.approx(-2.413508127)
    assert within["difference"] == pytest.approx(170.776360778 - 175)
    exceeds = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_total": 160}), "scope1_total")
    assert exceeds["status"] == "exceeds_tolerance" and exceeds["difference_pct"] == pytest.approx(6.735225486)
    ten = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_total": 160}, tolerance=10), "scope1_total")
    assert ten["status"] == "within_tolerance" and ten["tolerance_pct"] == 10
    # Exactly at the threshold counts as within.
    at = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_total": 170.776360778 / 1.05}),
              "scope1_total")
    assert at["status"] == "within_tolerance"


# --- not built / no evidence / absent ----------------------------------------------------------
def test_missing_categories_make_totals_partial_never_a_silent_zero() -> None:
    result = _rollup(_scenario_a())
    nodes = result["nodes"]
    scope1 = nodes["scope1_total"]
    assert scope1["status"] == "partial" and scope1["co2e_t"] == pytest.approx(170.776360778)
    assert scope1["lower_bound"] is True
    assert {(m["source"], m["reason"]) for m in scope1["missing"]} == {
        ("mobile_combustion", "no_evidence"), ("process_sources", "not_built"),
        ("fugitive_purchased_gases", "not_built"), ("agricultural_sources", "not_built")}
    assert nodes["process_total"]["co2e_t"] is None and nodes["process_total"]["status"] == "not_available"
    assert nodes["mobile_combustion_total"]["co2e_t"] is None
    # An unanswered Scope 1 source never touches Scope 2.
    assert {m["source"] for m in nodes["scope2_location_total"]["missing"]} == {
        "purchased_steam", "purchased_heating", "purchased_cooling"}
    statuses = {key: entry["status"] for key, entry in result["categories"].items()}
    assert statuses == {"stationary_combustion": "calculated", "mobile_combustion": "no_evidence",
                        "process_sources": "not_built", "fugitive_refrigerants": "calculated",
                        "fugitive_purchased_gases": "not_built", "agricultural_sources": "not_built",
                        "purchased_electricity": "calculated", "purchased_steam": "no_evidence",
                        "purchased_heating": "no_evidence", "purchased_cooling": "not_built"}


def test_a_partial_total_is_never_within_tolerance_but_can_exceed_as_a_lower_bound() -> None:
    near = _out(_rollup(_scenario_a(), reported={"scope1_total": 172}), "scope1_total")
    assert (near["status"], near["reason"], near["completeness"]) == ("incomplete", "partial_total", "partial")
    assert near["within_threshold"] is True  # "within 5% so far"
    below = _out(_rollup(_scenario_a(), reported={"scope1_total": 100}), "scope1_total")
    assert (below["status"], below["reason"]) == ("exceeds_tolerance", "lower_bound")  # only more can be added
    above = _out(_rollup(_scenario_a(), reported={"scope1_total": 400}), "scope1_total")
    assert above["status"] == "incomplete"  # the missing categories might make up the difference


def test_a_reported_value_against_nothing_recalculated_is_not_an_exception() -> None:
    result = _rollup(_scenario_a(), reported={"process_total": 50, "mobile_combustion_total": 5})
    process = _out(result, "process_total")
    assert (process["status"], process["reason"], process["recalculated"]) == ("not_recalculated", "not_built", None)
    assert process["difference_pct"] is None
    mobile = _out(result, "mobile_combustion_total")
    assert (mobile["status"], mobile["reason"]) == ("no_evidence", "no_evidence")
    assert _out(result, "fugitive_total")["status"] == "not_reported"


def test_a_reported_zero() -> None:
    zero = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"process_total": 0}), "process_total")
    assert (zero["status"], zero["difference_pct"]) == ("within_tolerance", 0.0)
    nonzero = _out(_rollup(_scenario_a(), reported={"scope1_total": 0}), "scope1_total")  # partial node
    assert (nonzero["status"], nonzero["reason"], nonzero["difference_pct"]) == (
        "exceeds_tolerance", "reported_zero", None)


def test_open_items_mark_only_their_own_source() -> None:
    categories = _scenario_a()
    result = _rollup(categories, absent=ABSENT_A, open_items={"purchased_electricity": 2})
    assert result["categories"]["purchased_electricity"]["status"] == "partial"
    assert result["nodes"]["scope1_total"]["status"] == "complete"
    assert result["nodes"]["scope2_location_total"]["missing"] == [
        {"source": "purchased_electricity", "reason": "inputs_open"}]
    assert result["nodes"]["inventory_location_total"]["status"] == "partial"
    # Built, no result yet, questions open: awaiting inputs, never 0.
    waiting = _rollup({**categories, "purchased_electricity_location_based": None,
                       "purchased_electricity_market_based": None},
                      absent=ABSENT_A, open_items={"purchased_electricity": 1},
                      reported={"purchased_electricity_total": 300})
    assert waiting["categories"]["purchased_electricity"]["status"] == "awaiting_inputs"
    assert waiting["nodes"]["scope2_location_total"]["co2e_t"] is None
    output = _out(waiting, "purchased_electricity_total")
    assert (output["status"], output["reason"]) == ("no_evidence", "awaiting_inputs")


def test_evidence_wins_over_a_source_marked_absent() -> None:
    result = _rollup(_scenario_a(), absent={**ABSENT_A, "stationary_combustion": "none"})
    stationary = result["categories"]["stationary_combustion"]
    assert stationary["status"] == "calculated" and "marked_absent_but_evidence_found" in stationary["flags"]
    assert result["nodes"]["stationary_combustion_total"]["co2e_t"] == pytest.approx(53.1145)
    assert "marked_absent_but_evidence_found" in result["nodes"]["scope1_total"]["flags"]
    assert result["categories"]["process_sources"]["absent_reason"] == "Site visit: none at this company"


def test_out_of_scope_rows_are_shown_not_judged_and_still_count_in_totals() -> None:
    result = _rollup(_scenario_a(), absent=ABSENT_A, reported={"fugitive_total": 1, "scope1_total": 1},
                     out_of_scope={"fugitive_total"})
    fugitive = _out(result, "fugitive_total")
    assert (fugitive["status"], fugitive["reason"]) == ("not_in_scope", "set_out_of_scope")
    assert fugitive["recalculated"] == pytest.approx(117.661860778)
    assert result["nodes"]["scope1_total"]["co2e_t"] == pytest.approx(170.776360778)
    assert _out(result, "scope1_total")["status"] == "exceeds_tolerance"


# --- gases ---------------------------------------------------------------------------------------
def test_blends_split_into_gas_groups_and_reconcile_to_the_total() -> None:
    fugitive = _refrigerants(calc.RefrigerantUse("R-508A", "kg", serviced=10),
                             calc.RefrigerantUse("R-402A", "lb", serviced=100))
    result = _rollup({"fugitive_refrigerants": fugitive}, absent=ABSENT_A)
    nodes = result["nodes"]
    r508a = 10 / 1000 * 11607
    assert nodes["scope1_pfcs"]["mass_t"] == pytest.approx(0.0061)
    assert nodes["scope1_pfcs"]["co2e_t"] == pytest.approx(r508a * 0.5833548720599638)
    # R-402A: 60% of its mass is HFC; its Table 12 CO2e counts only the HFCs.
    assert nodes["scope1_hfcs"]["mass_t"] == pytest.approx(0.0039 + 100 * LB_T * 0.6)
    assert nodes["scope1_hfcs"]["co2e_t"] + nodes["scope1_pfcs"]["co2e_t"] == pytest.approx(fugitive.total_co2e)
    assert next(c for c in result["checks"] if c["key"] == "scope1_total_equals_gas_sum")["ok"]


def test_unknown_blends_and_non_kyoto_gases_stay_in_the_total_under_other_gases() -> None:
    fugitive = calc.refrigerants([
        calc.RefrigerantUse("R-454B", "lb", serviced=10, gwp_override=466),
        calc.RefrigerantUse("R-1234yf", "lb", serviced=10, gwp_override=1),
        calc.RefrigerantUse("R-410A", "lb", serviced=10)], REF)
    result = _rollup({"fugitive_refrigerants": fugitive}, absent={**ABSENT_A, "stationary_combustion": "none"})
    nodes, source = result["nodes"], result["categories"]["fugitive_refrigerants"]
    assert source["gas_split"]["R-454B"]["flags"] == ["gas_split_unknown"]
    assert source["gas_split"]["R-1234yf"]["flags"] == ["non_kyoto_gas_in_total"]
    assert source["status"] == "calculated"  # the total is exact; only the per-gas split is unknown
    assert nodes["fugitive_total"]["status"] == "complete"
    assert nodes["scope1_other_gases"]["co2e_t"] == pytest.approx(10 * LB_T * (466 + 1))
    assert nodes["scope1_hfcs"]["status"] == "partial"
    assert {"source": "fugitive_refrigerants", "reason": "gas_split_unknown"} in nodes["scope1_hfcs"]["missing"]
    assert nodes["scope1_co2"]["status"] == "complete"
    assert all(check["ok"] for check in result["checks"])


def test_other_gwp_sets_flag_blend_splits_that_use_ar5_ratios() -> None:
    fugitive = _refrigerants(calc.RefrigerantUse("R-508A", "kg", serviced=10, gwp_override=13000))
    result = _rollup({"fugitive_refrigerants": fugitive}, absent=ABSENT_A, gwp_set="AR6")
    assert "gas_split_uses_ar5_ratios" in result["categories"]["fugitive_refrigerants"]["flags"]


def test_biogenic_co2_is_a_memo_outside_every_total() -> None:
    result = _rollup({"stationary_combustion": calc.stationary_combustion([
        calc.StationaryFuel("Natural Gas", calc.Measure(1000, "MMBtu")),
        calc.StationaryFuel("Wood and Wood Residuals", calc.Measure(1000, "MMBtu"))], REF)}, absent=ABSENT_A)
    nodes = result["nodes"]
    wood_co2 = calc.stationary_combustion([calc.StationaryFuel("Wood and Wood Residuals",
                                                               calc.Measure(1000, "MMBtu"))], REF).biogenic_co2_t
    assert wood_co2 > 0 and nodes["biogenic_co2"]["co2e_t"] == pytest.approx(wood_co2)
    assert nodes["scope1_co2"]["mass_t"] == pytest.approx(53.06)  # natural gas only
    assert nodes["scope1_total"]["co2e_t"] == pytest.approx(nodes["stationary_combustion_total"]["co2e_t"])
    assert "biogenic_co2" not in json.dumps(NODE_BY_KEY["scope1_total"].terms)
    assert _rollup({}, absent={})["nodes"]["biogenic_co2"]["co2e_t"] is None


def test_mobile_fuel_without_vehicle_groups_leaves_ch4_and_n2o_partial() -> None:
    mobile = calc.mobile_combustion([calc.MobileFuel("Diesel Fuel", calc.Measure(1000, "gal"))], REF)
    result = _rollup({"mobile_combustion": mobile},
                     absent={k: v for k, v in ABSENT_A.items() if k != "mobile_combustion"}
                     | {"stationary_combustion": "none", "fugitive_refrigerants": "none"})
    nodes = result["nodes"]
    assert result["categories"]["mobile_combustion"]["gaps"] == [
        {"gap": "vehicle_groups_missing", "gases": ["CH4", "N2O"], "affects_total": True}]
    for key in ("mobile_combustion_total", "scope1_ch4", "scope1_n2o", "scope1_total"):
        assert nodes[key]["status"] == "partial", key
        assert {"source": "mobile_combustion", "reason": "vehicle_groups_missing"} in nodes[key]["missing"]
    assert nodes["scope1_co2"]["status"] == "complete"


def test_scope2_fluorinated_gases_are_structural_zeros() -> None:
    location, market = _electricity()
    result = _rollup({"purchased_electricity_location_based": location,
                      "purchased_electricity_market_based": market}, absent=ABSENT_A,
                     reported={"scope2_hfcs": 0, "scope2_sf6": 2})
    assert result["nodes"]["scope2_nf3"]["basis"] == "structural_zero"
    assert (result["nodes"]["scope2_hfcs"]["co2e_t"], result["nodes"]["scope2_hfcs"]["status"]) == (0.0, "complete")
    assert _out(result, "scope2_hfcs")["status"] == "within_tolerance"
    assert _out(result, "scope2_sf6")["status"] == "exceeds_tolerance"  # often T&D SF6: not the company's Scope 2
    nothing = _rollup({}, absent={})
    assert nothing["nodes"]["scope2_hfcs"]["co2e_t"] is None


def test_per_gas_rows_need_the_reported_unit() -> None:
    reported = {"scope1_hfcs": 117.6}
    unset = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported=reported), "scope1_hfcs")
    assert (unset["status"], unset["reason"], unset["unit_hint"]) == ("needs_unit", "unit_unconfirmed", "t CO2e")
    assert unset["candidates"]["co2e_t"] == pytest.approx(117.661860778)
    co2e = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported=reported, units={"scope1_hfcs": "t CO2e"}),
                "scope1_hfcs")
    assert (co2e["status"], co2e["unit"]) == ("within_tolerance", "t CO2e")
    mass = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported=reported, units={"scope1_hfcs": "t"}),
                "scope1_hfcs")
    assert mass["status"] == "exceeds_tolerance" and "reported_matches_other_unit" in mass["flags"]
    # Both candidates 0: no unit needed.
    sf6 = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_sf6": 0}), "scope1_sf6")
    assert sf6["status"] == "within_tolerance"
    # CO2, CH4 and N2O default to tonnes of gas, as today.
    co2 = _out(_rollup(_scenario_a(), absent=ABSENT_A, reported={"scope1_co2": 53}), "scope1_co2")
    assert (co2["status"], co2["unit"]) == ("within_tolerance", "t")


def test_a_negative_refrigerant_balance_means_a_partial_total_cannot_conclude() -> None:
    fugitive = _refrigerants(calc.RefrigerantUse("R-410A", "lb", retired_capacity=10, recovered=50),
                             calc.RefrigerantUse("HFC-134a", "lb", serviced=100))
    result = _rollup({"fugitive_refrigerants": fugitive}, reported={"scope1_total": 1})
    assert result["nodes"]["scope1_total"]["lower_bound"] is False
    assert _out(result, "scope1_total")["status"] == "incomplete"


def test_an_open_refrigerant_question_keeps_sf6_and_nf3_open() -> None:
    fugitive = _refrigerants(calc.RefrigerantUse("R-410A", "lb", serviced=100))
    others = {k: "none" for k in SOURCE_KEYS if k != "fugitive_refrigerants"}
    open_question = _rollup({"fugitive_refrigerants": fugitive}, absent=others,
                            open_items={"fugitive_refrigerants": 1}, reported={"scope1_sf6": 0})
    for gas in ("scope1_sf6", "scope1_nf3"):
        assert open_question["nodes"][gas]["status"] == "partial", gas  # the open record may be SF6
    assert _out(open_question, "scope1_sf6")["status"] == "incomplete"
    waiting = _rollup({}, absent=others, open_items={"fugitive_refrigerants": 1}, reported={"scope1_sf6": 0})
    assert waiting["nodes"]["scope1_sf6"]["co2e_t"] is None
    assert (_out(waiting, "scope1_sf6")["status"], _out(waiting, "scope1_sf6")["reason"]) == (
        "no_evidence", "awaiting_inputs")
    answered = _rollup({"fugitive_refrigerants": fugitive}, absent=others, reported={"scope1_sf6": 0})
    assert _out(answered, "scope1_sf6")["status"] == "within_tolerance"  # no SF6 line: a true 0


def test_an_entered_gwp_on_a_blend_with_hcfcs_counts_only_its_hfc_share_as_hfcs() -> None:
    # AR6 has no blend GWPs, so the reviewer enters R-402A's from the safety data sheet (HCFC-22 included).
    fugitive = calc.refrigerants([calc.RefrigerantUse("R-402A", "kg", serviced=1000, gwp_override=2989)], REF,
                                 gwp_set="AR6")
    result = _rollup({"fugitive_refrigerants": fugitive}, absent=ABSENT_A, gwp_set="AR6")
    hub = REF.gwp("R-402A", "AR5").value
    split = result["categories"]["fugitive_refrigerants"]["gas_split"]["R-402A"]
    assert split["groups"]["HFCs"]["co2e_t"] == pytest.approx(hub)  # 1 t x the Table 12 (HFC-only) GWP
    assert split["groups"]["other"]["co2e_t"] == pytest.approx(2989 - hub)
    assert split["flags"] == ["gas_split_uses_ar5_ratios"]
    assert result["nodes"]["fugitive_total"]["co2e_t"] == pytest.approx(2989)


def test_a_negative_line_stops_only_the_partial_totals_it_is_part_of_from_concluding() -> None:
    # A negative R-410A balance makes HFCs and the totals no lower bound, but not CO2.
    fugitive = _refrigerants(calc.RefrigerantUse("R-410A", "lb", retired_capacity=10, recovered=50))
    result = _rollup({"stationary_combustion": _stationary(), "fugitive_refrigerants": fugitive},
                     reported={"scope1_co2": 10, "scope1_total": 1})
    assert result["nodes"]["scope1_co2"]["lower_bound"] is True
    assert (_out(result, "scope1_co2")["status"], _out(result, "scope1_co2")["reason"]) == (
        "exceeds_tolerance", "lower_bound")
    assert result["nodes"]["scope1_hfcs"]["lower_bound"] is False
    assert _out(result, "scope1_total")["status"] == "incomplete"
    # A negative fuel line (a credit on a bill) counts too, though the fuel total stays positive.
    stationary = calc.stationary_combustion([
        calc.StationaryFuel("Natural Gas", calc.Measure(-100, "MMBtu")),
        calc.StationaryFuel("Natural Gas", calc.Measure(1000, "MMBtu"))], REF)
    credited = _rollup({"stationary_combustion": stationary}, reported={"scope1_total": 1})
    assert credited["nodes"]["scope1_total"]["lower_bound"] is False
    assert _out(credited, "scope1_total")["status"] == "incomplete"


def test_gas_rows_carry_only_the_flags_of_lines_with_that_gas() -> None:
    fugitive = calc.refrigerants([calc.RefrigerantUse("R-410A", "lb", serviced=100),
                                  calc.RefrigerantUse("R-1234yf", "lb", serviced=10, gwp_override=1)], REF)
    result = _rollup({"fugitive_refrigerants": fugitive}, absent={**ABSENT_A, "stationary_combustion": "none"})
    nodes = result["nodes"]
    assert nodes["scope1_hfcs"]["flags"] == [] and nodes["scope1_co2"]["flags"] == []
    assert nodes["scope1_other_gases"]["flags"] == ["non_kyoto_gas_in_total"]
    assert nodes["fugitive_total"]["flags"] == ["non_kyoto_gas_in_total"]


# --- the tables themselves ---------------------------------------------------------------------
def test_the_roll_up_tables_are_consistent() -> None:
    assert (len(SOURCES), len(NODES), len(FINAL_OUTPUTS)) == (10, 37, 26)
    assert FINAL_OUTPUT_KEYS == CATALOGUE_KEYS
    assert {o.workbook_row for o in FINAL_OUTPUTS if o.key in UNIT_KEYS} == {23, 24, 25, 26, 27, 28, 30, 31, 32,
                                                                             33, 34, 35, 36}
    in_steps = [key for step in LAYOUT for key in step["node_keys"]]
    assert sorted(in_steps) == sorted(n.key for n in NODES)
    for node in NODES:
        for term in node.terms:
            kind, key = term.split(":", 1)
            assert key in (SOURCE_KEYS if kind == "category" else NODE_BY_KEY), term
    assert all(NODE_BY_KEY[o.node] for o in FINAL_OUTPUTS)
    layout = rollup_layout()
    assert [s["key"] for s in layout["steps"]] == ["step_1a", "step_1b", "step_2", "final_outputs"]
    json.dumps(layout)
    statuses = {o["status"] for o in _rollup(_scenario_a(), reported={k: 1.0 for k in FINAL_OUTPUT_KEYS})
                ["final_outputs"]}
    assert statuses <= set(OUTPUT_STATUSES)
