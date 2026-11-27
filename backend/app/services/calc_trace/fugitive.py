"""Fugitive refrigerants and fire suppression, by the simplified material balance (SMB): one line per refrigerant and
facility (boards 01 to 03).

    Emitted = (P_N − C_N) + P_S + (C_D − R_D)        P_N  charged into new equipment     C_N  full charge of the new equipment
    t       = Emitted × t per lb (or per kg)         P_S  added when servicing            C_D  full charge of retired equipment
    t CO2e  = t × GWP                                R_D  recovered from retired equipment

Step 1 lists each term with the service records it adds up (one row per record), Step 2 is the balance and the
conversion to metric tons, Step 3 the GWP. The lb to metric ton factor is the one the fugitive category has always used
(``fuel_units``: 0.45359237 kg per lb, exact), so a line and its category agree to the last digit.

The GWP (rulings for C4, Q1):

* A refrigerant the category counted uses the category's GWP: EPA Hub Table 12 for a blend (R-404A 3,943), Table 11 for
  a single gas, or the GWP entered for the engagement under Recalculation inputs. That is the value that counts.
* A blend's split into its components (Table 12's composition, each component's Table 11 GWP) is shown beside it for
  reference: 44% × 3,170 + 52% × 4,800 + 4% × 1,300 = 3,942.8 for R-404A. The step's note says which value counts.
* A blend Table 12 does not list but whose composition is known (``refrigerant_blends_not_in_hub.json``, R-448A) is
  worked from its components. A component Table 11 lacks (an HFO) needs a GWP a reviewer enters for the line, with its
  source (``component_gwp.<name>``). Until every one is entered the line is blocked ("Awaiting review: component
  GWPs"); then the blend's GWP is Σ share × GWP and the line counts (``line_totals``).
* Any other refrigerant without a GWP stays blocked until one is entered for the engagement (as before).

A negative balance is kept as it is and flagged (Q3): check the service records.

Decisions (``calc_trace/decisions``): a term (or one record of it) and a component GWP Table 11 lacks can be decided for
the line; the composition, the blend's GWP, the conversion and the consolidated share cannot (set for the whole
engagement or by the reference data). ``rework`` builds the trace again with the decided values in and returns the
line's decided figures.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace._line import _annotate, reference_source
from backend.app.services.calc_trace.model import (
    Blocking, Choice, ChoiceOption, Column, InputRow, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock,
    TraceInput, TraceResult, TraceStep,
)

TERMS = ("P_N", "C_N", "P_S", "C_D", "R_D")
TERM_LABEL = {"P_N": "New equipment charge", "C_N": "New equipment capacity", "P_S": "Added during service",
              "C_D": "Retired equipment capacity", "R_D": "Recovered from retired equipment"}
_TERM_OP = {"P_N": None, "C_N": "−", "P_S": "+", "C_D": "+", "R_D": "−"}
# The record field each term is read from (the row's evidence).
_TERM_FIELD = {"P_N": "refrigerant_added", "C_N": "equipment_capacity", "P_S": "refrigerant_added",
               "C_D": "equipment_capacity", "R_D": "refrigerant_recovered"}
METHOD = "smb"
EQUATION = "Emitted = (P_N − C_N) + P_S + (C_D − R_D)"
ROUTE = "Simplified material balance: (P_N − C_N) + P_S + (C_D − R_D), to metric tons, × GWP"
NOT_YET = "Sustentra cannot calculate this method yet."
COMPONENT_GWP = "component_gwp."
GWP_UNIT = "t CO2e/t"
UNIT_SOURCE = "fuel_units conversion table"
NEGATIVE_FLAG = "negative_refrigerant_emissions"
NO_GWP_FLAG = "refrigerant_gwp_needed"
COMPONENTS_FLAG = "awaiting_component_gwps"
MIXED_FLAG = "mixed_refrigerants"


def zero_allowed(input_id: str) -> bool:
    """A balance term (or one record of it) may be decided as 0: no new equipment, nothing recovered. A GWP may not."""

    return input_id.split("/", 1)[0] in TERMS
DECIDED = ("accepted", "edited")
NOT_IN_HUB = Path(__file__).resolve().parents[4] / "reference-data" / "emission-factors" / \
    "refrigerant_blends_not_in_hub.json"
_PART = re.compile(r"\s*([\d.]+)\s*%\s*(.+?)\s*$")


# --- reference data --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Component:
    name: str
    share: float  # mass fraction, 0.44
    pct: float  # 44.0


@dataclass(frozen=True)
class Blend:
    components: tuple[Component, ...]
    source: SourceRef
    in_hub: bool


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def parse_composition(text: str) -> tuple[Component, ...]:
    """``"44% HFC-125 , 4% HFC-134a , 52% HFC-143a"`` -> its components, or () when a part cannot be read or the parts do
    not add up to 100%."""

    parts: list[Component] = []
    for part in str(text).split(","):
        found = _PART.match(part)
        if found is None:
            return ()
        pct = float(found.group(1))
        parts.append(Component(found.group(2), pct / 100.0, pct))
    return tuple(parts) if parts and math.isclose(sum(c.pct for c in parts), 100.0, abs_tol=1e-6) else ()


@lru_cache(maxsize=1)
def _not_in_hub() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(NOT_IN_HUB.read_text(encoding="utf-8"))
    return data


def blend_of(gas: str, ref: EmissionFactorReference) -> Blend | None:
    """The blend's composition: EPA Hub Table 12, else ASHRAE's designation for a blend the Hub lacks; None for a single
    gas or a blend whose make-up is not known."""

    key = _norm(gas)
    for row in ref.data.get("gwp_refrigerant_blends") or []:
        if _norm(row["ashrae"]) == key:
            parts = parse_composition(row["composition"])
            source = SourceRef("reference", dataset=ref.dataset, table=str(row["source"]["table"]),
                               row=int(row["source"]["row"]), edition="2025",
                               citation=f"{ref.dataset}, {row['source']['table']}, row {row['source']['row']}: "
                                        f"{row['composition']}")
            return Blend(parts, source, True) if parts else None
    other = _not_in_hub()
    for row in other["blends"]:
        if _norm(row["ashrae"]) == key:
            parts = parse_composition(row["composition"])
            source = SourceRef("reference", dataset=str(other["dataset"]),
                               citation=f"{other['dataset']}: {row['ashrae']} {row['designation']}")
            return Blend(parts, source, False) if parts else None
    return None


def _component_gwp(name: str, ref: EmissionFactorReference | None, gwp_set: str) -> tuple[float, SourceRef] | None:
    if ref is None:
        return None
    try:
        factor = ref.gwp(name, gwp_set)
    except LookupError:
        return None
    source = reference_source(factor.source)
    assert source is not None
    return float(factor.value), source


def company_terms_of(records: Mapping[str, Mapping[str, Any]] | None) -> dict[str, float]:
    """The company's own terms a reviewer entered or accepted (``input|P_S|company``): shown, never an operand."""

    out: dict[str, float] = {}
    for term in TERMS:
        record = (records or {}).get(f"input|{term}|company")
        decision = record.get("decision") if isinstance(record, Mapping) else None
        if not isinstance(decision, Mapping) or decision.get("status") not in DECIDED:
            continue
        value = decision.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(float(value)) and 0 <= float(value) <= 1e15:
            out[term] = float(value)
    return out


