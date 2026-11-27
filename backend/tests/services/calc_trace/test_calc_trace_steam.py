"""C9: purchased steam, mass × net enthalpy, and the four emission factor options (boards 06 to 08).

The plan's example is Kent Cannery's direct line from a neighbouring CHP plant: 15,800 Mlb (twelve monthly bills), a net
enthalpy of 1,048 Btu/lb against the company's 1,000, and the CHP allocated factors 58.20 kg CO2, 1.100 g CH4 and
0.110 g N2O per MMBtu. Here it runs at the Kansas City Plant of the test Setup. GWPs are AR5 (CH4 28, N2O 265).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

import jsonschema
import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import emissions_calculator as calc
from backend.app.services.calc_line_review import Refused, decide_input
from backend.app.services.calc_trace import _thermal_ef as ef
from backend.app.services.calc_trace import decisions, steam
from backend.app.services.calculation_lines import make_line
from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.app.services.request_service import Actor
from backend.app.services.review_field import ReviewInvalid
from backend.tests.services.calc_trace.fixture_replay import FIXTURES
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, line_of
from backend.tests.services.calc_trace.test_calc_trace_fugitive import SCHEMA
from backend.tests.services.test_calculation_lines import KC, STL
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own

REF = default_emission_factor_reference()
KEY = "s2:purchased_energy:steam:fac-kc01"
PLANT = "Kansas City Plant"
MONTHS = [1450, 1380, 1420, 1300, 1250, 1200, 1180, 1190, 1240, 1330, 1400, 1460]  # Mlb, board 06
DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
CHP = {"CO2": 58.20, "CH4": 1.100, "N2O": 0.110}
AR5 = {"CO2": 1, "CH4": 28, "N2O": 265}


def bill(quantity: float, unit: str, month: int, plant: str = PLANT, energy: str = "steam") -> dict[str, tuple]:
    return {"energy_type": (energy, None), "activity_quantity": (quantity, unit), "activity_unit": (unit, None),
            "facility_name": (plant, None), "service_period_start": (f"2025-{month:02d}-01", None),
            "service_period_end": (f"2025-{month:02d}-{DAYS[month - 1]}", None), "account_number": ("CHP-1", None)}


def kent_store(unit: str = "Mlb") -> FakeStore:
    store = FakeStore()
    for month, mlb in enumerate(MONTHS, start=1):
        store.add_document(f"STEAM-{month:02d}", "CT-S2-THERMAL", [bill(mlb, unit, month)])
    return store


def run(store: FakeStore, line_decisions: list[dict] | None = None, with_traces: bool = True,
        facilities: list[dict] | None = None, **recalculation: Any) -> dict:
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": facilities or [KC, STL], "recalculation": recalculation}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, _own, None, with_traces=with_traces, line_decisions=line_decisions)


def edited(input_id: str, value: float, unit: str, side: str = "recomputed") -> dict:
    return event(KEY, f"input|{input_id}|{side}", "edited", value, unit)


def chosen(option: str) -> dict:
    return event(KEY, f"choice|{ef.CHOICE_ID}|", "edited", option)


def enthalpy_1048(side: str = "recomputed") -> dict:
    return edited(steam.NET_ENTHALPY, 1000 if side == "company" else 1048, "Btu/lb", side)


def chp_events(side: str = "recomputed") -> list[dict]:
    return [edited(f"chp_ef.{gas}", value, ef.UNIT[gas], side) for gas, value in CHP.items()]


def category(response: dict, which: str = "location") -> dict:
    found: dict = response["categories"][f"purchased_steam_{which}_based"]
    return found


HEAT = {"steam_heat_content": {PLANT: 1000}}
COMPANY = {"reported_activity": {KEY: {"quantity": 15800, "unit": "Mlb"}}}


# --- the plan's numbers --------------------------------------------------------------------------------------------
def test_mass_times_net_enthalpy_is_the_plans_16558_4_mmbtu_against_the_companys_15800() -> None:
    response = run(kent_store(), [enthalpy_1048(), enthalpy_1048("company")], **HEAT, **COMPANY)
    trace = line_of(response, KEY)["trace"]
    assert trace["panel"] == "steam" and trace["state"] == "complete"
    total = block(trace, "input.mass")
    assert total["recomputed"]["result"]["value"] == 15800
    assert [r["recomputed"]["value"] for r in trace["inputs"]["mass"]["rows"]] == MONTHS
    mass = block(trace, "mass")
    assert [t["operand"]["value"] for t in mass["recomputed"]["terms"]] == [15800, 1048, 0.001]
    assert mass["recomputed"]["result"]["value"] == pytest.approx(16558.4, rel=1e-12)
    assert mass["company"]["result"]["value"] == pytest.approx(15800, rel=1e-12)
    assert mass["recomputed"]["result"]["difference"] == pytest.approx(758.4, rel=1e-9)
    assert mass["recomputed"]["terms"][1]["operand"]["difference"] == pytest.approx(48)
    assert mass["tag"] == "detected_from_evidence"
    assert block(trace, "energy")["tag"] == "not_used_for_this_line"
    # no extractor reads a steam bill's cost yet: no cost-only block is drawn as if it could be acted on
    assert not any(b["id"] == "cost_only" for s in trace["steps"] for b in s["blocks"])
    assert trace["inputs"]["net_enthalpy"]["recomputed"]["value"] == 1048
    assert trace["inputs"]["net_enthalpy"]["company"]["value"] == 1000
    jsonschema.validate(trace, SCHEMA)


def test_chp_allocated_factors_give_the_plans_963_69888_t_co2_against_the_companys_919_56() -> None:
    response = run(kent_store(), [enthalpy_1048(), enthalpy_1048("company"), *chp_events(), *chp_events("company")],
                   **HEAT, **COMPANY)
    line = line_of(response, KEY)
    trace = line["trace"]
    choice = next(c for c in trace["choices"] if c["id"] == ef.CHOICE_ID)
    assert choice["chosen"] == ef.CHP and choice["chosen_by"] == "default" and choice["company"] == ef.CHP
    co2 = block(trace, "emissions.CO2")
    assert co2["recomputed"]["result"]["value"] == pytest.approx(963.69888, rel=1e-12)
    assert co2["company"]["result"]["value"] == pytest.approx(919.56, rel=1e-12)
    assert co2["recomputed"]["result"]["difference"] == pytest.approx(44.13888, rel=1e-9)
    ch4 = block(trace, "emissions.CH4")["recomputed"]["result"]["value"]
    n2o = block(trace, "emissions.N2O")["recomputed"]["result"]["value"]
    assert ch4 == pytest.approx(16558.4 * 1.1 / 1e6, rel=1e-12) and n2o == pytest.approx(16558.4 * 0.11 / 1e6, rel=1e-12)
    expected = 963.69888 + ch4 * 28 + n2o * 265
    assert trace["result"]["recomputed"] == pytest.approx(expected, rel=1e-12)
    assert line["results"]["total_co2e_t"] == pytest.approx(expected, rel=1e-12)
    # the tags: CHP used, the other three not
    tags = {b["id"].split(".")[1]: b.get("tag") for s in trace["steps"] for b in s["blocks"] if b["id"].startswith("ef.")}
    assert tags == {ef.SUPPLIER: "not_used_for_this_line", ef.CHP: "detected_from_evidence",
                    ef.FUEL: "not_used_for_this_line", ef.TABLE7: "not_used_for_this_line"}
    assert ef.CHP_FLAG in trace["flags"]
    assert "CHP allocation method: as stated by the supplier" in next(s for s in trace["steps"] if s["n"] == 3)["note"]
    # the category counts the decided line, location and market alike
    assert category(response)["total_co2e"] == pytest.approx(expected, rel=1e-12)
    assert category(response, "market")["total_co2e"] == pytest.approx(expected, rel=1e-12)
    jsonschema.validate(trace, SCHEMA)


def test_epa_table_7_on_16558_4_mmbtu_is_the_plans_1098_318672_t_co2() -> None:
    response = run(kent_store(), [enthalpy_1048()], **HEAT)
    trace = line_of(response, KEY)["trace"]
    assert next(c for c in trace["choices"] if c["id"] == ef.CHOICE_ID)["chosen"] == ef.TABLE7
    mass = {gas: block(trace, f"emissions.{gas}")["recomputed"]["result"]["value"] for gas in AR5}
    assert mass["CO2"] == pytest.approx(1098.318672, rel=1e-12)
    assert mass["CH4"] == pytest.approx(0.020698, rel=1e-12)
    assert mass["N2O"] == pytest.approx(0.0020698, rel=1e-12)
    assert trace["result"]["recomputed"] == pytest.approx(1099.446713, abs=5e-7)
    assert trace["result"]["recomputed"] == pytest.approx(sum(mass[g] * AR5[g] for g in AR5), rel=1e-12)
    table7 = block(trace, "ef.epa_table7.CO2")
    assert table7["recomputed"]["result"]["value"] == 66.33 and table7.get("tag") is None
    assert category(response)["total_co2e"] == pytest.approx(1099.446713, abs=5e-7)


def test_fuel_and_efficiency_on_natural_gas_at_80_percent_is_66_325_and_says_why_table_7_prints_66_33() -> None:
    response = run(kent_store(), [enthalpy_1048(), edited(ef.EFFICIENCY, 80, "%")], **HEAT)
    trace = line_of(response, KEY)["trace"]
    assert next(c for c in trace["choices"] if c["id"] == ef.CHOICE_ID)["chosen"] == ef.FUEL
    worked = {gas: block(trace, f"ef.{ef.FUEL}.{gas}")["recomputed"] for gas in AR5}
    assert worked["CO2"]["result"]["value"] == 66.325  # 53.06 ÷ 0.80, exactly
    assert worked["CH4"]["result"]["value"] == 1.25 and worked["N2O"]["result"]["value"] == 0.125
    assert [t["operand"]["value"] for t in worked["CO2"]["terms"]] == [53.06, 0.8]
    assert block(trace, "ef.epa_table7.CO2")["recomputed"]["result"]["value"] == 66.33
    # the 0.005 gap is explained, never hidden: Table 7 is the same calculation, printed rounded
    assert 66.33 - 66.325 == pytest.approx(0.005)
    note = next(s for s in trace["steps"] if s["n"] == 3)["note"]
    assert "53.06 ÷ 0.80 = 66.325" in note and "66.33" in note and "rounded" in note
    # the fuel is an assumption until a reviewer confirms it
    assumed = trace["inputs"]["fuel_ef.CO2"]
    assert assumed["assumption"] == "Default: natural gas, 53.06 kg/MMBtu (EPA Hub Table 1) · not confirmed"
    co2 = block(trace, "emissions.CO2")["recomputed"]["result"]["value"]
    assert co2 == pytest.approx(16558.4 * 66.325 / 1000, rel=1e-12)
    jsonschema.validate(trace, SCHEMA)


def test_the_steam_tables_give_about_1048_for_150_psig_saturated_and_condensate_at_180_f() -> None:
    net = steam.net_enthalpy(150, 180)
    assert net == pytest.approx(1195.97 - 148.01, abs=1e-9)
    assert round(net) == 1048  # the plan's 1,048, to the Btu/lb the table gives
    response = run(kent_store(), [edited(steam.PRESSURE, 150, "psig"), edited(steam.CONDENSATE, 180, "°F")], **HEAT)
    trace = line_of(response, KEY)["trace"]
    tables = block(trace, "net_enthalpy")["recomputed"]
    assert [t["operand"]["value"] for t in tables["terms"]] == [1195.97, 148.01]
    assert tables["result"]["value"] == pytest.approx(1047.96, abs=1e-9)
    assert trace["inputs"]["net_enthalpy"]["recomputed"]["status"] == "derived"
    assert "IAPWS" in trace["inputs"]["steam_table.h_g"]["recomputed"]["source"]["citation"]
    assert block(trace, "mass")["recomputed"]["result"]["value"] == pytest.approx(15800 * net * 0.001, rel=1e-12)
    assert "assumption" not in trace["inputs"]["condensate_f"]


def test_no_condensate_return_stated_is_the_gross_enthalpy_and_says_so() -> None:
    response = run(kent_store(), [edited(steam.PRESSURE, 150, "psig")], **HEAT)
    trace = line_of(response, KEY)["trace"]
    assert trace["inputs"]["net_enthalpy"]["recomputed"]["value"] == pytest.approx(1195.97, abs=1e-9)
    assert trace["inputs"]["condensate_f"]["assumption"] == \
        "Default: no condensate return, gross enthalpy (32 °F) · not confirmed"
    assert trace["inputs"]["condensate_f"]["recomputed"]["value"] == 32
    # the gross enthalpy is the larger, so the conservative, figure
    assert steam.net_enthalpy(150) > steam.net_enthalpy(150, 180)  # type: ignore[operator]


def test_interpolation_is_linear_between_rows_and_never_beyond_the_table() -> None:
    low, high = steam.saturated(145), steam.saturated(150)
    assert low is not None and high is not None
    middle = steam.saturated(147.5)
    assert middle == pytest.approx(((low[0] + high[0]) / 2, (low[1] + high[1]) / 2), abs=1e-12)
    assert steam.saturated(-1) is None and steam.saturated(301) is None and steam.liquid(410) is None
    assert steam.net_enthalpy(0, 220) is None  # condensate hotter than 0 psig steam (212 °F)


# --- the option priority and the reviewer's choice ------------------------------------------------------------------
def test_with_several_options_detected_supplier_specific_comes_first_and_a_reviewer_can_choose_otherwise() -> None:
    supplier = [edited(f"supplier_ef.{gas}", value, ef.UNIT[gas]) for gas, value in
                {"CO2": 60.0, "CH4": 1.0, "N2O": 0.1}.items()]
    base = [enthalpy_1048(), *supplier, *chp_events(), edited(ef.EFFICIENCY, 80, "%")]
    trace = line_of(run(kent_store(), base, **HEAT), KEY)["trace"]
    choice = next(c for c in trace["choices"] if c["id"] == ef.CHOICE_ID)
    assert choice["chosen"] == ef.SUPPLIER
    assert {o["id"]: o.get("detection") for o in choice["options"]} == {
        ef.SUPPLIER: "detected_from_evidence", ef.CHP: "detected_from_evidence", ef.FUEL: "detected_from_evidence",
        ef.TABLE7: None}
    assert block(trace, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(16558.4 * 60 / 1000)
    response = run(kent_store(), [*base, chosen(ef.TABLE7)], **HEAT)
    picked = line_of(response, KEY)
    assert next(c for c in picked["trace"]["choices"] if c["id"] == ef.CHOICE_ID)["chosen_by"] == "reviewer"
    assert block(picked["trace"], "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(1098.318672)
    applied = next(e for e in picked["decisions"]["applied"] if e["id"] == ef.CHOICE_ID)
    assert applied["value"] == ef.TABLE7 and applied["moves_totals"] is True


def test_an_option_chosen_without_its_factors_blocks_the_line_and_counts_it_as_calculated() -> None:
    plain = run(kent_store(), **HEAT)
    response = run(kent_store(), [chosen(ef.CHP)], **HEAT)
    line = line_of(response, KEY)
    assert line["trace"]["state"] == "blocked"
    assert "CHP allocated emission factors" in line["trace"]["blocking"][0]["message"]
    assert line["trace"]["inputs"]["chp_ef.CO2"]["decidable"] is True
    assert category(response)["total_co2e"] == category(plain)["total_co2e"]
    assert "held" in next(e for e in line["decisions"]["applied"] if e["id"] == ef.CHOICE_ID)["uses"]


# --- the line and its category ------------------------------------------------------------------------------------
def test_no_decision_the_line_is_the_categorys_own_working() -> None:
    response = run(kent_store(), **HEAT)
    line = line_of(response, KEY)
    assert line["counts_toward"] == "steam" and line["level2"] == "Steam" and line["category"] == "purchased_energy"
    assert line["results"]["mass_t"]["CO2"] == pytest.approx(15800 * 66.33 / 1000, rel=1e-12)
    assert category(response)["total_co2e"] == pytest.approx(line["results"]["total_co2e_t"], rel=1e-12)
    assert line["trace"]["state"] == "complete"
    assert line["trace"]["inputs"]["net_enthalpy"]["recomputed"]["value"] == 1000
    assert line["trace"]["result"]["recomputed"] == pytest.approx(line["results"]["total_co2e_t"], rel=1e-12)
    jsonschema.validate(line["trace"], SCHEMA)


def test_no_decisions_and_an_empty_list_leave_the_response_exactly_as_it_was() -> None:
    plain = run(kent_store(), with_traces=False, **HEAT)
    assert run(kent_store(), line_decisions=[], with_traces=False, **HEAT) == plain
    assert all("decisions" not in line for line in plain["calculation_lines"])


@pytest.mark.parametrize("name", [n for n in ("recalculationCompareProbes.json", "recalculationLive.json")])
def test_every_recorded_steam_fixture_keeps_its_total_and_its_lines_add_up(name: str) -> None:
    recorded = json.loads((FIXTURES / name).read_text())["categories"]["purchased_steam_location_based"]
    store = FakeStore()
    setup = []
    for i, item in enumerate(recorded["details"]["inputs"]):
        setup.append({"facilityId": f"fac-{i}", "name": item["fuel"]})
        for doc in item["documents"]:
            record = bill(float(doc["quantity"]), str(doc["unit"]), 1, plant=item["fuel"])
            store.add_document(doc["document_id"], "CT-S2-THERMAL", [record])
    response = run(store, facilities=setup)
    got = category(response)
    assert got["total_co2e"] == recorded["total_co2e"]  # bit for bit
    lines = [ln for ln in [*response["calculation_lines"], *response["calculation_unplaced"]]
             if ln["counts_toward"] == "steam"]
    assert lines and sum(ln["results"]["sum_co2e_t"] for ln in lines) == pytest.approx(recorded["total_co2e"],
                                                                                       rel=1e-12)


def test_steam_by_weight_with_no_heat_content_is_blocked_and_counted_once_its_enthalpy_is_decided() -> None:
    plain = run(kent_store())
    line = line_of(plain, KEY)
    assert line["trace"]["state"] == "blocked" and steam.ENTHALPY_FLAG in line["flags"]
    assert line["results"]["total_co2e_t"] == 0 and plain["categories"].get("purchased_steam_location_based") is None
    assert line["trace"]["inputs"]["net_enthalpy"]["decidable"] is True
    assert any(n["kind"] == "steam_heat_content" for n in plain["needs_input"])
    decided = run(kent_store(), [enthalpy_1048()])
    line = line_of(decided, KEY)
    assert line["trace"]["state"] == "complete" and steam.ENTHALPY_FLAG not in line["flags"]
    assert category(decided)["total_co2e"] == pytest.approx(1099.446713, abs=5e-7)
    assert category(decided, "market")["total_co2e"] == pytest.approx(1099.446713, abs=5e-7)
    assert not any(n["kind"] == "steam_heat_content" for n in decided["needs_input"])
    assert line["steam"]["mmbtu"] == pytest.approx(16558.4) and "awaiting" not in line["steam"]


def test_energy_billed_steam_converts_to_mmbtu_and_takes_no_enthalpy() -> None:
    store = FakeStore()
    store.add_document("E-1", "CT-S2-THERMAL", [bill(12_500, "therms", 1)])
    store.add_document("E-2", "CT-S2-THERMAL", [bill(1_000, "therms", 2)])
    response = run(store)
    trace = line_of(response, KEY)["trace"]
    energy = block(trace, "energy")
    assert energy["tag"] == "detected_from_evidence" and block(trace, "mass")["tag"] == "not_used_for_this_line"
    assert [t["operand"]["value"] for t in energy["recomputed"]["terms"]] == [13_500, 0.1]
    assert energy["recomputed"]["result"]["value"] == pytest.approx(1350, rel=1e-12)
    assert category(response)["total_co2e"] == pytest.approx(trace["result"]["recomputed"], rel=1e-12)


def test_a_decided_enthalpy_moves_the_line_and_its_category_by_exactly_the_decided_mmbtu() -> None:
    plain = run(kent_store(), **HEAT)
    response = run(kent_store(), [enthalpy_1048()], **HEAT)
    delta = category(response)["total_co2e"] - category(plain)["total_co2e"]
    per_mmbtu = (66.33 + 1.25e-3 * 28 + 0.125e-3 * 265) / 1000
    assert delta == pytest.approx(758.4 * per_mmbtu, rel=1e-9)
    line = line_of(response, KEY)
    assert line["step2"]["result"]["quantity"] == pytest.approx(16558.4) and line["steam"]["enthalpy"]["value"] == 1048
    assert "reviewer_decisions_applied" in line["flags"]


def test_the_engagement_total_follows_the_decided_line() -> None:
    plain = run(kent_store(), **HEAT)
    response = run(kent_store(), [enthalpy_1048(), *chp_events()], **HEAT)
    moved = category(response)["total_co2e"] - category(plain)["total_co2e"]
    assert response["scope_totals"]["scope2_location"]["total_co2e"] - plain["scope_totals"]["scope2_location"][
        "total_co2e"] == \
        pytest.approx(moved, rel=1e-9)


# --- hostile data -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("input_id", "value", "unit"), [
    (steam.NET_ENTHALPY, 50, "Btu/lb"), (steam.NET_ENTHALPY, 1e9, "Btu/lb"), (steam.PRESSURE, 900, "psig"),
    (ef.EFFICIENCY, 180, "%"), (steam.NET_ENTHALPY, "lots", "Btu/lb"), (steam.NET_ENTHALPY, -1048, "Btu/lb"),
    (steam.NET_ENTHALPY, float("nan"), "Btu/lb"), (steam.NET_ENTHALPY, 1048, "kJ/kg")])
def test_hostile_values_are_reported_never_used(input_id: str, value: Any, unit: str) -> None:
    plain = run(kent_store(), **HEAT)
    response = run(kent_store(), [edited(input_id, value, unit)], **HEAT)
    line = line_of(response, KEY)
    assert category(response)["total_co2e"] == category(plain)["total_co2e"]
    assert any(e["id"] == input_id for e in line["decisions"]["not_applied"])


def test_condensate_hotter_than_the_steam_is_refused() -> None:
    response = run(kent_store(), [edited(steam.PRESSURE, 0.5, "psig"), edited(steam.CONDENSATE, 300, "°F")], **HEAT)
    line = line_of(response, KEY)
    refused = next(e for e in line["decisions"]["not_applied"] if e["id"] == steam.CONDENSATE)
    assert "not below the steam's own temperature" in refused["message"]
    assert line["trace"]["inputs"]["net_enthalpy"]["recomputed"]["value"] == pytest.approx(steam.net_enthalpy(0.5))


def test_a_condensate_with_no_pressure_is_held_and_a_pressure_under_a_decided_enthalpy_too() -> None:
    line = line_of(run(kent_store(), [edited(steam.CONDENSATE, 180, "°F")], **HEAT), KEY)
    assert "held" in next(e for e in line["decisions"]["applied"] if e["id"] == steam.CONDENSATE)["uses"]
    line = line_of(run(kent_store(), [enthalpy_1048(), edited(steam.PRESSURE, 150, "psig")], **HEAT), KEY)
    assert "held" in next(e for e in line["decisions"]["applied"] if e["id"] == steam.PRESSURE)["uses"]
    assert line["trace"]["inputs"]["net_enthalpy"]["recomputed"]["value"] == 1048


def test_the_reference_factors_conversions_and_gwps_cannot_be_decided_for_a_line() -> None:
    trace = line_of(run(kent_store(), **HEAT), KEY)["trace"]
    for input_id in ("table7.CO2", "unit_conversion", "energy_conversion", "gwp.CH4", "share", "to_t.CO2"):
        assert trace["inputs"][input_id]["decidable"] is False, input_id
    for input_id in steam.INPUTS:
        assert trace["inputs"][input_id]["decidable"] is True, input_id
    actor = Actor(user_id="u1", name="Rev", login="r@example.com")
    with pytest.raises(Refused):
        decide_input({}, trace["inputs"]["table7.CO2"], None, "recomputed", "edit", value=70, unit="kg/MMBtu",
                     reason="r", actor=actor, now=__import__("datetime").datetime(2026, 11, 27))


def test_steam_lines_and_records_on_no_line_add_up_to_the_category_and_no_electricity_line_holds_steam() -> None:
    store = kent_store()
    response = run(store, **HEAT)
    lines = [ln for ln in [*response["calculation_lines"], *response["calculation_unplaced"]]
             if ln["counts_toward"] == "steam"]
    assert sum(ln["results"]["sum_co2e_t"] for ln in lines) == pytest.approx(category(response)["total_co2e"])
    assert not any(ln["counts_toward"] == "purchased_energy" for ln in response["calculation_lines"])


def test_a_steam_line_with_company_figures_and_no_bill_resolves() -> None:
    response = run(FakeStore(), **HEAT, **COMPANY, reported_lines={KEY: 920.5})
    line = line_of(response, KEY)
    assert line["counts_toward"] == "steam" and "no_evidence" in line["flags"]
    assert line["results"]["total_co2e_t"] == 0 and line["reported_total_co2e_t"] == 920.5
    assert line["company"]["results"]["mass_t"]["CO2"] == pytest.approx(15800 * 66.33 / 1000)


def test_a_company_quantity_that_is_not_steam_asks_instead_of_guessing() -> None:
    response = run(kent_store(), **HEAT, reported_activity={KEY: {"quantity": 15800, "unit": "gal"}})
    assert line_of(response, KEY)["company"] is None
    assert any(n["kind"] == "company_activity" and n["key"] == KEY for n in response["needs_input"])


def test_a_decision_for_another_line_never_touches_this_one() -> None:
    plain = run(kent_store(), **HEAT)
    other = event("s2:purchased_energy:steam:fac-stl2", f"input|{steam.NET_ENTHALPY}|recomputed", "edited", 1048,
                  "Btu/lb")
    response = run(kent_store(), [other], **HEAT)
    assert category(response)["total_co2e"] == category(plain)["total_co2e"]
    assert line_of(response, KEY)["results"] == line_of(plain, KEY)["results"]


def test_hot_water_stays_off_the_steam_lines() -> None:
    store = kent_store()
    store.add_document("HEAT-1", "CT-S2-THERMAL", [bill(340, "MMBtu", 1, energy="hot_water")])
    response = run(store, **HEAT)
    assert all(r["document_id"] != "HEAT-1" for ln in response["calculation_lines"] if ln["counts_toward"] == "steam"
               for r in ln["step1"]["rows"])
    assert response["categories"]["purchased_heating_location_based"]["total_co2e"] > 0


def test_the_line_family_is_steam() -> None:
    line = make_line("purchased_energy", "steam", "Steam", "facility", "fac-kc01", PLANT, created_by_user=True)
    assert line.family == "steam" and line.to_dict()["family"] == "steam"
    heating = make_line("purchased_energy", "heating", "Heating", "facility", "fac-kc01", PLANT, created_by_user=True)
    assert heating.family is None


def test_the_decision_rules_know_the_steam_inputs() -> None:
    for input_id in steam.INPUTS:
        assert decisions.not_decidable(input_id) is None, input_id
    assert decisions.not_decidable("steam_table.h_g") is not None
    assert math.isclose(calc.KG_PER_METRIC_TON, 1000)


# --- review: the supplier factor's basis, the market-based flag, 0 psig -----------------------------------------------
SUPPLIER = {"CO2": 60.0, "CH4": 1.0, "N2O": 0.1}


def supplier_events() -> list[dict]:
    return [edited(f"supplier_ef.{gas}", value, ef.UNIT[gas]) for gas, value in SUPPLIER.items()]


def co2e_per_mmbtu(factors: dict[str, float]) -> float:
    return factors["CO2"] / 1000 + factors["CH4"] / 1e6 * 28 + factors["N2O"] / 1e6 * 265


def test_a_physical_supplier_factor_counts_in_location_and_market_based_and_clears_the_no_supplier_flag() -> None:
    plain = run(kent_store(), **HEAT)
    assert "no_supplier_factor_market_equals_location" in category(plain, "market")["flags"]
    response = run(kent_store(), [enthalpy_1048(), *supplier_events()], **HEAT)
    trace = line_of(response, KEY)["trace"]
    option = next(o for c in trace["choices"] if c["id"] == ef.CHOICE_ID for o in c["options"] if o["id"] == ef.SUPPLIER)
    assert option["basis"] == ef.PHYSICAL
    expected = 16558.4 * co2e_per_mmbtu(SUPPLIER)
    assert category(response)["total_co2e"] == pytest.approx(expected, rel=1e-12)
    assert category(response, "market")["total_co2e"] == pytest.approx(expected, rel=1e-12)
    market_flags = category(response, "market")["flags"]
    assert "no_supplier_factor_market_equals_location" not in market_flags
    assert "supplier_factor_decided_on_lines" in market_flags
    jsonschema.validate(trace, SCHEMA)


def test_a_contractual_supplier_factor_moves_market_based_only() -> None:
    contractual = event(KEY, f"choice|{ef.BASIS_CHOICE}|", "edited", ef.CONTRACTUAL)
    response = run(kent_store(), [enthalpy_1048(), *supplier_events(), contractual], **HEAT)
    line = line_of(response, KEY)
    trace = line["trace"]
    table7 = 16558.4 * co2e_per_mmbtu({"CO2": 66.33, "CH4": 1.25, "N2O": 0.125})
    supplier = 16558.4 * co2e_per_mmbtu(SUPPLIER)
    # location-based: the next option the evidence gives (EPA Table 7); market-based: the supplier's factor
    assert block(trace, "emissions.CO2")["recomputed"]["terms"][1]["operand"]["value"] == 66.33
    assert trace["result"]["recomputed"] == pytest.approx(table7, rel=1e-12)
    assert block(trace, "results.market")["recomputed"]["result"]["value"] == pytest.approx(supplier, rel=1e-12)
    assert category(response)["total_co2e"] == pytest.approx(table7, rel=1e-12)
    assert category(response, "market")["total_co2e"] == pytest.approx(supplier, rel=1e-12)
    assert ef.MARKET_ONLY_FLAG in trace["flags"]
    assert "market-based only" in next(s for s in trace["steps"] if s["n"] == 3)["note"]
    tags = {b["id"]: b.get("tag") for s in trace["steps"] for b in s["blocks"] if b["id"].endswith(".CO2")
            and b["id"].startswith("ef.")}
    assert tags["ef.supplier_specific.CO2"] == "detected_from_evidence" and tags["ef.epa_table7.CO2"] is None
    assert "supplier_factor_decided_on_lines" in category(response, "market")["flags"]
    assert line["steam"]["market_total_co2e_t"] == pytest.approx(supplier, rel=1e-12)
    jsonschema.validate(trace, SCHEMA)


def test_steam_at_0_psig_can_be_decided_and_a_negative_or_nan_pressure_cannot() -> None:
    line = line_of(run(kent_store(), [edited(steam.PRESSURE, 0, "psig")], **HEAT), KEY)
    assert line["trace"]["inputs"]["net_enthalpy"]["recomputed"]["value"] == pytest.approx(1150.27, abs=1e-9)
    assert not line["decisions"]["not_applied"]
    for bad in (-5, float("nan")):
        line = line_of(run(kent_store(), [edited(steam.PRESSURE, bad, "psig")], **HEAT), KEY)
        assert any(e["id"] == steam.PRESSURE for e in line["decisions"]["not_applied"])
    trace = line_of(run(kent_store(), **HEAT), KEY)["trace"]
    actor = Actor(user_id="u1", name="Rev", login="r@example.com")
    now = datetime(2026, 11, 27)
    made = decide_input({}, trace["inputs"][steam.PRESSURE], None, "recomputed", "edit", value=0, unit="psig",
                        reason="Supplier statement", actor=actor, now=now)
    assert made["decision"]["value"] == 0
    with pytest.raises(ReviewInvalid):
        decide_input({}, trace["inputs"][steam.NET_ENTHALPY], None, "recomputed", "edit", value=0, unit="Btu/lb",
                     reason="r", actor=actor, now=now)
