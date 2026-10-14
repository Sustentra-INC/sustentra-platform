"""The calculator against the EPA's own Simplified GHG Emissions Calculator (September 2024).

The EPA tool uses the June 2024 Emission Factors Hub; we use the 2025 Hub. These tests pin
what must agree (the method, and every factor the two Hubs share) and how the known
differences arise (see docs/epa_calculator_crosscheck.md). The EPA values are in
reference_implementations/epa_simplified_calculator_2024.json, read from the tool itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.reference.emission_factor_loader import Factor, default_emission_factor_reference
from backend.app.services import emissions_calculator as calc

EPA = json.loads((Path(__file__).parents[1] / "reference_implementations" / "epa_simplified_calculator_2024.json")
                 .read_text())
REF = default_emission_factor_reference()
CH4_GWP, N2O_GWP = 28, 265
# The EPA tool's names where the Hub names a fuel differently.
STATIONARY_NAME = {"Anthracite Coal": "Anthracite", "Bituminous Coal": "Bituminous",
                   "Sub-bituminous Coal": "Sub-bituminous", "Lignite Coal": "Lignite"}
MOBILE_NAME = {"Biodiesel": "Biodiesel (100%)", "Ethanol": "Ethanol (100%)"}
# Biomass fuels whose CO2 the EPA tool lists as 0 per mmBtu; the 2025 Hub gives the factor and
# we report that CO2 as biogenic, outside Scope 1 (as the tool does for its other biomass fuels).
BIOGENIC_LISTED_AS_ZERO = {"Wood and Wood Residuals", "Landfill Gas"}


def _ours(fuel: str) -> dict:
    return next(r for r in REF.data["stationary_combustion"]
                if r["fuel_type"].lower() == STATIONARY_NAME.get(fuel, fuel).lower())


def test_every_stationary_fuel_factor_matches_the_epa_tool() -> None:
    for row in EPA["stationary"]:
        per_energy = _ours(row["fuel"])["per_energy"]
        assert per_energy["ch4_g_per_mmbtu"] == pytest.approx(row["ch4_g_per_mmbtu"]), row["fuel"]
        assert per_energy["n2o_g_per_mmbtu"] == pytest.approx(row["n2o_g_per_mmbtu"]), row["fuel"]
        if row["fuel"] in BIOGENIC_LISTED_AS_ZERO:
            assert row["co2_kg_per_mmbtu"] == 0 and per_energy["co2_kg_per_mmbtu"] > 0
        else:
            assert per_energy["co2_kg_per_mmbtu"] == pytest.approx(row["co2_kg_per_mmbtu"]), row["fuel"]


def test_biomass_co2_stays_out_of_scope_1_as_in_the_epa_tool() -> None:
    wood = calc.stationary_combustion([calc.StationaryFuel("Wood and Wood Residuals", calc.Measure(100, "MMBtu"))],
                                      REF)
    # Scope 1 holds only CH4 and N2O, exactly what the EPA tool's 0 CO2 factor gives.
    epa = (0 + 100 * 7.2 / 1000 * CH4_GWP + 100 * 3.6 / 1000 * N2O_GWP) / 1000
    assert wood.total_co2e == pytest.approx(epa, rel=1e-12)
    assert wood.biogenic_co2_t == pytest.approx(100 * 93.8 / 1000)


def test_mobile_co2_factors_and_gwps_match_the_epa_tool() -> None:
    ours = {r["fuel_type"]: r["co2_kg_per_unit"] for r in REF.data["mobile_co2"]}
    for row in EPA["mobile_co2"]:
        assert ours[MOBILE_NAME.get(row["fuel"], row["fuel"])] == pytest.approx(row["co2_kg_per_unit"]), row["fuel"]
    gwps = {g["formula"].lower(): g["gwp_100yr"] for g in REF.data["gwp"]}
    for row in EPA["gwp"]:
        assert gwps[row["formula"].lower()] == row["gwp_100yr"], row["name"]


def test_stationary_arithmetic_matches_the_epa_tool_formula() -> None:
    example = EPA["stationary_example"]
    factors = next(r for r in EPA["stationary"] if r["fuel"] == example["fuel"])
    mmbtu = example["mmbtu"]
    epa_t = (mmbtu * factors["co2_kg_per_mmbtu"] + mmbtu * factors["ch4_g_per_mmbtu"] / 1000 * CH4_GWP
             + mmbtu * factors["n2o_g_per_mmbtu"] / 1000 * N2O_GWP) / 1000
    ours = calc.stationary_combustion([calc.StationaryFuel(example["fuel"], calc.Measure(mmbtu, "MMBtu"))], REF)
    assert ours.total_co2e == pytest.approx(epa_t, rel=1e-12) == pytest.approx(531.145)


def test_the_epa_tools_electricity_example_is_reproduced_with_its_own_factors() -> None:
    example = EPA["electricity_example"]
    row = next(r for r in EPA["egrid"] if r["name"] == example["subregion"])
    factors = {gas: Factor(row[f"{gas.lower()}_lb_per_mwh"], "lb per MWh", "EPA calculator, eGRID2022")
               for gas in ("CO2", "CH4", "N2O")}
    facility = calc.FacilityElectricity("Bldg-012", calc.Measure(example["kwh"], "kWh"), "HIMS", factors=factors)
    result = calc.electricity_location_based([facility], REF)
    pounds = {s.label.split(" ")[0]: s.result for s in result.lines[0].steps if s.result_unit == "lb"}
    assert pounds == pytest.approx({"CO2": example["co2_lb"], "CH4": example["ch4_lb"], "N2O": example["n2o_lb"]})
    epa_t = (example["co2_lb"] + example["ch4_lb"] * CH4_GWP + example["n2o_lb"] * N2O_GWP) * 0.45359237 / 1000
    # We convert pounds with the workbook's 2,204.62 lb per metric ton; the EPA tool with
    # 0.45359237 kg per lb: one part in a million apart.
    assert result.total_co2e == pytest.approx(epa_t, rel=2e-6)


def test_every_epa_grid_region_exists_in_our_egrid_vintage() -> None:
    names = {r["name"].lower() for r in REF.data["electricity"]}
    assert {r["name"].lower() for r in EPA["egrid"]} <= names
