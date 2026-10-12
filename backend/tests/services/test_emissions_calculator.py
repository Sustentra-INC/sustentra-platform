"""Recalculation checked against the worked examples in the GHG Required Data workbook.

Expected values are the workbook's own numbers (Claire's examples) or are computed by
hand in the test from EPA GHG Emission Factors Hub 2025 factors, never from the
calculator itself.
"""

from __future__ import annotations

import pytest

from backend.app.reference.emission_factor_loader import (
    EmissionFactorNotFoundError,
    Factor,
    default_emission_factor_reference,
)
from backend.app.services.emissions_calculator import (
    CalculationError,
    Certificate,
    FacilityElectricity,
    Measure,
    MobileFuel,
    PurchasedGas,
    StationaryFuel,
    VehicleGroup,
    compare,
    electricity_location_based,
    electricity_market_based,
    mobile_combustion,
    purchased_gases,
    stationary_combustion,
)

LB_PER_T = 2204.6226218  # exact, to express a metric-ton result in lb


def _workbook_factors() -> dict[str, dict[str, Factor]]:
    """The factors as rounded in the workbook example (Hub: 240.99 and 594.74)."""

    return {
        "NYUP": {"CO2": Factor(241.0, "lb per MWh", "workbook"), "CH4": Factor(0.011, "lb per MWh", "workbook"),
                 "N2O": Factor(0.001, "lb per MWh", "workbook")},
        "RFCE": {"CO2": Factor(594.7, "lb per MWh", "workbook"), "CH4": Factor(0.036, "lb per MWh", "workbook"),
                 "N2O": Factor(0.005, "lb per MWh", "workbook")},
    }


def _facilities(factors: dict[str, dict[str, Factor]] | None = None) -> list[FacilityElectricity]:
    return [
        FacilityElectricity("Facility A, Albany NY", Measure(1_200_000, "kWh"), "NYUP", factors and factors["NYUP"]),
        FacilityElectricity("Facility B, Philadelphia PA", Measure(800_000, "kWh"), "RFCE",
                            factors and factors["RFCE"]),
    ]


# --- Scope 2 location-based (workbook example: 348.14 t CO2e) ----------------------------
def test_location_based_reproduces_the_workbook_example() -> None:
    result = electricity_location_based(_facilities(_workbook_factors()))
    facility_a, facility_b = result.lines
    assert round(facility_a.mass_t["CO2"], 2) == 131.18
    assert round(facility_b.mass_t["CO2"], 2) == 215.80
    assert round(result.total_mass_t["CO2"], 2) == 346.98
    assert round(result.total_mass_t["CH4"], 5) == 0.01905
    assert round(result.total_co2e_t["CH4"], 2) == 0.53
    assert round(result.total_co2e_t["N2O"], 2) == 0.63  # workbook shows 0.62 from truncated 0.00235 t
    assert round(result.total_co2e, 2) == 348.14
    assert result.gwp["CH4"]["value"] == 28 and result.gwp["N2O"]["value"] == 265


def test_location_based_with_exact_epa_factors() -> None:
    result = electricity_location_based(_facilities())
    assert result.lines[0].steps[1].inputs["EF (NYUP)"]["source"] == "EPA GHG Emission Factors Hub 2025, Table 6, row 353"
    expected_co2 = (1200 * 240.99 + 800 * 594.74) / 2204.62
    assert result.total_mass_t["CO2"] == pytest.approx(expected_co2)
    assert round(result.total_co2e, 2) == 348.15


# --- Scope 2 market-based (workbook example: 243.70 t CO2e) ------------------------------
def test_market_based_reproduces_the_workbook_example() -> None:
    certificates = [Certificate("REC retirement report 1", 400), Certificate("REC retirement report 2", 200)]
    result = electricity_market_based(_facilities(_workbook_factors()), certificates)
    assert result.details["covered_mwh"] == 600
    assert result.details["coverage"] == pytest.approx(0.30)
    remainders = [next(s.result for s in line.steps if s.label == "Remainder MWh") for line in result.lines]
    assert remainders == pytest.approx([840, 560])
    assert round(result.lines[0].mass_t["CO2"], 2) == 91.83
    assert round(result.lines[1].mass_t["CO2"], 2) == 151.06
    assert round(result.total_mass_t["CO2"], 2) == 242.89
    assert round(result.total_co2e, 2) == 243.70


def test_market_based_without_certificates_equals_location_based() -> None:
    market = electricity_market_based(_facilities(_workbook_factors()), [])
    location = electricity_location_based(_facilities(_workbook_factors()))
    assert market.total_co2e == pytest.approx(location.total_co2e)
    assert "no_certificates_market_equals_location" in market.flags


