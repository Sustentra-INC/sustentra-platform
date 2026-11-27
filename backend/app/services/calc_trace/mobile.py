"""Mobile combustion trace: fuel x CO2 factor; a vehicle group's CH4 and N2O by distance (Eq. 4) or fuel (Eq. 5).

On top of the shared trace, an on-road vehicle group's line shows its distance as a derived step: Step 2 is the
fuel converted to the factor's unit (gallons), then fuel x fuel economy = distance (the ``distance`` block). The
fuel economy is an input (``fuel_economy``, mi/gal) a reviewer can decide for the line.

Where the distance comes from, in order (Q5):

1. a fuel economy a reviewer accepted or entered for the line: distance = the line's fuel x that fuel economy;
2. otherwise the distance entered for the vehicle group under Recalculation inputs (the fuel economy shown is then
   what that distance implies: distance / fuel, source ``derived``);
3. an odometer reading would come last, but none is read from the evidence yet (the mobile extractor leaves
   distance out), so there is no third source today.

A reviewer who decides the distance itself keeps it unless a fuel economy is also decided: the fuel economy wins and
the distance decision is reported as not applied (``calc_trace/decisions.apply``).

The fuel economy only exists on a line that holds all of its fuel type's fuel in gallons and whose vehicle group states
a distance (the reasonableness check the line already carried, ``implied_fuel_economy``): on any other line the distance
cannot honestly be called fuel x fuel economy, so no fuel economy is offered and the distance stays as entered. Non-road
groups (Eq. 5, Table 5) have no distance and no fuel economy: their CH4 and N2O follow the group's own fuel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace._common import trace_for
from backend.app.services.calc_trace._line import _annotate, normalise_unit
from backend.app.services.calc_trace.model import (
    Column, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock, TraceInput,
)

FUEL_ECONOMY = "fuel_economy"
ECONOMY_UNIT = "mi/gal"
DISTANCE_BLOCK = "distance"
STEP2_NOTE = "To the unit the emission factor is in, then fuel × fuel economy = distance"
NOT_VEHICLE_LINE = "Fuel economy applies only to vehicle lines."
NOT_OFFERED = "Fuel economy isn't used on this line (non-road, or no distance stated)."
BAND = 3.0  # a decided fuel economy within 1/3 to 3 times what the line's distance implies
ABSOLUTE = (0.5, 100.0)  # mi/gal: below or above this is a slip of units, whatever the vehicle
DISTANCE_FROM_ECONOMY_FLAG = "distance_from_fuel_economy"


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    trace = trace_for("mobile", line, "epa_hub_fuel_and_vehicle_group", context)
    if trace is None:
        return None
    try:
        _add_fuel_economy(trace, line, context)
    except (ops.TraceError, KeyError, TypeError, ValueError):
        # The shared trace stands, with the distance as entered: a failed extra never takes the line's working down.
        return trace_for("mobile", line, "epa_hub_fuel_and_vehicle_group", context)
    return trace


def check_economy(number: float, trace: LineTrace) -> str | None:
    """None when a decided fuel economy may be used for the line, else why not (a sentence for ``not_applied``).
    It is checked against the line's own figures: within 1/3 to 3 times the fuel economy its distance and fuel imply,
    and between 0.5 and 100 mi/gal (a slip of units, km/L or L/100 km, is the usual mistake). Like the site values
    of a stationary line, a reason does not lift this: a value outside is a slip, not a judgement."""

    low, high = ABSOLUTE
    item = trace.inputs.get(FUEL_ECONOMY)
    implied = _number(item.recomputed.value) if item is not None and item.recomputed else None
    if implied is not None and implied > 0:
        low, high = max(low, implied / BAND), min(high, implied * BAND)
    if not low <= number <= high:
        return (f"Not applied: {number:g} mi/gal is outside {low:.3g} to {high:.3g}, around the {implied:.3g} this "
                "line's distance and fuel imply. Check the unit (miles per gallon, not km per litre)."
                if implied is not None else
                f"Not applied: {number:g} mi/gal is outside {low:g} to {high:g}. Check the unit (miles per gallon).")
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _economy_operation(fuel: float, economy: float, *, fuel_ref: str = "conversion") -> Operation:
    return ops.make_operation([
        Term(None, Operand("fuel", fuel, "gal", step_ref=fuel_ref)),
        Term("×", Operand("economy", economy, ECONOMY_UNIT, input_id=FUEL_ECONOMY)),
    ], "distance", "mi")


def _distance_columns() -> list[Column]:
    return [Column("fuel", "Fuel", "gal"), Column("economy", "Fuel economy", ECONOMY_UNIT),
            Column("distance", "Distance", "mi", True, {"dp": 0})]


def _add_fuel_economy(trace: LineTrace, line: dict[str, Any], context: dict[str, Any] | None) -> None:
    step2 = line["step2"]
    distance, implied = step2.get("distance"), step2.get("implied_fuel_economy")
    if not distance or not implied or "mixed_units_or_fuels" in line.get("flags", []) or trace.state != "complete":
        return
    if normalise_unit(str(step2["to_unit"])) != "gal" or normalise_unit(str(distance["unit"])) != "mi":
        return
    if "distance" not in trace.inputs or "conversion" not in {b.id for s in trace.steps for b in s.blocks}:
        return
    fuel = _number(step2["result"]["quantity"])
    miles = _number(distance["quantity"])
    if fuel is None or miles is None or fuel <= 0 or miles <= 0:
        return
    economy = miles / fuel
    mine = _economy_operation(fuel, economy)
    ops.verify(mine, miles)

    theirs: Operation | None = None
    company_economy: float | None = None
    company = line.get("company")
    if company:
        c_fuel = _number(company["step2"]["result"]["quantity"])
        c_row = next((r for r in company["step3"]["gases"] if r["gas"] == "CH4"), None)
        c_miles = _number(c_row["activity"]["value"]) if c_row and normalise_unit(
            str(c_row["activity"]["unit"])) == "mi" else None
        if c_fuel and c_fuel > 0 and c_miles and normalise_unit(str(company["step2"]["to_unit"])) == "gal":
            company_economy = c_miles / c_fuel
            theirs = _economy_operation(c_fuel, company_economy)
            ops.verify(theirs, c_miles)
            _annotate(mine, theirs)

    group = (context or {}).get("vehicle_group")
    item = TraceInput(
        FUEL_ECONOMY, "Fuel economy", "reviewer_entered", symbol="mpg", required_for=["eq4_distance"],
        recomputed=Side(economy, ECONOMY_UNIT, "derived", SourceRef(
            "derived", from_=["distance", "activity.total"], citation=group)),
        company=(Side(company_economy, ECONOMY_UNIT, "derived", SourceRef("derived", from_=["distance", "activity.total"]))
                 if company_economy is not None else None))
    _difference(item)
    trace.inputs[FUEL_ECONOMY] = item
    block = TraceBlock(DISTANCE_BLOCK, "Distance driven", _distance_columns(), company=theirs, recomputed=mine)
    for step in trace.steps:
        if step.id == "conversion":
            step.blocks.append(block)
            step.note = STEP2_NOTE
            break


def _difference(item: TraceInput) -> None:
    mine, theirs = item.recomputed, item.company
    if mine is None or theirs is None or not isinstance(mine.value, (int, float)) \
            or not isinstance(theirs.value, (int, float)):
        item.difference = item.differs = None
        return
    item.difference = ops.difference(float(mine.value), float(theirs.value), mine.unit, theirs.unit)
    item.differs = ops.differs(item.difference, float(mine.value))


def work_distance(trace: LineTrace, values: Mapping[str, tuple[float, Mapping[str, Any], Mapping[str, Any]]],
                  fuel: float, decided_side: Callable[..., Side]) -> tuple[float, Mapping[str, Any], Mapping[str, Any]] | None:
    """The distance the line's decisions give, worked into the ``distance`` input and Step 2's distance block
    (``decisions._rework`` calls this for a mobile line, after Step 2: ``fuel`` is its converted quantity, in the
    factor's unit). Returns ``(distance, decision, record)`` for the Step 3 operands, or None when no decision gives
    the distance (they stay on the distance entered under Recalculation inputs).

    A decided fuel economy gives distance = fuel x fuel economy. Otherwise a decided distance stands and the fuel
    economy shown is what it implies. A decided fuel (activity) with neither keeps the distance as entered, and the
    fuel economy shown follows the fuel."""

    distance_input = trace.inputs.get("distance")
    block = next((b for s in trace.steps for b in s.blocks if b.id == DISTANCE_BLOCK), None)
    economy_input = trace.inputs.get(FUEL_ECONOMY)
    decided_economy, decided_distance = values.get(FUEL_ECONOMY), values.get("distance")
    entered = _number(distance_input.recomputed.value) if distance_input is not None and distance_input.recomputed \
        else None
    if block is None or block.recomputed is None or economy_input is None or distance_input is None:
        # No fuel economy on this line (not offered, or not on-road): only a decided distance has anything to do.
        if decided_distance is not None and distance_input is not None:
            distance_input.recomputed = decided_side(distance_input.recomputed, *decided_distance)
        return decided_distance
    if fuel <= 0:
        raise ops.TraceError("the line's fuel is not above 0")

    result: tuple[float, Mapping[str, Any], Mapping[str, Any]] | None
    if decided_economy is not None:
        miles = fuel * decided_economy[0]
        economy_input.recomputed = decided_side(economy_input.recomputed, *decided_economy)
        distance_input.recomputed = Side(miles, "mi", "derived", SourceRef(
            "derived", from_=["activity.total", FUEL_ECONOMY]))
        economy = decided_economy[0]
        result = (miles, decided_economy[1], decided_economy[2])
        trace.flags = sorted({*trace.flags, DISTANCE_FROM_ECONOMY_FLAG})
    elif decided_distance is not None:
        miles = decided_distance[0]
        distance_input.recomputed = decided_side(distance_input.recomputed, *decided_distance)
        economy = miles / fuel
        economy_input.recomputed = Side(economy, ECONOMY_UNIT, "derived", SourceRef(
            "derived", from_=["distance", "activity.total"]))
        result = decided_distance
    elif entered is not None and not math.isclose(fuel, _number(block.recomputed.terms[0].operand.value) or 0.0,
                                                  rel_tol=1e-12, abs_tol=0.0):
        economy = entered / fuel  # the fuel was decided: the distance stays, the fuel economy it implies follows
        economy_input.recomputed = Side(economy, ECONOMY_UNIT, "derived", SourceRef(
            "derived", from_=["distance", "activity.total"]))
        result = None
    else:
        return None
    worked = _economy_operation(fuel, economy)
    block.recomputed = worked
    if block.company is not None:
        _annotate(worked, block.company)
    _difference(economy_input)
    return result
