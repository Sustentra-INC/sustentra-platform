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

Fugitive refrigerants (``_apply_fugitive``) are by refrigerant, not by gas: a decided line moves its refrigerant's mass,
and a refrigerant the category could not count (no GWP) is counted from the lines whose component GWPs are decided.

Purchased steam (``_apply_steam``) moves by facility, gas by gas, as electricity does; a facility the category could not
count (steam by weight, no heat content) is counted from its decided lines. Market-based steam moves with it: it has
always used the location-based factor (no supplier factor was read), and a supplier's factor decided on a line is now
the one both use.

With no decision that changes a number nothing here runs, so the categories are the calculators' own, bit for bit.
When the lines do not add up to their category (a line that could not be calculated, say), its decisions are not
applied to the totals: the line keeps its calculated figures and the decision is reported, never half applied.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
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
        if entry.get("status") in ("accepted", "edited") and (entry.get("target") == "input"
                                                              or entry.get("moves_totals")):
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
    refrigerants = [d for d in decided if d.family == "fugitive"]
    if refrigerants:
        applied.extend(_apply_fugitive(categories, refrigerants, every, tolerance))
    steam = [d for d in decided if d.family == "steam"]
    if steam:
        applied.extend(_apply_steam(categories, steam, every, ref, tolerance))
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
    line.steps.extend(_decided_inputs(item))
    line.flags = sorted({*line.flags, FLAG})


_LABELS = {"activity.total": "Activity", "distance": "Distance", "fuel_economy": "Fuel economy",
           "hhv": "Site heat content (HHV)", "cc": "Carbon content", "mass": "Steam by weight",
           "energy": "Steam as energy", "net_enthalpy": "Net steam enthalpy", "pressure_psig": "Steam pressure",
           "condensate_f": "Condensate return temperature", "efficiency": "Boiler thermal efficiency"}


def _label(input_id: str) -> str:
    if input_id.startswith("ef."):
        return f"{input_id[3:]} emission factor"
    if input_id.startswith("activity.total/"):
        return "Activity (one record)"
    if input_id.startswith("component_gwp."):
        return f"{input_id.split('.', 1)[1]} GWP"
    term, _, row = input_id.partition("/")
    if term in _TERM_LABELS:
        return f"{_TERM_LABELS[term]} {term}" + (" (one record)" if row else "")
    return _LABELS.get(input_id, input_id)


_TERM_LABELS = {"P_N": "New equipment charge", "C_N": "New equipment capacity", "P_S": "Added during service",
                "C_D": "Retired equipment capacity", "R_D": "Recovered from retired equipment"}


def _decided_inputs(item: DecidedLine) -> list[calc.Step]:
    """The inputs a reviewer decided for the line, as steps of its category line (so the Working sheet shows them):
    the value used, its unit, who decided it and why. A decided fuel economy also shows the distance it gave."""

    steps: list[calc.Step] = []
    key = str(item.line["key"])
    for entry in item.decided.applied:
        if entry.get("target") == "choice" and entry.get("moves_totals") and entry.get("id") == "grid_region":
            who = f"decided by {entry.get('decided_by') or 'a reviewer'}" + (
                f" on {entry['decided_at']}" if entry.get("decided_at") else "")
            why = f": {entry['reason_given']}" if entry.get("reason_given") else ""
            steps.append(calc.Step(f"Decided choice: Grid region ({key})",
                                   "line worked on the emission factors of the chosen eGRID subregion",
                                   {"grid region": {"value": str(entry.get("value")), "unit": "",
                                                    "source": f"{who}{why}"}}, item.figures.sum_co2e_t, "t CO2e"))
            continue
        if entry.get("target") != "input" or isinstance(entry.get("value"), bool) or not isinstance(
                entry.get("value"), (int, float)):
            continue  # a chosen equation is a choice, not an input
        who = f"decided by {entry.get('decided_by') or 'a reviewer'}" + (
            f" on {entry['decided_at']}" if entry.get("decided_at") else "")
        why = f": {entry['reason_given']}" if entry.get("reason_given") else ""
        held = f" ({entry['uses']})" if entry.get("uses") else ""
        value, unit = float(entry["value"]), str(entry.get("unit") or "")
        name = _label(str(entry["id"]))
        steps.append(calc.Step(f"Decided input: {name} ({key})", "used in place of the calculated value",
                               {name: {"value": value, "unit": unit, "source": f"{who}{why}{held}"}}, value, unit))
        if entry["id"] == "fuel_economy":
            ch4 = item.figures.rows.get("CH4")
            if ch4 is not None:
                miles = float(ch4["activity"])
                steps.append(calc.Step(f"Distance from the decided fuel economy ({key})", "Fuel x fuel economy",
                                       {"fuel": {"value": item.figures.activity, "unit": "gal", "source": None},
                                        "fuel economy": {"value": value, "unit": unit, "source": f"{who}{why}"}},
                                       miles, "mi"))
    return steps