def test_certificates_above_consumption_cap_at_zero_and_flag() -> None:
    result = electricity_market_based(_facilities(_workbook_factors()), [Certificate("large", 5000)])
    assert result.total_co2e == 0
    assert "certificates_exceed_consumption" in result.flags


def test_electricity_must_be_kwh_or_mwh() -> None:
    with pytest.raises(CalculationError):
        electricity_location_based([FacilityElectricity("X", Measure(10, "therm"), "NYUP")])


# --- Purchased industrial gases (workbook example) ---------------------------------------
def test_purchased_gases_reproduce_the_workbook_example_and_flag_its_gwp() -> None:
    # Workbook: CO2 2,000 lb x 1 = 2,000 lb CO2e; SF6 20 lb x 22,800 = 456,000 lb CO2e (AR4 value).
    workbook = purchased_gases([PurchasedGas("CO2", Measure(2000, "lb")),
                                PurchasedGas("SF6", Measure(20, "lb"), gwp_override=22800)])
    assert workbook.total_co2e_t["CO2"] * LB_PER_T == pytest.approx(2000)
    assert workbook.total_co2e_t["SF6"] * LB_PER_T == pytest.approx(456_000)
    # The EPA Hub 2025 (Table 11, AR5) SF6 GWP the workbook names as its source is 23,500.
    hub = purchased_gases([PurchasedGas("SF6", Measure(20, "lb"))])
    assert hub.gwp["SF6"]["value"] == 23500
    assert hub.total_co2e_t["SF6"] * LB_PER_T == pytest.approx(470_000)


# --- Scope 1 stationary combustion ---------------------------------------------------------
def test_stationary_workbook_example_natural_gas_and_diesel() -> None:
    # Workbook: natural gas 450,000 therms and diesel 8,200 gallons -> 2 rows, 3 gases each.
    result = stationary_combustion([
        StationaryFuel("Natural Gas", Measure(450_000, "therm")),
        StationaryFuel("Distillate Fuel Oil No. 2", Measure(8_200, "gallon")),
    ])
    gas, diesel = result.lines
    # 450,000 therm = 45,000 mmBtu; Table 1: 53.06 kg CO2, 1 g CH4, 0.1 g N2O per mmBtu
    assert gas.mass_t["CO2"] == pytest.approx(45_000 * 53.06 / 1000)
    assert gas.mass_t["CH4"] == pytest.approx(45_000 * 1 / 1e6)
    assert gas.mass_t["N2O"] == pytest.approx(45_000 * 0.1 / 1e6)
    # Table 1 Distillate Fuel Oil No. 2 per gallon: 10.21 kg CO2, 0.41 g CH4, 0.08 g N2O
    assert diesel.mass_t["CO2"] == pytest.approx(8_200 * 10.21 / 1000)
    assert diesel.mass_t["CH4"] == pytest.approx(8_200 * 0.41 / 1e6)
    assert diesel.mass_t["N2O"] == pytest.approx(8_200 * 0.08 / 1e6)
    assert gas.equations == diesel.equations == {"CO2": "Eq 1", "CH4": "Eq 1", "N2O": "Eq 1"}
    expected = ((45_000 * 53.06 + 8_200 * 10.21) / 1000 + (45_000 * 1 + 8_200 * 0.41) / 1e6 * 28
                + (45_000 * 0.1 + 8_200 * 0.08) / 1e6 * 265)
    assert result.total_co2e == pytest.approx(expected)


def test_stationary_matches_the_existing_demo_golden_ar6() -> None:
    # demo-fixtures/mock_outputs/mock_analysis_response.json: 28,100 MMBtu natural gas, AR6
    result = stationary_combustion([StationaryFuel("Natural Gas", Measure(28_100, "MMBtu"))], gwp_set="AR6")
    assert result.lines[0].mass_t["CO2"] * 1000 == pytest.approx(1_490_986)
    assert result.total_co2e == pytest.approx(1492.51183, abs=1e-5)


def test_route_selection_hhv_uses_eq2_for_all_gases() -> None:
    fuel = StationaryFuel("Natural Gas", Measure(1_000_000, "scf"), heat_content=Measure(1030, "Btu per scf"))
    line = stationary_combustion([fuel]).lines[0]
    assert line.equations == {"CO2": "Eq 2", "CH4": "Eq 2", "N2O": "Eq 2"}
    assert line.mass_t["CO2"] == pytest.approx(1_000_000 * 0.00103 * 53.06 / 1000)  # 1,030 mmBtu