# --- the line (``recalculation_lines``) ------------------------------------------------------------------------------
def _kind(terms: Mapping[str, float]) -> str:
    if "P_N" in terms or "C_N" in terms:
        return "installation"
    if "C_D" in terms or "R_D" in terms:
        return "disposal"
    return "service"


def mixed_parts(by_gas: Mapping[str, list[Any]], *, own: str, gwps: Mapping[str, Mapping[str, Any] | None],
                gwp_set: str, share_pct: float, iso: Callable[[Any], str | None]) -> dict[str, Any]:
    """A line holding records of more than one refrigerant: it is blocked (never one balance under one GWP). Its results
    still hold each refrigerant's mass and CO2e on its own GWP, exactly what the category counts of them, so the lines
    keep adding up to the category; the line has no total of its own to compare (``MIXED_FLAG``)."""

    gases = sorted(by_gas, key=lambda g: (g != own, g))
    parts = {g: line_parts(by_gas[g], gas=g, gwp=gwps.get(g), gwp_set=gwp_set, share_pct=share_pct, iso=iso)
             for g in gases}
    rows = [{**r, "gas": g} for g in gases for r in parts[g]["step1"]["rows"]]
    mass = {k: v for p in parts.values() for k, v in p["results"]["mass_t"].items()}
    co2e = {k: v for p in parts.values() for k, v in p["results"]["gas_co2e_t"].items()}
    first = parts[gases[0]]
    flags = sorted({MIXED_FLAG, *(f for p in parts.values() for f in p["flags"])})
    return {
        "method": {"route": ROUTE, "equations": {}},
        "step1": {"rows": rows, "total": {"quantity": 0.0, "unit": first["smb"]["unit"]}},
        "step2": {**first["step2"], "result": {"quantity": 0.0, "unit": "t"}},
        "step3": {"gases": []},
        "results": {"mass_t": mass, "gas_co2e_t": co2e, "sum_co2e_t": sum(co2e.values()),
                    "total_co2e_t": sum(co2e.values()) * share_pct / 100, "biogenic_co2_t": 0.0},
        "smb": {"gas": own, "gases": gases, "mixed": True, "unit": first["smb"]["unit"],
                "terms": dict.fromkeys(TERMS, 0.0), "emitted": 0.0, "factor": first["smb"]["factor"],
                "emitted_t": 0.0, "gwp": None, "gwp_set": gwp_set},
        "flags": flags,
    }


