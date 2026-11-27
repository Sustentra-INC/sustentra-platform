"""C4: fugitive refrigerants by the simplified material balance, one line per refrigerant and facility, with a blend's
components. The plan's R-404A example: P_N 42, C_N 40, P_S 90 (18 + 22 + 36 + 14), C_D 55, R_D 48 lb.

The lb to metric ton factor is the one the fugitive category has always used, 0.45359237 kg per lb exactly (the
plan's numbers were worked with 1/2,204.62, which the category never used for refrigerants): 99 lb is 0.04490564463 t,
not 0.0449057 t, and every number below follows from that. Keeping it leaves every existing total as it was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import emissions_calculator as calc
from backend.app.services.calc_trace import decisions, fugitive
from backend.app.services.calc_line_review import Refused, decide_input
from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.app.services.request_service import Actor
from backend.app.services.review_field import ReviewInvalid
from backend.tests.services.calc_trace.fixture_replay import FIXTURES
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, line_of
from backend.tests.services.test_calculation_lines import GAS_KC, KC, STL
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own, _refrigerant

SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())
REF = default_emission_factor_reference()
T_PER_LB = 0.45359237 / 1000
R404A_KC = "s1:fugitive:r-404a:fac-kc01"
R448A_KC = "s1:fugitive:r-448a:fac-kc01"
R448A_STL = "s1:fugitive:r-448a:fac-stl2"
R410A_KC = "s1:fugitive:r-410a:fac-kc01"
HFO = ("HFO-1234yf", "HFO-1234ze(E)")


def rec(gas: str, day: str, service_type: str | None = "service", plant: str = "Kansas City Plant",
        **amounts: Any) -> dict[str, tuple]:
    record = _refrigerant(gas, day, service_type, **amounts)
    record["facility_name"] = (plant, None)
    return record


def r404a_store() -> FakeStore:
    store = FakeStore()
    store.add_document("LOG", "CT-S1-REFRSVC", [
        rec("R-404A", "2025-02-01", "installation", added=42, capacity=40),
        rec("R-404A", "2025-03-01", added=18), rec("R-404A", "2025-05-01", added=22),
        rec("R-404A", "2025-07-01", added=36), rec("R-404A", "2025-09-01", added=14),
        rec("R-404A", "2025-11-01", "disposal", recovered=48, capacity=55)])
    return store


def run(store: FakeStore, line_decisions: list[dict] | None = None, with_traces: bool = True,
        **recalculation: Any) -> dict:
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [KC, STL], "recalculation": recalculation}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, _own, None, with_traces=with_traces, line_decisions=line_decisions)


def gwp_event(key: str, component: str, value: float) -> dict:
    return event(key, f"input|{fugitive.COMPONENT_GWP}{component}|recomputed", "edited", value, "t CO2e/t")


def category(response: dict) -> dict:
    found: dict = response["categories"]["fugitive_refrigerants"]
    return found


# --- the plan's numbers --------------------------------------------------------------------------------------------
def test_r404a_simplified_material_balance_is_the_plans_example_exactly() -> None:
    response = run(r404a_store(), reported_activity={R404A_KC: {"quantity": 129, "unit": "lb"}})
    line = line_of(response, R404A_KC)
    trace = line["trace"]
    assert trace["panel"] == "fugitive" and trace["state"] == "complete"
    # Step 1: each term, P_S as its four service records
    assert [block(trace, f"term.{t}")["recomputed"]["result"]["value"] for t in fugitive.TERMS] == [42, 40, 90, 55, 48]
    assert [r["recomputed"]["value"] for r in trace["inputs"]["P_S"]["rows"]] == [18, 22, 36, 14]
    assert [t["operand"]["value"] for t in block(trace, "term.P_S")["recomputed"]["terms"]] == [18, 22, 36, 14]
    # Step 2: 99 lb, then metric tons
    emitted = block(trace, "emitted")["recomputed"]
    assert [t["op"] for t in emitted["terms"]] == [None, "−", "+", "+", "−"]
    assert emitted["result"]["value"] == 99.0
    to_t = block(trace, "emitted_t")["recomputed"]
    assert to_t["terms"][1]["operand"]["value"] == pytest.approx(T_PER_LB, rel=1e-15)
    assert to_t["result"]["value"] == pytest.approx(0.04490564463, rel=1e-12)
    # Step 3: the Table 12 blend GWP counts (3,943), the components are shown (3,942.8)
    co2e = block(trace, "co2e")["recomputed"]
    assert co2e["terms"][1]["operand"]["value"] == 3943
    assert co2e["result"]["value"] == pytest.approx(177.06295677609, rel=1e-12)
    assert block(trace, "components.sum")["recomputed"]["result"]["value"] == pytest.approx(177.05397564716,
                                                                                             rel=1e-12)
    components = {b["id"]: b["recomputed"]["terms"] for s in trace["steps"] for b in s["blocks"]
                  if b["id"].startswith("component.")}
    assert {k: (t[1]["operand"]["value"], t[2]["operand"]["value"]) for k, t in components.items()} == {
        "component.HFC-125": (0.44, 3170), "component.HFC-143a": (0.52, 4800), "component.HFC-134a": (0.04, 1300)}
    note = next(s for s in trace["steps"] if s["id"] == "gwp")["note"]
    assert "3,943" in note and "3,942.8" in note and "counts in the totals" in note
    # the line, its trace and the category say the same number, to the last digit
    assert line["results"]["total_co2e_t"] == 177.06295677609
    assert trace["result"]["recomputed"] == line["results"]["total_co2e_t"]
    assert category(response)["total_co2e"] == line["results"]["total_co2e_t"]
    assert line["results"]["mass_t"] == {"R-404A": 0.04490564463}
    # the company: 129 lb as reported, × the same blend GWP
    assert block(trace, "emitted_t")["company"]["result"]["value"] == pytest.approx(129 * T_PER_LB, rel=1e-12)
    assert trace["result"]["company"] == pytest.approx(230.71839822339, rel=1e-12)
    assert trace["result"]["difference"] == pytest.approx(177.06295677609 - 230.71839822339, rel=1e-12)
    assert line["results"]["company_total_co2e_t"] == pytest.approx(230.71839822339, rel=1e-12)
    assert line["step1"]["total"] == {"quantity": 99.0, "unit": "lb"}
    assert line["counts_toward"] == "fugitive" and line["level2"] == "R-404A"
    jsonschema.validate(trace, SCHEMA)


def test_the_method_is_the_simplified_material_balance_with_screening_offered() -> None:
    trace = line_of(run(r404a_store()), R404A_KC)["trace"]
    method = trace["choices"][0]
    assert method["id"] == "method" and method["chosen"] == "smb"
    assert [(o["id"], o["available"]) for o in method["options"]] == [
        ("screening", True), ("smb", True), ("material_balance", True)]
    assert method["options"][1]["equation"] == fugitive.EQUATION


def test_company_terms_entered_by_a_reviewer_are_compared_term_by_term() -> None:
    company = [event(R404A_KC, f"input|{t}|company", "edited", v, "lb")
               for t, v in zip(fugitive.TERMS, (42, 40, 120, 55, 48), strict=True)]
    response = run(r404a_store(), line_decisions=company, reported_activity={R404A_KC: {"quantity": 129, "unit": "lb"}})
    trace = line_of(response, R404A_KC)["trace"]
    assert trace["inputs"]["P_S"]["company"]["value"] == 120 and trace["inputs"]["P_S"]["difference"] == -30
    emitted = block(trace, "emitted")
    assert emitted["company"]["result"]["value"] == 129.0
    assert emitted["recomputed"]["result"]["difference"] == -30.0
    # the company's terms are shown, never an operand: every total is as without them
    assert line_of(response, R404A_KC)["results"]["total_co2e_t"] == 177.06295677609
    assert "decisions" in line_of(response, R404A_KC)


def test_r410a_splits_fifty_fifty_into_hfc32_and_hfc125() -> None:
    store = FakeStore()
    store.add_document("R410", "CT-S1-REFRSVC", [rec("R-410A", "2025-04-09", added=40)])
    trace = line_of(run(store), R410A_KC)["trace"]
    parts = {b["id"]: [t["operand"]["value"] for t in b["recomputed"]["terms"][1:]]
             for s in trace["steps"] for b in s["blocks"] if b["id"].startswith("component.")}
    assert parts == {"component.HFC-32": [0.5, 677], "component.HFC-125": [0.5, 3170]}
    tonnes = 40 * T_PER_LB
    assert block(trace, "co2e")["recomputed"]["result"]["value"] == pytest.approx(tonnes * 1924, rel=1e-12)
    assert block(trace, "components.sum")["recomputed"]["result"]["value"] == pytest.approx(
        tonnes * (0.5 * 677 + 0.5 * 3170), rel=1e-12)


def test_a_single_gas_has_no_component_split() -> None:
    store = FakeStore()
    store.add_document("FM200", "CT-S1-REFRSVC", [rec("FM-200", "2025-06-01", added=12)])
    line = line_of(run(store), "s1:fugitive:hfc-227ea:fac-kc01")
    trace = line["trace"]
    assert not any(b["id"].startswith("component.") for s in trace["steps"] for b in s["blocks"])
    assert block(trace, "co2e")["recomputed"]["result"]["value"] == pytest.approx(12 * T_PER_LB * 3350, rel=1e-12)


# --- a blend the Hub lacks: component GWPs ------------------------------------------------------------------------
def r448a_store(*plants: str) -> FakeStore:
    store = FakeStore()
    store.add_document("R448", "CT-S1-REFRSVC", [rec("R-448A", "2025-04-01", added=10, plant=p)
                                                 for p in plants or ("Kansas City Plant",)])
    return store


def test_r448a_waits_for_its_hfo_component_gwps_and_counts_nothing_until_then() -> None:
    response = run(r448a_store())
    line = line_of(response, R448A_KC)
    trace = line["trace"]
    assert trace["state"] == "blocked"
    assert trace["blocking"][0]["message"].startswith("component GWPs.")
    assert "HFO-1234yf and HFO-1234ze(E)" in trace["blocking"][0]["message"]
    for name in HFO:  # the components EPA Table 11 lacks: decidable, awaiting
        item = trace["inputs"][f"component_gwp.{name}"]
        assert item["decidable"] is True and item["recomputed"]["status"] == "awaiting_review"
    for name in ("HFC-32", "HFC-125", "HFC-134a"):  # Table 11 components: the reference value, not decidable
        assert trace["inputs"][f"gwp.{name}"]["decidable"] is False
    assert trace["inputs"]["P_S"]["decidable"] is True  # the working is there: its terms can be decided
    assert trace["inputs"]["share.HFO-1234yf"]["recomputed"]["value"] == 0.2
    assert "ASHRAE" in trace["inputs"]["share.HFO-1234yf"]["recomputed"]["source"]["citation"]
    assert trace["result"]["recomputed"] is None
    assert line["results"]["mass_t"] == {} and line["results"]["total_co2e_t"] == 0.0
    assert "refrigerant_gwp_needed" in line["flags"]
    assert response["categories"]["fugitive_refrigerants"] is None
    assert any(n["kind"] == "refrigerant_gwp" and n["key"] == "R-448A" for n in response["needs_input"])
    jsonschema.validate(trace, SCHEMA)


def test_r448a_counts_once_its_component_gwps_are_entered() -> None:
    decided = [gwp_event(R448A_KC, "HFO-1234yf", 4), gwp_event(R448A_KC, "HFO-1234ze(E)", 6)]
    response = run(r448a_store(), line_decisions=decided)
    line = line_of(response, R448A_KC)
    trace = line["trace"]
    blend = 0.26 * 677 + 0.26 * 3170 + 0.20 * 4 + 0.21 * 1300 + 0.07 * 6  # 1,274.44
    expected = 10 * T_PER_LB * blend
    assert trace["state"] == "complete" and trace["inputs"]["gwp.R-448A"]["recomputed"]["value"] == pytest.approx(
        blend, rel=1e-12)
    assert trace["inputs"]["gwp.R-448A"]["recomputed"]["status"] == "derived"
    assert trace["inputs"]["component_gwp.HFO-1234yf"]["recomputed"]["status"] == "edited"
    assert line["results"]["total_co2e_t"] == pytest.approx(expected, rel=1e-12)
    assert line["results"]["total_co2e_t"] == pytest.approx(5.780762600228, rel=1e-12)
    assert trace["result"]["recomputed"] == line["results"]["total_co2e_t"]
    fugitive_category = category(response)
    assert fugitive_category["total_co2e"] == pytest.approx(expected, rel=1e-12)
    assert fugitive_category["gwp"]["R-448A"]["value"] == pytest.approx(blend, rel=1e-12)
    assert any(s["label"].startswith("Decided input: HFO-1234yf GWP") for s in fugitive_category["lines"][0]["steps"])
    assert not any(n["kind"] == "refrigerant_gwp" for n in response["needs_input"])
    assert "refrigerant_gwp_needed" not in line["flags"] and "reviewer_decisions_applied" in line["flags"]
    assert response["scope_totals"]["scope1"]["total_co2e"] == pytest.approx(expected, rel=1e-12)
    jsonschema.validate(trace, SCHEMA)


def test_one_component_gwp_entered_is_held_and_counts_nothing() -> None:
    response = run(r448a_store(), line_decisions=[gwp_event(R448A_KC, "HFO-1234yf", 4)])
    line = line_of(response, R448A_KC)
    assert line["trace"]["state"] == "blocked" and "HFO-1234ze(E)" in line["trace"]["blocking"][0]["message"]
    assert line["trace"]["inputs"]["component_gwp.HFO-1234yf"]["recomputed"]["value"] == 4
    applied = line["decisions"]["applied"]
    assert applied[0]["id"] == "component_gwp.HFO-1234yf" and applied[0]["uses"].startswith("held")
    assert line["results"]["total_co2e_t"] == 0.0 and response["categories"]["fugitive_refrigerants"] is None


def test_two_lines_of_one_blend_must_agree_on_its_component_gwps() -> None:
    store = r448a_store("Kansas City Plant", "St Louis Plant")
    agreed = [gwp_event(k, n, v) for k in (R448A_KC, R448A_STL) for n, v in zip(HFO, (4, 6), strict=True)]
    response = run(store, line_decisions=agreed)
    assert category(response)["total_co2e"] == pytest.approx(
        20 * T_PER_LB * (0.26 * 677 + 0.26 * 3170 + 0.20 * 4 + 0.21 * 1300 + 0.07 * 6), rel=1e-12)
    assert not any(n["kind"] == "refrigerant_gwp" for n in response["needs_input"])

    differing = [*agreed[:2], gwp_event(R448A_STL, HFO[0], 1), gwp_event(R448A_STL, HFO[1], 6)]
    response = run(store, line_decisions=differing)
    kc, stl = line_of(response, R448A_KC), line_of(response, R448A_STL)
    refused = stl["decisions"]["not_applied"]
    assert {r["reason"] for r in refused} == {"gwp_differs_between_lines"}
    assert all("Kansas City Plant was decided first" in r["message"] for r in refused)  # names the line that won
    assert stl["results"]["total_co2e_t"] == 0.0 and stl["trace"]["state"] == "blocked"  # the working counted
    assert category(response)["total_co2e"] == pytest.approx(kc["results"]["total_co2e_t"], rel=1e-12)
    # one R-448A line still has no GWP: the engagement keeps asking for it
    assert any(n["kind"] == "refrigerant_gwp" and n["key"] == "R-448A" for n in response["needs_input"])

    one_only = run(store, line_decisions=agreed[:2])  # the other line has no decision: still asked for
    assert any(n["kind"] == "refrigerant_gwp" for n in one_only["needs_input"])
    assert category(one_only)["total_co2e"] == pytest.approx(line_of(one_only, R448A_KC)["results"]["total_co2e_t"])


def test_an_engagement_gwp_for_r448a_counts_and_the_components_are_shown() -> None:
    response = run(r448a_store(), refrigerant_gwps={"R-448A": {"value": 1387, "gwp_set": "AR5"}})
    trace = line_of(response, R448A_KC)["trace"]
    assert trace["state"] == "complete"
    assert block(trace, "co2e")["recomputed"]["result"]["value"] == pytest.approx(10 * T_PER_LB * 1387, rel=1e-12)
    note = next(s for s in trace["steps"] if s["id"] == "gwp")["note"]
    assert "not shown" in note and "HFO-1234yf" in note
    assert category(response)["total_co2e"] == trace["result"]["recomputed"]


# --- decisions on the terms ---------------------------------------------------------------------------------------
def test_an_edited_service_total_moves_the_line_and_the_category_exactly() -> None:
    before = run(r404a_store())
    after = run(r404a_store(), line_decisions=[event(R404A_KC, "input|P_S|recomputed", "edited", 120, "lb")])
    line = line_of(after, R404A_KC)
    assert block(line["trace"], "emitted")["recomputed"]["result"]["value"] == 129.0
    assert line["results"]["total_co2e_t"] == pytest.approx(230.71839822339, rel=1e-12)
    assert line["step1"]["total"]["quantity"] == 129.0
    assert category(after)["total_co2e"] == pytest.approx(230.71839822339, rel=1e-12)
    assert category(after)["total_mass_t"]["R-404A"] == pytest.approx(129 * T_PER_LB, rel=1e-12)
    delta = 30 * T_PER_LB * 3943
    assert after["scope_totals"]["scope1"]["total_co2e"] - before["scope_totals"]["scope1"]["total_co2e"] == \
        pytest.approx(delta, rel=1e-9)
    steps = category(after)["lines"][0]["steps"]
    assert steps[-1]["label"] == "R-404A in CO2e" and steps[-1]["result"] == pytest.approx(230.71839822339)
    assert any(s["label"].startswith("Decided input: Added during service P_S") for s in steps)
    nodes_before, nodes_after = before["rollup"]["nodes"], after["rollup"]["nodes"]
    assert nodes_after["inventory_location_total"]["co2e_t"] - nodes_before["inventory_location_total"]["co2e_t"] == \
        pytest.approx(delta, rel=1e-9)
    # a revert returns every number exactly
    reverted = run(r404a_store(), line_decisions=[event(R404A_KC, "input|P_S|recomputed", "pending")])
    for key in ("categories", "scope_totals", "comparisons", "rollup"):
        assert reverted[key] == before[key], key


def test_one_service_record_edited_and_a_total_that_wins_over_its_records() -> None:
    trace = line_of(run(r404a_store()), R404A_KC)["trace"]
    row = trace["inputs"]["P_S"]["rows"][0]["id"]
    one = event(R404A_KC, f"input|P_S/{row}|recomputed", "edited", 48, "lb")  # 18 -> 48
    line = line_of(run(r404a_store(), line_decisions=[one]), R404A_KC)
    assert block(line["trace"], "term.P_S")["recomputed"]["result"]["value"] == 120.0
    assert line["results"]["total_co2e_t"] == pytest.approx(230.71839822339, rel=1e-12)
    both = [one, event(R404A_KC, "input|P_S|recomputed", "edited", 100, "lb")]
    line = line_of(run(r404a_store(), line_decisions=both), R404A_KC)
    assert block(line["trace"], "emitted")["recomputed"]["result"]["value"] == 109.0
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["total_decided"]


def test_a_negative_balance_is_kept_and_flagged() -> None:
    response = run(r404a_store(), line_decisions=[event(R404A_KC, "input|C_N|recomputed", "edited", 200, "lb")])
    line = line_of(response, R404A_KC)
    emitted = 42 - 200 + 90 + 55 - 48  # -61 lb
    assert line["step1"]["total"]["quantity"] == emitted
    assert line["results"]["total_co2e_t"] == pytest.approx(emitted * T_PER_LB * 3943, rel=1e-12)
    assert line["results"]["total_co2e_t"] < 0
    assert "negative_refrigerant_emissions" in line["flags"]
    assert "negative_refrigerant_emissions" in line["trace"]["flags"]
    assert category(response)["total_co2e"] == pytest.approx(emitted * T_PER_LB * 3943, rel=1e-12)
    assert "negative_refrigerant_emissions" in category(response)["flags"]


@pytest.mark.parametrize("value,unit", [(-0.0001, "lb"), (-5, "lb"), (float("nan"), "lb"), (1e16, "lb"), (90, "kg"),
                                        ("ninety", "lb"), (True, "lb")])
def test_hostile_values_are_reported_never_used(value: Any, unit: str) -> None:
    before = run(r404a_store())
    response = run(r404a_store(), line_decisions=[event(R404A_KC, "input|P_S|recomputed", "edited", value, unit)])
    line = line_of(response, R404A_KC)
    assert line["decisions"]["not_applied"] and not line["decisions"]["applied"]
    assert category(response) == category(before)


def test_the_blend_gwp_share_and_conversion_cannot_be_decided_for_a_line() -> None:
    trace = line_of(run(r404a_store()), R404A_KC)["trace"]
    for input_id in ("gwp.R-404A", "gwp.HFC-125", "share.HFC-125", "unit_conversion", "share"):
        assert trace["inputs"][input_id]["decidable"] is False, input_id
        assert trace["inputs"][input_id]["why_not"]
    response = run(r404a_store(), line_decisions=[event(R404A_KC, "input|gwp.R-404A|recomputed", "edited", 4000,
                                                        "t CO2e/t")])
    assert [n["reason"] for n in line_of(response, R404A_KC)["decisions"]["not_applied"]] == ["set_elsewhere"]
    actor = Actor(user_id="u1", login="rev@example.com", name="Rev Iewer")
    with pytest.raises(Refused):
        decide_input({}, trace["inputs"]["share.HFC-125"], None, "recomputed", "edit", value=0.5, unit=None,
                     reason="no", actor=actor, now=__import__("datetime").datetime.now())
    assert decisions.not_decidable("component_gwp.HFO-1234yf") is None
    assert decisions.not_decidable("P_S/doc/1") is None


def test_a_decision_for_another_line_never_touches_this_one() -> None:
    store = r404a_store()
    store.add_document("R448", "CT-S1-REFRSVC", [rec("R-448A", "2025-04-01", added=10)])
    response = run(store, line_decisions=[gwp_event("s1:fugitive:r-404a:fac-other", "HFO-1234yf", 4)])
    assert line_of(response, R404A_KC)["results"]["total_co2e_t"] == 177.06295677609
    assert response["calculation_line_decisions"]["orphaned"]


# --- placement, unplaced records and the guard -------------------------------------------------------------------
def test_a_refrigerant_record_moved_off_its_line_is_reported_unplaced_and_still_adds_up() -> None:
    store = r404a_store()
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas_record(1000, "2025-01-01", "2025-01-31")])
    moved = {"LOG": {"placements": [{"from": R404A_KC, "to": GAS_KC}]}}
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [KC, STL], "recalculation": {}}}
    response = EngagementRecalculationService(store, store, store).recalculate(engagement, _own, moved,
                                                                                with_traces=True)
    unplaced = [u for u in response["calculation_unplaced"] if u["counts_toward"] == "fugitive"]
    assert len(unplaced) == 1 and unplaced[0]["reason"] == "moved_to_another_place"
    assert unplaced[0]["results"]["mass_t"] == {"R-404A": pytest.approx(99 * T_PER_LB, rel=1e-12)}
    assert category(response)["total_mass_t"] == {"R-404A": unplaced[0]["results"]["mass_t"]["R-404A"]}
    assert not any(ln["counts_toward"] == "fugitive" for ln in response["calculation_lines"])


def test_no_decisions_leave_the_fugitive_category_exactly_as_the_calculator_makes_it() -> None:
    response = run(r404a_store(), with_traces=False)
    expected = calc.refrigerants([calc.RefrigerantUse("R-404A", "lb", new_charged=42, new_capacity=40, serviced=90,
                                                      retired_capacity=55, recovered=48, source="6 reviewed records")],
                                 REF).to_dict()
    got = dict(category(response))
    got.pop("details")
    expected.pop("details")
    assert got == expected
    assert run(r404a_store(), line_decisions=[], with_traces=False) == response


@pytest.mark.parametrize("name", ["recalculationRefrigerants.json", "recalculationLive.json"])
def test_every_recorded_refrigerant_fixture_keeps_its_total_and_its_lines_add_up(name: str) -> None:
    recorded = json.loads((FIXTURES / name).read_text())["categories"]["fugitive_refrigerants"]
    store = FakeStore()
    for item in recorded["details"]["inputs"]:
        terms = next(s for s in next(ln for ln in recorded["lines"] if ln["key"] == item["fuel"])["steps"])["inputs"]
        by_label = {k.split(" ")[0]: float(v["value"]) for k, v in terms.items()}
        for doc in item["documents"]:
            kind, quantity = doc["service_type"], float(doc["quantity"])
            amounts = {"installation": {"added": quantity, "capacity": by_label.get("C_N")},
                       "disposal": {"recovered": quantity, "capacity": by_label.get("C_D")}}.get(kind, {"added": quantity})
            store.add_document(doc["document_id"], "CT-S1-REFRSVC", [rec(item["fuel"], "2025-06-01", kind,
                                                                          unit=doc["unit"], **amounts)])
    response = run(store)
    got = category(response)
    assert got["total_co2e"] == recorded["total_co2e"]  # bit for bit
    lines = [ln for ln in response["calculation_lines"] if ln["counts_toward"] == "fugitive"]
    assert sum(ln["results"]["total_co2e_t"] for ln in lines) == pytest.approx(recorded["total_co2e"], rel=1e-12)
    for ln in lines:
        assert ln["trace"] is not None and ln["trace"]["result"]["recomputed"] == ln["results"]["total_co2e_t"]


# --- the reference data ----------------------------------------------------------------------------------------------
def test_every_blend_composition_adds_up_and_a_blend_not_in_the_hub_has_a_component_to_enter() -> None:
    for row in REF.data["gwp_refrigerant_blends"]:
        assert fugitive.parse_composition(row["composition"]), row["ashrae"]
    for row in fugitive._not_in_hub()["blends"]:
        blend = fugitive.blend_of(row["ashrae"], REF)
        assert blend is not None and not blend.in_hub
        # if every component had a Table 11 GWP the line would be worked without any decision, beside a category that
        # did not count it: each such blend must hold a component a reviewer enters
        assert any(fugitive._component_gwp(c.name, REF, "AR5") is None for c in blend.components), row["ashrae"]
    assert fugitive.blend_of("R-404A", REF).components[0] == fugitive.Component("HFC-125", 0.44, 44.0)  # type: ignore[union-attr]
    assert fugitive.blend_of("HFC-134a", REF) is None
    assert fugitive.parse_composition("50% HFC-32 , 40% HFC-125") == ()
    assert fugitive.parse_composition("half HFC-32") == ()


def test_a_company_mass_that_is_not_a_mass_asks_instead_of_guessing() -> None:
    response = run(r404a_store(), reported_activity={R404A_KC: {"quantity": 129, "unit": "gal"}})
    assert line_of(response, R404A_KC)["company"] is None
    assert any(n["kind"] == "company_activity" and "not a mass" in n["message"] for n in response["needs_input"])
    kg = run(r404a_store(), reported_activity={R404A_KC: {"quantity": 58.5, "unit": "kg"}})
    trace = line_of(kg, R404A_KC)["trace"]
    assert trace["result"]["company"] == pytest.approx(0.0585 * 3943, rel=1e-12)
    assert "difference" not in block(trace, "emitted_t")["recomputed"]["terms"][0]["operand"]  # lb against kg


# --- review fixes: one refrigerant per line, zero terms, lines with no records, export, which line wins ---------------
def two_refrigerants_on_one_line() -> tuple[FakeStore, dict[str, dict]]:
    store = r404a_store()
    store.add_document("R410", "CT-S1-REFRSVC", [rec("R-410A", "2025-04-09", added=40)])
    store.add_document("STL", "CT-S1-REFRSVC", [rec("R-404A", "2025-06-01", added=10, plant="St Louis Plant")])
    return store, {"R410": {"placements": [{"from": R410A_KC, "to": R404A_KC}]}}


def run_with(store: FakeStore, document_decisions: dict | None, line_decisions: list[dict] | None = None,
             **recalculation: Any) -> dict:
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [KC, STL], "recalculation": recalculation}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, _own, document_decisions, with_traces=True, line_decisions=line_decisions)


def test_a_line_holding_two_refrigerants_is_blocked_and_the_category_counts_each_on_its_own_gwp() -> None:
    store, moved = two_refrigerants_on_one_line()
    apart = run(store)
    response = run_with(store, moved, reported_lines={R404A_KC: 300.0})
    line = line_of(response, R404A_KC)
    assert "mixed_refrigerants" in line["flags"] and line["smb"]["gases"] == ["R-404A", "R-410A"]
    trace = line["trace"]
    assert trace["state"] == "blocked" and trace["steps"] == []
    assert trace["blocking"][0]["message"] == ("This line mixes refrigerants (R-404A, R-410A): move the R-410A records "
                                               "to their own line.")
    assert all(i["decidable"] is False and "mixes refrigerants" in i["why_not"] for i in trace["inputs"].values())
    assert [r["label"].split(" · ")[0] for r in trace["inputs"]["P_S"]["rows"]] == ["R-404A"] * 4 + ["R-410A"]
    # never one balance under one GWP: each refrigerant's mass and CO2e as the category counts them, and no verdict
    assert line["results"]["mass_t"] == {"R-404A": pytest.approx(99 * T_PER_LB, rel=1e-12),
                                         "R-410A": pytest.approx(40 * T_PER_LB, rel=1e-12)}
    assert line["results"]["gas_co2e_t"]["R-410A"] == pytest.approx(40 * T_PER_LB * 1924, rel=1e-12)
    assert line["reported_total_co2e_t"] == 300.0 and line["difference_t"] is None
    assert line["status"] == "not_reported" and line["company"] is None
    assert category(response) == category(apart)  # the category is exactly as with the records on their own lines
    jsonschema.validate(trace, SCHEMA)


def test_a_decision_on_a_mixed_line_is_refused_and_one_on_another_fugitive_line_still_applies() -> None:
    store, moved = two_refrigerants_on_one_line()
    before = run_with(store, moved)
    stl_key = "s1:fugitive:r-404a:fac-stl2"
    decided = [event(R404A_KC, "input|P_S|recomputed", "edited", 120, "lb"),
               event(stl_key, "input|P_S|recomputed", "edited", 20, "lb")]
    response = run_with(store, moved, decided)
    mixed = line_of(response, R404A_KC)
    assert [(n["id"], n["reason"]) for n in mixed["decisions"]["not_applied"]] == [("P_S", "line_mixes_runs")]
    assert "move the R-410A records" in mixed["decisions"]["not_applied"][0]["message"]
    stl = line_of(response, stl_key)
    assert stl["results"]["total_co2e_t"] == pytest.approx(20 * T_PER_LB * 3943, rel=1e-12)
    assert category(response)["total_co2e"] - category(before)["total_co2e"] == pytest.approx(
        10 * T_PER_LB * 3943, rel=1e-9)


def test_a_balance_term_may_be_decided_as_zero_but_never_below() -> None:
    zero = run(r404a_store(), line_decisions=[event(R404A_KC, "input|C_N|recomputed", "edited", 0, "lb")])
    line = line_of(zero, R404A_KC)
    assert [a["id"] for a in line["decisions"]["applied"]] == ["C_N"]
    assert line["step1"]["total"]["quantity"] == 139.0  # 42 - 0 + 90 + 55 - 48
    assert category(zero)["total_co2e"] == pytest.approx(139 * T_PER_LB * 3943, rel=1e-12)
    below = run(r404a_store(), line_decisions=[event(R404A_KC, "input|R_D|recomputed", "edited", -1, "lb")])
    assert line_of(below, R404A_KC)["decisions"]["not_applied"][0]["reason"] == "invalid_value"
    gwp_zero = run(r448a_store(), line_decisions=[gwp_event(R448A_KC, "HFO-1234yf", 0)])
    assert line_of(gwp_zero, R448A_KC)["decisions"]["not_applied"][0]["reason"] == "invalid_value"
    trace = line_of(run(r404a_store()), R404A_KC)["trace"]
    actor = Actor(user_id="u1", login="rev@example.com", name="Rev Iewer")
    now = __import__("datetime").datetime.now()
    made = decide_input({}, trace["inputs"]["C_N"], None, "recomputed", "edit", value=0, unit="lb", reason="none new",
                        actor=actor, now=now)
    assert made["decision"]["value"] == 0
    with pytest.raises(ReviewInvalid):
        decide_input({}, trace["inputs"]["C_N"], None, "recomputed", "edit", value=-1, unit="lb", reason="x",
                     actor=actor, now=now)


def test_a_refrigerant_line_with_company_figures_and_no_record_resolves() -> None:
    key = "s1:fugitive:r-404a:fac-stl2"
    response = run(r404a_store(), reported_lines={key: 50.0})
    line = line_of(response, key)
    assert "no_evidence" in line["flags"] and line["level2"] == "R-404A"
    assert line["results"]["total_co2e_t"] == 0.0 and line["reported_total_co2e_t"] == 50.0
    assert line["status"] == "above"
    assert not any(u["key"] == key for u in response["calculation_line_inputs"]["unknown_line_keys"])
    assert category(response)["total_co2e"] == 177.06295677609  # nothing added
    decided = run(r404a_store(), reported_lines={key: 50.0},
                  line_decisions=[event(R404A_KC, "input|P_S|recomputed", "edited", 120, "lb")])
    assert line_of(decided, R404A_KC)["decisions"]["applied"]  # the empty line keeps the lines adding up
    assert category(decided)["total_co2e"] == pytest.approx(230.71839822339, rel=1e-12)
    for bad in ("s1:fugitive:hcfc-22:fac-stl2", "s1:fugitive:r-404a:fac-nowhere", "s1:fugitive:nothing:fac-stl2"):
        assert any(u["key"] == bad for u in run(r404a_store(), reported_lines={bad: 1.0})[
            "calculation_line_inputs"]["unknown_line_keys"]), bad


def test_the_working_sheet_marks_a_refrigerant_awaiting_component_gwps_as_not_counted() -> None:
    from backend.app.services.workpaper_export_service import _source_rows

    rows = _source_rows(run(r448a_store()), {})
    mine = [r for r in rows if r[1] and "R-448A" in str(r[1])]
    assert len(mine) == 1
    assert mine[0][4] == 10 and mine[0][7] == "not counted: component GWPs awaiting review"
    counted = _source_rows(run(r448a_store(), line_decisions=[gwp_event(R448A_KC, n, v)
                                                               for n, v in zip(HFO, (4, 6), strict=True)]), {})
    assert [r[7] for r in counted if r[1] and "R-448A" in str(r[1])] == [10]


def test_the_line_decided_first_keeps_the_blend_gwp_whatever_its_key() -> None:
    store = r448a_store("Kansas City Plant", "St Louis Plant")
    early = [gwp_event(R448A_STL, n, v) for n, v in zip(HFO, (1, 6), strict=True)]
    for e in early:
        e["record"]["decision"]["at"] = "2026-11-20T09:00:00Z"
    later = [gwp_event(R448A_KC, n, v) for n, v in zip(HFO, (4, 6), strict=True)]
    response = run(store, line_decisions=[*later, *early])
    assert line_of(response, R448A_STL)["results"]["total_co2e_t"] > 0
    refused = line_of(response, R448A_KC)["decisions"]["not_applied"]
    assert {r["reason"] for r in refused} == {"gwp_differs_between_lines"}
    assert "St Louis Plant was decided first" in refused[0]["message"]


@pytest.mark.parametrize("phantom", ["s1:fugitive:r404a:fac-kc01", "s1:fugitive:r-404a-old:fac-kc01"])
def test_a_key_that_only_mentions_a_refrigerant_is_never_a_second_line_of_it(phantom: str) -> None:
    response = run(r404a_store(), reported_lines={phantom: 99.0, R404A_KC: 180.0},
                   reported_activity={phantom: {"quantity": 1, "unit": "lb"}, R404A_KC: {"quantity": 129, "unit": "lb"}},
                   line_decisions=[event(phantom, "input|P_S|recomputed", "edited", 500, "lb")])
    assert not any(ln["key"] == phantom for ln in response["calculation_lines"])
    unknown = response["calculation_line_inputs"]["unknown_line_keys"]
    assert {(u["setting"], u["key"]) for u in unknown} >= {("reported_lines", phantom), ("reported_activity", phantom)}
    real = line_of(response, R404A_KC)  # the real line keeps the company's figures
    assert real["reported_total_co2e_t"] == 180.0
    assert real["company"]["activity"] == {"quantity": 129.0, "unit": "lb"}
    assert category(response)["total_co2e"] == 177.06295677609  # the decision found no line: nothing added
    assert [o["line_key"] for o in response["calculation_line_decisions"]["orphaned"]] == [phantom]


def test_first_decided_is_compared_in_utc() -> None:
    store = r448a_store("Kansas City Plant", "St Louis Plant")
    kc = [gwp_event(R448A_KC, n, v) for n, v in zip(HFO, (4, 6), strict=True)]
    stl = [gwp_event(R448A_STL, n, v) for n, v in zip(HFO, (1, 6), strict=True)]
    for e in kc:  # 05:00 UTC: the earlier, though it sorts later as text
        e["record"]["decision"]["at"] = "2026-11-20T10:00:00+05:00"
    for e in stl:
        e["record"]["decision"]["at"] = "2026-11-20T06:00:00Z"
    response = run(store, line_decisions=[*stl, *kc])
    assert line_of(response, R448A_KC)["results"]["total_co2e_t"] > 0
    refused = line_of(response, R448A_STL)["decisions"]["not_applied"]
    assert {r["reason"] for r in refused} == {"gwp_differs_between_lines"}
    assert "Kansas City Plant was decided first" in refused[0]["message"]
