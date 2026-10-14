"""Purchased steam, heat and cooling (CT-S2-THERMAL, workbook rows 48-50): read from district
energy bills and recalculated with the EPA Hub Table 7 factor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services import emissions_calculator as calc
from backend.app.services.engagement_recalculation_service import validate_recalculation_settings
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _engagement, _own, _service

STEAM_BILL = """Metro District Energy
Steam Service Statement
Account Number: MDE-44120
Service Address: 500 Atlantic Ave, Boston, MA 02110
Customer: Facility C
Service Period: 01/01/2025 to 01/31/2025
Steam Usage: 1,250 MMBtu
"""
HOT_WATER_BILL = STEAM_BILL.replace("Steam Service Statement", "District Heating Statement").replace(
    "Steam Usage: 1,250 MMBtu", "Hot Water Usage: 3,400 therms").replace("Metro District Energy", "Northside Thermal")
CHILLED_BILL = STEAM_BILL.replace("Steam Service Statement", "Chilled Water Statement").replace(
    "Steam Usage: 1,250 MMBtu", "Chilled Water Usage: 42,000 ton-hours")
STEAM_BY_WEIGHT = STEAM_BILL.replace("1,250 MMBtu", "980 Mlb")
GAS_BILL = """Riverside Gas Company
Natural Gas Bill
Account Number: RG-11
Service Period: 01/01/2025 to 01/31/2025
Total Usage: 1,200 therms
Heating degree days: 610
"""


def _read(tmp_path: Path, text: str) -> dict[str, Any]:
    path = tmp_path / "bill.txt"
    path.write_text(text)
    service = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                           extraction_result_repository=InMemoryExtractionResultRepository())
    out = service.process_local_document(str(path), engagement_id="ENG", persist_run=False)
    values = {c["field_name"]: (c["normalized_value"], c.get("unit")) for c in out["extraction_result"]["items"]}
    return {"type": out["pipeline_run"]["canonical_type_id"], "values": values}


@pytest.mark.parametrize(("text", "energy", "mmbtu"), [
    (STEAM_BILL, "steam", 1250), (HOT_WATER_BILL, "hot_water", 340), (CHILLED_BILL, "chilled_water", 504)])
def test_district_energy_bills_are_read_as_thermal_energy(tmp_path: Path, text: str, energy: str, mmbtu: float) -> None:
    read = _read(tmp_path, text)
    assert read["type"] == "CT-S2-THERMAL"
    assert read["values"]["energy_type"][0] == energy
    assert read["values"]["activity_quantity"] == (pytest.approx(mmbtu), "MMBtu")
    assert read["values"]["account_number"][0] == "MDE-44120"


def test_steam_by_weight_keeps_its_weight_and_a_gas_bill_stays_fuel(tmp_path: Path) -> None:
    assert _read(tmp_path, STEAM_BY_WEIGHT)["values"]["activity_quantity"] == (980, "klb")
    assert _read(tmp_path, GAS_BILL)["type"] == "CT-S1-FUELQTY"  # "heating degree days" is not a hot water bill


def _thermal(energy: str, quantity: float, unit: str, facility: str = "Facility C",
             start: str = "2025-01-01", end: str = "2025-01-31") -> dict[str, tuple]:
    return {"energy_type": (energy, None), "activity_quantity": (quantity, unit), "activity_unit": (unit, None),
            "facility_name": (facility, None), "service_period_start": (start, None),
            "service_period_end": (end, None), "account_number": ("MDE-44120", None)}


def test_steam_and_heat_are_recalculated_with_the_hub_table_7_factor() -> None:
    store = FakeStore()
    store.add_document("STEAM-JAN", "CT-S2-THERMAL", [_thermal("steam", 1250, "MMBtu")])
    store.add_document("HEAT-Q1", "CT-S2-THERMAL", [_thermal("hot_water", 340, "MMBtu", "Facility A",
                                                             "2025-01-01", "2025-03-31")])
    result = _service(store).recalculate(_engagement(recalculation={"reported": {"purchased_steam_total": 83.0}}), _own)
    steam = result["categories"]["purchased_steam_location_based"]
    expected = 1250 * 66.33 / 1000 + 1250 * 1.25 / 1e6 * 28 + 1250 * 0.125 / 1e6 * 265
    assert steam["total_co2e"] == pytest.approx(expected)
    assert "Table 7" in steam["lines"][0]["steps"][0]["inputs"]["EF"]["source"]
    market = result["categories"]["purchased_steam_market_based"]
    assert market["total_co2e"] == pytest.approx(expected)
    assert "no_supplier_factor_market_equals_location" in market["flags"]
    heating = result["categories"]["purchased_heating_location_based"]["total_co2e"]
    assert result["scope_totals"]["scope2_location"]["total_co2e"] == pytest.approx(expected + heating)
    comparison = next(c for c in result["comparisons"] if c["key"] == "purchased_steam_total")
    assert comparison["status"] == "within_tolerance" and comparison["workbook_row"] == 48
    rollup = result["rollup"]
    assert rollup["categories"]["purchased_steam"]["status"] == "calculated"
    assert rollup["nodes"]["purchased_heating_total"]["co2e_t"] == pytest.approx(heating)


def test_steam_by_weight_asks_for_its_heat_content_and_cooling_is_listed() -> None:
    store = FakeStore()
    store.add_document("STEAM-FEB", "CT-S2-THERMAL", [_thermal("steam", 980, "klb")])
    store.add_document("COOL-JUL", "CT-S2-THERMAL", [_thermal("chilled_water", 504, "MMBtu", "Facility B",
                                                              "2025-07-01", "2025-07-31")])
    asked = _service(store).recalculate(_engagement(), _own)
    kinds = {(i["kind"], i["category"]) for i in asked["needs_input"]}
    assert kinds == {("steam_heat_content", "purchased_steam"), ("cooling_factor", "purchased_cooling")}
    assert asked["categories"].get("purchased_steam_location_based") is None
    assert asked["rollup"]["categories"]["purchased_steam"]["status"] == "awaiting_inputs"

    answered = _service(store).recalculate(
        _engagement(recalculation={"steam_heat_content": {"Facility C": 1194}}), _own)
    steam = answered["categories"]["purchased_steam_location_based"]
    mmbtu = 980_000 * 1194 / 1e6
    assert steam["lines"][0]["mass_t"]["CO2"] == pytest.approx(mmbtu * 66.33 / 1000)


def test_steam_heat_content_is_validated() -> None:
    validate_recalculation_settings({"steam_heat_content": {"Facility C": 1194}})
    for bad in ({"steam_heat_content": {"Facility C": 50}}, {"steam_heat_content": {"Facility C": "1194"}},
                {"steam_heat_content": []}):
        with pytest.raises(ValueError):
            validate_recalculation_settings(bad)


def test_the_thermal_calculation_converts_other_energy_units() -> None:
    result = calc.purchased_thermal("purchased_heating_location_based",
                                    [calc.FacilityThermal("A", calc.Measure(3400, "therm"))])
    assert result.lines[0].steps[0].result == pytest.approx(340)  # therms -> MMBtu
    assert result.total_mass_t["CO2"] == pytest.approx(340 * 66.33 / 1000)
