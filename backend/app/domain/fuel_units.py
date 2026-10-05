"""Fuel quantity units for Scope 1 stationary combustion (EXT-001).

Parses the unit labels found on fuel bills and delivery tickets into canonical units
and converts between units of the same dimension.

Policy (Scope 1 schema S1-STC-010/080/110 store the physical quantity + its unit; the
heat-content conversion is a separate, HHV-driven calculation step, S1-STC-020):

* energy units (therm, Dth, kWh, MWh, GJ, Btu) are converted to MMBtu, which is exact;
* gas volume (scf, ccf, Mcf, MMcf, m3), liquid volume (gal, L, bbl) and mass
  (lb, kg, short ton, metric ton) keep their canonical unit. Turning them into energy
  needs the fuel's heating value, so extraction never does it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

ENERGY = "energy"
GAS_VOLUME = "gas_volume"
LIQUID_VOLUME = "liquid_volume"
MASS = "mass"

# Canonical unit -> (dimension, size in the dimension's base unit).
# Bases: energy = MMBtu, gas volume = scf, liquid volume = gal (US), mass = kg.
_UNITS: dict[str, tuple[str, Decimal]] = {
    "MMBtu": (ENERGY, Decimal("1")),
    "Dth": (ENERGY, Decimal("1")),  # dekatherm = 10 therms = 1,000,000 Btu
    "therm": (ENERGY, Decimal("0.1")),  # 100,000 Btu
    "Btu": (ENERGY, Decimal("0.000001")),
    "kWh": (ENERGY, Decimal("0.003412141633")),  # 3,412.141633 Btu (IT)
    "MWh": (ENERGY, Decimal("3.412141633")),
    "GJ": (ENERGY, Decimal("0.9478171203")),
    "scf": (GAS_VOLUME, Decimal("1")),
    "ccf": (GAS_VOLUME, Decimal("100")),
    "Mcf": (GAS_VOLUME, Decimal("1000")),
    "MMcf": (GAS_VOLUME, Decimal("1000000")),
    "m3": (GAS_VOLUME, Decimal("35.31466672")),  # 1 m3 = 35.31466672 ft3
    "gal": (LIQUID_VOLUME, Decimal("1")),
    "L": (LIQUID_VOLUME, Decimal("0.2641720524")),  # 1 L = 1 / 3.785411784 gal
    "bbl": (LIQUID_VOLUME, Decimal("42")),
    "kg": (MASS, Decimal("1")),
    "lb": (MASS, Decimal("0.45359237")),
    "short_ton": (MASS, Decimal("907.18474")),
    "metric_ton": (MASS, Decimal("1000")),
}

# Unit each dimension is normalized to during extraction (None = keep as stated).
_NORMALIZED_UNIT: dict[str, str | None] = {
    ENERGY: "MMBtu",
    GAS_VOLUME: None,
    LIQUID_VOLUME: None,
    MASS: None,
}

# Alias (lower-case, spaces collapsed, trailing '.' removed) -> canonical unit.
_ALIASES: dict[str, str] = {}


def _alias(canonical: str, *aliases: str) -> None:
    for alias in (canonical, *aliases):
        _ALIASES[alias.lower()] = canonical


_alias("MMBtu", "mmbtus", "mm btu", "mmbtu's", "million btu", "mbtu (millions)")
_alias("Dth", "dth", "dths", "dekatherm", "dekatherms", "decatherm", "decatherms", "dt")
_alias("therm", "therms", "thm", "thms")
_alias("Btu", "btus", "british thermal units")
_alias("kWh", "kwh", "kwhs", "kw h", "kilowatt hour", "kilowatt hours", "kilowatt-hour", "kilowatt-hours")
_alias("MWh", "mwh", "megawatt hour", "megawatt hours")
_alias("GJ", "gj", "gigajoule", "gigajoules")
_alias("scf", "cf", "cu ft", "cu. ft", "cubic feet", "cubic foot", "ft3", "ft³", "standard cubic feet")
_alias("ccf", "hcf", "ccfs", "hundred cubic feet", "100 cubic feet", "100 cf")
_alias("Mcf", "mcf", "mcfs", "mscf", "thousand cubic feet", "1000 cubic feet")
_alias("MMcf", "mmcf", "mmscf", "million cubic feet")
_alias("m3", "m³", "cubic meter", "cubic meters", "cubic metre", "cubic metres", "cu m", "sm3", "nm3")
_alias("gal", "gals", "gallon", "gallons", "us gal", "us gallon", "us gallons", "gl")
_alias("L", "l", "liter", "liters", "litre", "litres", "ltr", "ltrs", "lt")
_alias("bbl", "bbls", "barrel", "barrels")
_alias("kg", "kgs", "kilogram", "kilograms")
_alias("lb", "lbs", "pound", "pounds")
_alias("short_ton", "ton", "tons", "short ton", "short tons", "st")
_alias("metric_ton", "tonne", "tonnes", "metric ton", "metric tons", "mt", "t")

# Longest aliases first so "cubic feet" wins over "cf" and "mmbtu" over "btu".
_UNIT_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(a) for a in sorted(_ALIASES, key=len, reverse=True))
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# Aliases too ambiguous to trust when scanning free text (only accepted as a whole cell).
_AMBIGUOUS_IN_TEXT = {"l", "t", "mt", "st", "dt", "lt", "gl", "cf", "ton", "tons"}


class UnitError(ValueError):
    """Raised for unknown units or conversions across dimensions."""


@dataclass(frozen=True)
class NormalizedQuantity:
    value: float
    unit: str
    dimension: str
    original_value: float
    original_unit: str
    converted: bool


def canonical_unit(text: str | None) -> str | None:
    """Canonical unit for a whole label ("Therms" -> "therm"), or None if unknown."""

    if text is None:
        return None
    key = " ".join(str(text).strip().rstrip(".").replace("(", " ").replace(")", " ").split()).lower()
    return _ALIASES.get(key)


def find_unit(text: str | None) -> str | None:
    """First recognizable unit mentioned inside free text ("32,400 MMBtu" -> "MMBtu")."""

    if not text:
        return None
    whole = canonical_unit(text)
    if whole is not None:
        return whole
    for match in _UNIT_TOKEN_RE.finditer(str(text)):
        token = match.group(1).lower()
        if token in _AMBIGUOUS_IN_TEXT:
            continue
        return _ALIASES[token]
    return None


def dimension_of(unit: str) -> str:
    try:
        return _UNITS[unit][0]
    except KeyError as exc:
        raise UnitError(f"unknown unit: {unit!r}") from exc


def convert(value: float | int | Decimal, from_unit: str, to_unit: str) -> float:
    """Convert between canonical units of the same dimension."""

    from_dim, from_size = _UNITS.get(from_unit, (None, None))
    to_dim, to_size = _UNITS.get(to_unit, (None, None))
    if from_dim is None or from_size is None:
        raise UnitError(f"unknown unit: {from_unit!r}")
    if to_dim is None or to_size is None:
        raise UnitError(f"unknown unit: {to_unit!r}")
    if from_dim != to_dim:
        raise UnitError(
            f"cannot convert {from_unit} ({from_dim}) to {to_unit} ({to_dim}) without a heating value"
        )
    result = Decimal(str(value)) * from_size / to_size
    return float(round(result, 6))


def normalize_quantity(value: float | int, unit_text: str) -> NormalizedQuantity:
    """Canonicalize ``unit_text`` and apply the extraction normalization policy."""

    unit = canonical_unit(unit_text) or find_unit(unit_text)
    if unit is None:
        raise UnitError(f"unknown unit: {unit_text!r}")
    dimension = dimension_of(unit)
    target = _NORMALIZED_UNIT[dimension] or unit
    converted_value = convert(value, unit, target) if target != unit else float(value)
    return NormalizedQuantity(
        value=converted_value,
        unit=target,
        dimension=dimension,
        original_value=float(value),
        original_unit=unit,
        converted=target != unit,
    )


SUPPORTED_UNITS: tuple[str, ...] = tuple(_UNITS)
