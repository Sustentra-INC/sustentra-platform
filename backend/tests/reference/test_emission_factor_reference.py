"""The EPA GHG Emission Factors Hub 2025 reference data is faithful to the EPA workbook."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from backend.app.reference.emission_factor_loader import (
    AR6_LIBRARY_PATH,
    DEFAULT_PATH,
    EmissionFactorNotFoundError,
    default_emission_factor_reference,
)

pytest.importorskip("openpyxl")

from backend.scripts.build_emission_factor_reference import DEFAULT_SOURCE, build  # noqa: E402


@pytest.fixture(scope="module")
def ref():
    return default_emission_factor_reference()


def test_committed_json_matches_a_fresh_build_from_the_epa_workbook() -> None:
    assert json.loads(Path(DEFAULT_PATH).read_text(encoding="utf-8")) == build(DEFAULT_SOURCE)


def test_egrid_factors_used_in_the_workbook_example(ref) -> None:
    # GHG Required Data workbook, Scope 2 example: NYUP and RFCE (eGRID2023, Hub 2025 Table 6)
    nyup = ref.electricity("NYUP")
    assert (nyup["CO2"].value, nyup["CH4"].value, nyup["N2O"].value) == (240.99, 0.011, 0.001)
    assert nyup["CO2"].source == "EPA GHG Emission Factors Hub 2025, Table 6, row 353"
    rfce = ref.electricity("RFCE")
    assert (rfce["CO2"].value, rfce["CH4"].value, rfce["N2O"].value) == (594.74, 0.036, 0.005)
    assert len(ref.egrid_subregions()) == 28  # 27 subregions + US Average


def test_stationary_and_mobile_factors(ref) -> None:
    gas = ref.stationary_fuel("Natural Gas")
    assert gas["per_energy"] == {"co2_kg_per_mmbtu": 53.06, "ch4_g_per_mmbtu": 1, "n2o_g_per_mmbtu": 0.1}
    assert gas["heat_content_hhv"] == {"value": 0.001026, "unit": "mmBtu per scf"}
    assert ref.stationary_fuel("Distillate Fuel Oil No. 2")["per_unit"]["co2_kg_per_unit"] == 10.21
    assert ref.mobile_co2("Diesel Fuel")["co2_kg_per_unit"] == 10.21
    heavy = ref.on_road("Medium- and Heavy-Duty Vehicles", "Diesel", 2018)
    assert (heavy["ch4_g_per_mile"], heavy["n2o_g_per_mile"]) == (0.0095, 0.0431)
    car_1975 = ref.on_road("Gasoline Passenger Cars", "Gasoline", 1975)  # single year stored as a number
    assert (car_1975["ch4_g_per_mile"], car_1975["n2o_g_per_mile"]) == (0.1423, 0.0443)


def test_vehicle_descriptions_and_open_model_years_parse_correctly(ref) -> None:
    # "(Vans, Pickup Trucks, SUVs)" describes Gasoline Light-Duty Trucks; it is not its own type.
    gasoline_types = {r["vehicle_type"] for r in ref.data["mobile_on_road_gasoline"]}
    assert gasoline_types == {"Gasoline Passenger Cars", "Gasoline Light-Duty Trucks",
                              "Gasoline Heavy-Duty Vehicles", "Gasoline Motorcycles"}
    truck = ref.on_road("Gasoline Light-Duty Trucks", "Gasoline", 1975)  # EPA row 166
    assert (truck["ch4_g_per_mile"], truck["source"]["row"]) == (0.1634, 166)
    # "≤1980" is an open-ended range
    old = ref.on_road("Gasoline Heavy-Duty Vehicles", "Gasoline", 1972)
    assert (old["ch4_g_per_mile"], old["model_year_from"], old["model_year_to"]) == (0.4604, None, 1980)


def test_gwp_sets(ref) -> None:
    assert [ref.gwp(g).value for g in ("CO2", "CH4", "N2O", "SF6", "NF3")] == [1, 28, 265, 23500, 16100]
    assert "Table 11" in ref.gwp("CH4").source
    assert ref.gwp("R-410A").value == 1924  # Table 12 refrigerant blend
    assert [ref.gwp(g, "AR6").value for g in ("CO2", "CH4", "N2O")] == [1, 27.0, 273]
    with pytest.raises(EmissionFactorNotFoundError):
        ref.gwp("SF6", "AR6")  # the AR6 library set covers combustion gases only
    with pytest.raises(EmissionFactorNotFoundError):
        ref.gwp("CH4", "AR4")


def test_unknown_lookups_raise_instead_of_guessing(ref) -> None:
    for lookup in (lambda: ref.stationary_fuel("fuel oil"), lambda: ref.electricity("XXXX"),
                   lambda: ref.on_road("Medium- and Heavy-Duty Vehicles", "Diesel", 1900),
                   lambda: ref.on_road("Medium- and Heavy-Duty Vehicles", "Diesel", None)):
        with pytest.raises(EmissionFactorNotFoundError):
            lookup()


def test_matches_the_curated_stationary_library(ref) -> None:
    """Independent check: config/libraries/emission_factor_library.json (EPA Hub 2025 Table 1)."""

    library = json.loads(AR6_LIBRARY_PATH.read_text(encoding="utf-8-sig"))
    assert len(library["stationary_combustion_factors"]) == len(ref.stationary_fuel_types()) == 63
    for record in library["stationary_combustion_factors"]:
        ours = ref.stationary_fuel(record["fuel_name"])
        theirs = record["energy_basis_factors"]
        assert math.isclose(theirs["co2"]["value"], ours["per_energy"]["co2_kg_per_mmbtu"])
        assert math.isclose(theirs["ch4"]["value"], ours["per_energy"]["ch4_g_per_mmbtu"])
        assert math.isclose(theirs["n2o"]["value"], ours["per_energy"]["n2o_g_per_mmbtu"])


# --- reported gas groups (HFCs, PFCs, SF6, NF3, CO2...) ------------------------------------
@pytest.mark.parametrize(
    ("gas", "groups"),
    [
        ("HFC-134a", {"HFCs": (1.0, 1.0)}),
        ("R-410A", {"HFCs": (1.0, 1.0)}),  # 50% HFC-32 + 50% HFC-125
        ("R-401A", {"HFCs": (0.13, 1.0)}),  # 87% HCFCs: mass but no CO2e in Table 12
        ("SF6", {"SF6": (1.0, 1.0)}),
        ("NF3", {"NF3": (1.0, 1.0)}),
        ("PFC-14", {"PFCs": (1.0, 1.0)}),
        ("CO2", {"CO2": (1.0, 1.0)}),
    ],
)
def test_gas_groups_of_pure_gases_and_blends(ref, gas: str, groups: dict) -> None:
    found = ref.gas_groups(gas)
    assert {g: (round(v["mass_fraction"], 6), round(v["co2e_fraction"], 6)) for g, v in found.items()} == groups


def test_a_blend_across_groups_splits_its_co2e_by_component_gwp(ref) -> None:
    groups = ref.gas_groups("R-508A")  # 39% HFC-23 (12,400) + 61% PFC-116 (11,100); Table 12 GWP 11,607
    assert groups["HFCs"]["mass_fraction"] == pytest.approx(0.39)
    assert groups["HFCs"]["co2e_fraction"] == pytest.approx(0.39 * 12400 / 11607)
    assert groups["PFCs"]["co2e_fraction"] == pytest.approx(0.61 * 11100 / 11607)


def test_gases_without_a_known_split_say_so(ref) -> None:
    assert ref.gas_groups("R-454B") is None  # not in the Hub: the reviewer gave its GWP
    assert ref.gas_groups("HCFC-22") is None  # a Montreal Protocol gas, not reported
