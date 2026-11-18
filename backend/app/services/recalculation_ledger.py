"""What the recalculation counted, record by record: the ledger the calculation lines re-add.

A leaf module (it imports no service): the recalculation fills a ``Ledger`` as it builds the
stationary, mobile and electricity categories, and ``recalculation_lines`` reads it. Keeping it
here means the lines are made from exactly what the categories used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.domain import fuel_units
from backend.app.services import emissions_calculator as calc
from backend.app.services.reviewed_evidence import ReviewedRecord

# Base unit per dimension used to sum quantities of one fuel across bills.
BASE_UNIT = {
    fuel_units.ENERGY: "MMBtu",
    fuel_units.GAS_VOLUME: "scf",
    fuel_units.LIQUID_VOLUME: "gal",
    fuel_units.MASS: "short_ton",
}


@dataclass
class Contribution:
    """One reviewed record's part in a recalculated number, as the category counted it."""

    family: str  # "stationary" | "mobile" | "electricity"
    record: ReviewedRecord
    sub: tuple[str, ...]  # (fuel, base unit) for fuels; (facility,) for electricity
    quantity: float  # reviewed quantity, before the reporting-period share
    counted: float  # quantity x share, in ``unit``
    unit: str
    share: float
    start: Any
    end: Any
    flags: list[str]


@dataclass
class Ledger:
    contributions: list[Contribution] = field(default_factory=list)
    # (fuel, base unit) -> [(index into settings vehicle_groups, the group the category used)]
    mobile_groups: dict[tuple[str, str], list[tuple[int, calc.VehicleGroup]]] = field(default_factory=dict)
    regions: dict[str, str] = field(default_factory=dict)  # electricity facility -> eGRID subregion