def mixed_message(smb: Mapping[str, Any]) -> str:
    gases = [str(g) for g in smb.get("gases") or []]
    others = [g for g in gases if g != smb.get("gas")] or gases[1:]
    return (f"This line mixes refrigerants ({', '.join(gases)}): move the {', '.join(others)} records to their own "
            "line.")


def line_parts(contribs: list[Any], *, gas: str, gwp: Mapping[str, Any] | None, gwp_set: str, share_pct: float,
               iso: Callable[[Any], str | None], awaiting: str | None = None) -> dict[str, Any]:
    """The line's Steps 1 to 3 and results from its records (``Contribution`` with ``terms``), all in the unit the
    category holds the refrigerant in. ``gwp`` is the category's ({value, source}), or None when the category did not
    count the refrigerant (no GWP): the line then counts nothing (its results hold no mass), and ``awaiting`` says
    what it waits for ("component GWPs" or "a GWP")."""

    unit = contribs[0].unit if contribs else "lb"
    totals = dict.fromkeys(TERMS, 0.0)
    rows: list[dict[str, Any]] = []
    for c in sorted(contribs, key=lambda c: (iso(c.start) or "9999", c.record.file_name or "")):
        own = {k: (float(v) if c.unit == unit else fuel_units.convert_exact(float(v), c.unit, unit))
               for k, v in (c.terms or {}).items() if k in TERMS}
        for k, v in own.items():
            totals[k] += v
        fields = c.record.fields
        kind = _kind(own)
        main = fields.get("refrigerant_recovered" if kind == "disposal" else "refrigerant_added")
        rows.append({
            "period_start": iso(c.start), "period_end": iso(c.end or c.start), "document_id": c.record.document_id,
            "evidence_code": None, "file_name": c.record.file_name, "record": c.record.label,
            "candidate_id": getattr(main, "candidate_id", None),
            "review": getattr(main, "status", None), "quantity": c.quantity, "unit": unit, "share_in_period": 1.0,
            "counted_quantity": c.counted, "counted_in_base": c.counted, "service_type": kind, "terms": own,
            "candidates": {k: getattr(fields.get(_TERM_FIELD[k]), "candidate_id", None) for k in own}})
    emitted = totals["P_N"] - totals["C_N"] + totals["P_S"] + totals["C_D"] - totals["R_D"]
    factor = fuel_units.convert_exact(1, unit, "metric_ton")
    emitted_t = fuel_units.convert_exact(emitted, unit, "metric_ton")
    counted = gwp is not None
    co2e = emitted_t * float(gwp["value"]) if gwp is not None else 0.0
    flags = ([NEGATIVE_FLAG] if emitted < 0 else []) + ([] if counted else [NO_GWP_FLAG])
    return {
        "method": {"route": ROUTE, "equations": {}},
        "step1": {"rows": rows, "total": {"quantity": emitted, "unit": unit}},
        "step2": {"from_unit": unit, "to_unit": "t", "factor": factor, "source": UNIT_SOURCE,
                  "result": {"quantity": emitted_t, "unit": "t"}, "distance": None, "implied_fuel_economy": None},
        "step3": {"gases": []},
        "results": {"mass_t": {gas: emitted_t} if counted else {}, "gas_co2e_t": {gas: co2e} if counted else {},
                    "sum_co2e_t": co2e, "total_co2e_t": co2e * share_pct / 100, "biogenic_co2_t": 0.0},
        "smb": {"gas": gas, "unit": unit, "terms": totals, "emitted": emitted, "factor": factor, "emitted_t": emitted_t,
                "gwp": {"value": float(gwp["value"]), "source": gwp.get("source")} if gwp is not None else None,
                "gwp_set": gwp_set, **({"awaiting": awaiting or "a GWP"} if gwp is None else {})},
        "flags": flags,
    }


