"""Calculation lines: biomass, company figures without evidence, unplaced reasons, failures, validation."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import emissions_calculator as calc
from backend.app.services import recalculation_lines
from backend.app.services.engagement_recalculation_service import validate_recalculation_settings
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.services.test_calculation_lines import GAS_KC, GAS_STL
from backend.tests.services.test_calculation_lines import _elec as _elec_record
from backend.tests.services.test_calculation_lines import _gas as _gas_record
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _own
from backend.tests.services.test_recalculation_lines import (
    GROUP_OFF,
    GROUP_ROAD,
    REGIONS,
    _by_key,
    _engagement,
    _gas_store,
    _mobile_store,
    _run,
    _service,
)


def test_vehicle_group_line_keys_equal_the_evidence_tree_keys() -> None:
    store = _mobile_store()
    engagement = _engagement(recalculation={"vehicle_groups": [GROUP_ROAD, GROUP_OFF]})
    tree_keys = {line["key"] for line in EvidenceTreeService(store, store, store).tree(engagement, _own)["lines"]
                 if line["category"] == "mobile"}
    recalc_keys = {ln["key"] for ln in _service(store).recalculate(engagement, _own)["calculation_lines"]}
    assert recalc_keys == tree_keys == {"s1:mobile:diesel-fuel:vg-heavy-trucks", "s1:mobile:diesel-fuel:vg-forklifts"}


def _biomass_store() -> FakeStore:
    store = FakeStore()
    store.add_document("WOOD", "CT-S1-FUELQTY", [{**_gas_record(100, fuel="biomass"),
                                                   "activity_quantity": (100, "short_ton")}])
    store.add_document("GAS", "CT-S1-FUELQTY", [_gas_record(1000)])
    return store


WOOD = "biogenic:biogenic:wood-and-wood-residuals:fac-kc01"


def test_every_lines_step_three_co2e_adds_up_to_its_sum_on_both_sides_including_biomass() -> None:
    result = _run(_biomass_store(), fuel_choices={"stationary:biomass": "Wood and Wood Residuals"},
                  reported_activity={GAS_KC: {"quantity": 900, "unit": "MMBtu"},
                                     WOOD: {"quantity": 50, "unit": "short_ton"}})
    wood = _by_key(result)[WOOD]
    co2 = next(g for g in wood["step3"]["gases"] if g["gas"] == "CO2")
    assert co2["biogenic"] is True and co2["co2e_t"] == 0 and co2["mass_t"] > 0
    assert co2["mass_t"] == pytest.approx(wood["results"]["biogenic_co2_t"])
    company_co2 = next(g for g in wood["company"]["step3"]["gases"] if g["gas"] == "CO2")
    assert company_co2["biogenic"] is True and company_co2["co2e_t"] == 0
    assert company_co2["mass_t"] == pytest.approx(co2["mass_t"] / 2)
    assert co2["company_co2e_t"] == 0
    assert any(ln["company"] for ln in result["calculation_lines"])
    for line in result["calculation_lines"]:
        assert sum(g["co2e_t"] for g in line["step3"]["gases"]) == pytest.approx(line["results"]["sum_co2e_t"])
        if line["company"]:
            assert sum(g["co2e_t"] for g in line["company"]["step3"]["gases"]) == pytest.approx(
                line["company"]["results"]["sum_co2e_t"])
            assert sum(g["company_co2e_t"] for g in line["step3"]["gases"]) == pytest.approx(
                line["company"]["results"]["sum_co2e_t"])


def test_status_uses_the_lines_own_reported_value_as_base_even_when_the_category_has_one() -> None:
    line = _by_key(_run(_gas_store(), reported={"stationary_combustion_total": 1_000_000},
                        reported_lines={GAS_KC: 3000}))[GAS_KC]
    assert line["status"] == "above"
    assert line["difference_pct_of_base"] == pytest.approx(line["difference_t"] / 3000 * 100)


def test_company_figures_for_a_line_with_no_evidence_give_a_zero_line_and_the_gap() -> None:
    store = FakeStore()
    store.add_document("OTHER", "CT-S1-FUELQTY", [_gas_record(10)])
    key = "s1:stationary:natural-gas:fac-stl2"
    result = _run(store, reported_lines={key: 120.0, "s1:stationary:natural-gas:fac-nowhere": 5},
                  reported_activity={key: {"quantity": 1000, "unit": "therms"}})
    line = _by_key(result)[key]
    assert "no_evidence" in line["flags"] and line["results"]["total_co2e_t"] == 0
    assert line["step1"]["rows"] == [] and line["step1"]["total"]["quantity"] == 0
    assert line["difference_t"] == -120 and line["status"] == "above"
    assert line["company"]["step2"]["result"]["quantity"] == pytest.approx(100)
    assert line["company"]["results"]["total_co2e_t"] > 5000 * 0.0 + 5000 / 1000  # 100 MMBtu x 53.06 kg
    # Only a key that matches nothing is "unknown".
    assert result["calculation_line_inputs"]["unknown_line_keys"] == [
        {"setting": "reported_lines", "key": "s1:stationary:natural-gas:fac-nowhere"}]


def test_implied_fuel_economy_is_withheld_when_the_fuel_is_shared_and_non_road_has_no_distance() -> None:
    result = _run(_mobile_store(), vehicle_groups=[GROUP_ROAD, GROUP_OFF])
    road = _by_key(result)["s1:mobile:diesel-fuel:vg-heavy-trucks"]
    assert road["step2"]["distance"]["quantity"] == 10000 and road["step2"]["implied_fuel_economy"] is None
    assert _by_key(result)["s1:mobile:diesel-fuel:vg-forklifts"]["step2"]["distance"] is None


def test_unplaced_reasons_say_why() -> None:
    mobile = _run(_mobile_store(), vehicle_groups=[GROUP_ROAD, GROUP_OFF])["calculation_unplaced"]
    assert [u["reason"] for u in mobile] == ["fuel_shared_by_vehicle_groups"]
    store = _gas_store()
    store.add_document("NOPLANT", "CT-S1-FUELQTY", [_gas_record(5, plant="Somewhere Else Ltd")])
    assert [u["reason"] for u in _run(store)["calculation_unplaced"]] == ["no_facility_match"]
    moved = _run(_gas_store(), {"GAS-STL": {"placements": [{"from": GAS_STL, "to": "block:summary"}]}})
    assert [u["reason"] for u in moved["calculation_unplaced"]] == ["moved_to_another_place"]
    gone = _run(_gas_store(), {"GAS-STL": {"placements": [{"from": GAS_STL, "to": "s1:stationary:coal:fac-x"}]}})
    assert [u["reason"] for u in gone["calculation_unplaced"]] == ["unknown_line"]


def test_mixed_units_rows_add_up_to_the_total_in_the_total_unit() -> None:
    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [{**_gas_record(1000), "activity_quantity": (1000, "therm")}])
    store.add_document("B", "CT-S1-FUELQTY", [_gas_record(50, "2025-02-01", "2025-02-28")])
    step1 = _by_key(_run(store))[GAS_KC]["step1"]
    assert step1["total"] == {"quantity": pytest.approx(150), "unit": "MMBtu"}
    assert sum(r["counted_in_base"] for r in step1["rows"]) == pytest.approx(150)


def test_inputs_incomplete_and_the_unknown_facility_ids_are_reported() -> None:
    store = _gas_store()
    store.add_document("COAL", "CT-S1-FUELQTY", [_gas_record(5, fuel="coal")])  # needs an EPA fuel choice
    result = _service(store).recalculate(_engagement(recalculation={"consolidated_shares": {"fac-zzz": 50}}), _own)
    assert result["calculation_lines"] and all(ln["inputs_incomplete"] for ln in result["calculation_lines"])
    assert result["calculation_line_inputs"]["unknown_facility_ids"] == ["fac-zzz"]
    assert not any(ln["inputs_incomplete"] for ln in _run(_gas_store())["calculation_lines"])


def test_a_failure_building_the_lines_is_a_needs_input_item_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(recalculation_lines, "build", boom)
    result = _run(_gas_store())
    assert result["calculation_lines"] == []
    assert [i["kind"] for i in result["needs_input"]] == ["calculation_lines"]
    assert result["categories"]["stationary_combustion"] is not None


def test_a_failed_run_keeps_the_line_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    real = calc.stationary_combustion
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] > 2:  # the category's own two runs work; the line's run fails
            raise calc.CalculationError("no")
        return real(*args, **kwargs)

    store = FakeStore()
    store.add_document("A", "CT-S1-FUELQTY", [_gas_record(10)])
    monkeypatch.setattr(calc, "stationary_combustion", flaky)
    line = _by_key(_run(store))[GAS_KC]
    assert "calculation_failed" in line["flags"] and line["results"]["total_co2e_t"] == 0


def test_the_existing_response_is_unchanged_by_the_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _gas_store()
    store.add_document("E", "CT-S2-ELEC", [_elec_record(10, start="2025-01-01", end="2025-12-31")])
    settings: dict[str, Any] = {"grid_regions": REGIONS, "vehicle_groups": [GROUP_ROAD], "reported_lines": {GAS_KC: 1}}
    with_lines = _run(store, **settings)
    monkeypatch.setattr(recalculation_lines, "build", lambda *a, **k: recalculation_lines.Built())
    without = _run(store, **settings)
    for key in ("calculation_lines", "calculation_unplaced", "calculation_line_inputs"):
        with_lines.pop(key)
        without.pop(key)
    assert with_lines == without


def test_line_inputs_validation_rejects_nan_bad_keys_and_too_many_shares() -> None:
    for bad in ({"reported_lines": {GAS_KC: float("nan")}}, {"reported_lines": {"not a key!": 1}},
                {"reported_activity": {GAS_KC: {"quantity": float("inf"), "unit": "gal"}}},
                {"consolidated_shares": {f"f{i}": 1 for i in range(501)}}):
        with pytest.raises(ValueError):
            validate_recalculation_settings(bad)
