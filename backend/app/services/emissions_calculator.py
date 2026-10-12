"""Emissions recalculation: Structure Breakdown step 3 of the GHG Required Data workbook.

Implements the equations written in "Data from Evidence (Scope 1)" and "(Scope 2)":

Stationary combustion (once per fuel type)
    CO2      Eq 3 if carbon content (CC) is given, Eq 2 if heat content (HHV) is given, else Eq 1
    CH4, N2O Eq 2 if HHV is given, else Eq 1 (Eq 3 produces CO2 only)
    Eq 1  Fuel x EF1        Eq 2  Fuel x HHV x EF2        Eq 3  Fuel x CC x 44/12
Mobile combustion
    CO2 per fuel type with the same Eq 1/2/3 route (Eq 1 factor from Table 2)
    CH4, N2O per vehicle group: Eq 4 on-road  Distance x EF4 (g per vehicle-mile, Tables 3-4)
                                Eq 5 non-road Fuel x EF5 (g per gallon, Table 5)
Purchased electricity (once per facility, per gas)
    location-based  Emissions = MWh x EF (lb/MWh, eGRID Table 6), then lb / 2,204.62 = metric tons
    market-based    the same on the remainder: MWh x (1 - certificate coverage %)
Purchased industrial gases
    emissions = amount purchased; CO2e = mass x GWP

Every gas result is in metric tons and converted to CO2e with GWP from Table 11. Each
calculation records its steps (formula, inputs with units and sources, result), so the
work can be shown next to the number. Factors come from the EPA GHG Emission Factors Hub
2025 via ``EmissionFactorReference``; nothing is assumed: a missing factor raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    EPA_UNIT_TO_CANONICAL,
    EmissionFactorReference,
    Factor,
    default_emission_factor_reference,
)

GASES = ("CO2", "CH4", "N2O")
LB_PER_METRIC_TON = 2204.62  # workbook: "metric tons = lb / 2,204.62"
KG_PER_METRIC_TON = 1000.0
G_PER_METRIC_TON = 1_000_000.0
CO2_PER_C = 44 / 12  # Eq 3 stoichiometry
KWH_PER_MWH = 1000.0  # workbook: "MWh = kWh / 1,000"
KM_PER_MILE = 1.609344
COMPARISON_TOLERANCE_PCT = 5.0  # flag reported vs recalculated differences over 5%

PERCENT_BY_MASS = "percent by mass"
KG_C_PER_MMBTU = "kg C per mmBtu"


class CalculationError(ValueError):
    """The inputs cannot produce a result (missing or incompatible data)."""


# =========================================================================================
# Inputs
# =========================================================================================
@dataclass
class Measure:
    value: float
    unit: str
    source: str | None = None  # provenance of an extracted input, e.g. "EV-12 p.1"


@dataclass
class StationaryFuel:
    fuel_type: str  # EPA Table 1 name, e.g. "Natural Gas"
    quantity: Measure
    heat_content: Measure | None = None  # HHV, unit "<energy> per <physical unit>"
    carbon_content: Measure | None = None  # unit "percent by mass" or "kg C per mmBtu"


@dataclass
class VehicleGroup:
    vehicle_type: str  # Table 3/4/5 vehicle type
    factor_fuel_type: str  # fuel as named in the CH4/N2O table ("Diesel", "Gasoline (4 stroke)")
    on_road: bool
    model_year: int | None = None
    distance: Measure | None = None  # Eq 4 (on-road): miles or km
    fuel_quantity: Measure | None = None  # Eq 5 (non-road): gallons or litres


@dataclass
class MobileFuel:
    fuel_type: str  # EPA Table 2 name, e.g. "Diesel Fuel"
    quantity: Measure
    vehicle_groups: list[VehicleGroup] = field(default_factory=list)
    heat_content: Measure | None = None
    carbon_content: Measure | None = None
    energy_basis_fuel_type: str | None = None  # Table 1 name whose kg/mmBtu factor Eq 2 uses


@dataclass
class FacilityElectricity:
    facility: str
    consumption: Measure  # kWh or MWh
    egrid_subregion: str
    factors: dict[str, Factor] | None = None  # override (e.g. to reproduce a worked example)


@dataclass
class Certificate:
    label: str
    mwh: float
    source: str | None = None


@dataclass
class PurchasedGas:
    gas: str
    amount: Measure  # lb, kg, short ton or metric ton
    gwp_override: float | None = None


# =========================================================================================
# Results
# =========================================================================================
@dataclass
class Step:
    label: str
    formula: str
    inputs: dict[str, dict[str, Any]]
    result: float
    result_unit: str


@dataclass
class LineResult:
    key: str
    equations: dict[str, str]
    mass_t: dict[str, float]
    steps: list[Step] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    biogenic_co2_t: float = 0.0


@dataclass
class CategoryResult:
    category: str
    lines: list[LineResult]
    total_mass_t: dict[str, float]
    total_co2e_t: dict[str, float]
    total_co2e: float
    gwp: dict[str, dict[str, Any]]
    biogenic_co2_t: float = 0.0
    steps: list[Step] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    gwp_set: str = DEFAULT_GWP_SET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _inp(value: float, unit: str, source: str | None = None) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": source}


def _canonical(unit: str) -> str:
    found = fuel_units.canonical_unit(unit) or fuel_units.find_unit(unit)
    if found is None:
        raise CalculationError(f"Unrecognized unit {unit!r}.")
    return found


def _to_metric_tons(value: float, unit: str) -> float:
    return fuel_units.convert_exact(value, _canonical(unit), "metric_ton")


# =========================================================================================
# Shared: totals + GWP
# =========================================================================================
def _category(category: str, lines: list[LineResult], ref: EmissionFactorReference, gases: tuple[str, ...] = GASES,
              flags: list[str] | None = None, details: dict[str, Any] | None = None,
              gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    steps: list[Step] = []
    total_mass = {gas: sum(line.mass_t.get(gas, 0.0) for line in lines) for gas in gases}
    gwp: dict[str, dict[str, Any]] = {}
    total_co2e: dict[str, float] = {}
    for gas in gases:
        steps.append(Step(f"Total {gas} emissions, in mass", f"sum of all {gas} outputs",
                          {line.key: _inp(line.mass_t.get(gas, 0.0), "t") for line in lines},
                          total_mass[gas], "t"))
        factor = ref.gwp(gas, gwp_set)
        gwp[gas] = {"value": factor.value, "source": factor.source}
        total_co2e[gas] = total_mass[gas] * factor.value
        steps.append(Step(f"Total {gas} emissions, in CO2e", f"total {gas} mass x GWP",
                          {"mass": _inp(total_mass[gas], "t"), "GWP": _inp(factor.value, "", factor.source)},
                          total_co2e[gas], "t CO2e"))
    total = sum(total_co2e.values())
    steps.append(Step(f"Total {category.replace('_', ' ')} emissions, in CO2e",
                      " + ".join(f"{g} in CO2e" for g in gases),
                      {g: _inp(total_co2e[g], "t CO2e") for g in gases}, total, "t CO2e"))
    biogenic = sum(line.biogenic_co2_t for line in lines)
    all_flags = list(flags or [])
    for line in lines:
        all_flags.extend(f for f in line.flags if f not in all_flags)
    return CategoryResult(category, lines, total_mass, total_co2e, total, gwp, biogenic, steps, all_flags,
                          details or {}, gwp_set)


# =========================================================================================
# Fuel combustion (Eq 1 / Eq 2 / Eq 3)
# =========================================================================================
def _energy_mmbtu(quantity: Measure, heat_content: Measure | None) -> tuple[float, Step | None]:
    """Fuel energy in mmBtu: direct when the quantity is already energy, else Fuel x HHV."""

    unit = _canonical(quantity.unit)
    if fuel_units.dimension_of(unit) == fuel_units.ENERGY:
        return fuel_units.convert_exact(quantity.value, unit, "MMBtu"), None
    if heat_content is None:
        raise CalculationError("Heat content (HHV) is required to express this fuel quantity as energy.")
    if " per " not in heat_content.unit:
        raise CalculationError(f"Heat content unit {heat_content.unit!r} must read '<energy> per <unit>'.")
    energy_text, per_text = heat_content.unit.split(" per ", 1)
    energy_unit = _canonical(energy_text)
    per_unit = _canonical(per_text)
    if fuel_units.dimension_of(per_unit) != fuel_units.dimension_of(unit):
        raise CalculationError(f"Heat content is per {per_text!r} but the fuel is measured in {quantity.unit!r}.")
    quantity_in_hhv_unit = fuel_units.convert_exact(quantity.value, unit, per_unit)
    mmbtu = quantity_in_hhv_unit * fuel_units.convert_exact(heat_content.value, energy_unit, "MMBtu")
    step = Step("Fuel energy", "Fuel x HHV",
                {"fuel": _inp(quantity.value, quantity.unit, quantity.source),
                 "HHV": _inp(heat_content.value, heat_content.unit, heat_content.source)}, mmbtu, "mmBtu")
    return mmbtu, step


def _co2_eq3(quantity: Measure, carbon: Measure, heat_content: Measure | None) -> tuple[float, list[Step]]:
    """CO2 in metric tons by Eq 3: Fuel x CC x 44/12."""

    steps: list[Step] = []
    cc_unit = " ".join(carbon.unit.lower().split())
    if cc_unit in ("percent by mass", "%", "percent", "% by mass", "mass percent"):
        unit = _canonical(quantity.unit)
        if fuel_units.dimension_of(unit) != fuel_units.MASS:
            raise CalculationError("Carbon content as percent by mass needs the fuel quantity in a mass unit.")
        fuel_kg = fuel_units.convert_exact(quantity.value, unit, "kg")
        carbon_kg = fuel_kg * carbon.value / 100
    elif cc_unit == KG_C_PER_MMBTU.lower():
        mmbtu, energy_step = _energy_mmbtu(quantity, heat_content)
        if energy_step:
            steps.append(energy_step)
        carbon_kg = mmbtu * carbon.value
    else:
        raise CalculationError(f"Carbon content unit {carbon.unit!r} is not '{PERCENT_BY_MASS}' or '{KG_C_PER_MMBTU}'.")
    co2_t = carbon_kg * CO2_PER_C / KG_PER_METRIC_TON
    steps.append(Step("CO2 (Eq 3)", "Fuel x CC x 44/12",
                      {"fuel": _inp(quantity.value, quantity.unit, quantity.source),
                       "CC": _inp(carbon.value, carbon.unit, carbon.source),
                       "44/12": _inp(CO2_PER_C, "kg CO2 per kg C")}, co2_t, "t"))
    return co2_t, steps


def stationary_combustion(fuels: list[StationaryFuel], ref: EmissionFactorReference | None = None,
                          gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    ref = ref or default_emission_factor_reference()
    lines: list[LineResult] = []
    for fuel in fuels:
        row = ref.stationary_fuel(fuel.fuel_type)
        cite = ref.cite(row)
        energy = row["per_energy"]
        line = LineResult(fuel.fuel_type, {}, {})
        unit = _canonical(fuel.quantity.unit)
        is_energy = fuel_units.dimension_of(unit) == fuel_units.ENERGY

        def energy_route(eq: str, gas: str, key: str, scale: float, per: str) -> float:
            mmbtu, energy_step = _energy_mmbtu(fuel.quantity, fuel.heat_content)
            if energy_step and not any(s.label == "Fuel energy" for s in line.steps):
                line.steps.append(energy_step)
            ef = float(energy[key])
            mass_t = mmbtu * ef / scale
            formula = "Fuel x HHV x EF2" if eq == "Eq 2" else "Fuel (mmBtu) x EF1"
            line.steps.append(Step(f"{gas} ({eq})", formula,
                                   {"fuel energy": _inp(mmbtu, "mmBtu"), "EF": _inp(ef, per, cite)}, mass_t, "t"))
            return mass_t

        def unit_route(gas: str, key: str, scale: float, per: str) -> float:
            per_unit = row["per_unit"]
            if per_unit is None:
                raise CalculationError(f"{fuel.fuel_type} has only energy-basis factors; give its heat content.")
            epa_unit = EPA_UNIT_TO_CANONICAL[per_unit["unit"]]
            if fuel_units.dimension_of(epa_unit) != fuel_units.dimension_of(unit):
                raise CalculationError(
                    f"{fuel.fuel_type} factors are per {per_unit['unit']}; {fuel.quantity.unit!r} cannot be "
                    "converted to it without a heat content."
                )
            quantity = fuel_units.convert_exact(fuel.quantity.value, unit, epa_unit)
            ef = float(per_unit[key])
            mass_t = quantity * ef / scale
            line.steps.append(Step(f"{gas} (Eq 1)", "Fuel x EF1",
                                   {"fuel": _inp(quantity, per_unit["unit"], fuel.quantity.source),
                                    "EF1": _inp(ef, f"{per} per {per_unit['unit']}", cite)}, mass_t, "t"))
            if quantity != fuel.quantity.value:
                line.flags.append("unit_converted")
            return mass_t

        # CO2: Eq 3 if CC, Eq 2 if HHV, else Eq 1
        if fuel.carbon_content is not None:
            co2_t, steps = _co2_eq3(fuel.quantity, fuel.carbon_content, fuel.heat_content)
            line.steps.extend(steps)
            line.equations["CO2"] = "Eq 3"
        elif fuel.heat_content is not None:
            co2_t = energy_route("Eq 2", "CO2", "co2_kg_per_mmbtu", KG_PER_METRIC_TON, "kg CO2 per mmBtu")
            line.equations["CO2"] = "Eq 2"
        elif is_energy:
            co2_t = energy_route("Eq 1", "CO2", "co2_kg_per_mmbtu", KG_PER_METRIC_TON, "kg CO2 per mmBtu")
            line.equations["CO2"] = "Eq 1"
        else:
            co2_t = unit_route("CO2", "co2_kg_per_unit", KG_PER_METRIC_TON, "kg CO2")
            line.equations["CO2"] = "Eq 1"
        # CH4, N2O: Eq 2 if HHV, else Eq 1
        for gas, energy_key, unit_key in (("CH4", "ch4_g_per_mmbtu", "ch4_g_per_unit"),
                                          ("N2O", "n2o_g_per_mmbtu", "n2o_g_per_unit")):
            if fuel.heat_content is not None:
                line.mass_t[gas] = energy_route("Eq 2", gas, energy_key, G_PER_METRIC_TON, f"g {gas} per mmBtu")
                line.equations[gas] = "Eq 2"
            elif is_energy:
                line.mass_t[gas] = energy_route("Eq 1", gas, energy_key, G_PER_METRIC_TON, f"g {gas} per mmBtu")
                line.equations[gas] = "Eq 1"
            else:
                line.mass_t[gas] = unit_route(gas, unit_key, G_PER_METRIC_TON, f"g {gas}")
                line.equations[gas] = "Eq 1"
        if str(row.get("category") or "").startswith("Biomass"):
            line.biogenic_co2_t = co2_t
            line.mass_t["CO2"] = 0.0
            line.flags.append("biogenic_co2_reported_separately")
        else:
            line.mass_t["CO2"] = co2_t
        lines.append(line)
    return _category("stationary_combustion", lines, ref, gwp_set=gwp_set)


# =========================================================================================
# Mobile combustion
# =========================================================================================
def _miles(distance: Measure) -> float:
    unit = " ".join(distance.unit.lower().split())
    if unit in ("mi", "mile", "miles", "vehicle-miles", "vehicle miles"):
        return distance.value
    if unit in ("km", "kilometer", "kilometers", "kilometre", "kilometres"):
        return distance.value / KM_PER_MILE
    raise CalculationError(f"Distance unit {distance.unit!r} is not miles or kilometers.")


def mobile_combustion(fuels: list[MobileFuel], ref: EmissionFactorReference | None = None,
                      gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    ref = ref or default_emission_factor_reference()
    biogenic_names = {r["fuel_type"].lower() for r in ref.data["stationary_combustion"]
                      if str(r.get("category") or "").startswith("Biomass")}
    lines: list[LineResult] = []
    for fuel in fuels:
        line = LineResult(fuel.fuel_type, {}, {"CH4": 0.0, "N2O": 0.0})
        # CO2 per fuel type: Eq 3 if CC, Eq 2 if HHV, else Eq 1 (Table 2)
        if fuel.carbon_content is not None:
            co2_t, steps = _co2_eq3(fuel.quantity, fuel.carbon_content, fuel.heat_content)
            line.steps.extend(steps)
            line.equations["CO2"] = "Eq 3"
        elif fuel.heat_content is not None:
            if not fuel.energy_basis_fuel_type:
                raise CalculationError(f"Eq 2 for {fuel.fuel_type} needs the Table 1 fuel whose kg/mmBtu factor applies.")
            row = ref.stationary_fuel(fuel.energy_basis_fuel_type)
            mmbtu, energy_step = _energy_mmbtu(fuel.quantity, fuel.heat_content)
            if energy_step:
                line.steps.append(energy_step)
            ef = float(row["per_energy"]["co2_kg_per_mmbtu"])
            co2_t = mmbtu * ef / KG_PER_METRIC_TON
            line.steps.append(Step("CO2 (Eq 2)", "Fuel x HHV x EF2",
                                   {"fuel energy": _inp(mmbtu, "mmBtu"),
                                    "EF2": _inp(ef, "kg CO2 per mmBtu", ref.cite(row))}, co2_t, "t"))
            line.equations["CO2"] = "Eq 2"
        else:
            row = ref.mobile_co2(fuel.fuel_type)
            epa_unit = EPA_UNIT_TO_CANONICAL[row["unit"]]
            unit = _canonical(fuel.quantity.unit)
            if fuel_units.dimension_of(epa_unit) != fuel_units.dimension_of(unit):
                raise CalculationError(f"{fuel.fuel_type} CO2 factor is per {row['unit']}; got {fuel.quantity.unit!r}.")
            quantity = fuel_units.convert_exact(fuel.quantity.value, unit, epa_unit)
            ef = float(row["co2_kg_per_unit"])
            co2_t = quantity * ef / KG_PER_METRIC_TON
            line.steps.append(Step("CO2 (Eq 1)", "Fuel x EF1",
                                   {"fuel": _inp(quantity, row["unit"], fuel.quantity.source),
                                    "EF1": _inp(ef, f"kg CO2 per {row['unit']}", ref.cite(row))}, co2_t, "t"))
            line.equations["CO2"] = "Eq 1"
        # CH4, N2O per vehicle group, summed to the fuel
        for group in fuel.vehicle_groups:
            label = f"{group.vehicle_type} ({group.factor_fuel_type})"
            if group.on_road:
                if group.distance is None:
                    raise CalculationError(f"On-road group {label} needs distance (Eq 4).")
                row = ref.on_road(group.vehicle_type, group.factor_fuel_type, group.model_year)
                miles = _miles(group.distance)
                for gas, key in (("CH4", "ch4_g_per_mile"), ("N2O", "n2o_g_per_mile")):
                    ef = float(row[key])
                    mass_t = miles * ef / G_PER_METRIC_TON
                    line.mass_t[gas] += mass_t
                    line.steps.append(Step(f"{gas} (Eq 4) {label}", "Distance x EF4",
                                           {"distance": _inp(miles, "miles", group.distance.source),
                                            "EF4": _inp(ef, f"g {gas} per vehicle-mile", ref.cite(row))},
                                           mass_t, "t"))
                line.equations.setdefault("CH4", "Eq 4")
            else:
                if group.fuel_quantity is None:
                    raise CalculationError(f"Non-road group {label} needs fuel quantity (Eq 5).")
                row = ref.non_road(group.vehicle_type, group.factor_fuel_type)
                gallons = fuel_units.convert_exact(group.fuel_quantity.value, _canonical(group.fuel_quantity.unit), "gal")
                for gas, key in (("CH4", "ch4_g_per_gallon"), ("N2O", "n2o_g_per_gallon")):
                    ef = float(row[key])
                    mass_t = gallons * ef / G_PER_METRIC_TON
                    line.mass_t[gas] += mass_t
                    line.steps.append(Step(f"{gas} (Eq 5) {label}", "Fuel x EF5",
                                           {"fuel": _inp(gallons, "gallon", group.fuel_quantity.source),
                                            "EF5": _inp(ef, f"g {gas} per gallon", ref.cite(row))}, mass_t, "t"))
                line.equations.setdefault("CH4", "Eq 5")
        line.equations["N2O"] = line.equations.get("CH4", "")
        if not fuel.vehicle_groups:
            line.flags.append("ch4_n2o_need_vehicle_groups")
        if fuel.fuel_type.lower() in biogenic_names:
            line.biogenic_co2_t = co2_t
            line.mass_t["CO2"] = 0.0
            line.flags.append("biogenic_co2_reported_separately")
        else:
            line.mass_t["CO2"] = co2_t
        lines.append(line)
    return _category("mobile_combustion", lines, ref, gwp_set=gwp_set)


# =========================================================================================
# Scope 2 purchased electricity
# =========================================================================================
def _facility_mwh(facility: FacilityElectricity) -> tuple[float, Step | None]:
    unit = _canonical(facility.consumption.unit)
    if unit == "MWh":
        return facility.consumption.value, None
    if unit == "kWh":
        mwh = facility.consumption.value / KWH_PER_MWH
        return mwh, Step("Electricity in MWh", "kWh / 1,000",
                         {"electricity": _inp(facility.consumption.value, "kWh", facility.consumption.source)},
                         mwh, "MWh")
    raise CalculationError(f"Electricity for {facility.facility} must be in kWh or MWh, not {facility.consumption.unit!r}.")


def _electricity_line(facility: FacilityElectricity, mwh: float, ref: EmissionFactorReference,
                      label: str, pre_steps: list[Step]) -> LineResult:
    factors = facility.factors or ref.electricity(facility.egrid_subregion)
    line = LineResult(facility.facility, {gas: "Emissions = MWh x EF" for gas in GASES}, {}, steps=list(pre_steps))
    for gas in GASES:
        factor = factors[gas]
        lb = mwh * factor.value
        line.steps.append(Step(f"{gas} ({label})", "MWh x EF",
                               {label: _inp(mwh, "MWh"),
                                f"EF ({facility.egrid_subregion})": _inp(factor.value, factor.unit, factor.source)},
                               lb, "lb"))
        tons = lb / LB_PER_METRIC_TON
        line.steps.append(Step(f"{gas} in metric tons", "lb / 2,204.62", {"emissions": _inp(lb, "lb")}, tons, "t"))
        line.mass_t[gas] = tons
    return line


def electricity_location_based(facilities: list[FacilityElectricity],
                               ref: EmissionFactorReference | None = None,
                               gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    ref = ref or default_emission_factor_reference()
    lines = []
    for facility in facilities:
        mwh, step = _facility_mwh(facility)
        lines.append(_electricity_line(facility, mwh, ref, "electricity", [step] if step else []))
    return _category("purchased_electricity_location_based", lines, ref, gwp_set=gwp_set)


def electricity_market_based(facilities: list[FacilityElectricity], certificates: list[Certificate],
                             ref: EmissionFactorReference | None = None,
                             gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    """Certificates (1 certificate = 1 MWh) are spread across facilities pro rata to consumption.

    No certificates: coverage 0%, market-based equals location-based. Certificates above
    total consumption: coverage capped at 100% and the excess is flagged.
    """

    ref = ref or default_emission_factor_reference()
    converted = [(facility, *_facility_mwh(facility)) for facility in facilities]
    total_mwh = sum(mwh for _, mwh, _ in converted)
    covered = sum(c.mwh for c in certificates)
    flags: list[str] = []
    if total_mwh <= 0:
        raise CalculationError("Total electricity consumption must be greater than zero.")
    coverage = covered / total_mwh
    if coverage > 1:
        flags.append("certificates_exceed_consumption")
        coverage = 1.0
    if not certificates:
        flags.append("no_certificates_market_equals_location")
    coverage_steps = [
        Step("Total electricity covered by certificates", "sum of certificate MWh",
             {c.label: _inp(c.mwh, "MWh", c.source) for c in certificates}, covered, "MWh"),
        Step("Certificate coverage percentage", "covered MWh / total electricity consumption (max 100%)",
             {"covered": _inp(covered, "MWh"), "total consumption": _inp(total_mwh, "MWh")}, coverage, "fraction"),
    ]
    lines = []
    for facility, mwh, unit_step in converted:
        remainder = mwh * (1 - coverage)
        remainder_step = Step("Remainder MWh", "electricity (MWh) x (1 - coverage %)",
                              {"electricity": _inp(mwh, "MWh"), "coverage": _inp(coverage, "fraction")},
                              remainder, "MWh")
        pre = ([unit_step] if unit_step else []) + [remainder_step]
        lines.append(_electricity_line(facility, remainder, ref, "remainder", pre))
    return _category("purchased_electricity_market_based", lines, ref, flags=flags, gwp_set=gwp_set,
                     details={"covered_mwh": covered, "total_mwh": total_mwh, "coverage": coverage,
                              "coverage_steps": [asdict(s) for s in coverage_steps]})


# =========================================================================================
# Scope 1 purchased industrial gases
# =========================================================================================
def purchased_gases(gases: list[PurchasedGas], ref: EmissionFactorReference | None = None,
                    gwp_set: str = DEFAULT_GWP_SET) -> CategoryResult:
    """One number per gas: emissions = amount purchased; CO2e = mass x GWP."""

    ref = ref or default_emission_factor_reference()
    lines = []
    total_co2e = 0.0
    gwp_used: dict[str, dict[str, Any]] = {}
    for item in gases:
        mass_t = _to_metric_tons(item.amount.value, item.amount.unit)
        if item.gwp_override is not None:
            gwp_value, gwp_source = item.gwp_override, "override"
        else:
            factor = ref.gwp(item.gas, gwp_set)
            gwp_value, gwp_source = factor.value, factor.source
        co2e = mass_t * gwp_value
        total_co2e += co2e
        gwp_used[item.gas] = {"value": gwp_value, "source": gwp_source}
        line = LineResult(item.gas, {item.gas: "emissions = amount purchased"}, {item.gas: mass_t}, steps=[
            Step(f"{item.gas} emitted", "equals the amount purchased",
                 {"purchased": _inp(item.amount.value, item.amount.unit, item.amount.source)}, mass_t, "t"),
            Step(f"{item.gas} in CO2e", "mass x GWP",
                 {"mass": _inp(mass_t, "t"), "GWP": _inp(gwp_value, "", gwp_source)}, co2e, "t CO2e"),
        ])
        lines.append(line)
    totals = {line.key: line.mass_t[line.key] for line in lines}
    co2e_by_gas = {line.key: line.steps[-1].result for line in lines}
    summary = Step("Total purchased gas emissions, all gases, in CO2e", "sum of emissions of each gas in CO2e",
                   {k: _inp(v, "t CO2e") for k, v in co2e_by_gas.items()}, total_co2e, "t CO2e")
    return CategoryResult("purchased_gases", lines, totals, co2e_by_gas, total_co2e, gwp_used, 0.0, [summary],
                          gwp_set=gwp_set)


# =========================================================================================
# Reported vs recalculated
# =========================================================================================
def compare(data_point: str, reported: float | None, recalculated: float,
            tolerance_pct: float = COMPARISON_TOLERANCE_PCT) -> dict[str, Any]:
    """Reported value, recalculated value and the difference (%), flagged over tolerance."""

    if reported is None:
        return {"data_point": data_point, "reported": None, "recalculated": recalculated, "difference": None,
                "difference_pct": None, "status": "not_reported"}
    difference = recalculated - reported
    if reported == 0:
        pct = 0.0 if recalculated == 0 else None
    else:
        pct = difference / reported * 100
    status = "within_tolerance" if pct is not None and abs(pct) <= tolerance_pct else "exceeds_tolerance"
    return {"data_point": data_point, "reported": reported, "recalculated": recalculated, "difference": difference,
            "difference_pct": pct, "status": status, "tolerance_pct": tolerance_pct}
