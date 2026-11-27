"""Traces of today's calculation lines: totals unchanged, EPA Hub numbers exact, schema valid."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from backend.app.services.calc_trace import ops
from backend.tests.services.calc_trace.recalc_scenarios import GROUP_ROAD, REGIONS, run, scenarios
from backend.tests.services.test_calculation_lines import ELEC_KC, GAS_KC
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _diesel_purchase

DATA = Path(__file__).parents[1] / "data"
SCHEMA = json.loads((Path(__file__).parents[4] / "contracts" / "calculation_trace.schema.json").read_text())
BEFORE = json.loads((DATA / "recalculation_before_trace.json").read_text())


def _strip(value: Any) -> Any:
    """The response as it was before traces existed: the added ``trace`` keys removed."""

    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "trace"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _settled(value: Any) -> Any:
    """Floats to 12 significant digits: Python 3.12's ``sum`` adds floats more precisely than 3.11's, so the last
    binary digits of a total differ between the two; nothing a reader would ever see does."""

    if isinstance(value, float):
        return float(format(value, ".12g"))
    if isinstance(value, dict):
        return {k: _settled(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_settled(v) for v in value]
    return value


def _digest(response: dict) -> str:
    settled = _settled(response)
    return hashlib.sha256(json.dumps(settled, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_the_default_response_is_byte_identical_to_before_traces_existed(name: str) -> None:
    """``recalculation_before_trace.json`` was produced by the code before traces were added (same scenarios).
    The default recalculation response, with nothing stripped, hashes the same, every total included."""

    response = scenarios(with_traces=False)[name]
    assert "trace" not in json.dumps(response)
    assert _digest(response) == BEFORE[name]["sha256"]
    for category, total in BEFORE[name]["categories"].items():
        assert (response["categories"][category] or {}).get("total_co2e") == pytest.approx(total, rel=1e-12)


@pytest.mark.parametrize("name", sorted(BEFORE))
def test_asking_for_traces_changes_nothing_but_adds_them(name: str) -> None:
    assert _digest(_strip(scenarios(with_traces=True)[name])) == BEFORE[name]["sha256"]
    assert _strip(scenarios(with_traces=True)[name]) == scenarios(with_traces=False)[name]  # exact, same run


def test_trace_is_purely_additive_on_the_lines() -> None:
    for response in scenarios().values():
        for line in response["calculation_lines"]:
            assert "trace" in line
            assert line["trace"]["result"]["recomputed"] == line["results"]["total_co2e_t"]


def test_every_trace_validates_against_the_schema_and_reproduces_the_calculator() -> None:
    seen = 0
    for response in scenarios().values():
        for line in response["calculation_lines"]:
            trace = line["trace"]
            assert trace is not None and trace["line_key"] == line["key"] and trace["state"] == "complete"
            jsonschema.validate(trace, SCHEMA)
            json.dumps(trace)
            gases = {g["gas"]: g for g in line["step3"]["gases"]}
            for block in trace["steps"][2]["blocks"]:  # Step 3: mass per gas
                assert block["recomputed"]["result"]["value"] == pytest.approx(
                    gases[block["id"].split(".")[1]]["mass_t"], rel=1e-9)
            seen += 1
    assert seen == 19


def test_unplaced_and_unknown_lines_carry_no_trace() -> None:
    store = FakeStore()
    store.add_document("G", "CT-S1-FUELQTY", [_gas_record(10, plant="Nowhere Plant")])
    result = run(store)
    for item in result["calculation_unplaced"]:
        assert item["trace"] is None


def test_a_line_with_no_evidence_is_blocked_or_partial_never_invented() -> None:
    result = run(FakeStore(), reported_activity={GAS_KC: {"quantity": 650000, "unit": "therms"}})
    line = next(ln for ln in result["calculation_lines"] if ln["key"] == GAS_KC)
    assert line["trace"]["state"] in ("complete", "partial")
    assert line["trace"]["inputs"]["activity.total"]["recomputed"]["status"] == "awaiting_review"


def _line(response: dict, key: str) -> dict:
    return next(ln for ln in response["calculation_lines"] if ln["key"] == key)


def _block(trace: dict, step: str, block_id: str) -> dict:
    return next(b for s in trace["steps"] if s["id"] == step for b in s["blocks"] if b["id"] == block_id)


def test_natural_gas_650000_therms_matches_the_epa_hub_exactly() -> None:
    """Kent Cannery: 650,000 therm = 65,000 MMBtu; CO2 3,448.9 t, CH4 1.82 t CO2e, N2O 1.7225 t CO2e = 3,452.4425."""

    store = FakeStore()
    store.add_document("G", "CT-S1-FUELQTY", [{**_gas_record(650000), "activity_quantity": (650000, "therm")}])
    trace = _line(run(store), GAS_KC)["trace"]
    conversion = _block(trace, "conversion", "conversion")["recomputed"]
    assert [t["operand"]["value"] for t in conversion["terms"]] == [650000, pytest.approx(0.1)]
    assert conversion["result"]["value"] == pytest.approx(65000)
    co2 = _block(trace, "emissions", "emissions.CO2")["recomputed"]
    assert [t["operand"]["value"] for t in co2["terms"]][1:] == [53.06, 0.001]
    assert co2["result"]["value"] == pytest.approx(3448.9, abs=1e-9)
    gwp = {g: _block(trace, "gwp", f"gwp.{g}")["recomputed"]["result"]["value"] for g in ("CO2", "CH4", "N2O")}
    assert gwp == {"CO2": pytest.approx(3448.9), "CH4": pytest.approx(1.82), "N2O": pytest.approx(1.7225)}
    assert trace["result"]["recomputed"] == pytest.approx(3452.4425, abs=1e-9)
    assert trace["inputs"]["ef.CO2"]["recomputed"]["source"]["table"] == "Table 1"
    assert trace["inputs"]["ef.CO2"]["recomputed"]["source"]["row"] == 38


def test_diesel_380000_gal_co2_is_3879_8_t() -> None:
    store = FakeStore()
    store.add_document("F", "CT-S1-MOBFUEL", [_diesel_purchase(380000)])
    trace = _line(run(store, vehicle_groups=[{**GROUP_ROAD, "distance": 100000}]),
                  "s1:mobile:diesel-fuel:vg-heavy-trucks")["trace"]
    co2 = _block(trace, "emissions", "emissions.CO2")["recomputed"]
    assert co2["result"]["value"] == pytest.approx(3879.8, abs=1e-9)
    ch4 = _block(trace, "emissions", "emissions.CH4")["recomputed"]  # driven by distance (Eq. 4), not fuel
    assert ch4["terms"][0]["operand"]["input_id"] == "distance" and ch4["terms"][0]["operand"]["unit"] == "mi"
    assert trace["inputs"]["distance"]["recomputed"]["value"] == 100000


def test_electricity_2747_mwh_in_camx_matches_egrid() -> None:
    """eGRID2023 CAMX: 436.655 / 0.025 / 0.003 lb per MWh -> 544.0807 / 0.0311505 / 0.0037381 t."""

    store = FakeStore()
    store.add_document("E", "CT-S2-ELEC", [_elec_record(2747, start="2025-01-01", end="2025-12-31")])
    trace = _line(run(store, grid_regions={**REGIONS, "Kansas City Plant": "CAMX"}), ELEC_KC)["trace"]
    mass = {g: _block(trace, "emissions", f"emissions.{g}")["recomputed"]["result"]["value"]
            for g in ("CO2", "CH4", "N2O")}
    assert mass["CO2"] == pytest.approx(544.0807, abs=5e-5)
    assert mass["CH4"] == pytest.approx(0.0311505, abs=5e-8)
    assert mass["N2O"] == pytest.approx(0.0037381, abs=5e-8)
    assert trace["result"]["recomputed"] == pytest.approx(545.9435, abs=5e-4)
    assert trace["inputs"]["grid_region"]["recomputed"]["value"] == "CAMX"
    assert [t["operand"]["value"] for t in _block(trace, "emissions", "emissions.CO2")["recomputed"]["terms"]][:2] == [
        2747, 436.655]


def test_company_side_differences_are_computed_by_the_server() -> None:
    """Company runs 1,000 MWh against our 1,200: the activity step shows the same unit's difference."""

    line = _line(scenarios()["company"], ELEC_KC)
    trace = line["trace"]
    assert trace["result"]["company"] == pytest.approx(line["results"]["company_total_co2e_t"])
    assert trace["result"]["difference"] == pytest.approx(line["results"]["difference_to_company_t"])
    co2 = _block(trace, "emissions", "emissions.CO2")
    activity = co2["recomputed"]["terms"][0]["operand"]
    assert co2["company"]["terms"][0]["operand"]["value"] == 1000
    assert activity["value"] == pytest.approx(1200) and activity["difference"] == pytest.approx(200)
    assert activity["differs"] is True
    ef = co2["recomputed"]["terms"][1]["operand"]
    assert ef["difference"] == 0 and ef["differs"] is False
    # Step 1 is in kWh on both sides, so its difference is made; a company figure in another unit would get none.
    assert trace["inputs"]["activity.total"]["company"]["unit"] == "kWh"
    assert trace["inputs"]["activity.total"]["difference"] == pytest.approx(200000)


