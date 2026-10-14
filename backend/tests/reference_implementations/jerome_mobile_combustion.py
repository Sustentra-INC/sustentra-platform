"""Mobile combustion emissions (CO2, CH4, N2O -> CO2e), per the flow diagram.

The same fuel/vehicle records are processed twice:

CO2 LOOP - records grouped by fuel type (f = 1..n), fuel summed across all vehicles:
    CC present  -> Eq 3: Fuel x CC x 44/12
    HHV present -> Eq 2: Fuel x HHV x EF_CO2   (EF per MMBtu)
    neither     -> Eq 1: Fuel x EF_CO2         (EF per fuel unit)

CH4 / N2O LOOP - records grouped by vehicle group (v = 1..m):
    group = vehicle type + fuel type (+ model year for on-road gasoline / diesel)
    on-road  (cars, trucks, buses)   -> Eq 4: Distance x EF   (EF per mile)
        gasoline / diesel: EF by vehicle type + fuel type + model year
        alternative fuel:  EF by vehicle type + fuel type
    non-road (forklifts, ships, aircraft, construction and farm equipment)
                                     -> Eq 5: Fuel x EF       (EF per fuel unit)

Then: total per gas, CO2e per gas (CO2 GWP is always 1), and the overall total.

Emission factors and GWPs come from a separate reference database, not from the
company's documents, so they are passed in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

CO2_PER_C = 44 / 12          # molecular weight ratio CO2 / C
HHV_EF_UNIT = "MMBtu"        # Eq 2 uses CO2 emission factors per MMBtu
MODEL_YEAR_FUELS = ("gasoline", "diesel")  # on-road fuels whose EF depends on model year

# CO2 EF:      (fuel_type, unit) -> EF
Co2EfLookup = Callable[[str, str], float]
# CH4/N2O EF:  (gas, vehicle_type, fuel_type, model_year or None, unit) -> EF
#              unit = distance unit (e.g. "mile") on-road, fuel unit non-road
GasEfLookup = Callable[[str, str, str, "int | None", str], float]


@dataclass(frozen=True)
class MobileRecord:
    """One fuel / vehicle record found in the company's sources."""

    vehicle_type: str             # e.g. "Passenger Car", "Forklift"
    fuel_type: str                # e.g. "Motor Gasoline", "Diesel Fuel", "CNG"
    on_road: bool                 # True: cars, trucks, buses; False: non-road equipment
    fuel_quantity: float          # always needed: CO2 is fuel-based for every record
    fuel_unit: str                # e.g. "gallon", "scf"
    distance: float | None = None     # required on-road (Eq 4)
    distance_unit: str = "mile"
    model_year: int | None = None     # required on-road gasoline / diesel
    hhv: float | None = None          # MMBtu per fuel unit, if present
    cc: float | None = None           # carbon content (mass C per fuel unit), if present


@dataclass
class FuelTypeResult:          # one row of the CO2 loop
    fuel_type: str
    fuel_quantity: float
    fuel_unit: str
    co2: float
    equation: str              # "Eq 1" | "Eq 2" | "Eq 3"


@dataclass
class VehicleGroupResult:      # one row of the CH4 / N2O loop
    vehicle_type: str
    fuel_type: str
    model_year: int | None
    on_road: bool
    activity: float            # total distance (on-road) or total fuel (non-road)
    activity_unit: str
    ch4: float
    n2o: float
    equation: str              # "Eq 4" | "Eq 5"


@dataclass
class MobileCombustionResult:
    co2_by_fuel_type: list[FuelTypeResult]
    ch4_n2o_by_vehicle_group: list[VehicleGroupResult]
    total_mass: dict[str, float] = field(default_factory=dict)   # gas -> total mass
    co2e: dict[str, float] = field(default_factory=dict)         # gas -> total in CO2e
    total_co2e: float = 0.0


def _uses_model_year(fuel_type: str, model_year_fuels: Iterable[str]) -> bool:
    name = fuel_type.lower()
    return any(f in name for f in model_year_fuels)


def _single_value(values: Iterable[float | None], what: str, fuel_type: str) -> float | None:
    """HHV / CC must be the same for every record of a fuel type (or absent)."""
    present = {v for v in values if v is not None}
    if len(present) > 1:
        raise ValueError(f"Conflicting {what} values for fuel type {fuel_type!r}: {sorted(present)}")
    return present.pop() if present else None


