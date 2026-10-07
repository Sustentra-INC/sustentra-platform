from __future__ import annotations

import pytest

from backend.app.domain.fuel_units import (
    ENERGY,
    GAS_VOLUME,
    LIQUID_VOLUME,
    MASS,
    UnitError,
    canonical_unit,
    convert,
    dimension_of,
    find_unit,
    normalize_quantity,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("MMBtu", "MMBtu"),
        ("mmbtu", "MMBtu"),
        ("Therms", "therm"),
        ("THM", "therm"),
        ("Dth", "Dth"),
        ("Dekatherms", "Dth"),
        ("kWh", "kWh"),
        ("GJ", "GJ"),
        ("CCF", "ccf"),
        ("HCF", "ccf"),
        ("MCF", "Mcf"),
        ("Mscf", "Mcf"),
        ("SCF", "scf"),
        ("cubic feet", "scf"),
        ("m³", "m3"),
        ("Gallons", "gal"),
        ("gal.", "gal"),
        ("Liters", "L"),
        ("litres", "L"),
        ("BBL", "bbl"),
        ("Short Tons", "short_ton"),
        ("tonnes", "metric_ton"),
        ("lbs", "lb"),
        ("(Therms)", "therm"),
        ("widgets", None),
        ("", None),
        (None, None),
    ],
)
def test_canonical_unit(label: str | None, expected: str | None) -> None:
    assert canonical_unit(label) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("32,400 MMBtu", "MMBtu"),
        ("Usage (Therms)", "therm"),
        ("Total: 1,250 CCF", "ccf"),
        ("Gallons Delivered 500.0", "gal"),
        ("Fuel oil #2, 2,500 liters", "L"),
        ("Usage 4,000 cubic feet", "scf"),
        ("Natural gas commodity", None),
        # single-letter / ambiguous aliases are only accepted as a whole label
        ("Tank T-4", None),
        ("Account L-100", None),
    ],
)
def test_find_unit_in_text(text: str, expected: str | None) -> None:
    assert find_unit(text) == expected


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        # energy -> MMBtu (exact or defined constants)
        (10, "therm", "MMBtu", 1.0),
        (3240, "therm", "MMBtu", 324.0),
        (5, "Dth", "MMBtu", 5.0),
        (1_000_000, "Btu", "MMBtu", 1.0),
        (1000, "kWh", "MMBtu", 3.412142),
        (2, "MWh", "MMBtu", 6.824283),
        (100, "GJ", "MMBtu", 94.781712),
        (1, "MMBtu", "therm", 10.0),
        (1, "MMBtu", "kWh", 293.07107),
        # gas volume
        (12, "ccf", "scf", 1200.0),
        (3, "Mcf", "scf", 3000.0),
        (25, "ccf", "Mcf", 2.5),
        (1, "MMcf", "Mcf", 1000.0),
        (100, "m3", "scf", 3531.466672),
        # liquid volume
        (1, "gal", "L", 3.785412),
        (3785.411784, "L", "gal", 1000.0),
        (2, "bbl", "gal", 84.0),
        # mass
        (1, "short_ton", "kg", 907.18474),
        (1, "metric_ton", "short_ton", 1.102311),
        (2000, "lb", "short_ton", 1.0),
    ],
)
def test_convert(value: float, from_unit: str, to_unit: str, expected: float) -> None:
    assert convert(value, from_unit, to_unit) == pytest.approx(expected, rel=1e-6)


def test_convert_identity() -> None:
    assert convert(42.5, "gal", "gal") == 42.5


@pytest.mark.parametrize(("from_unit", "to_unit"), [("ccf", "MMBtu"), ("gal", "MMBtu"), ("gal", "scf"), ("kg", "L")])
def test_convert_across_dimensions_needs_heating_value(from_unit: str, to_unit: str) -> None:
    with pytest.raises(UnitError, match="heating value"):
        convert(1, from_unit, to_unit)


def test_convert_unknown_unit() -> None:
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1, "furlong", "gal")
    with pytest.raises(UnitError, match="unknown unit"):
        convert(1, "gal", "furlong")
    with pytest.raises(UnitError, match="unknown unit"):
        dimension_of("furlong")


@pytest.mark.parametrize(
    ("unit", "dimension"),
    [("MMBtu", ENERGY), ("therm", ENERGY), ("ccf", GAS_VOLUME), ("scf", GAS_VOLUME), ("gal", LIQUID_VOLUME), ("L", LIQUID_VOLUME), ("short_ton", MASS)],
)
def test_dimension_of(unit: str, dimension: str) -> None:
    assert dimension_of(unit) == dimension


def test_normalize_energy_converts_to_mmbtu() -> None:
    result = normalize_quantity(3240, "Therms")
    assert result.value == pytest.approx(324.0)
    assert result.unit == "MMBtu"
    assert result.dimension == ENERGY
    assert result.original_value == 3240
    assert result.original_unit == "therm"
    assert result.converted is True


def test_normalize_mmbtu_is_unchanged() -> None:
    result = normalize_quantity(32400, "MMBtu")
    assert (result.value, result.unit, result.converted) == (32400, "MMBtu", False)


@pytest.mark.parametrize(
    ("unit_text", "unit"),
    [("CCF", "ccf"), ("MCF", "Mcf"), ("scf", "scf"), ("Gallons", "gal"), ("Liters", "L"), ("short tons", "short_ton")],
)
def test_normalize_volume_and_mass_keep_the_stated_unit(unit_text: str, unit: str) -> None:
    result = normalize_quantity(1250, unit_text)
    assert (result.value, result.unit, result.converted) == (1250, unit, False)


def test_normalize_unknown_unit() -> None:
    with pytest.raises(UnitError):
        normalize_quantity(1, "widgets")


@pytest.mark.parametrize(("label", "unit"), [("GGE", "GGE"), ("gasoline gallon equivalents", "GGE"), ("DGE", "DGE")])
def test_gallon_equivalents_are_recognized_and_kept(label: str, unit: str) -> None:
    from backend.app.domain.fuel_units import FUEL_EQUIVALENT

    assert canonical_unit(label) == unit
    assert dimension_of(unit) == FUEL_EQUIVALENT
    result = normalize_quantity(412.6, label)
    assert (result.value, result.unit, result.converted) == (412.6, unit, False)
    assert convert(5, unit, unit) == 5
    with pytest.raises(UnitError, match="fuel equivalent"):
        convert(1, "GGE", "DGE")
