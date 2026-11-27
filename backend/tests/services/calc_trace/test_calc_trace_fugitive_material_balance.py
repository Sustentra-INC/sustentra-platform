"""C6: fugitive emissions by EPA's material balance (the terms as ruled in Q8).

The plan's example, HFC-134a:

    E = (I_B − I_E) + (P − S) + (C_B − C_E) = (500 − 450) + (200 − 50) + (1,000 − 1,050) = 150 lb
    150 lb × 0.45359237 kg/lb / 1,000 = 0.0680388555 t, × 1,300 (EPA Table 11, AR5) = 88.45051215 t CO2e

The lb to metric ton factor is the one the fugitive category has always used (exact, as in C4 and C5); the plan's
0.0680390 t and 88.4507 t were worked with 1/2204.62 and differ from these in the fifth significant figure. No record
gives the six terms: each is entered by a reviewer (0 allowed), and until all six are the method is blocked and the
line counts its simplified material balance, with its decisions.
"""

from __future__ import annotations

import math
from typing import Any

import jsonschema
import pytest

from backend.app.services.calc_trace import decisions, fugitive
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, line_of
from backend.tests.services.calc_trace.test_calc_trace_fugitive import SCHEMA, T_PER_LB, category, rec, run
from backend.tests.services.test_engagement_recalculation_service import FakeStore

KEY = "s1:fugitive:hfc-134a:fac-kc01"
PLAN = {"I_B": 500, "I_E": 450, "P": 200, "S": 50, "C_B": 1000, "C_E": 1050}


def store() -> FakeStore:
    """One HFC-134a service record: 10 lb added (the simplified balance: 10 lb)."""

    out = FakeStore()
    out.add_document("CHILLER-LOG", "CT-S1-REFRSVC", [rec("HFC-134a", "2025-04-01", added=10)])
    return out


def material() -> dict[str, Any]:
    return event(KEY, "choice|method|", "edited", fugitive.MATERIAL_BALANCE)


def terms(values: dict[str, Any], unit: str | None = "lb") -> list[dict[str, Any]]:
    return [event(KEY, f"input|{t}|recomputed", "edited", v, unit) for t, v in values.items()]


def value(trace: dict, block_id: str) -> Any:
    return block(trace, block_id)["recomputed"]["result"]["value"]


# --- the plan's numbers ------------------------------------------------------------------------------------------------
def test_hfc134a_material_balance_is_the_plans_example_exactly() -> None:
    response = run(store(), line_decisions=[material(), *terms(PLAN)])
    line = line_of(response, KEY)
    trace = line["trace"]
    assert trace["state"] == "complete", trace["blocking"]
    # Step 1: the six terms, as entered
    assert [value(trace, f"term.{t}") for t in fugitive.MB_TERMS] == [500, 450, 200, 50, 1000, 1050]
    assert [block(trace, f"term.{t}").get("warning") for t in fugitive.MB_TERMS] == [None] * 6
    # Step 2: (I_B − I_E) + (P − S) + (C_B − C_E), then metric tons
    emitted = block(trace, "emitted")["recomputed"]
    assert [(t["op"], t["operand"]["column"], t["operand"]["value"]) for t in emitted["terms"]] == [
        (None, "I_B", 500), ("−", "I_E", 450), ("+", "P", 200), ("−", "S", 50), ("+", "C_B", 1000), ("−", "C_E", 1050)]
    assert emitted["result"]["value"] == 150.0
    to_t = block(trace, "emitted_t")["recomputed"]
    assert to_t["terms"][1]["operand"]["value"] == pytest.approx(0.00045359237, rel=1e-15)  # exact kg per lb
    assert to_t["result"]["value"] == pytest.approx(0.0680388555, rel=1e-15)
    # Step 3: × the HFC-134a GWP (EPA Table 11, AR5)
    assert block(trace, "co2e")["recomputed"]["terms"][1]["operand"]["value"] == 1300
    co2e = value(trace, "co2e")
    assert co2e == pytest.approx(150 * 0.45359237 / 1000 * 1300, rel=1e-15)
    assert co2e == pytest.approx(88.45051215, rel=1e-12) and round(co2e, 2) == 88.45
    # the line, its trace and the category say the same number; the route says material balance
    assert line["results"]["total_co2e_t"] == co2e == trace["result"]["recomputed"]
    assert line["results"]["mass_t"] == {"HFC-134a": pytest.approx(0.0680388555, rel=1e-15)}
    assert category(response)["total_co2e"] == pytest.approx(co2e, rel=1e-12)
    assert line["method"]["route"] == fugitive.MB_ROUTE
    assert line["step1"]["total"]["quantity"] == 150.0
    method = trace["choices"][0]
    assert method["chosen"] == fugitive.MATERIAL_BALANCE and method["chosen_by"] == "reviewer"
    assert next(s for s in trace["steps"] if s["id"] == "emitted")["note"].startswith(fugitive.MB_EQUATION)
    assert "reviewer_decisions_applied" in line["flags"]
    jsonschema.validate(trace, SCHEMA)


