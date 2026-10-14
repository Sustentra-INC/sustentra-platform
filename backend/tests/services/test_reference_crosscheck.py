"""The calculator agrees with Jerome's independent implementations of the workbook
equations (backend/tests/reference_implementations), on EPA Hub 2025 factors."""

from __future__ import annotations

import pytest

from backend.app.reference.emission_factor_loader import default_emission_factor_reference
from backend.app.services import emissions_calculator as calc
from backend.tests.reference_implementations import jerome_mobile_combustion as jm
from backend.tests.reference_implementations import jerome_stationary_combustion as js

REF = default_emission_factor_reference()
GWP = {"CH4": 28, "N2O": 265}  # AR5, EPA Hub Table 11
KG_PER_T = 1000
GASES = ("CO2", "CH4", "N2O")


def _stationary_ef(fuel_type: str, gas: str, unit: str) -> float:
    """EPA Hub Table 1 factor in kg (the reference implementation does no unit conversion)."""

    row = REF.stationary_fuel(fuel_type)
    if unit == "MMBtu":
        e = row["per_energy"]
        return {"CO2": e["co2_kg_per_mmbtu"], "CH4": e["ch4_g_per_mmbtu"] / 1000, "N2O": e["n2o_g_per_mmbtu"] / 1000}[gas]
    u = row["per_unit"]
    assert u["unit"] == unit
    return {"CO2": u["co2_kg_per_unit"], "CH4": u["ch4_g_per_unit"] / 1000, "N2O": u["n2o_g_per_unit"] / 1000}[gas]


def _mobile_co2_ef(fuel_type: str, unit: str) -> float:
    return float(REF.mobile_co2(fuel_type)["co2_kg_per_unit"])


def _mobile_gas_ef(gas: str, vehicle_type: str, fuel_type: str, model_year: int | None, unit: str) -> float:
    table_fuel = {"Diesel Fuel": "Diesel", "Motor Gasoline": "Gasoline"}.get(fuel_type, fuel_type)
    if unit == "mile":
        return REF.on_road(vehicle_type, table_fuel, model_year)[f"{gas.lower()}_g_per_mile"] / 1000
    return REF.non_road(vehicle_type, table_fuel)[f"{gas.lower()}_g_per_gallon"] / 1000


def _same(ours: calc.CategoryResult, theirs_mass_kg: dict[str, float], theirs_co2e_kg: float) -> None:
    for gas in GASES:
        assert ours.total_mass_t[gas] == pytest.approx(theirs_mass_kg[gas] / KG_PER_T, rel=1e-12, abs=1e-15)
    assert ours.total_co2e == pytest.approx(theirs_co2e_kg / KG_PER_T, rel=1e-12)


@pytest.mark.parametrize(
    ("ours", "theirs"),
    [
        # Eq 1 on an energy quantity (the Richmond gas bill: 21,899.11 t CO2e)
        (calc.StationaryFuel("Natural Gas", calc.Measure(412_300, "MMBtu")), js.Fuel("Natural Gas", 412_300, "MMBtu")),
        # Eq 1 on a physical unit
        (calc.StationaryFuel("Natural Gas", calc.Measure(1_000_000, "scf")), js.Fuel("Natural Gas", 1_000_000, "scf")),
        (calc.StationaryFuel("Distillate Fuel Oil No. 2", calc.Measure(5_000, "gallon")),
         js.Fuel("Distillate Fuel Oil No. 2", 5_000, "gallon")),
        # Eq 2: heat content given
        (calc.StationaryFuel("Natural Gas", calc.Measure(1_000_000, "scf"),
                             heat_content=calc.Measure(0.001026, "MMBtu per scf")),
         js.Fuel("Natural Gas", 1_000_000, "scf", hhv=0.001026)),
        # Eq 3 for CO2 (carbon content), Eq 2 for CH4 / N2O
        (calc.StationaryFuel("Distillate Fuel Oil No. 2", calc.Measure(2_000, "gallon"),
                             heat_content=calc.Measure(0.138, "MMBtu per gallon"),
                             carbon_content=calc.Measure(20.17, "kg C per mmBtu")),
         js.Fuel("Distillate Fuel Oil No. 2", 2_000, "gallon", hhv=0.138, cc=20.17 * 0.138)),
    ],
)
def test_stationary_matches_the_reference_implementation(ours: calc.StationaryFuel, theirs: js.Fuel) -> None:
    result = js.stationary_combustion_co2e([theirs], _stationary_ef, GWP)
    _same(calc.stationary_combustion([ours], REF), result.total_mass, result.total_co2e)


def test_mobile_matches_the_reference_implementation_by_distance_and_by_fuel() -> None:
    ours = calc.mobile_combustion([
        calc.MobileFuel("Diesel Fuel", calc.Measure(500, "gallon"), vehicle_groups=[
            calc.VehicleGroup("Medium- and Heavy-Duty Vehicles", "Diesel", True, 2019,
                              distance=calc.Measure(3_600, "mi")),
            calc.VehicleGroup("Industrial/Commercial Equipment", "Diesel", False,
                              fuel_quantity=calc.Measure(68.2, "gallon")),
        ]),
        calc.MobileFuel("Motor Gasoline", calc.Measure(2_400, "gallon"), vehicle_groups=[
            calc.VehicleGroup("Gasoline Passenger Cars", "Gasoline", True, 2019, distance=calc.Measure(30_000, "mi")),
            calc.VehicleGroup("Gasoline Passenger Cars", "Gasoline", True, 2022, distance=calc.Measure(33_000, "mi")),
        ]),
    ], REF)
    theirs = jm.mobile_combustion_co2e([
        jm.MobileRecord("Medium- and Heavy-Duty Vehicles", "Diesel Fuel", True, 431.8, "gallon", distance=3_600,
                        model_year=2019),
        jm.MobileRecord("Industrial/Commercial Equipment", "Diesel Fuel", False, 68.2, "gallon"),
        jm.MobileRecord("Gasoline Passenger Cars", "Motor Gasoline", True, 1_200, "gallon", distance=30_000,
                        model_year=2019),
        jm.MobileRecord("Gasoline Passenger Cars", "Motor Gasoline", True, 1_200, "gallon", distance=33_000,
                        model_year=2022),
    ], _mobile_co2_ef, _mobile_gas_ef, GWP)
    _same(ours, theirs.total_mass, theirs.total_co2e)
