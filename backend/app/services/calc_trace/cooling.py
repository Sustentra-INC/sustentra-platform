"""The cooling panel's trace. Not built yet (a later change fills this in); no panel means no trace."""

from __future__ import annotations

from typing import Any

from backend.app.services.calc_trace.model import LineTrace


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    return None