def test_a_negative_material_balance_is_kept_and_flagged() -> None:
    drawn_down = {"I_B": 100, "I_E": 300, "P": 0, "S": 0, "C_B": 50, "C_E": 50}  # −200 lb
    response = run(store(), line_decisions=[material(), *terms(drawn_down)])
    line = line_of(response, KEY)
    trace = line["trace"]
    assert trace["state"] == "complete"
    assert value(trace, "emitted") == -200.0
    expected = -200 * T_PER_LB * 1300
    assert line["results"]["total_co2e_t"] == pytest.approx(expected, rel=1e-15)
    assert category(response)["total_co2e"] == pytest.approx(expected, rel=1e-12)
    assert fugitive.NEGATIVE_FLAG in trace["flags"] and fugitive.NEGATIVE_FLAG in line["flags"]
    assert block(trace, "emitted")["warning"] == fugitive.MB_NEGATIVE


# --- not reported, blocked, held --------------------------------------------------------------------------------------
def test_a_term_not_reported_blocks_the_method_and_the_line_keeps_its_balance_with_its_decisions() -> None:
    plain = run(store())
    p_s = event(KEY, "input|P_S|recomputed", "edited", 20, "lb")
    four = {k: PLAN[k] for k in ("I_B", "I_E", "P", "S")}
    response = run(store(), line_decisions=[p_s, material(), *terms(four)])
    line = line_of(response, KEY)
    trace = line["trace"]
    assert trace["state"] == "blocked" and trace["result"]["recomputed"] is None
    assert trace["blocking"][0]["input_id"] == "C_B"
    assert trace["blocking"][0]["message"].startswith("material balance terms. Not reported: C_B, C_E.")
    assert block(trace, "term.C_B")["warning"] == block(trace, "term.C_E")["warning"] == fugitive.MB_NOT_REPORTED
    assert block(trace, "term.I_B").get("warning") is None
    assert value(trace, "term.C_B") is None and value(trace, "emitted") is None
    # the line counts the simplified balance with the reviewer's P_S (20 lb), not the material balance
    balance = 20 * T_PER_LB * 1300
    assert line["results"]["total_co2e_t"] == pytest.approx(balance, rel=1e-12)
    assert category(response)["total_co2e"] == pytest.approx(balance, rel=1e-12)
    assert category(plain)["total_co2e"] == pytest.approx(10 * T_PER_LB * 1300, rel=1e-12)
    assert line["method"]["route"] == fugitive.ROUTE
    applied = {a["id"]: a for a in line["decisions"]["applied"]}
    assert applied["method"]["uses"] == ("Material balance is chosen but blocked (awaiting material balance terms). "
                                         f"Counting the simplified material balance ({balance:,.2f} t) until then.")
    assert "uses" not in applied["P_S"]
    assert applied["I_B"]["uses"] == "held: the material balance awaits material balance terms"
    jsonschema.validate(trace, SCHEMA)


def test_a_blocked_material_balance_with_no_other_decision_leaves_the_line_as_calculated() -> None:
    plain = run(store())
    after = run(store(), line_decisions=[material()])
    assert after["categories"] == plain["categories"]
    assert line_of(after, KEY)["results"] == line_of(plain, KEY)["results"]
    trace = line_of(after, KEY)["trace"]
    assert trace["blocking"][0]["message"].startswith("material balance terms. Not reported: I_B, I_E, P, S, C_B, C_E.")