def _market(market: calc.CategoryResult | None, location_lines: list[calc.LineResult],
            location: calc.CategoryResult, usable: list[tuple[DecidedLine, int]],
            facilities: list[calc.FacilityElectricity], certificates: list[calc.Certificate],
            ref: EmissionFactorReference) -> tuple[bool, calc.CategoryResult | None]:
    """Market-based electricity on the decided MWh and factors: (True, the new result), (True, None) when there is
    none to move, or (False, None) when it cannot be calculated again (then nothing is applied)."""

    if market is None:
        return True, None
    if any(f.consumption.unit not in ("MWh", "kWh") for f in facilities):
        return False, None
    mwh = {f.facility: float(f.consumption.value) / (1000 if f.consumption.unit == "kWh" else 1) for f in facilities}
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


# --- fugitive refrigerants (C4) ---------------------------------------------------------------------------------------
FUGITIVE = "fugitive_refrigerants"
DECIDED_GWP_SOURCE = "Component GWPs decided on the calculation lines"
NEGATIVE = "negative_refrigerant_emissions"


def _first_decided(item: DecidedLine) -> datetime:
    """When the line's earliest applied decision was made, in UTC (a time without a zone is taken as UTC); the latest
    possible time when none says or none can be read, so such a line comes last."""

    times: list[datetime] = []
    for entry in item.decided.applied:
        text = str(entry.get("decided_at") or "").strip()
        try:
            at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        times.append(at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC))
    return min(times) if times else datetime.max.replace(tzinfo=UTC)


