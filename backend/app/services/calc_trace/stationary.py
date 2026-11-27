"""Stationary combustion trace: fuel (or energy) x per-unit factor, per gas (EPA Hub Table 1), and the equation
picker (C1): Eq. 1, Eq. 2 or Eq. 3 for each gas.

* Eq. 1: fuel x EF1 (per unit of fuel, or per MMBtu when the fuel is measured in energy). What every line is
  calculated with until a reviewer decides otherwise.
* Eq. 2: fuel x HHV x EF2 (kg or g per MMBtu). Needs a site heat content (HHV), an input the reviewer accepts or
  edits for the line: no extractor reads one yet, and the Hub's typical HHV is never used in its place.
* Eq. 3: fuel x carbon content x 44/12. CO2 only, and only for a fuel measured in mass; needs the fuel's carbon
  content (% by mass), accepted or edited the same way. CH4 and N2O have no Eq. 3: they stay on Eq. 1 or Eq. 2.

``build`` lists the three options of each gas with their availability, and the inputs a route needs (the site
HHV, the carbon content, the Hub's per-energy factors, the constants). The default working is the calculator's own:
the option an unavailable route would need is never worked until its input is decided. ``worked`` is the working
of a gas on the equation a reviewer chose (``decisions._rework`` calls it), checked against the calculator's own
Eq. 2 / Eq. 3 (``emissions_calculator.stationary_combustion``) to 1e-9 before it is used.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import (
    EPA_UNIT_TO_CANONICAL, EmissionFactorNotFoundError, default_emission_factor_reference,
)
from backend.app.services import emissions_calculator as calc
from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace._common import HUB, option_id
from backend.app.services.calc_trace._line import GAS_LABEL, _groups, normalise_unit, reference_source
from backend.app.services.calc_trace.model import (
    Choice, ChoiceOption, Column, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceInput,
)

EQ1, EQ2, EQ3 = "eq_1", "eq_2", "eq_3"  # option_id("Eq. 1"): the ids the default working has always had
EQUATION = {EQ1: ("Eq. 1", "Fuel × EF₁"), EQ2: ("Eq. 2", "Fuel × HHV × EF₂"),
            EQ3: ("Eq. 3", "Fuel × carbon content × 44/12")}
SITE_INPUTS = ("hhv", "cc")  # what a reviewer enters for a line to open Eq. 2 and Eq. 3
CC_UNIT = "% by mass"
HHV_BAND = (0.2, 5.0)  # a site HHV is taken within this factor of the Hub's typical one (a Btu / MMBtu slip is not)
CC_FLOOR = 0.2  # a carbon content is taken above this share of the fuel's Hub-implied one (0.75 for 75% is not)
SCALE = {"CO2": (1000.0, "kg/t"), "CH4": (1_000_000.0, "g/t"), "N2O": (1_000_000.0, "g/t")}
ENERGY_UNIT = {"CO2": "kg/MMBtu", "CH4": "g/MMBtu", "N2O": "g/MMBtu"}
CO2_PER_C = calc.CO2_PER_C
MIXED = "This line mixes fuels or units: move the other records to their own line first."


@dataclass
class Shape:
    """What a stationary line's trace needs to offer the equations: its fuel, the unit Step 2 leaves it in, and
    the Hub's row."""

    fuel: str
    to_unit: str
    physical: bool  # a quantity of fuel (gal, short_ton, scf), not energy
    mass: bool
    row: dict[str, Any] | None
    single_run: bool
    decided: frozenset[str]