def test_zero_is_allowed_for_every_term() -> None:
    assert all(fugitive.zero_allowed(t) for t in fugitive.MB_TERMS)
    only_bought = {"I_B": 0, "I_E": 0, "P": 25, "S": 0, "C_B": 0, "C_E": 0}
    line = line_of(run(store(), line_decisions=[material(), *terms(only_bought)]), KEY)
    assert line["trace"]["state"] == "complete"
    assert line["results"]["total_co2e_t"] == pytest.approx(25 * T_PER_LB * 1300, rel=1e-15)
    assert line["decisions"]["not_applied"] == []


def test_terms_entered_while_the_simplified_balance_is_used_are_held_and_change_nothing() -> None:
    plain = run(store())
    held = run(store(), line_decisions=terms(PLAN))
    assert held["categories"] == plain["categories"]
    assert line_of(held, KEY)["results"] == line_of(plain, KEY)["results"]
    line = line_of(held, KEY)
    assert {a["uses"] for a in line["decisions"]["applied"]} == {"held: only the material balance uses it"}
    assert line["trace"]["inputs"]["I_B"]["recomputed"]["value"] == 500  # shown as decided


def test_a_balance_or_screening_decision_is_held_under_the_material_balance() -> None:
    p_s = event(KEY, "input|P_S|recomputed", "edited", 60, "lb")
    x = event(KEY, "input|x|recomputed", "edited", 10, "%")
    line = line_of(run(store(), line_decisions=[material(), *terms(PLAN), p_s, x]), KEY)
    assert round(line["results"]["total_co2e_t"], 2) == 88.45
    applied = {a["id"]: a.get("uses") for a in line["decisions"]["applied"]}
    assert applied["P_S"] == "held: the material balance does not use it"
    assert applied["x"] == "held: the material balance does not use it"
    # and a material balance term is held under the screening
    assert fugitive.used_by("I_B", fugitive.SCREENING) is False and fugitive.users("C_E") == "the material balance"


def test_the_company_terms_are_compared_term_by_term() -> None:
    company = [event(KEY, f"input|{t}|company", "edited", v, "lb")
               for t, v in {**PLAN, "S": 40}.items()]  # the company: 160 lb
    line = line_of(run(store(), line_decisions=[material(), *terms(PLAN), *company]), KEY)
    trace = line["trace"]
    assert trace["inputs"]["S"]["company"]["value"] == 40 and trace["inputs"]["S"]["difference"] == 10
    emitted = block(trace, "emitted")
    assert emitted["company"]["result"]["value"] == 160.0
    assert emitted["recomputed"]["result"]["difference"] == -10.0
    assert round(line["results"]["total_co2e_t"], 2) == 88.45  # shown, never an operand


# --- availability and hostile values ----------------------------------------------------------------------------------
def test_the_terms_are_decidable_awaiting_and_unused_with_no_decision() -> None:
    plain = run(store())
    assert run(store(), line_decisions=[]) == plain
    trace = line_of(plain, KEY)["trace"]
    method = trace["choices"][0]
    option = next(o for o in method["options"] if o["id"] == fugitive.MATERIAL_BALANCE)
    assert option["available"] is True and option["equation"] == fugitive.MB_EQUATION
    assert option["required_inputs"] == list(fugitive.MB_TERMS) and method["chosen"] == "smb"
    for t in fugitive.MB_TERMS:
        item = trace["inputs"][t]
        assert item["decidable"] is True and decisions.not_decidable(t) is None
        assert item["recomputed"]["value"] is None and item["recomputed"]["status"] == "awaiting_review"
        assert item["kind"] == "reviewer_entered"
    shown = {t["operand"].get("input_id") for s in trace["steps"] for b in s["blocks"] for t in b["recomputed"]["terms"]}
    assert not shown & set(fugitive.MB_TERMS)
    jsonschema.validate(trace, SCHEMA)


