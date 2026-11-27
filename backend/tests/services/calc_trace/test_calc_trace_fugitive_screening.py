"""C5: fugitive emissions by EPA's screening method, for refrigeration and A/C and for fire suppression.

The plan's example (Claire's board 13 to 15), R-410A residential and commercial A/C:

    Σ (C × T) = 132 × 1.00 + 16 × 1.00 + 8 × 0.50 = 152.0 lb, × x 10%      = 15.2 lb
    C_D 8 lb × y 80% × (1 − z 80%)                                        =  1.28 lb
    emitted 16.48 lb, × 0.45359237 kg/lb / 1,000 = 0.0074752022576 t, × 1,924 (EPA Table 12) = 14.3822891 t CO2e

The plan's 0.0074752 t and 14.3823 t are these to its precision (the lb to metric ton factor is the one the fugitive
category always used, as in C4). The method is the simplified material balance until a reviewer picks screening; the
equipment type gives EPA's factors (EPA Table 1, December 2023 edition), each shown as a default until confirmed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.services.calc_trace import decisions, fugitive
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, line_of
from backend.tests.services.calc_trace.test_calc_trace_fugitive import SCHEMA, T_PER_LB, category, rec, run
from backend.tests.services.test_engagement_recalculation_service import FakeStore

R410A_KC = "s1:fugitive:r-410a:fac-kc01"
FM200_KC = "s1:fugitive:hfc-227ea:fac-kc01"
FACTORS_FILE = Path(__file__).parents[4] / "reference-data" / "emission-factors" / "epa_fugitive_screening_factors.json"


def unit(record: dict[str, tuple], equipment: str | None) -> dict[str, tuple]:
    if equipment is None:
        record.pop("equipment_id", None)
    else:
        record["equipment_id"] = (equipment, None)
    return record


def office_store() -> FakeStore:
    """Three rooftop units: two in use all year (132 and 16 lb), one retired (8 lb, 6 lb recovered)."""

    store = FakeStore()
    store.add_document("RTU-LOG", "CT-S1-REFRSVC", [
        unit(rec("R-410A", "2025-03-01", added=4, capacity=132), "RTU-1"),
        unit(rec("R-410A", "2025-05-01", added=2, capacity=16), "RTU-2"),
        unit(rec("R-410A", "2025-07-01", "disposal", recovered=6, capacity=8), "RTU-3")])
    return store


def choose(key: str, choice: str, option: str) -> dict[str, Any]:
    return event(key, f"choice|{choice}|", "edited", option)


def screening(key: str = R410A_KC, kind: str | None = "residential_commercial_ac") -> list[dict[str, Any]]:
    out = [choose(key, "method", "screening")]
    return out + ([choose(key, fugitive.EQUIPMENT_CHOICE, kind)] if kind else [])


def time_id(trace: dict, name: str) -> str:
    return next(i for i, item in trace["inputs"].items() if item["label"] == f"{name} time in use")


def capacity_id(trace: dict, name: str) -> str:
    return next(i for i, item in trace["inputs"].items() if item["label"] == f"{name} capacity")


def half_year(key: str = R410A_KC, name: str = "RTU-3") -> dict[str, Any]:
    trace = line_of(run(office_store()), key)["trace"]
    return event(key, f"input|{time_id(trace, name)}|recomputed", "edited", 0.5)


def value(trace: dict, block_id: str) -> Any:
    return block(trace, block_id)["recomputed"]["result"]["value"]


# --- the plan's numbers ------------------------------------------------------------------------------------------------
def test_r410a_screening_is_the_plans_example_exactly() -> None:
    plain = run(office_store())
    response = run(office_store(), line_decisions=[*screening(), half_year()])
    line = line_of(response, R410A_KC)
    trace = line["trace"]
    assert trace["state"] == "complete", trace["blocking"]
    # Step 1: each unit's C × T, then Σ (C × T)
    units = [b for b in next(s for s in trace["steps"] if s["id"] == "inputs")["blocks"] if b["id"].startswith("unit.")]
    assert [(b["label"], [t["operand"]["value"] for t in b["recomputed"]["terms"]], b["recomputed"]["result"]["value"])
            for b in units] == [("RTU-1 · equipment in use", [132, 1.0], 132.0),
                                ("RTU-2 · equipment in use", [16, 1.0], 16.0),
                                ("RTU-3 · equipment in use", [8, 0.5], 4.0)]
    assert value(trace, "in_use") == 152.0
    assert value(trace, "term.C_D") == 8.0
    assert [value(trace, f"factor.{f}") for f in ("x", "y", "z")] == [0.10, 0.80, 0.80]
    assert "factor.k" not in {b["id"] for s in trace["steps"] for b in s["blocks"]}  # no new equipment: no k
    # Step 2: operation, disposal, emitted, metric tons
    assert value(trace, "operation") == pytest.approx(15.2, rel=1e-15)
    assert value(trace, "not_recovered") == pytest.approx(0.2, rel=1e-15)
    assert value(trace, "disposal") == pytest.approx(1.28, rel=1e-15)
    assert value(trace, "emitted") == pytest.approx(16.48, rel=1e-15)
    assert value(trace, "emitted_t") == pytest.approx(16.48 * T_PER_LB, rel=1e-15)
    assert round(value(trace, "emitted_t"), 7) == 0.0074752
    # Step 3: the Table 12 GWP counts; the components (1,923.5) are shown
    assert block(trace, "co2e")["recomputed"]["terms"][1]["operand"]["value"] == 1924
    co2e = value(trace, "co2e")
    assert co2e == pytest.approx(16.48 * T_PER_LB * 1924, rel=1e-15)
    assert round(co2e, 4) == 14.3823
    assert round(value(trace, "components.sum"), 4) == 14.3786
    # the line, its trace and the category say the same number; the route says screening
    assert line["results"]["total_co2e_t"] == co2e == trace["result"]["recomputed"]
    assert line["results"]["mass_t"] == {"R-410A": pytest.approx(16.48 * T_PER_LB, rel=1e-15)}
    assert category(response)["total_co2e"] == pytest.approx(co2e, rel=1e-12)
    assert line["method"]["route"] == fugitive.SCREENING_ROUTE
    assert line["step1"]["total"]["quantity"] == pytest.approx(16.48, rel=1e-15)
    # without the decisions the line is the simplified material balance: P_S 6 + C_D 8 − R_D 6 = 8 lb
    smb = line_of(plain, R410A_KC)
    assert smb["step1"]["total"]["quantity"] == 8.0 and smb["method"]["route"] == fugitive.ROUTE
    assert category(plain)["total_co2e"] == pytest.approx(8 * T_PER_LB * 1924, rel=1e-12)
    method = trace["choices"][0]
    assert method["chosen"] == "screening" and method["chosen_by"] == "reviewer"
    assert "reviewer_decisions_applied" in line["flags"]
    jsonschema.validate(trace, SCHEMA)


def test_every_default_is_shown_as_an_assumption_until_a_reviewer_confirms_it() -> None:
    trace = line_of(run(office_store(), line_decisions=screening()), R410A_KC)["trace"]
    tags = {b["id"]: b.get("assumption") for s in trace["steps"] for b in s["blocks"]}
    assert tags["factor.x"] == ("Default: 10% (EPA Table 1, Residential and commercial A/C including heat pumps) · "
                                "not confirmed")
    assert tags["factor.y"].startswith("Default: 80% (EPA Table 1") and tags["factor.z"].startswith("Default: 80%")
    assert all(t.startswith("Default: 1.00 (in use the whole reporting period) · not confirmed")
               for k, t in tags.items() if k.startswith("unit."))
    x = trace["inputs"]["x"]["recomputed"]
    assert x["value"] == 10 and x["unit"] == "%" and x["status"] == "reference"
    assert x["source"]["table"] == "EPA Table 1" and "page 11" in x["source"]["citation"]
    # confirmed (edited with the same value): no tag, the decided value is the operand
    confirm = event(R410A_KC, "input|x|recomputed", "edited", 10, "%")
    trace = line_of(run(office_store(), line_decisions=[*screening(), confirm, half_year()]), R410A_KC)["trace"]
    assert block(trace, "factor.x").get("assumption") is None
    assert trace["inputs"]["x"]["recomputed"]["status"] == "edited"
    assert round(trace["result"]["recomputed"], 4) == 14.3823


def test_a_decided_factor_moves_the_total() -> None:
    leak = event(R410A_KC, "input|x|recomputed", "edited", 15, "%")
    line = line_of(run(office_store(), line_decisions=[*screening(), half_year(), leak]), R410A_KC)
    emitted = 152 * 0.15 + 1.28
    assert line["trace"]["result"]["recomputed"] == pytest.approx(emitted * T_PER_LB * 1924, rel=1e-12)


# --- fire suppression ---------------------------------------------------------------------------------------------------
def fm200_store() -> FakeStore:
    store = FakeStore()
    store.add_document("FS-LOG", "CT-S1-REFRSVC", [unit(rec("FM-200", "2025-06-01", added=3, capacity=200), "FS-1")])
    return store


@pytest.mark.parametrize(("kind", "rate"), [("fire_fixed", 0.025), ("fire_portable", 0.035)])
def test_hfc227ea_fire_suppression_is_capacity_times_epas_rate(kind: str, rate: float) -> None:
    response = run(fm200_store(), line_decisions=screening(FM200_KC, kind))
    line = line_of(response, FM200_KC)
    trace = line["trace"]
    assert trace["state"] == "complete"
    assert value(trace, "factor.x") == rate
    assert value(trace, "operation") == pytest.approx(200 * rate, rel=1e-15)
    blocks = {b["id"] for s in trace["steps"] for b in s["blocks"]}
    assert not blocks & {"factor.k", "factor.y", "factor.z", "installation", "disposal"}
    expected = 200 * rate * T_PER_LB * 3350  # HFC-227ea, EPA Table 11 (AR5)
    assert trace["result"]["recomputed"] == pytest.approx(expected, rel=1e-12)
    assert block(trace, "co2e")["recomputed"]["terms"][1]["operand"]["value"] == 3350
    assert line["method"]["route"] == fugitive.FIRE_ROUTE
    assert category(response)["total_co2e"] == pytest.approx(expected, rel=1e-12)
    assert block(trace, "factor.x")["label"] == "Annual emission rate · x"
    jsonschema.validate(trace, SCHEMA)


# --- availability, blocking and holding -------------------------------------------------------------------------------
def test_screening_without_an_equipment_type_is_blocked_and_the_line_keeps_its_balance() -> None:
    plain = run(office_store())
    response = run(office_store(), line_decisions=screening(kind=None))
    line = line_of(response, R410A_KC)
    trace = line["trace"]
    assert trace["state"] == "blocked"
    assert trace["blocking"][0]["input_id"] == fugitive.EQUIPMENT_CHOICE
    assert trace["blocking"][0]["message"].startswith("the equipment type.")
    assert trace["result"]["recomputed"] is None
    assert response["categories"] == plain["categories"]
    assert line["results"] == line_of(plain, R410A_KC)["results"]
    held = next(a for a in line["decisions"]["applied"] if a["id"] == "method")
    assert held["uses"].startswith("held: the screening method awaits the equipment type")


def test_factors_entered_without_an_equipment_type_are_used() -> None:
    entered = [event(R410A_KC, f"input|{f}|recomputed", "edited", v, "%") for f, v in (("x", 10), ("y", 80), ("z", 80))]
    line = line_of(run(office_store(), line_decisions=[*screening(kind=None), *entered, half_year()]), R410A_KC)
    assert line["trace"]["state"] == "complete"
    assert round(line["trace"]["result"]["recomputed"], 4) == 14.3823


def test_a_unit_with_no_capacity_waits_for_one_then_counts() -> None:
    store = office_store()
    store.add_document("RTU-4", "CT-S1-REFRSVC", [unit(rec("R-410A", "2025-08-01", added=1), "RTU-4")])
    trace = line_of(run(store, line_decisions=[*screening(), half_year()]), R410A_KC)["trace"]
    assert trace["state"] == "blocked"
    c4 = capacity_id(trace, "RTU-4")
    assert trace["blocking"][0]["input_id"] == c4 and "RTU-4" in trace["blocking"][0]["message"]
    assert trace["inputs"][c4]["decidable"] is True
    entered = event(R410A_KC, f"input|{c4}|recomputed", "edited", 10, "lb")
    trace = line_of(run(store, line_decisions=[*screening(), half_year(), entered]), R410A_KC)["trace"]
    assert value(trace, "in_use") == 162.0
    assert trace["result"]["recomputed"] == pytest.approx((162 * 0.1 + 1.28) * T_PER_LB * 1924, rel=1e-12)


def test_an_equipment_type_alone_changes_nothing() -> None:
    plain = run(office_store())
    after = run(office_store(), line_decisions=[choose(R410A_KC, fugitive.EQUIPMENT_CHOICE, "chillers")])
    assert after["categories"] == plain["categories"]
    assert line_of(after, R410A_KC)["results"] == line_of(plain, R410A_KC)["results"]
    held = line_of(after, R410A_KC)["decisions"]["applied"][0]
    assert held["uses"].startswith("held: the line is worked by the simplified material balance")


def test_with_no_decision_every_total_is_todays_and_the_screening_inputs_wait_unseen() -> None:
    plain = run(office_store())
    assert run(office_store(), line_decisions=[]) == plain
    trace = line_of(plain, R410A_KC)["trace"]
    assert trace["choices"][0]["chosen"] == "smb"
    assert trace["choices"][1]["id"] == fugitive.EQUIPMENT_CHOICE and trace["choices"][1]["chosen"] == ""
    assert trace["inputs"]["x"]["recomputed"]["status"] == "awaiting_review"
    shown = {t["operand"].get("input_id") for s in trace["steps"] for b in s["blocks"] for t in b["recomputed"]["terms"]}
    assert not shown & {"k", "x", "y", "z"}
    jsonschema.validate(trace, SCHEMA)
    # a screening-only decision while the balance is used holds, and changes no number
    held = run(office_store(), line_decisions=[event(R410A_KC, "input|x|recomputed", "edited", 15, "%")])
    assert held["categories"] == plain["categories"]
    assert line_of(held, R410A_KC)["decisions"]["applied"][0]["uses"] == "held: only the screening method uses it"


def test_a_service_decision_is_held_under_screening() -> None:
    p_s = line_of(run(office_store()), R410A_KC)["trace"]["inputs"]["P_S"]
    assert p_s["recomputed"]["value"] == 6
    decided = event(R410A_KC, "input|P_S|recomputed", "edited", 60, "lb")
    line = line_of(run(office_store(), line_decisions=[*screening(), half_year(), decided]), R410A_KC)
    assert round(line["trace"]["result"]["recomputed"], 4) == 14.3823
    assert next(a for a in line["decisions"]["applied"] if a["id"] == "P_S")["uses"] == \
        "held: the screening method does not use it"


def test_new_equipment_adds_its_installation_loss() -> None:
    store = office_store()
    store.add_document("RTU-5", "CT-S1-REFRSVC", [
        unit(rec("R-410A", "2025-09-01", "installation", added=21, capacity=20), "RTU-5")])
    trace = line_of(run(store, line_decisions=[*screening(), half_year()]), R410A_KC)["trace"]
    assert value(trace, "factor.k") == 0.01 and value(trace, "term.P_N") == 21.0
    assert value(trace, "installation") == pytest.approx(0.21, rel=1e-15)
    assert value(trace, "in_use") == 172.0  # RTU-5 is in use too, its full charge as C
    assert value(trace, "emitted") == pytest.approx(0.21 + 17.2 + 1.28, rel=1e-15)


def test_one_unit_seen_on_several_records_counts_once_at_its_largest_capacity_flagged() -> None:
    store = office_store()
    store.add_document("RTU-1B", "CT-S1-REFRSVC", [unit(rec("R-410A", "2025-10-01", added=1, capacity=130), "rtu-1")])
    trace = line_of(run(store, line_decisions=[*screening(), half_year()]), R410A_KC)["trace"]
    units = [b for s in trace["steps"] for b in s["blocks"] if b["id"].startswith("unit.")]
    assert len(units) == 3
    assert units[0]["recomputed"]["terms"][0]["operand"]["value"] == 132
    assert "different capacities" in units[0]["label"]
    assert fugitive.CAPACITY_CONFLICT_FLAG in trace["flags"]


def test_records_without_an_equipment_id_are_each_a_unit() -> None:
    store = FakeStore()
    store.add_document("LOG", "CT-S1-REFRSVC", [unit(rec("R-410A", "2025-03-01", added=4, capacity=50), None),
                                                unit(rec("R-410A", "2025-04-01", added=4, capacity=50), None)])
    trace = line_of(run(store, line_decisions=screening()), R410A_KC)["trace"]
    assert value(trace, "in_use") == 100.0


def test_a_mixed_line_offers_no_screening() -> None:
    method = fugitive._mixed_trace({"key": "k", "smb": {"gas": "R-410A", "gases": ["R-410A", "R-404A"],
                                                        "unit": "lb"}, "step1": {"rows": []}, "flags": []}).choices[0]
    assert method.options[0].id == "screening" and method.options[0].available is False
    assert "mixes refrigerants" in (method.options[0].why_unavailable or "")


# --- hostile values ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("input_id", "number", "unit_text"), [
    ("x", 150, "%"), ("x", 0, "%"), ("x", -5, "%"), ("x", float("nan"), "%"), ("x", "10", "%"), ("y", 101, "%"),
    ("x", 10, "lb"), ("T", 1.5, None), ("T", -0.5, None)])
def test_a_factor_or_time_that_is_not_plausible_never_reaches_the_math(input_id: str, number: Any,
                                                                         unit_text: str | None) -> None:
    trace = line_of(run(office_store()), R410A_KC)["trace"]
    target = time_id(trace, "RTU-1") if input_id == "T" else input_id
    bad = event(R410A_KC, f"input|{target}|recomputed", "edited", number, unit_text)
    line = line_of(run(office_store(), line_decisions=[*screening(), half_year(), bad]), R410A_KC)
    assert any(n["id"] == target for n in line["decisions"]["not_applied"])
    assert round(line["trace"]["result"]["recomputed"], 4) == 14.3823


def test_zero_is_allowed_where_it_means_nothing_happened() -> None:
    assert fugitive.zero_allowed("k") and fugitive.zero_allowed("z") and fugitive.zero_allowed("T.u123")
    assert not fugitive.zero_allowed("x") and not fugitive.zero_allowed("C.u123")
    trace = line_of(run(office_store()), R410A_KC)["trace"]
    gone = event(R410A_KC, f"input|{time_id(trace, 'RTU-3')}|recomputed", "edited", 0)
    line = line_of(run(office_store(), line_decisions=[*screening(), gone]), R410A_KC)
    assert value(line["trace"], "in_use") == 148.0


def test_an_unknown_equipment_type_or_method_is_refused() -> None:
    for bad in (choose(R410A_KC, fugitive.EQUIPMENT_CHOICE, "toaster"), choose(R410A_KC, "method", "material_balance"),
                choose(R410A_KC, "method", "<script>")):
        line = line_of(run(office_store(), line_decisions=[bad]), R410A_KC)
        assert line["decisions"]["not_applied"][0]["reason"] == "option_not_available"
        assert line["method"]["route"] == fugitive.ROUTE


def test_long_and_unicode_equipment_ids_are_kept_short_and_stable() -> None:
    store = FakeStore()
    name = "Kühlraum ☃ " + "x" * 500
    store.add_document("LOG", "CT-S1-REFRSVC", [unit(rec("R-410A", "2025-03-01", added=4, capacity=50), name)])
    first = line_of(run(store), R410A_KC)["trace"]
    again = line_of(run(store), R410A_KC)["trace"]
    ids = [i for i in first["inputs"] if i.startswith(fugitive.UNIT_C)]
    assert ids == [i for i in again["inputs"] if i.startswith(fugitive.UNIT_C)] and len(ids[0]) == 13
    assert first["inputs"][ids[0]]["label"].startswith("Kühlraum ☃") and len(first["inputs"][ids[0]]["label"]) < 140


def test_the_screening_inputs_are_decidable_and_the_reference_ones_are_not() -> None:
    trace = line_of(run(office_store()), R410A_KC)["trace"]
    for input_id in ("x", "y", "z", "k", capacity_id(trace, "RTU-1"), time_id(trace, "RTU-1")):
        assert trace["inputs"][input_id]["decidable"] is True, input_id
        assert decisions.not_decidable(input_id) is None
    assert decisions.not_decidable("gwp.R-410A") is not None


# --- the reference data: transcribed from the EPA guidance --------------------------------------------------------------
# Typed here a second time from the PDF (EPA, December 2023, Table 1 page 11 and Section 2.1.2 page 5); the file must
# agree with it to the digit.
EPA_TABLE_1 = {
    "domestic_refrigeration": ("0.05–0.5", 1, 0.5, 80, 70),
    "stand_alone_commercial": ("0.2–6", 3, 15, 80, 70),
    "medium_large_commercial": ("50–2,000", 3, 35, 100, 70),
    "transport_refrigeration": ("3–8", 1, 50, 50, 70),
    "industrial_refrigeration": ("10–10,000", 3, 25, 100, 90),
    "chillers": ("10–2,000", 1, 15, 100, 95),
    "residential_commercial_ac": ("0.5-100", 1, 10, 80, 80),
    "mobile_ac_maritime": ("5-6,500", 0.5, 40, 50, 50),
    "mobile_ac_railway": ("10-30", 0.5, 20, 50, 50),
    "mobile_ac_buses": ("4-18", 0.5, 20, 50, 50),
    "mobile_ac_other": ("0.5-2", 0.5, 20, 50, 50),
}


def test_the_screening_factors_match_epas_table_1_and_fire_rates() -> None:
    data = json.loads(FACTORS_FILE.read_text())
    assert data["edition"] == "December 2023"
    assert data["source_url"].startswith("https://www.epa.gov/")
    assert data["refrigeration"]["page"] == 11 and data["refrigeration"]["table"].startswith("Table 1:")
    assert data["fire_suppression"]["page"] == 5
    rows = {r["id"]: (r["capacity_kg"], r["k"], r["x"], r["y"], r["z"]) for r in data["refrigeration"]["rows"]}
    assert rows == EPA_TABLE_1
    assert {r["id"]: r["x"] for r in data["fire_suppression"]["rows"]} == {"fire_fixed": 2.5, "fire_portable": 3.5}
    loaded = fugitive.screening_factors()
    assert set(loaded) == set(EPA_TABLE_1) | {"fire_fixed", "fire_portable"}
    assert loaded["fire_fixed"].fire and loaded["fire_fixed"].factors == {"k": None, "x": 2.5, "y": None, "z": None}
    assert loaded["residential_commercial_ac"].factors == {"k": 1.0, "x": 10.0, "y": 80.0, "z": 80.0}
    for row in loaded.values():
        assert all(v is None or 0 <= v <= 100 for v in row.factors.values())