def site_decided(records: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
    """The site inputs (``hhv``, ``cc``) a line's stored decisions have accepted or edited on the recomputed side.
    Only that they were decided: the value is checked when the decision is read into the line (``decisions``)."""

    out: list[str] = []
    for input_id in SITE_INPUTS:
        record = (records or {}).get(f"input|{input_id}|recomputed")
        decision = record.get("decision") if isinstance(record, Mapping) else None
        if isinstance(decision, Mapping) and decision.get("status") in ("accepted", "edited"):
            out.append(input_id)
    return out


def _shape(line: dict[str, Any], context: dict[str, Any]) -> Shape | None:
    fuel = context.get("fuel")
    if not isinstance(fuel, str) or not line["step3"]["gases"]:
        return None
    to_unit = normalise_unit(str(line["step2"]["to_unit"]))
    try:
        dimension = fuel_units.dimension_of(to_unit)
        row: dict[str, Any] | None = default_emission_factor_reference().stationary_fuel(fuel)
    except (fuel_units.UnitError, EmissionFactorNotFoundError):
        dimension, row = None, None
    return Shape(fuel, to_unit, dimension in (fuel_units.MASS, fuel_units.LIQUID_VOLUME, fuel_units.GAS_VOLUME),
                 dimension == fuel_units.MASS, row, len(_groups(line["step3"]["gases"])) == 1,
                 frozenset(context.get("decided") or ()))


def _options(gas: str, shape: Shape | None) -> list[ChoiceOption]:
    out: list[ChoiceOption] = []
    for option, (label, formula) in EQUATION.items():
        available, why, needs = _available(option, gas, shape)
        out.append(ChoiceOption(option, label, available=available, equation=formula,
                                why_unavailable=None if available else why, required_inputs=needs, citation=HUB))
    return out


def _available(option: str, gas: str, shape: Shape | None) -> tuple[bool, str | None, list[str]]:
    if option == EQ1:
        return True, None, []
    needs = ["hhv"] if option == EQ2 else ["cc"] if gas == "CO2" else []
    if shape is None:
        return False, "This line has no working to calculate from.", needs
    if not shape.single_run:
        return False, MIXED, needs
    per_energy = (shape.row or {}).get("per_energy")
    if option == EQ2:
        if not shape.physical:
            return False, "The fuel is already measured in energy: Eq. 1 uses it directly.", needs
        if not per_energy:
            return False, "EPA publishes no per-energy factor for this fuel.", needs
        if "hhv" not in shape.decided:
            return False, "Needs an accepted site heat content (HHV) for this line.", needs
        return True, None, needs
    if gas != "CO2":
        return False, "Eq. 3 gives CO₂ only: CH₄ and N₂O use Eq. 2, or Eq. 1 without a heat content.", needs
    if not shape.mass:
        return False, "Eq. 3 takes the carbon content as % by mass: the fuel must be measured in mass.", needs
    if "cc" not in shape.decided:
        return False, "Needs an accepted carbon content (% by mass) for this fuel.", needs
    return True, None, needs


def _choices(line: dict[str, Any], shape: Shape | None) -> list[Choice]:
    method = line["method"]
    route = method["route"]
    out = [Choice("method", "Calculation method", [ChoiceOption("epa_hub_per_unit_factor", route, citation=HUB)],
                  chosen="epa_hub_per_unit_factor")]
    for gas, equation in method["equations"].items():
        chosen = option_id(equation)
        options = _options(gas, shape)
        if chosen not in {o.id for o in options}:  # an equation this module does not know: only what was used
            options = [ChoiceOption(chosen, equation, equation=equation, citation=HUB)]
        out.append(Choice(f"equation:{gas}", f"{GAS_LABEL[gas]} equation", options, chosen=chosen))
    return out


def _inputs(line: dict[str, Any], shape: Shape | None) -> dict[str, TraceInput]:
    if shape is None or not shape.single_run or not shape.physical:
        return {}
    out: dict[str, TraceInput] = {}
    row = shape.row or {}
    per_energy = row.get("per_energy")
    if per_energy:
        out["hhv"] = TraceInput(
            "hhv", "Site heat content (HHV)", "reviewer_entered", symbol="HHV", required_for=[EQ2],
            recomputed=Side(None, f"MMBtu/{shape.to_unit}", "awaiting_review"))
        keys = {"CO2": "co2_kg_per_mmbtu", "CH4": "ch4_g_per_mmbtu", "N2O": "n2o_g_per_mmbtu"}
        cite = default_emission_factor_reference().cite(row)
        for gas in line["method"]["equations"]:
            if gas in keys and keys[gas] in per_energy:
                out[f"ef2.{gas}"] = TraceInput(
                    f"ef2.{gas}", f"{GAS_LABEL[gas]} emission factor per MMBtu", "reference", symbol=f"EF₂ {gas}",
                    required_for=[EQ2],
                    recomputed=Side(float(per_energy[keys[gas]]), ENERGY_UNIT[gas], "reference", reference_source(cite)))
    if shape.mass and "CO2" in line["method"]["equations"]:
        out["cc"] = TraceInput("cc", "Carbon content", "reviewer_entered", symbol="CC", required_for=[EQ3],
                               recomputed=Side(None, CC_UNIT, "awaiting_review"))
        out["fuel_to_kg"] = TraceInput(
            "fuel_to_kg", "Fuel mass to kg", "constant", required_for=[EQ3],
            recomputed=Side(fuel_units.convert_exact(1, shape.to_unit, "kg"), f"kg/{shape.to_unit}", "reference",
                            reference_source("fuel_units conversion table")))
        out["co2_per_c"] = TraceInput(
            "co2_per_c", "CO₂ per carbon", "constant", symbol="44/12", required_for=[EQ3],
            recomputed=Side(CO2_PER_C, None, "reference",
                            SourceRef("reference", dataset="Molar masses", citation="CO2 / C = 44/12")))
    return out


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    from backend.app.services.calc_trace import _line

    context = context or {}
    shape = _shape(line, context)
    return _line.build("stationary", line, choices=_choices(line, shape),
                       context={**context, "inputs": {**_inputs(line, shape), **context.get("inputs", {})}})


# --- the working of a chosen equation --------------------------------------------------------------------------
class Refused(ValueError):
    """The equation or site value cannot be worked; the message says why, for the reviewer."""


@dataclass
class Worked:
    operation: Operation
    columns: list[Column]
    row: dict[str, Any]  # the legacy Step 3 row's figures: activity, ef (and their units), mass_t


def _site(trace: LineTrace, input_id: str) -> tuple[float, str]:
    item = trace.inputs.get(input_id)
    side = item.recomputed if item is not None else None
    if side is None or isinstance(side.value, bool) or not isinstance(side.value, (int, float)):
        raise Refused(f"the {input_id} is not decided for this line")
    return float(side.value), str(side.unit)


def _input(trace: LineTrace, input_id: str) -> Any:
    item = trace.inputs.get(input_id)
    if item is None or item.recomputed is None or not isinstance(item.recomputed.value, (int, float)):
        raise Refused(f"{input_id} is not on this line")
    return item.recomputed


def route_refusal(trace: LineTrace, gas: str, option: str, site: Mapping[str, float]) -> str | None:
    """None when ``gas`` can be worked on ``option`` with the site values decided, else why not."""

    need = "hhv" if option == EQ2 else "cc" if option == EQ3 else None
    if need is None:
        return "Not applied: Sustentra cannot calculate this option yet."
    if need not in site:
        label = "site heat content (HHV)" if need == "hhv" else "carbon content"
        return f"Not applied: {EQUATION[option][0]} needs the line's {label} to be accepted first."
    if option == EQ3 and gas != "CO2":
        return "Not applied: Eq. 3 gives CO₂ only."
    needed = ["ef2." + gas] if option == EQ2 else ["fuel_to_kg", "co2_per_c"]
    if any(i not in trace.inputs for i in [need, *needed]):
        return f"Not applied: {EQUATION[option][0]} cannot be worked for this line."
    return None


def check_site(input_id: str, number: float, trace: LineTrace, context: dict[str, Any] | None) -> str | None:
    """None when a decided site value is plausible for the line's fuel, else why not. A carbon content is at most
    100% and not far under what EPA's CO2 factor implies; an HHV is within a factor of 5 of EPA's typical one. A
    slip of units (Btu for MMBtu, 0.75 for 75%) is the usual mistake, and it must not move a total."""

    fuel = (context or {}).get("fuel")
    item = trace.inputs.get(input_id)
    unit = normalise_unit(str(item.recomputed.unit)) if item is not None and item.recomputed else ""
    try:
        row = default_emission_factor_reference().stationary_fuel(str(fuel))
    except EmissionFactorNotFoundError:
        row = {}
    if input_id == "cc":
        if number > 100:
            return "Not applied: a carbon content is at most 100% by mass."
        implied = _implied_cc(row, unit)
        if implied is not None and number < CC_FLOOR * implied:
            return (f"Not applied: {number:g}% by mass is far below the {implied:.0f}% EPA's factor implies for "
                    f"{fuel}. Enter it as a percent (75 for 75%).")
        return None
    typical = row.get("heat_content_hhv") or {}
    per = str(typical.get("unit", "")).split(" per ", 1)[-1]
    canonical = EPA_UNIT_TO_CANONICAL.get(per) or fuel_units.canonical_unit(per)
    if typical.get("value") and unit == f"MMBtu/{canonical}":
        low, high = (f * float(typical["value"]) for f in HHV_BAND)
        if not low <= number <= high:
            return (f"Not applied: an HHV of {number:g} MMBtu per {canonical} is far from the {typical['value']:g} "
                    f"EPA gives for {fuel}. Check the unit (MMBtu, not Btu).")
    return None


def _implied_cc(row: dict[str, Any], unit: str) -> float | None:
    """The % carbon by mass EPA's per-unit CO2 factor implies for a fuel sold by mass, or None."""

    per_unit = row.get("per_unit")
    try:
        if not per_unit or not unit.startswith("%"):
            return None
        canonical = EPA_UNIT_TO_CANONICAL[per_unit["unit"]]
        if fuel_units.dimension_of(canonical) != fuel_units.MASS:
            return None
        kg = fuel_units.convert_exact(1, canonical, "kg")
        return float(per_unit["co2_kg_per_unit"]) / CO2_PER_C / kg * 100
    except (KeyError, fuel_units.UnitError):
        return None


def worked(trace: LineTrace, gas: str, option: str, converted: float, site: Mapping[str, float],
           context: dict[str, Any] | None) -> Worked:
    """``gas`` worked on Eq. 2 or Eq. 3 from the line's converted fuel quantity (Step 2's result, in the unit Step 2
    leaves it in) and the site values decided. The operation is evaluated by the trace's own evaluator and checked
    against the calculator's Eq. 2 / Eq. 3 for the same fuel before it is returned (``Refused`` or the evaluator's
    own error when it does not agree)."""

    why = route_refusal(trace, gas, option, site)
    if why is not None:
        raise Refused(why)
    scale, scale_unit = SCALE[gas]
    if option == EQ2:
        unit = str(trace.inputs["hhv"].recomputed.unit).split("/", 1)[1]  # type: ignore[union-attr]
        ef = _input(trace, f"ef2.{gas}")
        terms = [Term(None, Operand("activity", converted, unit, step_ref="conversion")),
                 Term("×", Operand("hhv", site["hhv"], f"MMBtu/{unit}", input_id="hhv")),
                 Term("×", Operand("ef", float(ef.value), str(ef.unit), input_id=f"ef2.{gas}")),
                 Term("÷", Operand("conversion", scale, scale_unit))]
        columns = [Column("activity", "Activity", unit), Column("hhv", "Heat content (HHV)", f"MMBtu/{unit}"),
                   Column("ef", "Emission factor", ENERGY_UNIT[gas]), Column("conversion", "To metric tons", scale_unit),
                   Column("mass", "Mass", "t", True, {"sig": 6})]
        energy = converted * site["hhv"]
        row = {"activity": energy, "activity_unit": "MMBtu", "ef": float(ef.value), "ef_unit": ENERGY_UNIT[gas],
               "ef_source": ef.source.citation if ef.source else None, "unit_conversion": 1 / scale}
    else:
        unit = _mass_unit(trace)
        to_kg, c = _input(trace, "fuel_to_kg"), _input(trace, "co2_per_c")
        terms = [Term(None, Operand("activity", converted, unit, step_ref="conversion")),
                 Term("×", Operand("fuel_to_kg", float(to_kg.value), f"kg/{unit}", input_id="fuel_to_kg")),
                 Term("×", Operand("cc", site["cc"], "%", input_id="cc")),
                 Term("÷", Operand("percent", 100.0, "%")),
                 Term("×", Operand("co2_per_c", float(c.value), None, input_id="co2_per_c")),
                 Term("÷", Operand("conversion", scale, scale_unit))]
        columns = [Column("activity", "Activity", unit), Column("fuel_to_kg", "To kg", f"kg/{unit}"),
                   Column("cc", "Carbon content", "%"), Column("percent", "Percent", "%"),
                   Column("co2_per_c", "CO₂ per C"), Column("conversion", "To metric tons", scale_unit),
                   Column("mass", "Mass", "t", True, {"sig": 6})]
        row = {"activity": converted * float(to_kg.value), "activity_unit": "kg",
               "ef": site["cc"] / 100 * float(c.value), "ef_unit": "kg CO2/kg",
               "ef_source": "Eq. 3: carbon content × 44/12",
               "unit_conversion": 1 / scale}
    operation = ops.make_operation(terms, "mass", "t")
    ops.verify(operation, _calculator_mass(context, gas, option, converted, unit, site))
    row["mass_t"] = float(operation.result.value)  # type: ignore[arg-type]
    return Worked(operation, columns, row)


def _mass_unit(trace: LineTrace) -> str:
    unit = str(_input(trace, "fuel_to_kg").unit)
    return unit.split("/", 1)[1]


def _calculator_mass(context: dict[str, Any] | None, gas: str, option: str, converted: float, unit: str,
                     site: Mapping[str, float]) -> float:
    """The same gas by the calculator's own Eq. 2 / Eq. 3 (``emissions_calculator.stationary_combustion``): a
    biogenic fuel's CO2 is read from where the calculator keeps it."""

    fuel = (context or {}).get("fuel")
    if not isinstance(fuel, str):
        raise Refused("the line's fuel is not known")
    measure = calc.Measure(converted, unit)
    if option == EQ2:
        item = calc.StationaryFuel(fuel, measure, heat_content=calc.Measure(site["hhv"], f"MMBtu per {unit}"))
    else:
        item = calc.StationaryFuel(fuel, measure, carbon_content=calc.Measure(site["cc"], calc.PERCENT_BY_MASS))
    result = calc.stationary_combustion([item]).lines[0]
    value = result.biogenic_co2_t if gas == "CO2" and result.biogenic_co2_t else result.mass_t[gas]
    if not math.isfinite(value):
        raise Refused("the calculator returned no number")
    return float(value)
