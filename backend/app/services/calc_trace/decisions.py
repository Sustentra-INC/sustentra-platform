"""A reviewer's decisions read into a line's trace: the recomputed side worked again with the values decided.

``apply(trace, records, panel)`` takes the line's default trace (built from, and checked against, the calculators)
and the line's current decision records (``calc_line_review``: ``{stream: record}``). It returns the decided trace,
what happened to each decision, and the line's decided figures (``Figures``), or no figures when nothing decided
changes a number.

What counts, per stream:

* an input's **recomputed** side, ``accepted`` or ``edited``: its value replaces the automatic one. A pending
  suggestion never does (it is not an operand); a ``rejected`` one leaves the automatic value, with a flag.
* a **choice**, ``accepted`` or ``edited`` (chosen): the option the line uses. Each choice offers only today's route
  so far, so a chosen option is the default one; an option no route exists for is never applied.
* the **company** side: shown on the trace (``calc_line_review.with_decisions``), never an operand.

Only the activity (the total, or a document's row), the emission factors and a vehicle group's distance or fuel economy can be decided
for a line. The GWP, the consolidated share, the unit conversion and the grid region are set for the whole engagement
(Methodology, Recalculation inputs, the conversion table): a decision on one of them is reported, not applied.

A value is checked again here before it reaches the arithmetic (stored rows may predate a rule): a finite number above
0 and within ``MAX_NUMBER``, in the input's own unit. A decision that fails is reported (``not_applied``), never used.
A line whose working holds more than one calculator run (it mixes fuels or units) takes no decision on a number.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from backend.app.services.calc_trace import mobile, ops, stationary
from backend.app.services.calc_trace._line import _annotate, normalise_unit
from backend.app.services.calc_trace.model import (
    Choice, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock, TraceResult,
)

MAX_NUMBER = 1e15
DECIDABLE = ("activity.total", "distance", "fuel_economy", *stationary.SITE_INPUTS)  # and every "ef.<gas>"
SET_ELSEWHERE = {
    "unit_conversion": "the unit conversion comes from the conversion table",
    "share": "the consolidated share is set under Recalculation inputs",
    "grid_region": "the grid region is set under Recalculation inputs or in Setup",
}
APPLIED_FLAG = "reviewer_decisions_applied"
REJECTED_FLAG = "reviewer_rejected_input"
GROUP_FUEL_FLAG = "decided_ch4_n2o_use_vehicle_group"
DECIDED = ("accepted", "edited")


@dataclass
class Figures:
    """The line's decided numbers, pre-share (as the categories add them): mass by gas (a biogenic line's CO2 is in
    ``biogenic_co2_t``, not ``mass_t``), CO2e by gas, and the activity in the factor's unit (Step 2's result)."""

    mass_t: dict[str, float]
    gas_co2e_t: dict[str, float]
    sum_co2e_t: float
    total_co2e_t: float
    biogenic_co2_t: float
    activity: float
    activity_total: float
    # per gas: activity, ef, mass_t, co2e_t (a gas worked on Eq. 2 or Eq. 3 also: activity_unit, ef_unit, ef_source,
    # unit_conversion, as its legacy Step 3 row shows them)
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Outcome:
    applied: list[dict[str, Any]] = field(default_factory=list)
    not_applied: list[dict[str, Any]] = field(default_factory=list)
    routes: dict[str, tuple[str, str]] = field(default_factory=dict)  # choice id -> (calculated, chosen) equation


def _parse(stream: str) -> tuple[str, str, str | None] | None:
    parts = stream.split("|")
    if len(parts) != 3 or parts[0] not in ("choice", "input"):
        return None
    return parts[0], parts[1], parts[2] or None


def _entry(target: str, target_id: str, side: str | None, **more: Any) -> dict[str, Any]:
    return {"target": target, "id": target_id, "side": side, **more}


def _decision(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    decision = record.get("decision") if isinstance(record, Mapping) else None
    return decision if isinstance(decision, Mapping) else None


def _by(decision: Mapping[str, Any]) -> str:
    by = decision.get("by")
    return str(by.get("name") if isinstance(by, Mapping) else by or "")


def _number(value: Any) -> float | None:
    """A value as the arithmetic may take it, or None: a finite number above 0, at most MAX_NUMBER."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > MAX_NUMBER:
        return None
    return number