def company_parts(given: Mapping[str, Any], line: Mapping[str, Any]) -> dict[str, Any] | str:
    """The company's side from its emitted mass (``reported_activity`` of the line: 129 lb): to metric tons, × the line's
    GWP (ours, as on every panel until the company's own is read). A message when it cannot be read as a mass."""

    entered = str(given.get("unit", "")).strip()
    unit = fuel_units.canonical_unit(entered) or fuel_units.find_unit(entered)
    try:
        quantity = float(given["quantity"])
        if unit is None or fuel_units.dimension_of(unit) != fuel_units.MASS or not math.isfinite(quantity):
            raise fuel_units.UnitError(entered)
        factor = fuel_units.convert_exact(1, unit, "metric_ton")
        tonnes = fuel_units.convert_exact(quantity, unit, "metric_ton")
    except (fuel_units.UnitError, KeyError, TypeError, ValueError):
        return (f"'{entered}' is not a mass. Enter the refrigerant the company says was emitted in lb or kg.")
    smb = line["smb"]
    gwp = smb["gwp"]
    co2e = tonnes * float(gwp["value"]) if gwp is not None else None
    share = float(line["consolidated_share_pct"])
    return {
        "activity": {"quantity": quantity, "unit": entered},
        "step2": {"from_unit": entered, "to_unit": "t", "factor": factor, "source": UNIT_SOURCE, "distance": None,
                  "implied_fuel_economy": None, "result": {"quantity": tonnes, "unit": "t"}},
        "step3": {"gases": []},
        "results": {"mass_t": {smb["gas"]: tonnes}, "gas_co2e_t": {smb["gas"]: co2e} if co2e is not None else {},
                    "sum_co2e_t": co2e if co2e is not None else 0.0,
                    "total_co2e_t": co2e * share / 100 if co2e is not None else 0.0, "biogenic_co2_t": 0.0},
        "counted": co2e is not None,
    }


# --- the trace -------------------------------------------------------------------------------------------------------
Decided = Mapping[str, tuple[float, Side]]  # input id (or "<term>/<row id>") -> the decided value and its side


def _single(column: str, value: float | None, unit: str | None, **kw: Any) -> Operation:
    return Operation([Term(None, Operand(column, value, unit, **kw))], Operand(column, value, unit, **kw))


def _open(terms: list[Term], column: str, unit: str | None) -> Operation:
    """An operation that cannot be worked yet (an operand awaits review): its result is shown as awaiting."""

    return Operation(terms, Operand(column, None, unit))


def _choice() -> Choice:
    return Choice("method", "Calculation method", [
        ChoiceOption("screening", "Screening", available=False, why_unavailable=NOT_YET),
        ChoiceOption(METHOD, "Simplified material balance", equation=EQUATION, required_inputs=list(TERMS)),
        ChoiceOption("material_balance", "Material balance", available=False, why_unavailable=NOT_YET),
    ], chosen=METHOD)


def _g(value: float) -> str:
    return format(value, ",.6g")


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    """The line's working, checked against the line's own numbers; None when the line holds nothing to trace or the
    working does not reproduce them (never repaired)."""

    if not line.get("key") or not isinstance(line.get("smb"), Mapping):
        return None
    if line["smb"].get("mixed"):
        return _mixed_trace(line)
    try:
        return _build(line, context or {}, {})
    except (ops.TraceError, KeyError, TypeError, ValueError):
        return None


def rework(trace: LineTrace, line_context: tuple[dict[str, Any], dict[str, Any]], decided: Decided
           ) -> dict[str, float] | None:
    """The trace built again with the decided values (``trace`` is changed in place) and the line's decided figures
    ({emitted, emitted_t, gwp, co2e, total}), or None when the line still cannot be worked (a GWP is awaited)."""

    line, context = line_context
    again = _build(line, context, decided)
    for name in ("state", "blocking", "inputs", "steps", "result", "flags"):
        setattr(trace, name, getattr(again, name))
    if again.state == "blocked":
        return None
    blocks = {b.id: b for s in again.steps for b in s.blocks}

    def result(block_id: str) -> float:
        op = blocks[block_id].recomputed
        assert op is not None and isinstance(op.result.value, (int, float))
        return float(op.result.value)

    gwp = trace.inputs[f"gwp.{line['smb']['gas']}"].recomputed
    assert gwp is not None and isinstance(gwp.value, (int, float))
    return {"emitted": result("emitted"), "emitted_t": result("emitted_t"), "gwp": float(gwp.value),
            "co2e": result("co2e"), "total": result("results.total")}