def fugitive_sums(lines: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Σ of the fugitive lines' (and unplaced records') mass by refrigerant. A line whose refrigerant has no GWP holds
    no mass: the category does not count it either."""

    out: dict[str, float] = {}
    for line in lines:
        if line.get("counts_toward") != "fugitive":
            continue
        for gas, mass in (line["results"].get("mass_t") or {}).items():
            out[gas] = out.get(gas, 0.0) + float(mass)
    return out


def _apply_fugitive(categories: dict[str, calc.CategoryResult | None], mine: list[DecidedLine],
                    every: list[dict[str, Any]], tolerance: float) -> list[DecidedLine]:
    """The fugitive category moved by its lines' decisions. A refrigerant the category counted takes each decided
    line's change of mass (its GWP is the category's: a line cannot decide it). A refrigerant it could not count (no
    GWP) is counted from the lines whose component GWPs are decided, at the blend GWP they give; every such line of
    one refrigerant must give the same GWP. Then the category is totalled again as ``calc.refrigerants`` totals it."""

    category = categories.get(FUGITIVE)
    counted = {line.key: float(line.mass_t.get(line.key, 0.0)) for line in category.lines} if category else {}
    sums = fugitive_sums(every)
    # a refrigerant missing on one side counts 0 there (a line with the company's figures and no record holds 0 t)
    if (category is not None and len(counted) != len(category.lines)) or any(
            not _close(sums.get(gas, 0.0), counted.get(gas, 0.0)) for gas in {*sums, *counted}):
        for item in mine:
            _refuse(item, "category_does_not_add_up", "Not applied: this category's lines do not add up to its "
                    "total, so a change on one line cannot be counted. Check the lines marked as not calculated.")
        return []
    gwp: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (category.gwp if category else {}).items()}
    added: dict[str, tuple[float, DecidedLine]] = {}
    usable: list[DecidedLine] = []
    # A refrigerant counted for the first time takes the GWP of the line decided first (then by line key): every later
    # line of it with another GWP is refused, naming that line, whatever order the lines are built in.
    for item in sorted(mine, key=lambda d: (_first_decided(d), str(d.line.get("key")))):
        gas = item.sub[0]
        decided_gwp = (item.figures.rows.get(gas) or {}).get("gwp")
        if not isinstance(decided_gwp, (int, float)) or gas not in item.figures.mass_t:
            _refuse(item, "could_not_count", "Not applied: the decision could not be counted in the totals.")
        elif gas in counted:
            if not math.isclose(float(decided_gwp), float(gwp[gas]["value"]), rel_tol=1e-12, abs_tol=0.0):
                _refuse(item, "could_not_count", "Not applied: the line's GWP is not the one its category uses.")
            else:
                usable.append(item)
        elif gas in added and not math.isclose(added[gas][0], float(decided_gwp), rel_tol=1e-12, abs_tol=0.0):
            first = added[gas][1].line
            _refuse(item, "gwp_differs_between_lines",
                    f"Not applied: the {gas} line at {first.get('label') or first.get('key')} was decided first, with "
                    f"component GWPs that give {gas} a GWP of {added[gas][0]:,.6g}. Decide the same component GWPs "
                    f"here, or change that line's.")
        else:
            added.setdefault(gas, (float(decided_gwp), item))
            usable.append(item)
    if not usable:
        return []
    new_lines = {line.key: copy.deepcopy(line) for line in category.lines} if category else {}
    details = copy.deepcopy(category.details) if category else {}
    for item in usable:
        gas = item.sub[0]
        line = new_lines.get(gas)
        if line is None:  # a refrigerant counted for the first time, from its decided lines
            line = new_lines[gas] = calc.LineResult(gas, {gas: calc.REFRIGERANT_EQUATION}, {gas: 0.0})
            own = (added[gas][1].line.get("smb") or {}).get("gwp")  # a GWP the line had (no record yet), else decided
            gwp[gas] = {"value": added[gas][0], "source": own.get("source") if own else DECIDED_GWP_SOURCE}
        if gas in added:  # the Working sheet lists the records it counted, as for every other refrigerant
            entry = next((e for e in details.setdefault("inputs", []) if e.get("fuel") == gas), None)
            if entry is None:
                entry = {"fuel": gas, "unit": item.line["smb"]["unit"], "quantity": 0.0, "documents": []}
                details["inputs"].append(entry)
            entry["quantity"] += item.figures.activity_total
            entry["documents"].extend({"document_id": r["document_id"], "record": r.get("record"),
                                       "service_type": r.get("service_type"), "quantity": r["counted_quantity"],
                                       "unit": r["unit"]} for r in item.line["step1"]["rows"])
        before = float(item.line["results"]["mass_t"].get(gas, 0.0))
        delta = item.figures.mass_t[gas] - before
        old = line.mass_t.get(gas, 0.0)
        line.mass_t[gas] = old + delta
        line.steps.extend(_decided_inputs(item))
        line.steps.append(calc.Step(f"{gas} after {STEP.lower()}", "calculated + (decided - calculated) per line",
                                    {"calculated": {"value": old, "unit": "t", "source": None},
                                     str(item.line["key"]): {"value": delta, "unit": "t", "source": STEP}},
                                    line.mass_t[gas], "t"))
        value = float(gwp[gas]["value"])
        line.steps.append(calc.Step(f"{gas} in CO2e", "mass x GWP", {  # the last step: the refrigerant's CO2e
            "mass": {"value": line.mass_t[gas], "unit": "t", "source": None},
            "GWP": {"value": value, "unit": "", "source": gwp[gas]["source"]}}, line.mass_t[gas] * value, "t CO2e"))
        line.flags = sorted(({*line.flags, FLAG} - {NEGATIVE}) | ({NEGATIVE} if line.mass_t[gas] < 0 else set()))
    ordered = list(new_lines.values())
    totals = {line.key: line.mass_t[line.key] for line in ordered}
    co2e = {line.key: line.steps[-1].result for line in ordered}
    total = sum(co2e.values())
    summary = calc.Step("Total refrigerant emissions in CO2e", "sum of each refrigerant's emissions in CO2e",
                        {k: {"value": v, "unit": "t CO2e", "source": None} for k, v in co2e.items()}, total, "t CO2e")
    flags = {*(category.flags if category else []), FLAG} - {NEGATIVE}
    flags |= {f for line in ordered for f in line.flags}
    gwp_set = category.gwp_set if category else str(usable[0].line["smb"]["gwp_set"])
    categories[FUGITIVE] = calc.CategoryResult(FUGITIVE, ordered, totals, co2e, total, gwp, 0.0, [summary],
                                               sorted(flags), details, gwp_set)
    for item in usable:
        item.write(tolerance)
    return usable


# --- purchased steam (C9) ---------------------------------------------------------------------------------------------
STEAM_LOCATION, STEAM_MARKET = "purchased_steam_location_based", "purchased_steam_market_based"
STEAM_MARKET_FLAG = "no_supplier_factor_market_equals_location"


def _apply_steam(categories: dict[str, calc.CategoryResult | None], mine: list[DecidedLine],
                 every: list[dict[str, Any]], ref: EmissionFactorReference, tolerance: float) -> list[DecidedLine]:
    """Location- and market-based purchased steam moved by their lines' decisions: each facility's category line takes
    its decided lines' change of mass, gas by gas; a facility the category did not count is added from its lines."""

    location = categories.get(STEAM_LOCATION)
    if not adds_up(line_sums(every, "steam"), location):
        for item in mine:
            _refuse(item, "category_does_not_add_up", "Not applied: this category's lines do not add up to its "
                    "total, so a change on one line cannot be counted. Check the lines marked as not calculated.")
        return []
    gwp_set = location.gwp_set if location is not None else str(mine[0].line["steam"]["gwp_set"])
    empty = calc.purchased_thermal(STEAM_LOCATION, [], ref, gwp_set=gwp_set)
    base = location if location is not None else empty
    new_lines = [copy.deepcopy(line) for line in base.lines]
    usable: list[DecidedLine] = []
    for item in mine:
        found = [line for line in new_lines if line.key == item.sub[0]]
        if len(found) > 1:
            _refuse(item, "no_category_line", "Not applied: the category has no single entry for this line's facility.")
            continue
        if not found:  # steam by weight the category could not count: from the line's decided enthalpy
            found = [calc.LineResult(item.sub[0], {gas: "Emissions = MMBtu x EF" for gas in calc.GASES},
                                     dict.fromkeys(calc.GASES, 0.0), steps=[])]
            new_lines.append(found[0])
        _shift(found[0], item)
        usable.append(item)
    if not usable:
        return []
    categories[STEAM_LOCATION] = _retotal_steam(base, new_lines, ref, location is None)
    market = categories.get(STEAM_MARKET)
    market_base = market if market is not None else calc.purchased_thermal(
        STEAM_MARKET, [], ref, gwp_set=gwp_set, flags=[STEAM_MARKET_FLAG])
    categories[STEAM_MARKET] = _retotal_steam(market_base, [copy.deepcopy(line) for line in new_lines], ref,
                                              market is None)
    for item in usable:
        item.write(tolerance)
    return usable


def _retotal_steam(base: calc.CategoryResult, lines: list[calc.LineResult], ref: EmissionFactorReference,
                   new: bool) -> calc.CategoryResult:
    result = calc.retotal(base, lines, ref, [FLAG])
    if new:  # the Working sheet lists what the lines counted
        result.details = {**result.details, "inputs": []}
    result.flags = sorted(set(result.flags))
    return result
