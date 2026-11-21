"""Electricity trace, location-based: MWh x eGRID subregion factor (lb per MWh) x metric tons per lb."""

from __future__ import annotations

from typing import Any

from backend.app.services.calc_trace.model import LineTrace, Side, SourceRef, TraceInput
from backend.app.services.calc_trace._common import trace_for


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    """``context["grid_region"]`` is the eGRID subregion the calculator used for the line, when known."""

    context = dict(context or {})
    region = context.pop("grid_region", None)
    if region:
        context["inputs"] = {"grid_region": TraceInput(
            "grid_region", "eGRID subregion", "reference", required_for=["location_based"],
            recomputed=Side(str(region), None, "derived", SourceRef("derived", from_=["facility grid region"])))}
    return trace_for("electricity", line, "location_based", context)
