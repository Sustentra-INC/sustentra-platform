"""Calculation traces: the step-by-step working of a calculation line, one shape for every panel.

``build_trace(panel, line)`` returns the trace of a recalculation line as a JSON-ready dict, or None when
the panel has no builder yet or the line cannot be traced. A trace only restates what the calculators
already produced: it never changes a number in the response, and a failure here never fails a recalculation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.app.services.calc_trace import cooling, electricity, fugitive, heat, mobile, purchased_gases
from backend.app.services.calc_trace import stationary, steam
from backend.app.services.calc_trace.model import PANELS, TRACE_VERSION, LineTrace

log = logging.getLogger(__name__)

Builder = Callable[[dict[str, Any], dict[str, Any] | None], LineTrace | None]
BUILDERS: dict[str, Builder] = {
    "stationary": stationary.build, "mobile": mobile.build, "fugitive": fugitive.build,
    "purchased_gases": purchased_gases.build, "electricity": electricity.build, "steam": steam.build,
    "heat": heat.build, "cooling": cooling.build,
}
assert tuple(BUILDERS) == PANELS

__all__ = ["BUILDERS", "PANELS", "TRACE_VERSION", "build_trace"]


def build_trace(panel: str, line: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    builder = BUILDERS.get(panel)
    if builder is None:
        return None
    try:
        trace = builder(line, context)
    except Exception as exc:  # noqa: BLE001 - a trace must never take a recalculation down
        log.warning("calculation trace failed: %s", type(exc).__name__)
        return None
    return trace.to_dict() if trace is not None else None