def test_a_mixed_line_offers_no_material_balance() -> None:
    method = fugitive._mixed_trace({"key": "k", "smb": {"gas": "R-410A", "gases": ["R-410A", "R-404A"],
                                                        "unit": "lb"}, "step1": {"rows": []}, "flags": []}).choices[0]
    option = next(o for o in method.options if o.id == fugitive.MATERIAL_BALANCE)
    assert option.available is False and "mixes refrigerants" in (option.why_unavailable or "")


@pytest.mark.parametrize(("number", "unit"), [
    (-5, "lb"), (float("nan"), "lb"), (math.inf, "lb"), ("500", "lb"), (True, "lb"), (1e16, "lb"), (500, "kg"),
    (500, "gallons")])
def test_a_term_that_is_not_a_plausible_mass_never_reaches_the_math(number: Any, unit: str) -> None:
    bad = event(KEY, "input|I_B|recomputed", "edited", number, unit)
    rest = {k: v for k, v in PLAN.items() if k != "I_B"}
    line = line_of(run(store(), line_decisions=[material(), *terms(rest), bad]), KEY)
    assert [n["id"] for n in line["decisions"]["not_applied"]] == ["I_B"]
    assert line["trace"]["state"] == "blocked" and line["trace"]["blocking"][0]["input_id"] == "I_B"
    assert line["results"]["total_co2e_t"] == pytest.approx(10 * T_PER_LB * 1300, rel=1e-12)


def test_each_entered_input_says_where_its_value_is_found() -> None:
    """``TraceInput.source_hint``: the entry form asks "Its source (<hint>)"; the safety data sheet is only for a
    component GWP."""

    trace = line_of(run(store()), KEY)["trace"]
    hints = {t: trace["inputs"][t]["source_hint"] for t in fugitive.MB_TERMS}
    assert hints == {"I_B": "inventory count", "I_E": "inventory count", "P": "purchase invoice",
                     "S": "sales, return or disposal record", "C_B": "equipment register (full charge)",
                     "C_E": "equipment register (full charge)"}
    assert trace["inputs"]["C_B"]["label"] == "Full charge of equipment at the start of the year"
    assert trace["inputs"]["C_E"]["label"] == "Full charge of equipment at the end of the year"
    units = {i: v["source_hint"] for i, v in trace["inputs"].items() if i.startswith((fugitive.UNIT_C, fugitive.UNIT_T))}
    assert set(units.values()) == {"equipment nameplate or register", "equipment register (months in use)"}
    from backend.tests.services.calc_trace.test_calc_trace_fugitive import R448A_KC, r448a_store

    r448a = line_of(run(r448a_store()), R448A_KC)["trace"]["inputs"]
    assert {v["source_hint"] for i, v in r448a.items() if i.startswith(fugitive.COMPONENT_GWP)} == \
        {"the safety data sheet, say"}
    from backend.tests.services.calc_trace.test_calc_trace_steam import KEY as STEAM, kent_store
    from backend.tests.services.calc_trace.test_calc_trace_steam import run as run_steam

    steam = line_of(run_steam(kent_store()), STEAM)["trace"]["inputs"]
    assert steam["mass"]["source_hint"] == "supplier statement"
    assert {steam[i]["source_hint"] for i in ("net_enthalpy", "pressure_psig", "condensate_f")} == \
        {"supplier statement or steam conditions"}
    assert steam["efficiency"]["source_hint"] == "supplier or boiler documentation"
    supplier = {v["source_hint"] for v in steam.values() if v["kind"] == "reviewer_entered" and v["symbol"] == "EF"}
    assert supplier == {"supplier emission factor statement"}
    jsonschema.validate(line_of(run_steam(kent_store()), STEAM)["trace"], SCHEMA)


def test_a_decision_for_another_line_never_touches_this_one() -> None:
    other = "s1:fugitive:hfc-134a:fac-stl2"
    stray = [event(other, "choice|method|", "edited", fugitive.MATERIAL_BALANCE),
             *[event(other, f"input|{t}|recomputed", "edited", v, "lb") for t, v in PLAN.items()]]
    plain = run(store())
    after = run(store(), line_decisions=stray)
    assert after["categories"] == plain["categories"]
    assert line_of(after, KEY)["results"] == line_of(plain, KEY)["results"]
