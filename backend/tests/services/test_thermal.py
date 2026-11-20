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
    assert comparison["status"] == "within_tolerance" and comparison["workbook_row"] == 49
    rollup = result["rollup"]
    assert rollup["categories"]["purchased_steam"]["status"] == "calculated"
    assert rollup["nodes"]["purchased_heating_total"]["co2e_t"] == pytest.approx(heating)


def test_steam_by_weight_asks_for_its_heat_content_and_cooling_is_listed_as_not_calculated() -> None:
    store = FakeStore()
    store.add_document("STEAM-FEB", "CT-S2-THERMAL", [_thermal("steam", 980, "klb")])
    store.add_document("COOL-JUL", "CT-S2-THERMAL", [_thermal("chilled_water", 504, "MMBtu", "Facility B",
                                                              "2025-07-01", "2025-07-31")])
    asked = _service(store).recalculate(_engagement(), _own)
    kinds = {(i["kind"], i["category"]) for i in asked["needs_input"]}
    assert kinds == {("steam_heat_content", "purchased_steam")}  # nothing the reviewer enters prices cooling yet
    cooling = [e for e in asked["excluded"] if e["document_id"] == "COOL-JUL"]
    assert [(e["reason"], e["period"]) for e in cooling] == [("purchased_cooling_not_calculated",
                                                               "2025-07-01 to 2025-07-31")]
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


GAS_FOR_STEAM_BOILER = """Lakeshore Gas Company
Natural Gas Bill
Account Number: 552-118-91
Facility: Steam Boiler House
Service Address: 2525 S Michigan Ave, Chicago, IL 60616
Billing Period: 01/05/2025 to 02/04/2025
Therms: 48,210
"""
GAS_FOR_HOT_WATER = """Lakeshore Gas Company
Natural Gas Bill
Account Number: 552-118-90
Service Type: Natural gas for central heating and hot water
Billing Period: 01/05/2025 to 02/04/2025
Therms: 1,234
"""


@pytest.mark.parametrize("text", [GAS_FOR_STEAM_BOILER, GAS_FOR_HOT_WATER])
def test_a_gas_bill_that_mentions_steam_or_hot_water_is_never_purchased_steam(tmp_path: Path, text: str) -> None:
    # The company burns this gas itself (Scope 1); it did not buy steam or heat (Scope 2).
    assert _read(tmp_path, text)["type"] != "CT-S2-THERMAL"


def test_a_thousand_pounds_is_pounds_not_thousands_of_pounds() -> None:
    from backend.app.domain import fuel_units

    assert fuel_units.find_unit("Quantity Delivered: 1,000 lbs") == "lb"
    assert fuel_units.find_unit("1000 lbs") == "lb"
    assert fuel_units.find_unit("Steam Usage: 980 Mlb", thermal=True) == "klb"
    assert fuel_units.canonical_unit("M lbs", thermal=True) == "klb"


def test_district_energy_units_never_change_how_fuel_and_electricity_are_read() -> None:
    from backend.app.domain import fuel_units

    # Outside the thermal extractor these are not units, so a fuel log's "Chilled Water
    # (Ton-Hrs)" column next to "Natural Gas (Therms)" is never taken as the quantity.
    assert fuel_units.find_unit("Steam Usage: 980 Mlb") is None
    assert fuel_units.find_unit("Chilled Water (Ton-Hrs)") is None
    assert fuel_units.canonical_unit("kBtu") is None
    assert fuel_units.canonical_unit("kBtu", thermal=True) == "kBtu"


def test_reviewer_typed_energy_types_are_normalized_and_an_unknown_one_is_asked() -> None:
    store = FakeStore()
    store.add_document("STEAM-MAR", "CT-S2-THERMAL", [_thermal("Steam", 100, "MMBtu")])
    store.add_document("HEAT-MAR", "CT-S2-THERMAL", [_thermal("Hot-water", 50, "MMBtu", "Facility A")])
    store.add_document("ODD-MAR", "CT-S2-THERMAL", [_thermal("District energy", 70, "MMBtu", "Facility B")])
    result = _service(store).recalculate(_engagement(), _own)
    assert result["categories"]["purchased_steam_location_based"]["lines"][0]["key"] == "Facility C"
    assert result["categories"]["purchased_heating_location_based"]["lines"][0]["key"] == "Facility A"
    asks = [(i["kind"], i["key"]) for i in result["needs_input"]]
    # The unknown type has no line, so Results also says its record is not counted (its category stays incomplete).
    assert asks == [("thermal_type", "ODD-MAR.pdf"), ("not_on_a_line", "not_on_a_line:purchased_steam:no_calculation_line")]
    assert all(i["category"] == "purchased_steam" for i in result["needs_input"] if i["kind"] == "thermal_type")