def _source(decision: Mapping[str, Any], record: Mapping[str, Any]) -> SourceRef:
    reason = decision.get("reason")
    if not reason and decision.get("status") == "accepted":
        suggestion = record.get("suggestion") if isinstance(record.get("suggestion"), Mapping) else {}
        reason = (suggestion or {}).get("reason") or "Suggested by Sustentra's AI and accepted"
    return SourceRef("entered", by=_by(decision), at=str(decision.get("at") or ""), reason=str(reason or ""),
                     document_id=decision.get("document_id") if isinstance(decision.get("document_id"), str) else None)


def not_decidable(input_id: str) -> str | None:
    """None when the input can be decided for a line, else why not."""

    base = input_id.split("/", 1)[0]
    if base in SET_ELSEWHERE:
        return SET_ELSEWHERE[base]
    if base.startswith("gwp."):
        return "the GWP is chosen for the whole engagement on the Methodology page"
    if base in DECIDABLE or base.startswith("ef."):
        return None
    return "this input cannot be decided for a line"


MIXED_RUNS = "this line mixes fuels or units: move the other records to their own line first"


def mark_decidable(trace: LineTrace) -> None:
    """``decidable`` and ``why_not`` on each input, by the same rules ``apply`` and the decision POST use."""

    mixed = _multi_run(trace)
    for input_id, item in trace.inputs.items():
        why = not_decidable(input_id)
        if why is None and (mixed or trace.state == "blocked"):
            why = MIXED_RUNS if mixed else "this line has no working to calculate from"
        item.decidable, item.why_not = why is None, why


def _multi_run(trace: LineTrace) -> bool:
    return any("#" in b.id for s in trace.steps for b in s.blocks)