def _as_lookup(source: Callable[..., float] | Mapping[tuple, float], name: str) -> Callable[..., float]:
    if not isinstance(source, Mapping):
        return source
    table = source

    def lookup(*key: object) -> float:
        try:
            return table[key]
        except KeyError:
            raise KeyError(f"No {name} emission factor for {key}") from None

    return lookup


def mobile_combustion_co2e(
    records: Iterable[MobileRecord],
    co2_emission_factor: Co2EfLookup | Mapping[tuple[str, str], float],
    ch4_n2o_emission_factor: GasEfLookup | Mapping[tuple[str, str, str, int | None, str], float],
    gwp: Mapping[str, float],
    model_year_fuels: Iterable[str] = MODEL_YEAR_FUELS,
) -> MobileCombustionResult:
    """Compute mobile combustion CO2 (by fuel type), CH4/N2O (by vehicle group), and total CO2e.

    records:                  fuel and vehicle records found across all company sources.
    co2_emission_factor:      CO2 EF by (fuel_type, unit). Eq 1 looks up the fuel unit,
                              Eq 2 looks up "MMBtu". A function or a dict.
    ch4_n2o_emission_factor:  CH4/N2O EF by (gas, vehicle_type, fuel_type, model_year, unit).
                              model_year is None unless on-road gasoline/diesel; unit is the
                              distance unit on-road and the fuel unit non-road.
    gwp:                      GWP for "CH4" and "N2O" (CO2 is always 1).
    model_year_fuels:         fuel-type substrings whose on-road EF depends on model year.
    """
    records = list(records)
    co2_ef = _as_lookup(co2_emission_factor, "CO2")
    gas_ef = _as_lookup(ch4_n2o_emission_factor, "CH4/N2O")
    model_year_fuels = tuple(f.lower() for f in model_year_fuels)

    missing = [g for g in ("CH4", "N2O") if g not in gwp]
    if missing:
        raise ValueError(f"GWP missing for {', '.join(missing)}")

    # --- CO2 LOOP: one pass per fuel type f = 1..n ------------------------------------
    by_fuel: dict[str, list[MobileRecord]] = {}
    for r in records:
        by_fuel.setdefault(r.fuel_type, []).append(r)

    co2_rows: list[FuelTypeResult] = []
    for fuel_type, group in by_fuel.items():
        units = {r.fuel_unit for r in group}
        if len(units) > 1:
            raise ValueError(f"Fuel type {fuel_type!r} has mixed units {sorted(units)}; convert first")
        unit = units.pop()
        fuel = sum(r.fuel_quantity for r in group)    # summed across on-road and non-road
        cc = _single_value((r.cc for r in group), "CC", fuel_type)
        hhv = _single_value((r.hhv for r in group), "HHV", fuel_type)

        if cc is not None:
            co2, eq = fuel * cc * CO2_PER_C, "Eq 3"
        elif hhv is not None:
            co2, eq = fuel * hhv * co2_ef(fuel_type, HHV_EF_UNIT), "Eq 2"
        else:
            co2, eq = fuel * co2_ef(fuel_type, unit), "Eq 1"
        co2_rows.append(FuelTypeResult(fuel_type, fuel, unit, co2, eq))

    # --- CH4 / N2O LOOP: one pass per vehicle group v = 1..m --------------------------
    by_group: dict[tuple[str, str, int | None, bool], list[MobileRecord]] = {}
    for r in records:
        model_year = None
        if r.on_road and _uses_model_year(r.fuel_type, model_year_fuels):
            if r.model_year is None:
                raise ValueError(f"On-road {r.fuel_type} {r.vehicle_type} needs a model year")
            model_year = r.model_year
        by_group.setdefault((r.vehicle_type, r.fuel_type, model_year, r.on_road), []).append(r)

    gas_rows: list[VehicleGroupResult] = []
    for (vehicle_type, fuel_type, model_year, on_road), group in by_group.items():
        if on_road:   # Eq 4: Distance x EF (per mile)
            if any(r.distance is None for r in group):
                raise ValueError(f"On-road {vehicle_type} / {fuel_type} needs a distance")
            units = {r.distance_unit for r in group}
            eq = "Eq 4"
            activity = sum(r.distance for r in group)  # type: ignore[misc]
        else:         # Eq 5: Fuel x EF (per fuel unit)
            units = {r.fuel_unit for r in group}
            eq = "Eq 5"
            activity = sum(r.fuel_quantity for r in group)
        if len(units) > 1:
            raise ValueError(f"Vehicle group {vehicle_type} / {fuel_type} has mixed units {sorted(units)}")
        unit = units.pop()

        ch4 = activity * gas_ef("CH4", vehicle_type, fuel_type, model_year, unit)
        n2o = activity * gas_ef("N2O", vehicle_type, fuel_type, model_year, unit)
        gas_rows.append(VehicleGroupResult(
            vehicle_type, fuel_type, model_year, on_road, activity, unit, ch4, n2o, eq))

    # --- Totals -----------------------------------------------------------------------
    total_mass = {
        "CO2": sum(r.co2 for r in co2_rows),
        "CH4": sum(r.ch4 for r in gas_rows),
        "N2O": sum(r.n2o for r in gas_rows),
    }
    co2e = {
        "CO2": total_mass["CO2"] * 1,
        "CH4": total_mass["CH4"] * gwp["CH4"],
        "N2O": total_mass["N2O"] * gwp["N2O"],
    }
    return MobileCombustionResult(
        co2_by_fuel_type=co2_rows,
        ch4_n2o_by_vehicle_group=gas_rows,
        total_mass=total_mass,
        co2e=co2e,
        total_co2e=sum(co2e.values()),
    )