def test_route_selection_carbon_content_uses_eq3_for_co2_only() -> None:
    fuel = StationaryFuel("Bituminous", Measure(100, "short ton"), carbon_content=Measure(75, "percent by mass"))
    line = stationary_combustion([fuel]).lines[0]
    assert line.equations == {"CO2": "Eq 3", "CH4": "Eq 1", "N2O": "Eq 1"}
    assert line.mass_t["CO2"] == pytest.approx(100 * 907.18474 * 0.75 * 44 / 12 / 1000)
    assert line.mass_t["CH4"] == pytest.approx(100 * 274 / 1e6)  # Table 1 Bituminous: 274 g CH4 per short ton


def test_unit_converted_to_the_epa_unit() -> None:
    line = stationary_combustion([StationaryFuel("Natural Gas", Measure(10, "Mcf"))]).lines[0]
    assert line.mass_t["CO2"] == pytest.approx(10_000 * 0.05444 / 1000)  # Table 1 per scf
    assert "unit_converted" in line.flags


def test_biomass_co2_is_reported_separately() -> None:
    result = stationary_combustion([StationaryFuel("Wood and Wood Residuals", Measure(10, "short ton"))])
    line = result.lines[0]
    assert line.mass_t["CO2"] == 0
    assert line.biogenic_co2_t == pytest.approx(10 * 1640 / 1000)
    assert result.biogenic_co2_t == pytest.approx(16.4)
    assert "biogenic_co2_reported_separately" in result.flags


def test_incompatible_inputs_raise() -> None:
    with pytest.raises(CalculationError):
        stationary_combustion([StationaryFuel("Natural Gas", Measure(5, "gallon"))])  # factors are per scf
    with pytest.raises(EmissionFactorNotFoundError):
        stationary_combustion([StationaryFuel("fuel oil", Measure(5, "gallon"))])  # ambiguous, not an EPA name


# --- Scope 1 mobile combustion ---------------------------------------------------------------
def test_mobile_co2_per_fuel_and_ch4_n2o_per_vehicle_group() -> None:
    ref = default_emission_factor_reference()
    forklift = next(r for r in ref.data["mobile_non_road"] if r["source"]["row"] == 318)  # Ind./Comm. diesel
    result = mobile_combustion([
        MobileFuel("Diesel Fuel", Measure(23_400, "gallon"), vehicle_groups=[
            VehicleGroup("Medium- and Heavy-Duty Vehicles", "Diesel", on_road=True, model_year=2018,
                         distance=Measure(180_000, "miles")),
            VehicleGroup(forklift["vehicle_type"], forklift["fuel_type"], on_road=False,
                         fuel_quantity=Measure(1_400, "gallon")),
        ]),
    ])
    line = result.lines[0]
    assert line.mass_t["CO2"] == pytest.approx(23_400 * 10.21 / 1000)  # Table 2
    assert line.mass_t["CH4"] == pytest.approx((180_000 * 0.0095 + 1_400 * forklift["ch4_g_per_gallon"]) / 1e6)
    assert line.mass_t["N2O"] == pytest.approx((180_000 * 0.0431 + 1_400 * forklift["n2o_g_per_gallon"]) / 1e6)
    assert any("Eq 4" in s.label for s in line.steps) and any("Eq 5" in s.label for s in line.steps)


def test_mobile_without_vehicle_groups_is_flagged() -> None:
    result = mobile_combustion([MobileFuel("Motor Gasoline", Measure(18_000, "gallon"))])
    assert result.lines[0].mass_t["CO2"] == pytest.approx(18_000 * 8.78 / 1000)
    assert "ch4_n2o_need_vehicle_groups" in result.flags


# --- Reported vs recalculated -----------------------------------------------------------------
def test_compare_reports_difference_and_tolerance() -> None:
    assert compare("Scope 2 (Total)", 348.14, 348.15)["status"] == "within_tolerance"
    over = compare("Scope 1 (Total)", 1540, 1705)
    assert over["difference"] == pytest.approx(165)  # recalculated - reported
    assert over["difference_pct"] == pytest.approx(10.714, abs=1e-3)
    assert over["status"] == "exceeds_tolerance"
    assert compare("Scope 1 (Total)", None, 10)["status"] == "not_reported"


def test_every_step_cites_its_factor_source() -> None:
    result = electricity_location_based(_facilities())
    for line in result.lines:
        for step in line.steps:
            for name, value in step.inputs.items():
                if name.startswith("EF"):
                    assert value["source"].startswith("EPA GHG Emission Factors Hub 2025")
    assert all(g["source"] for g in result.gwp.values())