def apply(trace: LineTrace, records: Mapping[str, Mapping[str, Any]], panel: str,
          context: dict[str, Any] | None = None) -> tuple[LineTrace, Outcome, Figures | None]:
    """The decided trace (``trace`` itself, worked in place: a copy of a trace costs more than building it again),
    the outcome of every decision, and the figures."""

    out = trace
    outcome = Outcome()
    values: dict[str, tuple[float, Mapping[str, Any], Mapping[str, Any]]] = {}  # input id -> (value, decision, record)
    rejected: list[str] = []
    chosen: list[tuple[str, Mapping[str, Any]]] = []  # read after the inputs: a route needs its site values
    multi_run = _multi_run(out)

    for stream, record in sorted(records.items()):
        parsed = _parse(stream)
        decision = _decision(record)
        if parsed is None or decision is None:
            continue
        target, target_id, side = parsed
        status = str(decision.get("status"))
        if status == "pending":  # a suggestion, or a revert back to the automatic value: no operand
            continue
        if target == "choice":
            chosen.append((target_id, decision))
            continue
        if side != "recomputed":
            continue  # the company's side is shown, never an operand
        why = not_decidable(target_id)
        found = _find(out, target_id)
        if found is None:
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="not_on_this_line",
                                              message=mobile.NOT_OFFERED if target_id == mobile.FUEL_ECONOMY
                                              else "This input is no longer part of the line's working."))
            continue
        if why is not None:
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="set_elsewhere",
                                              message=f"Not applied: {why}."))
            continue
        if status == "rejected":
            rejected.append(target_id)
            outcome.applied.append(_entry(target, target_id, side, status=status, uses="automatic value"))
            continue
        if status not in DECIDED:
            continue
        if multi_run:
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="line_mixes_runs",
                                              message="Not applied: this line mixes fuels or units. Move the other "
                                                      "records to their own line first."))
            continue
        stale = _stale(out, found, decision)
        if stale is not None:
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="stale",
                                              automatic_then=stale[0], automatic_now=stale[1],
                                              message="Not applied: the evidence or reference data changed after this "
                                                      "decision, so the new automatic value is used. Decide again."))
            continue
        number = _number(decision.get("value"))
        if number is None:
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="invalid_value",
                                              message="Not applied: the value is not a number above 0."))
            continue
        side_now = found.recomputed
        unit = decision.get("unit")
        if isinstance(unit, str) and unit.strip() and side_now is not None and side_now.unit and \
                normalise_unit(unit) != normalise_unit(str(side_now.unit)):
            outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="unit_mismatch",
                                              message=f"Not applied: the value is in {unit}, the input in "
                                                      f"{side_now.unit}."))
            continue
        implausible: str | None = None
        if panel == "stationary" and target_id in stationary.SITE_INPUTS:
            implausible = stationary.check_site(target_id, number, out, context, bool(decision.get("reason")))
        elif panel == "mobile" and target_id == mobile.FUEL_ECONOMY:
            implausible = mobile.check_economy(number, out)
        if implausible is not None:
                outcome.not_applied.append(_entry(target, target_id, side, status=status, reason="invalid_value",
                                                  message=implausible))
                continue
        values[target_id] = (number, decision, record)
        outcome.applied.append(_entry(target, target_id, side, status=status, value=number, unit=side_now.unit,
                                      decided_by=_by(decision), decided_at=str(decision.get("at") or ""),
                                      reason_given=str(decision.get("reason") or "")))

    site = {k: values[k][0] for k in stationary.SITE_INPUTS if k in values}
    for target_id, decision in chosen:
        _choice(out, target_id, decision, outcome, panel, site)
    if panel == "stationary":
        stationary.follow_co2(out, outcome.routes, {i for i, _ in chosen}, site)
    _equation_overrides(out, values, outcome)
    used = {option for _, option in outcome.routes.values()}
    for input_id, option in (("hhv", stationary.EQ2), ("cc", stationary.EQ3)):
        # a site value is shown as decided; it is an operand only through the equation that needs it
        if input_id in values and input_id in out.inputs:
            number, decision, record = values.pop(input_id)
            out.inputs[input_id].recomputed = _decided_side(out.inputs[input_id].recomputed, number, decision, record)
            if option not in used:
                for item in outcome.applied:
                    if item["id"] == input_id:
                        item["uses"] = "held: no equation chosen for this line uses it"

    if rejected:
        out.flags = sorted({*out.flags, REJECTED_FLAG})
    for input_id in rejected:
        found = _find(out, input_id)
        if found is not None and found.recomputed is not None:
            found.recomputed.status = "rejected"  # the automatic value stands: the suggestion was rejected
    if "activity.total" in values:  # the total decided outright wins over its rows
        for input_id in [i for i in values if i.startswith("activity.total/")]:
            values.pop(input_id)
            for item in outcome.applied:
                if item["id"] == input_id:
                    outcome.applied.remove(item)
                    outcome.not_applied.append({**item, "reason": "total_decided",
                                                "message": "Not applied: the line's activity total is decided."})
                    break
    if "fuel_economy" in values and "distance" in values:  # the fuel economy gives the distance (calc_trace/mobile.py)
        values.pop("distance")
        _move_to_not_applied(outcome, "distance", "fuel_economy_decided",
                             "Not applied: the fuel economy is decided, and the distance follows from it.")
    if (not values and not outcome.routes) or out.state == "blocked" or not out.steps:
        if values:
            for input_id in values:
                _move_to_not_applied(outcome, input_id, "line_has_no_working",
                                     "Not applied: this line has no working to calculate from.")
        return out, outcome, None
    figures = _rework(out, values, panel, outcome.routes, site, context)
    out.flags = sorted({*out.flags, APPLIED_FLAG})
    return out, outcome, figures


def _move_to_not_applied(outcome: Outcome, input_id: str, reason: str, message: str) -> None:
    for item in list(outcome.applied):
        if item["id"] == input_id:
            outcome.applied.remove(item)
            outcome.not_applied.append({**{k: v for k, v in item.items() if k != "value"}, "reason": reason,
                                        "message": message})