if __name__ == "__main__":
    # Illustrative numbers only - real EFs/GWPs come from the reference database.
    co2_efs = {
        ("Motor Gasoline", "gallon"): 8.78,      # kg CO2 / gallon
        ("Diesel Fuel", "gallon"): 10.21,
        ("CNG", "MMBtu"): 53.06,                 # kg CO2 / MMBtu
    }
    ch4_n2o_efs = {
        # on-road gasoline/diesel: per mile, by model year
        ("CH4", "Passenger Car", "Motor Gasoline", 2019, "mile"): 0.0000050,  # kg / mile (all EFs in kg so CO2e adds up)
        ("N2O", "Passenger Car", "Motor Gasoline", 2019, "mile"): 0.0000019,
        ("CH4", "Passenger Car", "Motor Gasoline", 2022, "mile"): 0.0000049,
        ("N2O", "Passenger Car", "Motor Gasoline", 2022, "mile"): 0.0000018,
        # on-road alternative fuel: per mile, no model year
        ("CH4", "Bus", "CNG", None, "mile"): 0.0019670,
        ("N2O", "Bus", "CNG", None, "mile"): 0.0001880,
        # non-road: per fuel unit
        ("CH4", "Forklift", "Diesel Fuel", None, "gallon"): 0.00057,        # kg / gallon
        ("N2O", "Forklift", "Diesel Fuel", None, "gallon"): 0.00026,
    }
    records = [
        MobileRecord("Passenger Car", "Motor Gasoline", True, 1_200, "gallon", distance=30_000, model_year=2019),
        MobileRecord("Passenger Car", "Motor Gasoline", True, 800, "gallon", distance=22_000, model_year=2022),
        MobileRecord("Passenger Car", "Motor Gasoline", True, 400, "gallon", distance=11_000, model_year=2022),
        MobileRecord("Bus", "CNG", True, 50_000, "scf", distance=15_000, hhv=0.001026),
        MobileRecord("Forklift", "Diesel Fuel", False, 2_500, "gallon"),
    ]
    result = mobile_combustion_co2e(records, co2_efs, ch4_n2o_efs, gwp={"CH4": 28, "N2O": 265})

    print("CO2 by fuel type:")
    for r in result.co2_by_fuel_type:
        print(f"  {r.fuel_type}: {r.fuel_quantity:,} {r.fuel_unit} -> CO2 {r.co2:,.4f} ({r.equation})")
    print("CH4 / N2O by vehicle group:")
    for g in result.ch4_n2o_by_vehicle_group:
        year = f" {g.model_year}" if g.model_year else ""
        print(f"  {g.vehicle_type} / {g.fuel_type}{year}: {g.activity:,} {g.activity_unit} -> "
              f"CH4 {g.ch4:,.4f}, N2O {g.n2o:,.4f} ({g.equation})")
    for gas in ("CO2", "CH4", "N2O"):
        print(f"Total {gas}: {result.total_mass[gas]:,.4f}  ->  {result.co2e[gas]:,.4f} CO2e")
    print(f"Total mobile combustion CO2e: {result.total_co2e:,.4f}")
