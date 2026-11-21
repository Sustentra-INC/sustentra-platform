"""Stationary combustion trace: fuel (or energy) x per-unit factor, per gas (EPA Hub Table 1)."""

from __future__ import annotations

from typing import Any

from backend.app.services.calc_trace._common import trace_for
from backend.app.services.calc_trace.model import LineTrace


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    return trace_for("stationary", line, "epa_hub_per_unit_factor", context)
