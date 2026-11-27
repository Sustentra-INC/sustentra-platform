"""Builds a ``LineTrace`` from a recalculation line (the dict ``recalculation_lines`` assembled).

The line already holds what the calculators produced: Step 1 rows, Step 2's conversion, and per gas
the activity, factor, unit conversion, mass, GWP and CO2e. This module restates those as operations the
evaluator re-runs, then checks each against the calculator's own number to 1e-9. Nothing is written back:
a trace that disagrees with the line is dropped (``None``), the line and every total stay as they were.
"""

from __future__ import annotations

import re
from typing import Any

from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace.model import (
    Blocking, Choice, Column, InputRow, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock,
    TraceInput, TraceResult, TraceStep,
)

GAS_LABEL = {"CO2": "CO₂", "CH4": "CH₄", "N2O": "N₂O"}
GASES = ("CO2", "CH4", "N2O")
_UNIT_ALIASES = {"vehicle-mile": "mi", "mile": "mi", "gallon": "gal", "mmBtu": "MMBtu"}
_SOURCE = re.compile(r"^(?P<dataset>.*?)(?:,\s*(?P<table>Table\s+\d+))?(?:,\s*row\s+(?P<row>\d+))?(?:\s*\((?P<note>[^)]*)\))?$")
_YEAR = re.compile(r"\b(20\d\d)\b")


def normalise_unit(text: str) -> str:
    """``"kg CO2 per MMBtu"`` -> ``"kg/MMBtu"``; ``"g CH4 per vehicle-mile"`` -> ``"g/mi"``; ``"gal"`` -> ``"gal"``."""

    text = text.strip()
    if " per " in text:
        top, bottom = text.split(" per ", 1)
        return f"{top.split()[0]}/{_UNIT_ALIASES.get(bottom.strip(), bottom.strip())}"
    return _UNIT_ALIASES.get(text, text)


def reference_source(text: str | None) -> SourceRef | None:
    if not text:
        return None
    found = _SOURCE.match(text)
    year = _YEAR.search(text)
    return SourceRef(kind="reference", dataset=(found.group("dataset") if found else text) or text,
                     table=found.group("table") if found else None,
                     row=int(found.group("row")) if found and found.group("row") else None,
                     edition=year.group(1) if year else None, citation=text)


def _operand(column: str, value: float | str | None, unit: str | None, **kw: Any) -> Operand:
    return Operand(column=column, value=value, unit=unit, **kw)


def _groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Step 3 rows come in runs of one gas each per calculator run; a gas seen twice starts the next run."""

    out: list[list[dict[str, Any]]] = []
    for row in rows:
        if not out or any(r["gas"] == row["gas"] for r in out[-1]):
            out.append([])
        out[-1].append(row)
    return out


def _columns() -> dict[str, list[Column]]:
    return {
        "emissions": [Column("activity", "Activity"), Column("ef", "Emission factor"),
                      Column("conversion", "To metric tons"), Column("mass", "Mass", "t", True, {"sig": 6})],
        "gwp": [Column("mass", "Mass", "t"), Column("gwp", "GWP", "t CO2e/t"),
                Column("co2e", "CO₂e", "t CO2e", True, {"dp": 2})],
    }


def _gas_operations(row: dict[str, Any], *, driver: dict[str, str | None], ef_id: str, gwp_id: str,
                    ) -> tuple[Operation, Operation | None]:
    """(activity x factor x conversion = mass, mass x GWP = CO2e) of one gas row. The second is None for a
    biogenic CO2 row: its CO2 is reported apart and counts 0 toward CO2e."""

    unit = normalise_unit(str(row["ef"]["unit"]))
    mass_unit = unit.split("/")[0]
    activity = row["activity"]
    emissions = ops.make_operation([
        Term(None, _operand("activity", float(activity["value"]), normalise_unit(str(activity["unit"])), **driver)),
        Term("×", _operand("ef", float(row["ef"]["value"]), unit, input_id=ef_id)),
        Term("×", _operand("conversion", float(row["unit_conversion"]), f"t/{mass_unit}")),
    ], "mass", "t")
    ops.verify(emissions, float(row["mass_t"]))
    if row.get("biogenic"):
        return emissions, None
    co2e = ops.make_operation([
        Term(None, _operand("mass", emissions.result.value, "t", step_ref="emissions")),
        Term("×", _operand("gwp", float(row["gwp"]["value"]), "t CO2e/t", input_id=gwp_id)),
    ], "co2e", "t CO2e")
    ops.verify(co2e, float(row["co2e_t"]))
    return emissions, co2e


def build(family: str, line: dict[str, Any], *, choices: list[Choice], context: dict[str, Any] | None = None
          ) -> LineTrace | None:
    """The trace of one recalculation line, or None when the line holds nothing to trace or the trace's own
    arithmetic does not reproduce the calculator's numbers (it is then left off, never repaired)."""

    context = context or {}
    key = line.get("key")
    rows = line["step3"]["gases"]
    flags = list(line.get("flags", []))
    result = line["results"]
    if not key:
        return None
    if not rows:
        return LineTrace(
            line_key=key, panel=family, state="blocked",
            result=TraceResult("t CO2e", None, None, None), choices=choices, flags=flags,
            blocking=[Blocking("activity.total", "No accepted activity data and no company figure to calculate from.")])
    try:
        return _build(family, line, rows, flags, result, choices, context)
    except (ops.TraceError, KeyError, TypeError, ValueError):
        return None