def _build(line: dict[str, Any], context: dict[str, Any], decided: Decided) -> LineTrace:
    smb = line["smb"]
    gas, unit, gwp_set = str(smb["gas"]), str(smb["unit"]), str(smb["gwp_set"])
    ref: EmissionFactorReference | None = context.get("ref")
    company_terms: Mapping[str, float] = context.get("company_terms") or {}
    company = line.get("company")
    check = not decided  # the default working must reproduce the line's numbers
    inputs: dict[str, TraceInput] = {}

    # --- Step 1: each term, the records it adds up ---------------------------------------------------------------
    values: dict[str, float] = {}
    step1: list[TraceBlock] = []
    for term in TERMS:
        rows: list[InputRow] = []
        parts: list[float] = []
        seen: set[str] = set()
        for i, r in enumerate(line["step1"]["rows"]):
            if term not in (r.get("terms") or {}):
                continue
            cand = (r.get("candidates") or {}).get(term) or r.get("candidate_id") or str(i)
            row_id = f"{r['document_id']}/{cand}"
            if row_id in seen:
                row_id = f"{row_id}#{i}"
            seen.add(row_id)
            value = float(r["terms"][term])
            side = Side(value, unit, "edited" if r.get("review") in ("edited", "corrected") else "accepted",
                        SourceRef("document", document_id=r["document_id"], candidate_id=cand,
                                  file_name=r.get("file_name")))
            if f"{term}/{row_id}" in decided:
                value, side = decided[f"{term}/{row_id}"]
            label = " · ".join(str(x) for x in (r.get("file_name") or r["document_id"], r.get("period_start")) if x)
            rows.append(InputRow(row_id, label, recomputed=side))
            parts.append(value)
        if term in decided:
            total, total_side = decided[term]
            op = _single("amount", total, unit, input_id=term)
        elif parts:
            op = ops.make_operation([Term(None if i == 0 else "+", Operand("amount", v, unit, input_id=term))
                                     for i, v in enumerate(parts)], "amount", unit, input_id=term)
            total = float(op.result.value)  # type: ignore[arg-type]
            total_side = Side(total, unit, "accepted", SourceRef("derived", from_=[r.id for r in rows]))
        else:
            total = 0.0
            op = _single("amount", 0.0, unit, input_id=term)
            total_side = Side(0.0, unit, "derived", SourceRef("derived", from_=["no service record of this kind"]))
        if check:
            ops.verify(op, float(smb["terms"][term]))
        values[term] = total
        given = company_terms.get(term)
        theirs = _single("amount", given, unit, input_id=term) if given is not None else None
        item = TraceInput(term, TERM_LABEL[term], "evidence_sum", symbol=term, required_for=[METHOD],
                          recomputed=total_side, rows=rows,
                          company=Side(given, unit, "accepted") if given is not None else None)
        if given is not None:
            item.difference = total - given
            item.differs = ops.differs(item.difference, total)
            _annotate(op, theirs)  # type: ignore[arg-type]
        inputs[term] = item
        step1.append(TraceBlock(f"term.{term}", f"{TERM_LABEL[term]} · {term}",
                                [Column("amount", "Total", unit, True, {"sig": 6})],
                                recomputed=op, company=theirs))

    # --- Step 2: the balance, then metric tons --------------------------------------------------------------------
    columns = [Column(t, t, unit) for t in TERMS] + [Column("emitted", "Emitted", unit, True,
                                                                                {"sig": 6})]

    def balance(source: Mapping[str, float]) -> Operation:
        return ops.make_operation([Term(_TERM_OP[t], Operand(t, source[t], unit, step_ref=f"term.{t}"))
                                   for t in TERMS], "emitted", unit)

    emitted_op = balance(values)
    if check:
        ops.verify(emitted_op, float(smb["emitted"]))
    company_emitted = balance(company_terms) if all(t in company_terms for t in TERMS) else None
    if company_emitted is not None:
        _annotate(emitted_op, company_emitted)
    emitted = float(emitted_op.result.value)  # type: ignore[arg-type]
    factor = float(smb["factor"])
    inputs["unit_conversion"] = TraceInput(
        "unit_conversion", "Unit conversion", "constant",
        recomputed=Side(factor, f"t/{unit}", "reference", SourceRef(
            "reference", dataset=UNIT_SOURCE, citation=f"{UNIT_SOURCE}: 1 lb = 0.45359237 kg exactly; 1 t = 1,000 kg")))
    to_t = ops.make_operation([Term(None, Operand("emitted", emitted, unit, step_ref="emitted")),
                               Term("×", Operand("factor", factor, f"t/{unit}", input_id="unit_conversion"))],
                              "emitted_t", "t")
    if check:
        ops.verify(to_t, float(smb["emitted_t"]))
    emitted_t = float(to_t.result.value)  # type: ignore[arg-type]
    company_t: float | None = None
    company_to_t: Operation | None = None
    if company:
        given = company["activity"]
        c_unit, c_factor = str(given["unit"]), float(company["step2"]["factor"])
        company_to_t = ops.make_operation([
            Term(None, Operand("emitted", float(given["quantity"]), c_unit, step_ref="emitted")),
            Term("×", Operand("factor", c_factor, f"t/{c_unit}", input_id="unit_conversion"))], "emitted_t", "t")
        ops.verify(company_to_t, float(company["step2"]["result"]["quantity"]))
    elif company_emitted is not None:
        company_to_t = ops.make_operation([
            Term(None, Operand("emitted", float(company_emitted.result.value), unit,  # type: ignore[arg-type]
                               step_ref="emitted")),
            Term("×", Operand("factor", factor, f"t/{unit}", input_id="unit_conversion"))], "emitted_t", "t")
    if company_to_t is not None:
        company_t = float(company_to_t.result.value)  # type: ignore[arg-type]
        _annotate(to_t, company_to_t)
    step2 = [
        TraceBlock("emitted", "Refrigerant emitted", columns, recomputed=emitted_op, company=company_emitted),
        TraceBlock("emitted_t", "Unit conversion", [
            Column("emitted", "Emitted (as reported)" if company else "Emitted", unit), Column("factor", "Unit conversion"),
            Column("emitted_t", "Emitted", "t", True, {"sig": 6})], recomputed=to_t, company=company_to_t)]

    # --- Step 3: the GWP, and a blend's components ------------------------------------------------------------------
    blend = blend_of(gas, ref) if ref is not None else None
    if blend is not None and len(blend.components) < 2:
        blend = None
    parts_gwp: list[tuple[Component, float | None, str]] = []
    for c in blend.components if blend else ():
        hub = _component_gwp(c.name, ref, gwp_set)
        inputs[f"share.{c.name}"] = TraceInput(f"share.{c.name}", f"{c.name} share of {gas}", "reference",
                                               symbol="share", recomputed=Side(c.share, None, "reference",
                                                                               blend.source if blend else None))
        if hub is not None:
            input_id = f"gwp.{c.name}"
            inputs[input_id] = TraceInput(input_id, f"{c.name} GWP", "reference", symbol="GWP",
                                          recomputed=Side(hub[0], GWP_UNIT, "reference", hub[1]))
            parts_gwp.append((c, hub[0], input_id))
            continue
        input_id = f"{COMPONENT_GWP}{c.name}"
        entered: float | None = None
        side = Side(None, GWP_UNIT, "awaiting_review")
        if input_id in decided:
            entered, side = decided[input_id]
        inputs[input_id] = TraceInput(input_id, f"{c.name} GWP ({gwp_set}, 100-year)", "reviewer_entered", symbol="GWP",
                                      required_for=[METHOD], recomputed=side)
        parts_gwp.append((c, entered, input_id))
    missing = [c.name for c, v, _ in parts_gwp if v is None]
    effective = sum(c.share * v for c, v, _ in parts_gwp if v is not None) if blend and not missing else None

    counted = smb.get("gwp")
    gwp_id = f"gwp.{gas}"
    gwp_value: float | None
    if counted is not None:
        gwp_value = float(counted["value"])
        gwp_side = Side(gwp_value, GWP_UNIT, "reference", reference_source(str(counted.get("source") or "")))
    elif effective is not None and blend is not None:
        gwp_value = effective
        gwp_side = Side(effective, GWP_UNIT, "derived", SourceRef("derived", from_=[i for _, _, i in parts_gwp]))
    else:
        gwp_value, gwp_side = None, Side(None, GWP_UNIT, "awaiting_review")
    inputs[gwp_id] = TraceInput(gwp_id, f"{gas} GWP" + (" (blend)" if blend else ""), "reference", symbol="GWP",
                                required_for=[METHOD], recomputed=gwp_side)

    def gwp_terms(tonnes: float | None, gwp: float | None) -> list[Term]:
        return [Term(None, Operand("emitted_t", tonnes, "t", step_ref="emitted_t")),
                Term("×", Operand("gwp", gwp, GWP_UNIT, input_id=gwp_id))]

    gwp_columns = [Column("emitted_t", "Emitted", "t"), Column("gwp", "GWP", GWP_UNIT),
                   Column("co2e", "CO₂e", "t CO2e", True, {"dp": 2})]
    if gwp_value is not None:
        co2e_op = ops.make_operation(gwp_terms(emitted_t, gwp_value), "co2e", "t CO2e")
        if check:
            ops.verify(co2e_op, float(line["results"]["sum_co2e_t"]))
    else:
        co2e_op = _open(gwp_terms(emitted_t, None), "co2e", "t CO2e")
    company_co2e = ops.make_operation(gwp_terms(company_t, gwp_value), "co2e", "t CO2e") \
        if company_t is not None and gwp_value is not None else None
    if company_co2e is not None and gwp_value is not None:
        _annotate(co2e_op, company_co2e)
    label = f"{gas} · blend GWP" if blend else gas
    step3 = [TraceBlock("co2e", label + (" (counts)" if blend else ""), gwp_columns, recomputed=co2e_op,
                        company=company_co2e)]
    if blend is not None:
        component_terms: list[Term] = []
        company_terms_sum: list[Term] = []
        for c, part_gwp, input_id in parts_gwp:
            def terms(tonnes: float | None, c: Component = c, part_gwp: float | None = part_gwp,
                      input_id: str = input_id) -> list[Term]:
                return [Term(None, Operand("emitted_t", tonnes, "t", step_ref="emitted_t")),
                        Term("×", Operand("share", c.share, None, input_id=f"share.{c.name}")),
                        Term("×", Operand("gwp", part_gwp, GWP_UNIT, input_id=input_id))]
            mine = ops.make_operation(terms(emitted_t), "co2e", "t CO2e") if part_gwp is not None \
                else _open(terms(emitted_t), "co2e", "t CO2e")
            theirs = ops.make_operation(terms(company_t), "co2e", "t CO2e") \
                if part_gwp is not None and company_t is not None else None
            if theirs is not None:
                _annotate(mine, theirs)
                company_terms_sum.append(Term("+" if company_terms_sum else None, Operand(
                    "co2e", theirs.result.value, "t CO2e", step_ref=f"component.{c.name}")))
            if part_gwp is not None:
                component_terms.append(Term("+" if component_terms else None, Operand(
                    "co2e", mine.result.value, "t CO2e", step_ref=f"component.{c.name}")))
            step3.append(TraceBlock(f"component.{c.name}", f"{c.name} · {_g(c.pct)}% of the blend", [
                Column("emitted_t", "Emitted", "t"), Column("share", "Share of blend"), Column("gwp", "GWP", GWP_UNIT),
                Column("co2e", "CO₂e", "t CO2e", True, {"dp": 2})], recomputed=mine, company=theirs))
        if not missing:
            summed = ops.make_operation(component_terms, "sum", "t CO2e")
            summed_company = ops.make_operation(company_terms_sum, "sum", "t CO2e") \
                if len(company_terms_sum) == len(component_terms) else None
            if summed_company is not None:
                _annotate(summed, summed_company)
            step3.append(TraceBlock("components.sum", "Components added", [
                Column("co2e", "CO₂e", "t CO2e"), Column("sum", "Sum", "t CO2e", True, {"dp": 2})],
                recomputed=summed, company=summed_company))
    if counted is not None and blend is not None and effective is not None:
        note = (f"The {gas} GWP ({_g(gwp_value or 0.0)}, {_cited(counted)}) counts in the totals. The split by "
                f"component ({_g(effective)}: each component's share × GWP) is shown for reference.")
    elif counted is not None and blend is not None:
        note = (f"The {gas} GWP ({_g(gwp_value or 0.0)}, {_cited(counted)}) counts in the totals. The split by component "
                f"is not shown: {', '.join(missing)} {'has' if len(missing) == 1 else 'have'} no {gwp_set} GWP in "
                "Sustentra's reference data.")
    elif blend is not None:
        note = (f"{gas} is not in EPA Table 12: its GWP is the sum of each component's share × GWP. A component "
                "EPA Table 11 lacks needs a GWP entered by a reviewer, with its source.")
    else:
        note = "Emitted × global warming potential"

    # --- Results: × the consolidated share ---------------------------------------------------------------------------
    share = float(line.get("consolidated_share_pct", 100.0))
    inputs["share"] = TraceInput("share", "Consolidated share", "methodology", symbol="share", recomputed=Side(
        share, "%", "accepted" if share != 100.0 else "derived",
        SourceRef("methodology", field="consolidated_share", label="Consolidated share")))

    def total_terms(co2e: float | None) -> list[Term]:
        return [Term(None, Operand("co2e", co2e, "t CO2e", step_ref="co2e")),
                Term("×", Operand("share", share / 100.0, None, input_id="share"))]

    co2e_value = co2e_op.result.value if isinstance(co2e_op.result.value, (int, float)) else None
    total_op = ops.make_operation(total_terms(float(co2e_value)), "total", "t CO2e") if co2e_value is not None \
        else _open(total_terms(None), "total", "t CO2e")
    if check and co2e_value is not None:
        ops.verify(total_op, float(line["results"]["total_co2e_t"]))
    company_total = ops.make_operation(total_terms(float(company_co2e.result.value)),  # type: ignore[arg-type]
                                       "total", "t CO2e") if company_co2e is not None else None
    if company_total is not None:
        _annotate(total_op, company_total)
    results = TraceStep("results", None, "Results", [TraceBlock("results.total", "Line total", [
        Column("co2e", "CO₂e", "t CO2e"), Column("share", "Consolidated share"),
        Column("total", "Total", "t CO2e", True, {"dp": 2})], recomputed=total_op, company=company_total)])

    steps = [
        TraceStep("inputs", 1, "Step 1 · Inputs", step1, note="The reviewed service records, added up per term"),
        TraceStep("emitted", 2, "Step 2 · Refrigerant emitted", step2,
                  note=f"{EQUATION}, then to metric tons"),
        TraceStep("gwp", 3, "Step 3 · Emissions by gas", step3, note=note),
        results]

    blocking: list[Blocking] = []
    flags = set(line.get("flags") or [])
    if gwp_value is None:
        if blend is not None and missing:
            blocking.append(Blocking(f"{COMPONENT_GWP}{missing[0]}", (
                f"component GWPs. Enter the {gwp_set} GWP of {' and '.join(missing)}, with its source (the "
                "safety data sheet, say).")))
            flags.add(COMPONENTS_FLAG)
        else:
            blocking.append(Blocking(gwp_id, (
                f"the {gas} GWP. Sustentra's reference data has no {gwp_set} GWP for {gas}: enter it under "
                "Recalculation inputs.")))
    else:
        flags.discard(NO_GWP_FLAG)
    if emitted < 0:
        flags.add(NEGATIVE_FLAG)
    else:
        flags.discard(NEGATIVE_FLAG)
    recomputed_total = float(total_op.result.value) if isinstance(total_op.result.value, (int, float)) else None
    their_total = float(company_total.result.value) if company_total is not None else None  # type: ignore[arg-type]
    return LineTrace(
        line_key=str(line["key"]), panel="fugitive", state="blocked" if blocking else "complete", blocking=blocking,
        choices=[_choice()], inputs=inputs, steps=steps, flags=sorted(flags),
        result=TraceResult("t CO2e", their_total, recomputed_total,
                           ops.difference(recomputed_total, their_total, "t CO2e", "t CO2e")))


