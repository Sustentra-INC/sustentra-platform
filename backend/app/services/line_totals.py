"""Category totals from the calculation lines, so a reviewer's decision on a line moves its category (F3b).

For stationary combustion, mobile combustion and location-based electricity, a family's category is the sum of its
calculation lines (each line's trace total, pre-share) plus the records on no line (``calculation_unplaced``). Today
both are made from the same ledger by the same calculator, so they agree; ``adds_up`` checks that they do, to 1e-9,
on every recalculation that carries a decision.

``apply`` then moves each category by its lines' decisions. A decided line is counted at its decided figures instead
of its calculated ones: the category line of its calculator run (its fuel, or its facility) takes the difference, gas
by gas, as a step of its own (so the Working sheet shows it), and the category is totalled again (``retotal``). The
category total is therefore Σ lines (decided) + unplaced. Market-based electricity follows: run again on the decided
MWh (certificate coverage moves with the total), with a facility whose factor was decided worked as its decided
location-based mass x (1 - coverage), exactly what the market-based calculator does with a facility's own factor.

With no decision that changes a number nothing here runs, so the categories are the calculators' own, bit for bit.
When the lines do not add up to their category (a line that could not be calculated, say), its decisions are not
applied to the totals: the line keeps its calculated figures and the decision is reported, never half applied.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from backend.app.reference.emission_factor_loader import EmissionFactorNotFoundError, EmissionFactorReference
from backend.app.services import emissions_calculator as calc
from backend.app.services.recalculation_lines import DecidedLine

FAMILY_CATEGORY = {"stationary": "stationary_combustion", "mobile": "mobile_combustion",
                   "electricity": "purchased_electricity_location_based"}
COUNTS_TOWARD = {"stationary": "stationary", "mobile": "mobile", "electricity": "purchased_energy"}
MARKET = "purchased_electricity_market_based"
REL_TOL = 1e-9
FLAG = "reviewer_decisions_applied"
STEP = "Reviewer decisions on calculation lines"


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=REL_TOL)


def line_sums(lines: Iterable[Mapping[str, Any]], counts_toward: str,
              results_of: Mapping[int, Mapping[str, Any]] | None = None) -> dict[str, float]:
    """Σ of the lines' (and unplaced records') results that count toward one category: mass by gas, pre-share, and
    biogenic CO2. ``results_of`` (by ``id`` of the line) puts other results in place of a line's own."""

    out = {gas: 0.0 for gas in calc.GASES} | {"biogenic": 0.0}
    for line in lines:
        if line.get("counts_toward") != counts_toward:
            continue
        results = (results_of or {}).get(id(line)) or line["results"]
        for gas in calc.GASES:
            out[gas] += float(results["mass_t"].get(gas, 0.0))
        out["biogenic"] += float(results.get("biogenic_co2_t") or 0.0)
    return out


def adds_up(sums: Mapping[str, float], category: calc.CategoryResult | Mapping[str, Any] | None) -> bool:
    """True when the lines' sums equal the category's totals, gas by gas, to 1e-9."""

    if category is None:
        return all(_close(v, 0.0) for v in sums.values())
    mass = category.total_mass_t if isinstance(category, calc.CategoryResult) else category["total_mass_t"]
    biogenic = category.biogenic_co2_t if isinstance(category, calc.CategoryResult) else category["biogenic_co2_t"]
    return all(_close(sums[g], float(mass.get(g, 0.0))) for g in calc.GASES) and _close(sums["biogenic"],
                                                                                         float(biogenic or 0.0))


def _position(category: calc.CategoryResult, family: str, sub: tuple[str, ...]) -> int | None:
    """The index of the category line that holds the calculator run ``sub``."""

    if family == "electricity":
        found = [i for i, line in enumerate(category.lines) if line.key == sub[0]]
    else:
        inputs = category.details.get("inputs") or []
        found = [i for i, item in enumerate(inputs) if (item.get("fuel"), item.get("unit")) == tuple(sub)]
        if len(inputs) != len(category.lines):
            return None
    return found[0] if len(found) == 1 else None


def refuse(line: dict[str, Any], default_trace: Callable[[dict[str, Any]], dict[str, Any] | None] | None,
           reason: str, message: str) -> None:
    """The line keeps its calculated figures: each decision that changed a number is reported as not applied."""

    report = line.setdefault("decisions", {"applied": [], "not_applied": []})
    kept: list[dict[str, Any]] = []
    for entry in report["applied"]:
        if entry.get("status") in ("accepted", "edited") and entry.get("target") == "input":
            report["not_applied"].append({**{k: v for k, v in entry.items() if k != "value"}, "reason": reason,
                                          "message": message})
        else:
            kept.append(entry)
    report["applied"] = kept
    if "trace" in line:  # the working shown is the one counted: the calculated one
        line["trace"] = default_trace(line) if default_trace is not None else None


def _refuse(item: DecidedLine, reason: str, message: str) -> None:
    refuse(item.line, item.decided.default, reason, message)