def _build(family: str, line: dict[str, Any], rows: list[dict[str, Any]], flags: list[str],
           result: dict[str, Any], choices: list[Choice], context: dict[str, Any]) -> LineTrace:
    step1, step2 = line["step1"], line["step2"]
    company = line.get("company")
    company_rows = company["step3"]["gases"] if company else None
    runs = _groups(rows)
    company_runs = _groups(company_rows) if company_rows else None
    inputs: dict[str, TraceInput] = {}

    def suffix(i: int) -> str:
        return "" if i == 0 else f"#{i + 1}"

    # --- Step 1: the activity data, summed over the evidence ------------------------------------------
    total, total_unit = step1["total"]["quantity"], normalise_unit(step1["total"]["unit"])
    parts = [r for r in step1["rows"] if r.get("counted_in_base") is not None]
    input_rows = [InputRow(
        id=f"{r['document_id']}/{r['candidate_id'] or i}", label=r.get("file_name") or r["document_id"],
        recomputed=Side(r["counted_in_base"], total_unit,
                        "edited" if r.get("review") in ("edited", "corrected") else "accepted",
                        SourceRef("document", document_id=r["document_id"], candidate_id=r.get("candidate_id"),
                                  file_name=r.get("file_name")))) for i, r in enumerate(parts)]
    given = company["activity"] if company else None
    inputs["activity.total"] = TraceInput(
        "activity.total", "Activity data", "evidence_sum", required_for=[c.chosen for c in choices[:1]],
        recomputed=Side(total, total_unit, "accepted" if parts else "awaiting_review",
                        SourceRef("derived", from_=[ir.id for ir in input_rows]) if input_rows else None),
        company=Side(float(given["quantity"]), normalise_unit(str(given["unit"])), "accepted") if given else None,
        rows=input_rows)
    if given and ops.same_unit(total_unit, normalise_unit(str(given["unit"]))):
        d = ops.difference(total, float(given["quantity"]), total_unit, normalise_unit(str(given["unit"])))
        inputs["activity.total"].difference, inputs["activity.total"].differs = d, ops.differs(d, total)
    step1_block = TraceBlock("activity", "Activity data", [Column("activity", "Activity", total_unit, True, {"dp": 2})],
                             recomputed=_sum_operation(parts, total_unit, total) if parts else None,
                             company=_entered(given) if given else None)

    # --- Step 2: conversion to the factor's unit -----------------------------------------------------
    to_unit = normalise_unit(step2["to_unit"])
    factor_unit = f"{to_unit}/{total_unit}"
    conversion = ops.make_operation([
        Term(None, _operand("activity", total, total_unit, input_id="activity.total", step_ref="activity")),
        Term("×", _operand("factor", float(step2["factor"]), factor_unit, input_id="unit_conversion")),
    ], "converted", to_unit)
    ops.verify(conversion, float(step2["result"]["quantity"]))
    inputs["unit_conversion"] = TraceInput(
        "unit_conversion", "Unit conversion", "constant",
        recomputed=Side(float(step2["factor"]), factor_unit, "reference", reference_source(step2.get("source"))))
    company_conversion = None
    if company and given:
        cs2 = company["step2"]
        c_from, c_to = normalise_unit(cs2["from_unit"]), normalise_unit(cs2["to_unit"])
        company_conversion = ops.make_operation([
            Term(None, _operand("activity", float(given["quantity"]), c_from, input_id="activity.total",
                                step_ref="activity")),
            Term("×", _operand("factor", float(cs2["factor"]), f"{c_to}/{c_from}", input_id="unit_conversion")),
        ], "converted", c_to)
        ops.verify(company_conversion, float(cs2["result"]["quantity"]))
        _annotate(conversion, company_conversion)
    step2_block = TraceBlock("conversion", "Conversion", [
        Column("activity", "Activity", total_unit), Column("factor", "Factor", factor_unit),
        Column("converted", "Converted", to_unit, True, {"dp": 2})], recomputed=conversion, company=company_conversion)
    distance = step2.get("distance")
    if distance:
        inputs["distance"] = TraceInput(
            "distance", "Distance driven", "reviewer_entered", required_for=["eq4_distance"],
            recomputed=Side(float(distance["quantity"]), normalise_unit(distance["unit"]), "accepted",
                            SourceRef("derived", from_=[str(distance.get("source"))])))

    # --- Steps 3 and 4: the factor applied per gas, then the GWP ---------------------------------------
    emission_blocks: list[TraceBlock] = []
    gwp_blocks: list[TraceBlock] = []
    co2e_terms: list[Term] = []
    co2e_company_terms: list[Term] = []
    for i, run in enumerate(runs):
        c_run = company_runs[i] if company_runs and i < len(company_runs) else None
        for row in run:
            gas = row["gas"]
            sfx = suffix(i)
            ef_id, gwp_id = f"ef.{gas}{sfx}", f"gwp.{gas}{sfx}"
            by_distance = bool(distance) and normalise_unit(row["activity"]["unit"]) == "mi"
            driver: dict[str, str | None] = (
                {"input_id": "distance"} if by_distance else {"step_ref": "conversion"} if i == 0 else {})
            inputs[ef_id] = TraceInput(
                ef_id, f"{GAS_LABEL[gas]} emission factor", "reference", symbol=f"EF {gas}",
                recomputed=Side(float(row["ef"]["value"]), normalise_unit(str(row["ef"]["unit"])), "reference",
                                reference_source(row["ef"].get("source"))))
            inputs[gwp_id] = TraceInput(
                gwp_id, f"{GAS_LABEL[gas]} global warming potential", "reference", symbol=f"GWP {gas}",
                recomputed=Side(float(row["gwp"]["value"]), "t CO2e/t", "reference",
                                reference_source(row["gwp"].get("source"))))
            mine = _gas_operations(row, driver=driver, ef_id=ef_id, gwp_id=gwp_id)
            c_row = next((r for r in c_run or [] if r["gas"] == gas), None)
            theirs = _gas_operations(c_row, driver=driver, ef_id=ef_id, gwp_id=gwp_id) \
                if c_row else (None, None)
            for a, b in zip(mine, theirs, strict=True):
                if a and b:
                    _annotate(a, b)
            label = GAS_LABEL[gas] + (f" ({i + 1})" if i else "")
            equation = line["method"]["equations"].get(gas)
            cols = _columns()
            emission_blocks.append(TraceBlock(f"emissions.{gas}{sfx}", label, cols["emissions"], recomputed=mine[0],
                                              company=theirs[0], choice_id=f"equation:{gas}" if equation else None))
            if mine[1]:
                gwp_blocks.append(TraceBlock(f"gwp.{gas}{sfx}", label, cols["gwp"], recomputed=mine[1],
                                             company=theirs[1]))
                co2e_terms.append(Term("+" if co2e_terms else None, _operand(
                    "co2e", mine[1].result.value, "t CO2e", step_ref=f"gwp.{gas}{sfx}")))
            else:  # biogenic CO2: shown, counted as 0
                co2e_terms.append(Term("+" if co2e_terms else None, _operand("co2e", 0.0, "t CO2e")))
            if theirs[1]:
                co2e_company_terms.append(Term("+" if co2e_company_terms else None, _operand(
                    "co2e", theirs[1].result.value, "t CO2e", step_ref=f"gwp.{gas}{sfx}")))
            elif c_row is not None and c_row.get("biogenic"):
                co2e_company_terms.append(Term("+" if co2e_company_terms else None, _operand("co2e", 0.0, "t CO2e")))

    # --- Results: the gases added, then the consolidated share ----------------------------------------------
    share = float(line.get("consolidated_share_pct", 100.0))
    inputs["share"] = TraceInput(
        "share", "Consolidated share", "methodology", symbol="share",
        recomputed=Side(share, "%", "accepted" if share != 100.0 else "derived",
                        SourceRef("methodology", field="consolidated_share", label="Consolidated share")))

    def totals(terms: list[Term], share_value: float) -> tuple[Operation, Operation]:
        added = ops.make_operation(terms, "sum", "t CO2e")
        scaled = ops.make_operation([
            Term(None, _operand("sum", added.result.value, "t CO2e", step_ref="sum")),
            Term("×", _operand("share", share_value / 100.0, None, input_id="share"))], "total", "t CO2e")
        return added, scaled

    mine_sum, mine_total = totals(co2e_terms, share)
    ops.verify(mine_sum, float(result["sum_co2e_t"]))
    ops.verify(mine_total, float(result["total_co2e_t"]))
    their_sum = their_total = None
    if company and co2e_company_terms:
        their_sum, their_total = totals(co2e_company_terms, share)
        ops.verify(their_sum, float(company["results"]["sum_co2e_t"]))
        ops.verify(their_total, float(company["results"]["total_co2e_t"]))
        _annotate(mine_sum, their_sum)
        _annotate(mine_total, their_total)
    results_step = TraceStep("results", None, "Results", [
        TraceBlock("results.sum", "Gases added", [Column("co2e", "CO₂e", "t CO2e"), Column("sum", "Sum", "t CO2e", True)],
                   recomputed=mine_sum, company=their_sum),
        TraceBlock("results.total", "Line total", [Column("sum", "Sum", "t CO2e"), Column("share", "Share"),
                                                   Column("total", "Total", "t CO2e", True, {"dp": 2})],
                   recomputed=mine_total, company=their_total)])
    steps = [
        TraceStep("activity", 1, "Step 1 · Activity data", [step1_block], note="The reviewed evidence, summed"),
        TraceStep("conversion", 2, "Step 2 · Conversion", [step2_block], note="To the unit the emission factor is in"),
        TraceStep("emissions", 3, "Step 3 · Emissions per gas", emission_blocks,
                  note="Activity × emission factor × unit conversion"),
        TraceStep("gwp", 4, "Step 4 · CO₂e", gwp_blocks, note="Mass × global warming potential"),
        results_step]
    recomputed_total = float(result["total_co2e_t"])
    company_total = float(company["results"]["total_co2e_t"]) if company else None
    diff = ops.difference(recomputed_total, company_total, "t CO2e", "t CO2e")
    state = "partial" if "calculation_failed" in flags else "complete"
    inputs.update(context.get("inputs", {}))
    return LineTrace(
        line_key=line["key"], panel=family, state=state, choices=choices, inputs=inputs, steps=steps,
        result=TraceResult("t CO2e", company_total, recomputed_total, diff), flags=flags)