def test_a_thermal_bill_outside_the_reporting_period_is_listed_as_excluded() -> None:
    store = FakeStore()
    store.add_document("STEAM-2024", "CT-S2-THERMAL", [_thermal("steam", 900, "MMBtu", start="2024-11-01",
                                                                end="2024-11-30")])
    result = _service(store).recalculate(_engagement(), _own)
    assert [(e["document_id"], e["reason"]) for e in result["excluded"]] == [("STEAM-2024", "outside_reporting_period")]
    assert result["categories"].get("purchased_steam_location_based") is None


COMBINED_BILL = """Metro District Energy
Steam and Chilled Water Statement
Account Number: MDE-44120
Customer: Facility C
Service Period: 07/01/2025 to 07/31/2025
Steam Usage: 410 MMBtu
Steam Demand: 12 Mlb/hr
Chilled Water Usage: 42,000 ton-hours
Condensate Return Credit: 35 MMBtu
"""
DISTRICT_HEAT_IN_MWH = STEAM_BILL.replace("Steam Service Statement", "District Heating Statement").replace(
    "Steam Usage: 1,250 MMBtu", "Heat Delivered: 310 MWh")
ELECTRIC_BILL_WITH_A_HOT_WATER_TIP = """Riverside Electric Utility
Electricity Bill
Account Number: RE-7781-2210
Service Period: 01/01/2025 to 01/31/2025
Total kWh Used: 12,450 kWh
Energy tip: lower your hot water heater to 120 F.
"""


def _records(tmp_path: Path, text: str) -> dict[Any, dict[str, Any]]:
    path = tmp_path / "bill.txt"
    path.write_text(text)
    out = PipelineOrchestrationService().process_local_document(str(path), engagement_id="ENG", persist_run=False)
    records: dict[Any, dict[str, Any]] = {}
    for c in out["extraction_result"]["items"]:
        records.setdefault(c["record_index"], {})[c["field_name"]] = (c["normalized_value"], c.get("unit"))
    return records


def test_a_combined_bill_keeps_each_commodity_and_skips_demand_and_condensate(tmp_path: Path) -> None:
    records = _records(tmp_path, COMBINED_BILL)
    read = sorted((r["energy_type"][0], r["activity_quantity"]) for r in records.values())
    assert read == [("chilled_water", (pytest.approx(504), "MMBtu")), ("steam", (pytest.approx(410), "MMBtu"))]


def test_district_heat_in_mwh_is_purchased_heat_and_an_electric_bill_stays_electricity(tmp_path: Path) -> None:
    from backend.tests.services.test_electricity_extractor import _text_output

    heat = _text_output(DISTRICT_HEAT_IN_MWH)
    assert PipelineOrchestrationService._electricity_reroute("CT-S1-FUELQTY", heat) is False
    assert PipelineOrchestrationService._thermal_reroute("CT-S1-FUELQTY", heat) is True
    assert PipelineOrchestrationService._thermal_reroute("CT-S2-ELEC", heat) is True
    tip = _text_output(ELECTRIC_BILL_WITH_A_HOT_WATER_TIP)
    assert PipelineOrchestrationService._thermal_reroute("CT-S2-ELEC", tip) is False
    assert _read(tmp_path, DISTRICT_HEAT_IN_MWH)["values"]["activity_quantity"] == (
        pytest.approx(310 * 3.412141633), "MMBtu")


SPARSE_DISTRICT_HEAT = "Northside Thermal\nDistrict Heating Statement\nService Period: 01/01/2025 to 01/31/2025\nHeat Delivered: 310 MWh\n"


def test_a_sparse_district_heat_bill_is_not_lost_to_a_weak_vehicle_fuel_guess(tmp_path: Path) -> None:
    read = _read(tmp_path, SPARSE_DISTRICT_HEAT)
    assert read["type"] == "CT-S2-THERMAL"
    assert read["values"]["energy_type"][0] == "hot_water"


# --- the energy type comes from the usage line, never a stray word (EXT-014, N27) -------------