def _basis(decision: Mapping[str, Any]) -> dict[str, Any] | None:
    """The stored context of a decision (``calc_line_review.basis_of``), or None for one made before it was kept."""

    raw = decision.get("basis")
    if not isinstance(raw, str):
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) \
            and not isinstance(b, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
    return bool(a == b)


def _stale(trace: LineTrace, found: Any, decision: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(what the decision replaced, what is automatic now) when they differ, else None."""

    then = _basis(decision)
    if then is None:
        return None
    side = found.recomputed
    grid = trace.inputs.get("grid_region")
    now = {"value": side.value if side else None, "unit": side.unit if side else None,
           "source": (side.source.citation[:200] if side and side.source and side.source.citation else None),
           "grid_region": grid.recomputed.value if grid is not None and grid.recomputed is not None else None}
    # A fuel economy is a rate: its automatic value is the line's distance over its fuel, so a new fuel record moves
    # the distance (fuel x the decided rate) instead of making the decision stale. Only its unit is checked.
    keys = ("unit",) if getattr(found, "id", None) == mobile.FUEL_ECONOMY else tuple(now)
    if all(_same(then.get(k), now[k]) for k in keys):
        return None
    return {k: then.get(k) for k in keys}, {k: now[k] for k in keys}


def _equation_overrides(trace: LineTrace, values: dict[str, Any], outcome: Outcome) -> None:
    """A factor decided for a gas that a chosen equation works another way is not used: that equation has no such
    factor (Eq. 2 and Eq. 3 do not take the per-unit one). Reported, never half applied."""

    for choice_id, (_, option) in outcome.routes.items():
        input_id = f"ef.{choice_id.split(':', 1)[1]}"
        if input_id in values:
            values.pop(input_id)
            for item in list(outcome.applied):
                if item["id"] == input_id:
                    outcome.applied.remove(item)
                    outcome.not_applied.append({**{k: v for k, v in item.items() if k != "value"},
                                                "reason": "equation_not_used",
                                                "message": f"Not applied: this gas is worked by "
                                                           f"{stationary.EQUATION[option][0]}, which does not use "
                                                           "this emission factor."})


def _choice(trace: LineTrace, choice_id: str, decision: Mapping[str, Any], outcome: Outcome, panel: str = "",
            site: Mapping[str, float] | None = None) -> None:
    choice: Choice | None = next((c for c in trace.choices if c.id == choice_id), None)
    status = str(decision.get("status"))
    if choice is None:
        outcome.not_applied.append(_entry("choice", choice_id, None, status=status, reason="not_on_this_line",
                                          message="This choice is no longer part of the line's working."))
        return
    if status == "rejected":
        trace.flags = sorted({*trace.flags, REJECTED_FLAG})
        outcome.applied.append(_entry("choice", choice_id, None, status=status, uses="automatic value"))
        return
    if status not in DECIDED:
        return
    then = _basis(decision)
    if then is not None and "chosen" in then and then["chosen"] != (choice.chosen if choice.chosen_by == "default"
                                                                    else None):
        outcome.not_applied.append(_entry("choice", choice_id, None, status=status, reason="stale",
                                          automatic_then=then["chosen"], automatic_now=choice.chosen,
                                          message="Not applied: the line's automatic method changed after this "
                                                  "decision. Decide again."))
        return
    picked = decision.get("value")
    option = next((o for o in choice.options if o.id == picked), None)
    if option is None or not option.available:
        outcome.not_applied.append(_entry("choice", choice_id, None, status=status, reason="option_not_available",
                                          message="Not applied: that option is not available for this line."))
        return
    if option.id != choice.chosen:  # a route is worked only where one is built: never a number from one that is not
        gas = choice_id.split(":", 1)[1] if choice_id.startswith("equation:") else ""
        refusal: str | None = "Not applied: Sustentra cannot calculate this option yet."
        if panel == "stationary" and gas and choice.chosen == stationary.EQ1:
            refusal = stationary.route_refusal(trace, gas, option.id, site or {})
        if refusal is not None:
            outcome.not_applied.append(_entry("choice", choice_id, None, status=status, reason="no_route_for_option",
                                              message=refusal))
            return
        outcome.routes[choice_id] = (choice.chosen, option.id)
        choice.chosen = option.id
    choice.chosen_by = "reviewer"
    outcome.applied.append(_entry("choice", choice_id, None, status=status, value=option.id))


def _find(trace: LineTrace, input_id: str) -> Any:
    """The input (or its row) the id names, or None."""

    if input_id in trace.inputs:
        return trace.inputs[input_id]
    base, _, row_id = input_id.partition("/")
    item = trace.inputs.get(base)
    if item is None or not row_id:
        return None
    return next((r for r in item.rows or [] if r.id == row_id), None)


def _f(value: Any) -> float:
    """An operand's value as a float: every value the rework reads is a number (the builder checked it)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ops.TraceError(f"not a number: {value!r}")
    return float(value)


def _fresh(operand: Operand, value: float | str | None) -> Operand:
    return Operand(column=operand.column, value=value, unit=operand.unit, input_id=operand.input_id,
                   step_ref=operand.step_ref)


def _redo(op: Operation, values: list[float | str | None]) -> Operation:
    """The operation evaluated again with each term's value replaced (in order)."""

    terms = [Term(t.op, _fresh(t.operand, v)) for t, v in zip(op.terms, values, strict=True)]
    return ops.make_operation(terms, op.result.column, op.result.unit, input_id=op.result.input_id)


def _set(block: TraceBlock, op: Operation) -> None:
    block.recomputed = op
    if block.company is not None:
        _annotate(op, block.company)


def _decided_side(side: Side | None, value: float, decision: Mapping[str, Any], record: Mapping[str, Any]) -> Side:
    unit = side.unit if side is not None else None
    return Side(value, unit, "edited" if decision.get("status") == "edited" else "accepted",
                _source(decision, record))


def _rework(trace: LineTrace, values: Mapping[str, tuple[float, Mapping[str, Any], Mapping[str, Any]]],
            panel: str, routes: Mapping[str, tuple[str, str]] | None = None, site: Mapping[str, float] | None = None,
            context: dict[str, Any] | None = None) -> Figures:
    """Steps 1 to 4 and the results worked again, in order, with the decided values. Units never change: every
    operand keeps its unit and ``make_operation`` re-checks them."""

    blocks = {b.id: b for s in trace.steps for b in s.blocks}
    activity_input = trace.inputs["activity.total"]

    # Step 1: the activity total, decided outright or as the sum of its rows (each decided or as found)
    activity_block = blocks["activity"]
    conversion_block = blocks["conversion"]
    assert conversion_block.recomputed is not None
    old_activity = _f(conversion_block.recomputed.terms[0].operand.value)
    old_converted = _f(conversion_block.recomputed.result.value)
    if "activity.total" in values:
        total, decision, record = values["activity.total"]
        unit = activity_input.recomputed.unit if activity_input.recomputed else None
        op = Operation([Term(None, Operand("activity", total, unit, input_id="activity.total"))],
                       Operand("activity", total, unit, input_id="activity.total"))
        if activity_block.recomputed is not None or activity_block.company is not None:
            _set(activity_block, op)
        activity_input.recomputed = _decided_side(activity_input.recomputed, total, decision, record)
    else:
        rows = activity_input.rows or []
        total = old_activity
        if activity_block.recomputed is not None and any(f"activity.total/{r.id}" in values for r in rows):
            parts: list[float | str | None] = []
            for row, term in zip(rows, activity_block.recomputed.terms, strict=True):
                found = values.get(f"activity.total/{row.id}")
                if found is not None:
                    row.recomputed = _decided_side(row.recomputed, found[0], found[1], found[2])
                    parts.append(found[0])
                else:
                    parts.append(term.operand.value)
            op = _redo(activity_block.recomputed, parts)
            _set(activity_block, op)
            total = _f(op.result.value)
            if activity_input.recomputed is not None:
                activity_input.recomputed = replace(activity_input.recomputed, value=total)
    if activity_input.company is not None and activity_input.recomputed is not None and ops.same_unit(
            activity_input.recomputed.unit, activity_input.company.unit):
        d = ops.difference(total, _f(activity_input.company.value), activity_input.recomputed.unit,
                           activity_input.company.unit)
        activity_input.difference, activity_input.differs = d, ops.differs(d, total)

    # Step 2: the conversion
    conversion = _redo(conversion_block.recomputed, [total, conversion_block.recomputed.terms[1].operand.value])
    _set(conversion_block, conversion)
    converted = _f(conversion.result.value)

    distance = values.get("distance")
    if panel == "mobile":  # a decided fuel economy gives the distance, and Step 2's distance block follows
        distance = mobile.work_distance(trace, values, converted, _decided_side)
    elif distance is not None and "distance" in trace.inputs:
        trace.inputs["distance"].recomputed = _decided_side(trace.inputs["distance"].recomputed, *distance)

    # Steps 3 and 4: per gas
    mass: dict[str, float] = {}
    co2e: dict[str, float] = {}
    biogenic = 0.0
    rows_out: dict[str, dict[str, Any]] = {}
    follows_vehicle_group = False
    emission_ids = [b.id for b in blocks.values() if b.id.startswith("emissions.")]
    for block_id in emission_ids:
        gas = block_id.split(".", 1)[1]
        block = blocks[block_id]
        assert block.recomputed is not None
        first, ef_term, conv_term = (t.operand for t in block.recomputed.terms)
        activity_value: float | str | None = first.value
        route = (routes or {}).get(f"equation:{gas}")
        if first.input_id == "distance":  # on-road CH4 and N2O: Eq. 4
            activity_value = distance[0] if distance is not None else first.value
        elif first.step_ref == "conversion":
            follows = (panel != "mobile" or gas == "CO2") and math.isclose(
                _f(first.value), old_converted, rel_tol=1e-9, abs_tol=1e-12)
            if follows:
                activity_value = converted
            elif not math.isclose(converted, old_converted, rel_tol=1e-12, abs_tol=0.0):
                follows_vehicle_group = True  # a non-road group's CH4 and N2O follow the group's own fuel
        ef = values.get(f"ef.{gas}")
        if ef is not None:
            item = trace.inputs[f"ef.{gas}"]
            item.recomputed = _decided_side(item.recomputed, *ef)
        extra: dict[str, Any] = {}
        if route is not None:  # a chosen Eq. 2 or Eq. 3 (stationary): the gas worked on that equation
            made = stationary.worked(trace, gas, route[1], converted, site or {}, context)
            emitted, block.columns, extra = made.operation, made.columns, made.row
        else:
            emitted = _redo(block.recomputed, [activity_value, ef[0] if ef else ef_term.value, conv_term.value])
        _set(block, emitted)
        mass_t = _f(emitted.result.value)
        gwp_block = blocks.get(f"gwp.{gas}")
        if gwp_block is not None and gwp_block.recomputed is not None:
            worked = _redo(gwp_block.recomputed, [mass_t, gwp_block.recomputed.terms[1].operand.value])
            _set(gwp_block, worked)
            co2e[gas] = _f(worked.result.value)
            mass[gas] = mass_t
        else:  # biogenic CO2: shown, reported apart, counted 0
            biogenic += mass_t
            mass[gas], co2e[gas] = 0.0, 0.0
        rows_out[gas] = {"activity": _f(activity_value), "ef": _f(ef[0] if ef else ef_term.value), "mass_t": mass_t,
                         "co2e_t": co2e[gas]}
        if extra:  # the legacy Step 3 row of a routed gas: its own activity, factor and units
            rows_out[gas] = {**rows_out[gas], **extra, "mass_t": mass_t}
    if follows_vehicle_group:
        trace.flags = sorted({*trace.flags, GROUP_FUEL_FLAG})

    # Results
    sum_block, total_block = blocks["results.sum"], blocks["results.total"]
    assert sum_block.recomputed is not None and total_block.recomputed is not None
    summed = _redo(sum_block.recomputed, [
        co2e[t.operand.step_ref.split(".", 1)[1]] if t.operand.step_ref and t.operand.step_ref.startswith("gwp.")
        else t.operand.value for t in sum_block.recomputed.terms])
    _set(sum_block, summed)
    scaled = _redo(total_block.recomputed, [summed.result.value, total_block.recomputed.terms[1].operand.value])
    _set(total_block, scaled)
    line_total = _f(scaled.result.value)
    company = trace.result.company
    trace.result = TraceResult(trace.result.unit, company, line_total,
                               ops.difference(line_total, company, "t CO2e", "t CO2e"))
    return Figures(mass_t=mass, gas_co2e_t=co2e, sum_co2e_t=_f(summed.result.value), total_co2e_t=line_total, biogenic_co2_t=biogenic, activity=converted, activity_total=total,
                   rows=rows_out)
