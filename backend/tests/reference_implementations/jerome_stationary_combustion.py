"""Stationary combustion emissions (CO2, CH4, N2O -> CO2e), per the flow diagram.

For each fuel i = 1..n:
    CO2: CC present  -> Eq 3: Fuel x CC x 44/12
         HHV present -> Eq 2: Fuel x HHV x EF_CO2   (EF per MMBtu)
         neither     -> Eq 1: Fuel x EF_CO2         (EF per fuel unit)
    CH4, N2O: HHV present -> Eq 2, otherwise Eq 1 (CC never applies)

Then totals per gas, CO2e per gas (CO2 GWP is always 1), and the overall total.

Emission factors and GWPs come from a separate reference database, not from the
company's documents, so they are passed in: EFs as a lookup keyed by
(fuel type, gas, unit), GWPs as a constant per gas.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

GASES = ("CO2", "CH4", "N2O")
CO2_PER_C = 44 / 12  # molecular weight ratio CO2 / C
HHV_EF_UNIT = "MMBtu"  # Eq 2 uses emission factors per MMBtu

EfLookup = Callable[[str, str, str], float]  # (fuel_type, gas, unit) -> EF


@dataclass(frozen=True)
class Fuel:
    """One row of the fuel list in the workbook."""

    fuel_type: str
    quantity: float
    unit: str                  # e.g. "scf", "gallon", "therm", "MMBtu"
    hhv: float | None = None   # MMBtu per fuel unit, if present
    cc: float | None = None    # carbon content (mass C per fuel unit), if present


@dataclass
class FuelResult:
    fuel: Fuel
    mass: dict[str, float]      # gas -> mass of that gas for this fuel
    equation: dict[str, str]    # gas -> "Eq 1" | "Eq 2" | "Eq 3"


@dataclass
class CombustionResult:
    per_fuel: list[FuelResult]
    total_mass: dict[str, float] = field(default_factory=dict)  # gas -> total mass
    co2e: dict[str, float] = field(default_factory=dict)        # gas -> total in CO2e
    total_co2e: float = 0.0


def _gas_mass(fuel: Fuel, gas: str, ef: EfLookup) -> tuple[float, str]:
    """Pick the equation for one gas of one fuel and compute its mass."""
    if gas == "CO2" and fuel.cc is not None:
        return fuel.quantity * fuel.cc * CO2_PER_C, "Eq 3"
    if fuel.hhv is not None:
        return fuel.quantity * fuel.hhv * ef(fuel.fuel_type, gas, HHV_EF_UNIT), "Eq 2"
    return fuel.quantity * ef(fuel.fuel_type, gas, fuel.unit), "Eq 1"


def stationary_combustion_co2e(
    fuels: Iterable[Fuel],
    emission_factor: EfLookup | Mapping[tuple[str, str, str], float],
    gwp: Mapping[str, float],
) -> CombustionResult:
    """Compute per-fuel gas masses, per-gas totals, CO2e, and total stationary combustion CO2e.

    fuels:            the fuel list from the workbook.
    emission_factor:  EF lookup by (fuel_type, gas, unit) - a function or a dict.
                      Eq 1 looks up the fuel's own unit; Eq 2 looks up "MMBtu".
    gwp:              GWP for "CH4" and "N2O" (CO2 is always 1).
    """
    if isinstance(emission_factor, Mapping):
        table = emission_factor

        def ef(fuel_type: str, gas: str, unit: str) -> float:
            try:
                return table[(fuel_type, gas, unit)]
            except KeyError:
                raise KeyError(f"No emission factor for {fuel_type!r}, {gas}, per {unit!r}") from None
    else:
        ef = emission_factor

    missing = [g for g in ("CH4", "N2O") if g not in gwp]
    if missing:
        raise ValueError(f"GWP missing for {', '.join(missing)}")
    gwp_by_gas = {"CO2": 1.0, "CH4": gwp["CH4"], "N2O": gwp["N2O"]}

    # Loop: one result per fuel i = 1..n
    per_fuel: list[FuelResult] = []
    for fuel in fuels:
        mass: dict[str, float] = {}
        equation: dict[str, str] = {}
        for gas in GASES:
            mass[gas], equation[gas] = _gas_mass(fuel, gas, ef)
        per_fuel.append(FuelResult(fuel=fuel, mass=mass, equation=equation))

    # All fuels done: total per gas, convert to CO2e, sum
    total_mass = {gas: sum(r.mass[gas] for r in per_fuel) for gas in GASES}
    co2e = {gas: total_mass[gas] * gwp_by_gas[gas] for gas in GASES}
    return CombustionResult(
        per_fuel=per_fuel,
        total_mass=total_mass,
        co2e=co2e,
        total_co2e=sum(co2e.values()),
    )


if __name__ == "__main__":
    # Illustrative numbers only - real EFs/GWPs come from the reference database.
    efs = {
        ("Natural Gas", "CO2", "MMBtu"): 53.06,      # kg/MMBtu
        ("Natural Gas", "CH4", "MMBtu"): 0.001,
        ("Natural Gas", "N2O", "MMBtu"): 0.0001,
        ("Distillate Fuel Oil No. 2", "CO2", "gallon"): 10.21,  # kg/gallon
        ("Distillate Fuel Oil No. 2", "CH4", "gallon"): 0.00041,
        ("Distillate Fuel Oil No. 2", "N2O", "gallon"): 0.00008,
        ("Distillate Fuel Oil No. 2", "CH4", "MMBtu"): 0.003,
        ("Distillate Fuel Oil No. 2", "N2O", "MMBtu"): 0.0006,
    }
    fuels = [
        Fuel("Natural Gas", 100_000, "scf", hhv=0.001026),            # Eq 2 for all gases
        Fuel("Distillate Fuel Oil No. 2", 5_000, "gallon"),           # Eq 1 for all gases
        Fuel("Distillate Fuel Oil No. 2", 2_000, "gallon", hhv=0.138, cc=2.8),  # Eq 3 CO2, Eq 2 CH4/N2O
    ]
    result = stationary_combustion_co2e(fuels, efs, gwp={"CH4": 28, "N2O": 265})

    for i, r in enumerate(result.per_fuel, 1):
        cells = ", ".join(f"{g} {r.mass[g]:,.4f} ({r.equation[g]})" for g in GASES)
        print(f"Fuel {i} [{r.fuel.fuel_type}]: {cells}")
    for g in GASES:
        print(f"Total {g}: {result.total_mass[g]:,.4f}  ->  {result.co2e[g]:,.4f} CO2e")
    print(f"Total stationary combustion CO2e: {result.total_co2e:,.4f}")