TAGLINE = "Harborline District Energy\nSteam & chilled water utility - 60 Quay Way, Zürich\n"
STEAM_SECTION = """Steam Consumption
Meter | Start Read (Mlb) | End Read (Mlb) | Usage (Mlb) | Conversion | Usage (MMBtu)
STM-17-B | 14,882.6 | 15,695.0 | 812.4 | 1.194 MMBtu / Mlb | 970.01
Mlb = thousand pounds of steam.
"""
BILL_HEAD = "Account: HDE-00417\nService Location: Müller Käserei – Zürich Plant, 10 Quay Way\nFrom: 01/01/2025\nTo: 01/31/2025\n"
RATE_CARD = "Rate card: chilled water $0.12 per ton-hour, district cooling services on request; boiler at 180 °F\n"


def _extract(tmp_path: Path, text: str) -> dict[str, Any]:
    path = tmp_path / "bill.txt"
    path.write_text(text, encoding="utf-8")
    return PipelineOrchestrationService(
        pipeline_repository=InMemoryPipelineRunRepository(),
        extraction_result_repository=InMemoryExtractionResultRepository(),
    ).process_local_document(str(path), engagement_id="ENG", persist_run=False)


def _energy(tmp_path: Path, text: str) -> list[tuple[Any, Any, Any]]:
    """(energy type, quantity, unit) of every record, in a stable order."""

    by_record: dict[Any, dict[str, Any]] = {}
    for c in _extract(tmp_path, text)["extraction_result"]["items"]:
        by_record.setdefault(c.get("record_index"), {})[c["field_name"]] = c
    return sorted(
        ((r["energy_type"]["normalized_value"], r["activity_quantity"]["normalized_value"],
          r["activity_quantity"].get("unit")) for r in by_record.values()), key=str)


@pytest.mark.parametrize("extra", ["", RATE_CARD, "Chilled water service is available at this campus.\n",
                                   "Cooling tower makeup water is billed separately.\n"])
def test_a_steam_bill_whose_letterhead_also_names_chilled_water_is_steam(tmp_path: Path, extra: str) -> None:
    text = TAGLINE + BILL_HEAD + STEAM_SECTION + extra
    assert _energy(tmp_path, text) == [("steam", pytest.approx(970.01), "MMBtu")]


@pytest.mark.parametrize("unit", ["Mlb", "klb", "lb"])
def test_steam_by_weight_is_steam_whatever_else_the_bill_names(tmp_path: Path, unit: str) -> None:
    text = TAGLINE + BILL_HEAD + f"Total Usage: 812.4 {unit}\n" + RATE_CARD
    [(energy, quantity, _)] = _energy(tmp_path, text)
    assert (energy, quantity) == ("steam", 812.4)


def test_ton_hours_are_chilled_water_even_on_a_steam_and_chilled_water_letterhead(tmp_path: Path) -> None:
    text = TAGLINE + BILL_HEAD + "Total Usage: 42,000 ton-hours\n"
    assert _energy(tmp_path, text) == [("chilled_water", pytest.approx(504), "MMBtu")]


def test_a_bill_with_both_services_keeps_each_by_its_own_line(tmp_path: Path) -> None:
    text = TAGLINE + BILL_HEAD + "Steam Usage: 410 MMBtu\nSteam Demand: 12 Mlb/hr\nChilled Water Usage: 504 MMBtu\n"
    assert _energy(tmp_path, text) == [("chilled_water", 504, "MMBtu"), ("steam", 410, "MMBtu")]


def test_a_bill_naming_both_with_nothing_near_the_quantity_leaves_the_type_empty_and_says_so(tmp_path: Path) -> None:
    out = _extract(tmp_path, TAGLINE + BILL_HEAD + "Total Usage: 410 MMBtu\n")
    items = {c["field_name"]: c for c in out["extraction_result"]["items"]}
    assert items["energy_type"]["normalized_value"] is None  # never guessed, and never cooling
    assert items["activity_quantity"]["normalized_value"] == 410
    assert any("energy type" in w and "Choose it" in w for w in out["pipeline_run"]["warnings"])


def test_a_bill_that_names_one_type_only_needs_no_heading(tmp_path: Path) -> None:
    steam = "Harborline District Energy\nSteam Service Statement\n" + BILL_HEAD + "Total Usage: 410 MMBtu\n"
    cooling = "Harborline District Energy\nChilled Water Statement\n" + BILL_HEAD + "Total Usage: 410 MMBtu\n"
    assert _energy(tmp_path, steam) == [("steam", 410, "MMBtu")]
    assert _energy(tmp_path, cooling) == [("chilled_water", 410, "MMBtu")]