def _sum_operation(parts: list[dict[str, Any]], unit: str, total: float) -> Operation:
    terms = [Term(None if i == 0 else "+", _operand("activity", float(r["counted_in_base"]), unit,
                                                    input_id="activity.total")) for i, r in enumerate(parts)]
    op = ops.make_operation(terms, "activity", unit, input_id="activity.total")
    ops.verify(op, float(total))
    return op


def _entered(given: dict[str, Any]) -> Operation:
    unit = normalise_unit(str(given["unit"]))
    value = float(given["quantity"])
    return Operation([Term(None, _operand("activity", value, unit, input_id="activity.total"))],
                     _operand("activity", value, unit, input_id="activity.total"))


def _annotate(mine: Operation, theirs: Operation) -> None:
    """Put ``recomputed − company`` and ``differs`` on each recomputed operand that has a company twin of
    the same unit and column. A pair in different units is left without a difference.

    Twins are found by position when the two operations have the same shape (a sum of three CO2e terms
    has the same column three times, so the column alone cannot say which is which); otherwise by column,
    and a column that repeats on either side is left without a difference rather than paired wrongly."""

    pairs: list[tuple[Operand, Operand | None]] = []
    same_shape = len(mine.terms) == len(theirs.terms) and all(
        a.operand.column == b.operand.column for a, b in zip(mine.terms, theirs.terms))
    if same_shape:
        pairs = [(a.operand, b.operand) for a, b in zip(mine.terms, theirs.terms)]
    else:
        def unique(op: Operation, column: str) -> Operand | None:
            found = [t.operand for t in op.terms if t.operand.column == column]
            return found[0] if len(found) == 1 else None
        pairs = [(t.operand, unique(theirs, t.operand.column)) for t in mine.terms
                 if unique(mine, t.operand.column) is not None]
    pairs.append((mine.result, theirs.result if theirs.result.column == mine.result.column else None))
    for operand, twin in pairs:
        if twin is None or not isinstance(operand.value, (int, float)) or not isinstance(twin.value, (int, float)):
            continue
        if not ops.same_unit(operand.unit, twin.unit):
            continue
        d = ops.difference(float(operand.value), float(twin.value), operand.unit, twin.unit)
        operand.difference, operand.differs = d, ops.differs(d, float(operand.value))
