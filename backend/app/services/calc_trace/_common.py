"""Pieces the stationary, mobile and electricity builders share."""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.calc_trace import _line
from backend.app.services.calc_trace.model import Choice, ChoiceOption, LineTrace, SourceRef

HUB = SourceRef(kind="reference", dataset="EPA GHG Emission Factors Hub", edition="2025",
                citation="EPA GHG Emission Factors Hub 2025")


def option_id(equation: str) -> str:
    """``"Eq. 4"`` -> ``"eq4"``; ``"Emissions = MWh x EF"`` -> ``"emissions_mwh_x_ef"``."""

    return re.sub(r"[^a-z0-9]+", "_", equation.lower()).strip("_")


def choices_for(line: dict[str, Any], method_id: str) -> list[Choice]:
    """What the calculation used today, as choices: the route, and per gas the equation. Each lists only the
    option actually used (reviewers cannot pick another yet), chosen by default."""

    method = line["method"]
    out = [Choice("method", "Calculation method", [ChoiceOption(method_id, method["route"], citation=HUB)],
                  chosen=method_id)]
    for gas, equation in method["equations"].items():
        oid = option_id(equation)
        out.append(Choice(f"equation:{gas}", f"{gas} equation",
                          [ChoiceOption(oid, equation, equation=equation, citation=HUB)], chosen=oid))
    return out


def trace_for(family: str, line: dict[str, Any], method_id: str, context: dict[str, Any] | None = None
              ) -> LineTrace | None:
    return _line.build(family, line, choices=choices_for(line, method_id), context=context)
