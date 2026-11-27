"""C8: the electricity grid region compared (company against ZIP/chosen), a ZIP code in two subregions as a choice, and
the company's own per-gas factors. Expected numbers are the plan's (2,747 MWh: company NWPP, recomputed CAMX)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import line_totals
from backend.app.services.calc_trace import decisions
from backend.app.services.calc_trace import electricity
from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.tests.services.calc_trace.recalc_scenarios import REGIONS, run
from backend.tests.services.calc_trace.test_calc_trace_decisions import block, event, line_of
from backend.tests.services.test_calculation_lines import ELEC_KC, KC, STL
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.calc_trace.test_stationary_equations import COAL, COAL_KW, hhv, pick
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase, _own
from backend.tests.services.calc_trace.test_calc_trace_mobile import DIESEL, ECONOMY, GROUP_7MPG
from backend.tests.services.test_calculation_lines import _gas as _gas_record

SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())
COMPANY = "input|grid_region|company"
REGION_CHOICE = "choice|grid_region|"
LB_PER_T = 2204.62
REF = default_emission_factor_reference()
COMPANY_KWH = {ELEC_KC: {"quantity": 2747000, "unit": "kWh"}}
NJ = {**KC, "address": "1 Ridge Road, Allendale, NJ 07401"}  # EPA: RFCE or NYUP
CA = {**KC, "address": "5 Yosemite Blvd, Modesto, CA 95358"}  # EPA: CAMX
OR = {**KC, "address": "9 Main St, Tualatin, OR 97062"}  # EPA: NWPP


def store_2747() -> FakeStore:
    store = FakeStore()
    store.add_document("E", "CT-S2-ELEC", [_elec_record(2747, start="2025-01-01", end="2025-12-31")])
    return store


def run_at(facility: dict[str, Any], store: FakeStore, **recalculation: Any) -> dict:
    """A recalculation of one facility (its address decides the ZIP code), with decisions as ``line_decisions``."""

    decisions = recalculation.pop("line_decisions", None)
    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": [facility, STL], "recalculation": recalculation}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, _own, None, with_traces=True, line_decisions=decisions)


def mass(code: str, gas: str, mwh: float = 2747) -> float:
    return mwh * REF.electricity(code)[gas].value / LB_PER_T


# --- the plan's numbers -------------------------------------------------------------------------------------------
def test_company_nwpp_against_recomputed_camx_is_the_plans_numbers_exactly() -> None:
    entered = event(ELEC_KC, COMPANY, "edited", "NWPP")
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH,
                   line_decisions=[entered])
    line = line_of(response, ELEC_KC)
    trace = line["trace"]
    co2, ch4, n2o = (block(trace, f"emissions.{g}") for g in ("CO2", "CH4", "N2O"))
    assert co2["company"]["result"]["value"] == pytest.approx(787.1169, abs=5e-5)
    assert ch4["company"]["result"]["value"] == pytest.approx(0.0672851, abs=5e-8)
    assert n2o["company"]["result"]["value"] == pytest.approx(0.0099682, abs=5e-8)
    assert block(trace, "results.total")["company"]["result"]["value"] == pytest.approx(791.6424, abs=5e-5)
    assert trace["result"]["company"] == pytest.approx(791.6424, abs=5e-5)
    assert trace["result"]["recomputed"] == pytest.approx(545.9435, abs=5e-5)  # not Claire's mock 535.8
    assert trace["result"]["difference"] == pytest.approx(-245.6989, abs=5e-5)
    # the lines table and the category agree with the panel, not only the panel with itself
    assert line["results"]["company_total_co2e_t"] == pytest.approx(791.6424, abs=5e-5)
    assert line["results"]["difference_to_company_t"] == pytest.approx(-245.6989, abs=5e-5)
    assert response["categories"]["purchased_electricity_location_based"]["total_co2e"] == pytest.approx(545.9435,
                                                                                                         abs=5e-5)
    grid = trace["inputs"]["grid_region"]
    assert grid["company"]["value"] == "NWPP" and grid["recomputed"]["value"] == "CAMX"
    assert grid["differs"] is True and grid["decidable"] is False
    assert block(trace, "grid_region")["recomputed"]["result"]["differs"] is True
    ef = trace["inputs"]["ef.CO2"]  # the company's factor beside ours, with the difference
    assert (ef["company"]["value"], ef["recomputed"]["value"]) == (631.705, 436.655)
    assert ef["difference"] == pytest.approx(436.655 - 631.705)
    jsonschema.validate(trace, SCHEMA)


def test_the_zip_regions() -> None:
    assert electricity.egrid_zip.subregions_for_zip("95358") == ["CAMX"]
    assert electricity.egrid_zip.subregions_for_zip("97062") == ["NWPP"]
    entered = [event(ELEC_KC, COMPANY, "edited", "NWPP")]
    camx = line_of(run_at(CA, store_2747(), line_decisions=entered), ELEC_KC)["trace"]["inputs"]["grid_region"]
    assert camx["recomputed"]["value"] == "CAMX" and camx["differs"] is True
    assert camx["recomputed"]["source"]["citation"].startswith("ZIP 95358")
    nwpp = line_of(run_at(OR, store_2747(), line_decisions=entered), ELEC_KC)["trace"]["inputs"]["grid_region"]
    assert nwpp["recomputed"]["value"] == "NWPP" and nwpp["differs"] is False
    assert block(line_of(run_at(OR, store_2747(), line_decisions=entered), ELEC_KC)["trace"],
                 "grid_region")["recomputed"]["result"]["differs"] is False


@pytest.mark.parametrize("text", ["nwpp", " NWPP ", "NWPP · WECC Northwest", "NWPP - WECC Northwest", "WECC Northwest",
                                  "ＮＷＰＰ"])
def test_the_company_region_may_be_written_many_ways_and_is_the_same_subregion(text: str) -> None:
    response = run_at(OR, store_2747(), reported_activity=COMPANY_KWH,
                      line_decisions=[event(ELEC_KC, COMPANY, "edited", text)])
    trace = line_of(response, ELEC_KC)["trace"]
    assert trace["inputs"]["grid_region"]["company"]["value"] == "NWPP"
    assert trace["inputs"]["grid_region"]["differs"] is False
    assert trace["result"]["difference"] == pytest.approx(0.0, abs=1e-9)  # same region, same factors, same MWh


# --- no company region: nothing changes ---------------------------------------------------------------------------
def test_without_a_company_region_the_company_runs_on_our_factors_as_before_and_nothing_differs() -> None:
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH)
    line = line_of(response, ELEC_KC)
    grid = line["trace"]["inputs"]["grid_region"]
    assert grid["company"] == {"value": None, "status": "not_reported"} and "differs" not in grid
    assert line["results"]["company_total_co2e_t"] == pytest.approx(545.9435, abs=5e-5)  # ours, as it always was
    assert "differs" not in block(line["trace"], "grid_region")["recomputed"]["result"]
    jsonschema.validate(line["trace"], SCHEMA)


def test_with_no_decisions_the_totals_are_the_calculators_bit_for_bit() -> None:
    settings: dict[str, Any] = {"grid_regions": {**REGIONS, "Kansas City Plant": "CAMX"}, "reported_activity": COMPANY_KWH}
    plain = run(store_2747(), with_traces=False, **settings)
    traced = run(store_2747(), with_traces=True, **settings)
    for name in ("categories", "scope_totals", "comparisons"):
        assert traced[name] == plain[name]
    strip = [{k: v for k, v in ln.items() if k != "trace"} for ln in traced["calculation_lines"]]
    assert strip == plain["calculation_lines"]
    # an empty decision list and a decision on another stream change no number either
    other = run(store_2747(), line_decisions=[event(ELEC_KC, "input|activity.total|company", "edited", 1.0, "MWh")],
                **settings)
    assert other["categories"] == plain["categories"]
    assert line_of(other, ELEC_KC)["results"] == line_of(plain, ELEC_KC)["results"]


def test_the_company_region_alone_moves_only_the_company_side() -> None:
    settings: dict[str, Any] = {"grid_regions": {**REGIONS, "Kansas City Plant": "CAMX"}, "reported_activity": COMPANY_KWH}
    plain = run(store_2747(), **settings)
    decided = run(store_2747(), line_decisions=[event(ELEC_KC, COMPANY, "edited", "NWPP")], **settings)
    assert decided["categories"] == plain["categories"] and decided["scope_totals"] == plain["scope_totals"]
    a, b = line_of(plain, ELEC_KC)["results"], line_of(decided, ELEC_KC)["results"]
    assert {k: v for k, v in b.items() if not k.startswith(("company", "difference"))} == \
        {k: v for k, v in a.items() if not k.startswith(("company", "difference"))}


# --- hostile company regions ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "   ", "x" * 5000, "NWPP\x00", "'; DROP TABLE regions;--", "West", "NW", "N/A",
                                  "WECC", "ＮＷＰ", "🙂", "CAMX2", "0.054", "null"])
def test_a_company_region_that_names_no_subregion_is_shown_never_used(text: str) -> None:
    assert electricity.code_of(text, REF) is None
    store = store_2747()
    base = run(store, grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH)
    response = run(store, grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH,
                   line_decisions=[event(ELEC_KC, COMPANY, "edited", text)])
    line = line_of(response, ELEC_KC)
    assert line["results"] == line_of(base, ELEC_KC)["results"]  # our factors, exactly as before
    if text.strip():
        assert line["trace"]["inputs"]["grid_region"]["company"]["value"] == text.strip()
        assert "company_grid_region_not_recognised" in line["trace"]["flags"]
    assert line["trace"]["result"]["recomputed"] == pytest.approx(545.9435, abs=5e-5)


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_a_pending_or_rejected_company_region_is_not_the_company_region(status: str) -> None:
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH,
                   line_decisions=[event(ELEC_KC, COMPANY, status, "NWPP")])
    grid = line_of(response, ELEC_KC)["trace"]["inputs"]["grid_region"]
    assert grid["company"]["status"] == "not_reported"


def test_a_company_region_on_another_line_or_a_wrong_orgs_line_is_never_applied() -> None:
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH,
                   line_decisions=[event("s2:purchased_energy:electricity:fac-elsewhere", COMPANY, "edited", "NWPP")])
    assert line_of(response, ELEC_KC)["results"]["company_total_co2e_t"] == pytest.approx(545.9435, abs=5e-5)
    assert len(response["calculation_line_decisions"]["orphaned"]) == 1


def test_the_recomputed_grid_region_is_still_not_decidable() -> None:
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"},
                   line_decisions=[event(ELEC_KC, "input|grid_region|recomputed", "edited", "NWPP")])
    line = line_of(response, ELEC_KC)
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["set_elsewhere"]
    assert line["trace"]["result"]["recomputed"] == pytest.approx(545.9435, abs=5e-5)
    assert line["trace"]["inputs"]["grid_region"]["decidable"] is False


# --- a ZIP code in two subregions is a choice ---------------------------------------------------------------------
def test_a_zip_in_two_subregions_is_a_choice_with_one_option_each_and_the_region_in_use_chosen() -> None:
    response = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    trace = line_of(response, ELEC_KC)["trace"]
    choice = next(c for c in trace["choices"] if c["id"] == "grid_region")
    assert [o["id"] for o in choice["options"]] == ["RFCE", "NYUP"] and all(o["available"] for o in choice["options"])
    assert choice["chosen"] == "RFCE" and choice["chosen_by"] == "default"
    assert block(trace, "grid_region")["choice_id"] == "grid_region"
    assert "ZIP 07401" in choice["options"][0]["citation"]["citation"]
    jsonschema.validate(trace, SCHEMA)


@pytest.mark.parametrize("facility", [CA, OR, KC])
def test_a_zip_with_one_subregion_or_none_is_no_choice(facility: dict[str, Any]) -> None:
    regions = {"Kansas City Plant": "CAMX"} if facility is KC else {}
    trace = line_of(run_at(facility, store_2747(), grid_regions=regions), ELEC_KC)["trace"]
    assert all(c["id"] != "grid_region" for c in trace["choices"])


def test_choosing_the_other_subregion_moves_the_line_the_category_and_the_market_based_total() -> None:
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    pick = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"}, line_decisions=[pick])
    line, old = line_of(after, ELEC_KC), line_of(before, ELEC_KC)
    gwp = {"CO2": 1, "CH4": 28, "N2O": 265}
    expected = sum(mass("NYUP", g) * gwp[g] for g in gwp)
    assert sum(mass("RFCE", g) * gwp[g] for g in gwp) == pytest.approx(old["results"]["total_co2e_t"], rel=1e-12)
    assert line["results"]["total_co2e_t"] == pytest.approx(expected, rel=1e-12)
    assert line["trace"]["result"]["recomputed"] == pytest.approx(expected, rel=1e-12)
    for gas in gwp:
        assert line["results"]["mass_t"][gas] == pytest.approx(mass("NYUP", gas), rel=1e-12)
        assert block(line["trace"], f"emissions.{gas}")["recomputed"]["result"]["value"] == pytest.approx(
            mass("NYUP", gas), rel=1e-12)
    category = after["categories"]["purchased_electricity_location_based"]
    assert category["total_co2e"] == pytest.approx(expected, rel=1e-9)
    assert category["total_co2e"] != before["categories"]["purchased_electricity_location_based"]["total_co2e"]
    market = after["categories"]["purchased_electricity_market_based"]["total_co2e"]
    assert market == pytest.approx(expected, rel=1e-9)  # no certificates: market-based = location-based
    grid = line["trace"]["inputs"]["grid_region"]
    assert grid["recomputed"]["value"] == "NYUP" and grid["recomputed"]["status"] == "edited"
    assert grid["recomputed"]["source"]["by"] == "Rev Iewer"
    choice = next(c for c in line["trace"]["choices"] if c["id"] == "grid_region")
    assert (choice["chosen"], choice["chosen_by"]) == ("NYUP", "reviewer")
    ef = line["trace"]["inputs"]["ef.CO2"]["recomputed"]
    assert ef["value"] == REF.electricity("NYUP")["CO2"].value and ef["source"]["kind"] == "reference"
    assert "Table 6" in ef["source"]["citation"]
    assert line["decisions"]["applied"][0]["value"] == "NYUP" and line["decisions"]["not_applied"] == []
    assert "reviewer_decisions_applied" in line["flags"]
    jsonschema.validate(line["trace"], SCHEMA)


def test_choosing_the_subregion_already_used_changes_no_number() -> None:
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"},
                   line_decisions=[event(ELEC_KC, REGION_CHOICE, "edited", "RFCE")])
    assert after["categories"] == before["categories"]
    assert line_of(after, ELEC_KC)["results"] == line_of(before, ELEC_KC)["results"]


def test_the_picked_subregion_changes_differs_against_the_company() -> None:
    settings: dict[str, Any] = {"grid_regions": {"Kansas City Plant": "RFCE"}, "reported_activity": COMPANY_KWH}
    entered = event(ELEC_KC, COMPANY, "edited", "NYUP")
    same = line_of(run_at(NJ, store_2747(), line_decisions=[entered], **settings), ELEC_KC)["trace"]
    assert same["inputs"]["grid_region"]["differs"] is True
    pick = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    trace = line_of(run_at(NJ, store_2747(), line_decisions=[entered, pick], **settings), ELEC_KC)["trace"]
    assert trace["inputs"]["grid_region"]["differs"] is False
    assert block(trace, "grid_region")["recomputed"]["result"]["differs"] is False
    assert trace["result"]["difference"] == pytest.approx(0.0, abs=1e-9)  # both on NYUP now


def test_a_factor_the_reviewer_decided_separately_wins_over_the_picked_subregions() -> None:
    settings: dict[str, Any] = {"grid_regions": {"Kansas City Plant": "RFCE"}}
    pick = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    own = event(ELEC_KC, "input|ef.CO2|recomputed", "edited", 400.0, "lb/MWh")
    trace = line_of(run_at(NJ, store_2747(), line_decisions=[pick, own], **settings), ELEC_KC)["trace"]
    assert block(trace, "emissions.CO2")["recomputed"]["result"]["value"] == pytest.approx(2747 * 400.0 / LB_PER_T,
                                                                                          rel=1e-12)
    assert block(trace, "emissions.CH4")["recomputed"]["result"]["value"] == pytest.approx(mass("NYUP", "CH4"),
                                                                                          rel=1e-12)
    assert trace["inputs"]["ef.CO2"]["recomputed"]["status"] == "edited"


@pytest.mark.parametrize("option", ["XXXX", "", "nyup", "CAMX", None, 7])
def test_an_option_that_is_not_one_of_the_zips_subregions_is_not_applied(option: Any) -> None:
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"},
                   line_decisions=[event(ELEC_KC, REGION_CHOICE, "edited", option)])
    assert after["categories"] == before["categories"]
    assert [n["reason"] for n in line_of(after, ELEC_KC)["decisions"]["not_applied"]] == ["option_not_available"]


def test_a_decision_made_before_the_automatic_region_changed_is_stale_not_applied() -> None:
    pick = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    pick["record"]["decision"]["basis"] = json.dumps({"chosen": "NYUP"})  # when it was made the line used NYUP
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"}, line_decisions=[pick])
    assert after["categories"] == before["categories"]
    assert [n["reason"] for n in line_of(after, ELEC_KC)["decisions"]["not_applied"]] == ["stale"]


def test_a_rejected_or_pending_region_choice_leaves_every_number() -> None:
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    for status in ("rejected", "pending"):
        after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"},
                       line_decisions=[event(ELEC_KC, REGION_CHOICE, status, "NYUP")])
        assert after["categories"] == before["categories"]


def test_the_setup_region_outside_the_zips_subregions_is_still_an_option() -> None:
    nj = {**NJ, "gridRegion": "CAMX"}
    trace = line_of(run_at(nj, store_2747()), ELEC_KC)["trace"]
    choice = next(c for c in trace["choices"] if c["id"] == "grid_region")
    assert [o["id"] for o in choice["options"]] == ["RFCE", "NYUP", "CAMX"] and choice["chosen"] == "CAMX"
    assert trace["inputs"]["grid_region"]["recomputed"]["source"]["from"] == ["set in Setup"]


def test_a_picked_subregion_the_category_cannot_count_is_reported_and_leaves_every_number(
        monkeypatch: pytest.MonkeyPatch) -> None:
    before = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"})
    monkeypatch.setattr(line_totals, "adds_up", lambda sums, category: False)
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"},
                   line_decisions=[event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")])
    line = line_of(after, ELEC_KC)
    assert after["categories"] == before["categories"] and after["scope_totals"] == before["scope_totals"]
    assert line["results"] == line_of(before, ELEC_KC)["results"]
    assert line["trace"]["result"] == line_of(before, ELEC_KC)["trace"]["result"]  # the working shown is counted
    assert line["trace"]["inputs"]["grid_region"]["recomputed"]["value"] == "RFCE"
    assert [n["reason"] for n in line["decisions"]["not_applied"]] == ["category_does_not_add_up"]
    assert line["decisions"]["applied"] == []


def test_a_no_evidence_line_with_a_two_subregion_zip_and_no_region_is_blocked_and_says_which() -> None:
    response = run_at(NJ, FakeStore(), reported_activity=COMPANY_KWH)
    trace = line_of(response, ELEC_KC)["trace"]
    assert trace["state"] == "blocked" and trace["blocking"][0]["input_id"] == "grid_region"
    assert "RFCE or NYUP" in trace["blocking"][0]["message"]
    jsonschema.validate(trace, SCHEMA)
    # with evidence the facility is not calculated at all: Recalculation inputs asks, with the same two options
    asked = [n for n in run_at(NJ, store_2747())["needs_input"] if n["kind"] == "grid_region"]
    assert asked[0]["options"] == ["RFCE", "NYUP"]


@pytest.mark.parametrize("text", ["NW\u200bPP", "\u202eNWPP", "NWPP\ufeff", "N\u2066WPP", "NWPP\u200d"])
def test_hidden_and_bidi_characters_never_pass_for_a_region_code(text: str) -> None:
    assert electricity.code_of(text, REF) is None
    base = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH)
    response = run(store_2747(), grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}, reported_activity=COMPANY_KWH,
                   line_decisions=[event(ELEC_KC, COMPANY, "edited", text)])
    line = line_of(response, ELEC_KC)
    shown = line["trace"]["inputs"]["grid_region"]["company"]["value"]
    assert "\ufffd" in shown and not electricity._HIDDEN.search(shown)  # each one is marked, not drawn
    assert "company_grid_region_not_recognised" in line["trace"]["flags"]
    assert line["results"] == line_of(base, ELEC_KC)["results"]


def test_the_pick_uses_the_reference_the_engine_ran_on(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> None:
        raise AssertionError("the default reference must not be read")

    monkeypatch.setattr(decisions, "default_emission_factor_reference", refuse)
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"},
                   line_decisions=[event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")])
    assert line_of(after, ELEC_KC)["decisions"]["not_applied"] == []
    assert line_of(after, ELEC_KC)["trace"]["inputs"]["grid_region"]["recomputed"]["value"] == "NYUP"


def test_the_working_sheet_says_who_chose_the_region_and_why() -> None:
    pick_ = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    after = run_at(NJ, store_2747(), grid_regions={"Kansas City Plant": "RFCE"}, line_decisions=[pick_])
    steps = [st for ln in after["categories"]["purchased_electricity_location_based"]["lines"] for st in ln["steps"]
             if st["label"].startswith("Decided choice: Grid region")]
    assert len(steps) == 1
    source = steps[0]["inputs"]["grid region"]
    assert source["value"] == "NYUP"
    assert "decided by Rev Iewer on 2026-11-26T10:00:00Z" in source["source"]
    assert "Corrected from the invoice" in source["source"]


def _all_three_store() -> FakeStore:
    store = FakeStore()
    store.add_document("S", "CT-S1-FUELQTY", [{**_gas_record(1000, fuel="coal"), "activity_quantity": (1000, "short_ton"),
                                               "activity_unit": ("short_ton", None)}])
    store.add_document("E", "CT-S2-ELEC", [_elec_record(2747, start="2025-01-01", end="2025-12-31")])
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(380000)])
    return store


def test_a_region_pick_applies_fully_beside_the_equation_choices_and_the_fuel_economy() -> None:
    settings: dict[str, Any] = {"grid_regions": {"Kansas City Plant": "RFCE"}, "vehicle_groups": [GROUP_7MPG], **COAL_KW}
    region = event(ELEC_KC, REGION_CHOICE, "edited", "NYUP")
    equation = [hhv(), pick("CO2", "eq_2")]
    economy = event(DIESEL, ECONOMY, "edited", 6.55, "mi/gal")
    base = run_at(NJ, _all_three_store(), **settings)
    only = {name: run_at(NJ, _all_three_store(), line_decisions=d, **settings)
            for name, d in (("region", [region]), ("equation", equation), ("economy", [economy]))}
    every = run_at(NJ, _all_three_store(), line_decisions=[region, *equation, economy], **settings)
    for category in ("purchased_electricity_location_based", "stationary_combustion", "mobile_combustion"):
        delta = sum(r["categories"][category]["total_co2e"] - base["categories"][category]["total_co2e"]
                    for r in only.values())
        assert every["categories"][category]["total_co2e"] - base["categories"][category]["total_co2e"] == \
            pytest.approx(delta, rel=1e-9)
    # the region moved its own category only, and the others moved without it
    assert only["region"]["categories"]["stationary_combustion"] == base["categories"]["stationary_combustion"]
    assert only["equation"]["categories"]["purchased_electricity_location_based"] == \
        base["categories"]["purchased_electricity_location_based"]
    line = line_of(every, ELEC_KC)
    assert line["decisions"]["not_applied"] == []
    assert line["trace"]["inputs"]["grid_region"]["recomputed"]["value"] == "NYUP"
    # the equation routes are C1's alone: the coal line keeps its eq_2 and the electricity line has none
    coal = line_of(every, COAL)["trace"]
    assert next(c for c in coal["choices"] if c["id"] == "equation:CO2")["chosen"] == "eq_2"
    assert line_of(every, DIESEL)["trace"]["inputs"]["fuel_economy"]["recomputed"]["value"] == 6.55


# --- the helper: reading a region from text ---------------------------------------------------------------------------
def test_code_of_never_guesses() -> None:
    assert electricity.code_of("NWPP; DROP TABLE", REF) is None and electricity.code_of("NWPP WECC Southwest", REF) is None
    assert electricity.code_of("CAMX", REF) == "CAMX"
    assert electricity.code_of("WECC California", REF) == "CAMX"
    assert electricity.code_of("camx - wecc california", REF) == "CAMX"
    assert electricity.code_of(None, REF) is None and electricity.code_of(12, REF) is None
    assert electricity.code_of("WECC", REF) is None  # a region family, not a subregion