def test_consolidated_share_is_an_input_and_scales_the_total_only() -> None:
    trace = _line(scenarios()["share"], GAS_KC)["trace"]
    assert trace["inputs"]["share"]["recomputed"]["value"] == 60.0
    total = _block(trace, "results", "results.total")["recomputed"]
    assert total["terms"][1]["operand"]["value"] == pytest.approx(0.6)
    assert total["result"]["value"] == pytest.approx(0.6 * _block(trace, "results", "results.sum")["recomputed"]
                                                     ["result"]["value"])


def test_a_trace_that_cannot_reproduce_the_calculator_is_dropped_not_repaired(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.calc_trace import _line as builder

    def boom(*_a: Any, **_k: Any) -> None:
        raise ops.TraceError("mismatch")

    monkeypatch.setattr(builder.ops, "verify", boom)
    for line in scenarios()["plain"]["calculation_lines"]:
        assert line["trace"] is None  # the line itself and its totals are untouched
        assert line["results"]["total_co2e_t"] > 0


def test_a_line_trace_stays_small_enough_to_fetch_on_expanding_a_line() -> None:
    """A line's trace is fetched on its own (never carried on the recalculation response). Unset fields are
    left out, so a line with 12 monthly bills and company figures is about 20 KB; this guards against growth."""

    from backend.tests.services.test_engagement_recalculation_service import FakeStore as Store

    store = Store()
    for month in range(1, 13):
        store.add_document(f"G{month}", "CT-S1-FUELQTY", [_gas_record(1000 + month, f"2025-{month:02d}-01",
                                                                      f"2025-{month:02d}-28")])
    line = _line(run(store, reported_activity={GAS_KC: {"quantity": 13000, "unit": "MMBtu"}}), GAS_KC)
    size = len(json.dumps(line["trace"], separators=(",", ":")).encode())
    assert len(line["trace"]["inputs"]["activity.total"]["rows"]) == 12
    assert size < 25_000, size


def test_the_frontend_fixture_is_the_backends_current_trace() -> None:
    """``calcTraceStationary.json`` (read by the TypeScript contract test) must be what the backend builds now."""

    from backend.tests.services.test_engagement_recalculation_service import FakeStore as Store

    store = Store()
    store.add_document("GAS-KC", "CT-S1-FUELQTY", [{**_gas_record(650000), "activity_quantity": (650000, "therm")}])
    live = _line(run(store, reported_activity={GAS_KC: {"quantity": 650000, "unit": "therms"}}), GAS_KC)["trace"]
    path = Path(__file__).parents[4] / "frontend" / "features" / "s1" / "api" / "__fixtures__" / "calcTraceStationary.json"
    assert json.loads(path.read_text()) == live


def test_gases_added_pairs_each_co2e_term_with_its_own_company_twin() -> None:
    """The sum block repeats the ``co2e`` column once per gas. Each recomputed term's difference must be
    against the same gas on the company side, not the last company term (which gave wrong, huge diffs)."""

    trace = _line(scenarios()["company"], ELEC_KC)["trace"]
    block = _block(trace, "results", "results.sum")
    mine, theirs = block["recomputed"]["terms"], block["company"]["terms"]
    assert len(mine) == len(theirs) == 3
    for ours, company in zip(mine, theirs):
        expected = ours["operand"]["value"] - company["operand"]["value"]
        assert ours["operand"]["difference"] == pytest.approx(expected, abs=1e-9)
        assert ours["operand"]["differs"] is True  # 1,200 MWh against 1,000 MWh moves every gas
    assert block["recomputed"]["result"]["difference"] == pytest.approx(
        block["recomputed"]["result"]["value"] - block["company"]["result"]["value"])
    # A pair that matches shows no difference, and the sum of the term differences is the result's.
    assert sum(t["operand"]["difference"] for t in mine) == pytest.approx(block["recomputed"]["result"]["difference"])


def _gas_trace(parts: int, recomputed_each: int, company_total: int) -> dict:
    from backend.tests.services.test_engagement_recalculation_service import FakeStore as Store

    store = Store()
    for month in range(1, parts + 1):
        store.add_document(f"G{month}", "CT-S1-FUELQTY", [_gas_record(recomputed_each, f"2025-{month:02d}-01",
                                                                      f"2025-{month:02d}-28")])
    line = _line(run(store, reported_activity={GAS_KC: {"quantity": company_total, "unit": "MMBtu"}}), GAS_KC)
    return line["trace"]


def test_step_one_total_carries_the_difference_from_the_builder() -> None:
    """Company 650,000 therms against our 600,000: the Step 1 total's own result says -50,000."""

    trace = _gas_trace(1, 600000, 650000)
    block = _block(trace, "activity", "activity")
    assert block["company"]["result"]["value"] == 650000
    assert block["recomputed"]["result"]["value"] == 600000
    assert block["recomputed"]["result"]["difference"] == pytest.approx(-50000)
    assert block["recomputed"]["result"]["differs"] is True
    assert trace["inputs"]["activity.total"]["difference"] == pytest.approx(-50000)


def test_step_one_with_twelve_parts_has_one_company_total_and_a_total_difference() -> None:
    """Twelve monthly bills are twelve terms and twelve input rows; the company gave one figure. The total's
    difference is made on the result, and no part is compared with the company's whole."""

    trace = _gas_trace(12, 50000, 650000)
    block = _block(trace, "activity", "activity")
    assert len(block["recomputed"]["terms"]) == 12 and len(trace["inputs"]["activity.total"]["rows"]) == 12
    assert len(block["company"]["terms"]) == 1
    assert block["recomputed"]["result"]["value"] == 600000
    assert block["recomputed"]["result"]["difference"] == pytest.approx(-50000)
    assert all("difference" not in t["operand"] for t in block["recomputed"]["terms"])
