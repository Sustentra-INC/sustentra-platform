"""Calculation traces: the step-by-step working of a calculation line, one shape for every panel.

``build_trace(panel, line)`` returns the trace of a recalculation line as a JSON-ready dict, or None when
the panel has no builder yet or the line cannot be traced. A trace restates what the calculators
already produced, and a failure here never fails a recalculation.

``decided_trace(panel, line, context, records)`` is the same trace with the reviewer's decisions on the line read
in (``decisions.apply``): the trace, what happened to each decision, and the line's decided figures (None when no
decision changes a number). A line that cannot be traced takes no decision: every one is reported, none applied.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.app.services.calc_trace import cooling, electricity, fugitive, heat, mobile, purchased_gases
from backend.app.services.calc_trace import decisions, stationary, steam
from backend.app.services.calc_trace.model import PANELS, TRACE_VERSION, LineTrace

log = logging.getLogger(__name__)

Builder = Callable[[dict[str, Any], dict[str, Any] | None], LineTrace | None]
BUILDERS: dict[str, Builder] = {
    "stationary": stationary.build, "mobile": mobile.build, "fugitive": fugitive.build,
    "purchased_gases": purchased_gases.build, "electricity": electricity.build, "steam": steam.build,
    "heat": heat.build, "cooling": cooling.build,
}
assert tuple(BUILDERS) == PANELS

__all__ = ["BUILDERS", "PANELS", "TRACE_VERSION", "Decided", "build_trace", "decided_trace"]


@dataclass
class Decided:
    trace: dict[str, Any] | None
    applied: list[dict[str, Any]] = field(default_factory=list)
    not_applied: list[dict[str, Any]] = field(default_factory=list)
    figures: decisions.Figures | None = None
    # the line's working as calculated, built again from the line as calculated, for when a decision is not counted
    default: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None


def _built(panel: str, line: dict[str, Any], context: dict[str, Any] | None) -> LineTrace | None:
    builder = BUILDERS.get(panel)
    if builder is None:
        return None
    try:
        trace = builder(line, context)
    except Exception as exc:  # noqa: BLE001 - a trace must never take a recalculation down
        log.warning("calculation trace failed: %s", type(exc).__name__)
        return None
    if trace is not None:
        decisions.mark_decidable(trace)
    return trace


def build_trace(panel: str, line: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    trace = _built(panel, line, context)
    return trace.to_dict() if trace is not None else None


def decided_trace(panel: str, line: dict[str, Any], context: dict[str, Any] | None,
                  records: Mapping[str, Mapping[str, Any]], *, serialise: bool = True) -> Decided:
    """``serialise``: put the trace's JSON on the result (only a response that carries traces needs it)."""

    def default(calculated: dict[str, Any]) -> dict[str, Any] | None:
        return build_trace(panel, calculated, context)

    trace = _built(panel, line, context)
    if trace is None:
        return Decided(None, not_applied=_unread(records, "line_not_traceable",
                                                 "Not applied: this line's working could not be built."))
    try:
        decided, outcome, figures = decisions.apply(trace, records, panel, context)
    except Exception as exc:  # noqa: BLE001 - the default working stands, every decision reported
        log.warning("calculation decisions failed: %s", type(exc).__name__)
        return Decided(default(line) if serialise else None, not_applied=_unread(
            records, "could_not_apply", "Not applied: the decision could not be worked in."))
    return Decided(decided.to_dict() if serialise else None, outcome.applied, outcome.not_applied, figures, default)


def _unread(records: Mapping[str, Mapping[str, Any]], reason: str, message: str) -> list[dict[str, Any]]:
    out = []
    for stream, record in sorted(records.items()):
        decision = record.get("decision") if isinstance(record, Mapping) else None
        target, _, rest = stream.partition("|")
        target_id, _, side = rest.rpartition("|")
        if side == "company":  # shown on the trace, never an operand
            continue
        if isinstance(decision, Mapping) and decision.get("status") not in (None, "pending"):
            out.append({"target": target, "id": target_id, "side": side or None, "status": decision.get("status"),
                        "reason": reason, "message": message})
    return out