def apply(categories: dict[str, calc.CategoryResult | None], decided: list[DecidedLine],
          lines: list[dict[str, Any]], unplaced: list[dict[str, Any]], *, ref: EmissionFactorReference,
          tolerance: float, electricity: list[calc.FacilityElectricity] | None = None,
          certificates: list[calc.Certificate] | None = None) -> list[DecidedLine]:
    """Move each category by its lines' decisions (in place) and write the decided figures on those lines. Returns
    the decided lines that were applied."""

    applied: list[DecidedLine] = []
    every = [*lines, *unplaced]
    for family, name in FAMILY_CATEGORY.items():
        mine = [d for d in decided if d.family == family]
        if not mine:
            continue
        category = categories.get(name)
        if category is None or not adds_up(line_sums(every, COUNTS_TOWARD[family]), category):
            for item in mine:
                _refuse(item, "category_does_not_add_up", "Not applied: this category's lines do not add up to its "
                        "total, so a change on one line cannot be counted. Check the lines marked as not calculated.")
            continue
        placed = [(item, _position(category, family, item.sub)) for item in mine]
        for item, position in placed:
            if position is None:
                _refuse(item, "no_category_line", "Not applied: the category has no single entry for this line's "
                        "fuel or facility.")
        usable = [(item, position) for item, position in placed if position is not None]
        if not usable:
            continue
        new_lines = [copy.deepcopy(line) for line in category.lines]
        for item, position in usable:
            _shift(new_lines[position], item)
        if family == "electricity":
            ok, market = _market(categories.get(MARKET), new_lines, category, usable, electricity or [],
                                 certificates or [], ref)
            if not ok:
                for item, _ in usable:
                    _refuse(item, "market_based_not_recalculated", "Not applied: the market-based electricity could "
                            "not be calculated again with this value.")
                continue
            if market is not None:
                categories[MARKET] = market
        result = calc.retotal(category, new_lines, ref, [FLAG])
        result.flags = sorted(set(result.flags))
        categories[name] = result
        for item, _ in usable:
            item.write(tolerance)
            applied.append(item)
    return applied


def _shift(line: calc.LineResult, item: DecidedLine) -> None:
    """The category line moved by one calculation line's decided figures, gas by gas, with the step that says so."""

    before, figures = item.line["results"], item.figures
    for gas in calc.GASES:
        delta = figures.mass_t.get(gas, before["mass_t"].get(gas, 0.0)) - float(before["mass_t"].get(gas, 0.0))
        if delta == 0.0:
            continue
        old = line.mass_t.get(gas, 0.0)
        line.mass_t[gas] = old + delta
        line.steps.append(calc.Step(f"{gas} after {STEP.lower()}", "calculated + (decided - calculated) per line",
                                    {"calculated": {"value": old, "unit": "t", "source": None},
                                     str(item.line["key"]): {"value": delta, "unit": "t", "source": STEP}},
                                    line.mass_t[gas], "t"))
    biogenic = figures.biogenic_co2_t - float(before.get("biogenic_co2_t") or 0.0)
    if biogenic != 0.0:
        line.biogenic_co2_t += biogenic
    line.flags = sorted({*line.flags, FLAG})


def _market(market: calc.CategoryResult | None, location_lines: list[calc.LineResult],
            location: calc.CategoryResult, usable: list[tuple[DecidedLine, int]],
            facilities: list[calc.FacilityElectricity], certificates: list[calc.Certificate],
            ref: EmissionFactorReference) -> tuple[bool, calc.CategoryResult | None]:
    """Market-based electricity on the decided MWh and factors: (True, the new result), (True, None) when there is
    none to move, or (False, None) when it cannot be calculated again (then nothing is applied)."""

    if market is None:
        return True, None
    mwh = {f.facility: float(f.consumption.value) for f in facilities}
    if set(mwh) != {line.key for line in location.lines}:
        return False, None
    changed: set[str] = set()
    for item, position in usable:
        facility = location.lines[position].key
        mwh[facility] += item.figures.activity - item.activity
        changed.add(facility)
    try:
        rerun = calc.electricity_market_based(
            [replace(f, consumption=calc.Measure(mwh[f.facility], "MWh", f.consumption.source)) for f in facilities],
            certificates, ref, gwp_set=market.gwp_set)
    except (calc.CalculationError, EmissionFactorNotFoundError):
        return False, None
    coverage = float(rerun.details["coverage"])
    by_key = {line.key: line for line in location_lines}
    flags_of = {line.key: line.flags for line in market.lines}
    for line in rerun.lines:
        line.flags = sorted({*line.flags, *flags_of.get(line.key, [])})
        if line.key not in changed:
            continue
        decided = by_key[line.key]
        for gas in calc.GASES:  # a decided factor: the market-based remainder uses it as the location-based does
            worked = decided.mass_t.get(gas, 0.0) * (1 - coverage)
            if not math.isclose(worked, line.mass_t.get(gas, 0.0), rel_tol=1e-12, abs_tol=0.0):
                line.steps.append(calc.Step(f"{gas} after {STEP.lower()}", "decided location-based mass x "
                                            "(1 - coverage)", {"location-based": {"value": decided.mass_t.get(gas, 0.0),
                                                                                  "unit": "t", "source": STEP},
                                                               "coverage": {"value": coverage, "unit": "fraction",
                                                                            "source": None}}, worked, "t"))
                line.mass_t[gas] = worked
        line.flags = sorted({*line.flags, FLAG})
    rerun.details = {**market.details, **{k: v for k, v in rerun.details.items() if k != "inputs"}}
    result = calc.retotal(rerun, rerun.lines, ref, [*market.flags, FLAG])
    result.flags = sorted(set(result.flags))
    return True, result