def _mixed_trace(line: dict[str, Any]) -> LineTrace:
    """A line mixing refrigerants: blocked, its records listed per term (each with its refrigerant), nothing worked and
    nothing decidable (``decisions.mark_decidable`` says why)."""

    smb = line["smb"]
    inputs: dict[str, TraceInput] = {}
    for term in TERMS:
        rows: list[InputRow] = []
        for i, r in enumerate(line["step1"]["rows"]):
            if term not in (r.get("terms") or {}):
                continue
            cand = (r.get("candidates") or {}).get(term) or r.get("candidate_id") or str(i)
            rows.append(InputRow(f"{r['document_id']}/{cand}#{i}", " · ".join(
                str(x) for x in (r.get("gas"), r.get("file_name") or r["document_id"], r.get("period_start")) if x),
                recomputed=Side(float(r["terms"][term]), str(r["unit"]), "accepted", SourceRef(
                    "document", document_id=r["document_id"], candidate_id=cand, file_name=r.get("file_name")))))
        inputs[term] = TraceInput(term, TERM_LABEL[term], "evidence_sum", symbol=term, required_for=[METHOD],
                                  recomputed=Side(None, str(smb["unit"]), "awaiting_review"), rows=rows)
    return LineTrace(
        line_key=str(line["key"]), panel="fugitive", state="blocked",
        blocking=[Blocking("P_S", mixed_message(smb))], choices=[_choice()], inputs=inputs, steps=[],
        flags=sorted({*(line.get("flags") or []), MIXED_FLAG}),
        result=TraceResult("t CO2e", None, None, None))


def _cited(gwp: Mapping[str, Any]) -> str:
    source = str(gwp.get("source") or "")
    found = re.search(r"Table \d+", source)
    return f"EPA {found.group(0)}" if found and "Hub" in source else (source or "entered")
