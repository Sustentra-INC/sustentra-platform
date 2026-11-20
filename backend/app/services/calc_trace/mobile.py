"""Mobile combustion trace: fuel x CO2 factor; a vehicle group's CH4 and N2O by distance (Eq. 4) or fuel (Eq. 5)."""

from __future__ import annotations

from typing import Any

from backend.app.services.calc_trace._common import trace_for
from backend.app.services.calc_trace.model import LineTrace


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    return trace_for("mobile", line, "epa_hub_fuel_and_vehicle_group", context)
