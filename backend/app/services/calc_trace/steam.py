"""Purchased steam (Scope 2, location-based): one line per facility, boards 06 to 08.

    MMBtu    = Mlb × net enthalpy (Btu/lb) × 0.001        steam billed by weight
             = energy × unit conversion                    steam billed as energy (MMBtu, therms, GJ, kWh ...)
    t (gas)  = MMBtu × emission factor × t per kg (or g)   per gas, the factor from one of four options (``_thermal_ef``)
    t CO2e   = t × GWP, summed, × the consolidated share

Step 1 lists the reviewed bills (by weight, by energy), the net enthalpy and the steam conditions it comes from; Step 2
converts to MMBtu (an "Energy" block, a "Mass" block and a "Cost only" block, each tagged whether the line uses it);
Step 3 holds the four emission factor options; Step 4 the emissions by gas; then the results.

The net enthalpy (rulings for C9), first found of:

* the net enthalpy decided for the line (``net_enthalpy``: the supplier states it, or a reviewer enters it);
* the steam tables: saturated steam at the stated gauge pressure (``pressure_psig``) less the condensate returned at its
  temperature (``condensate_f``), from ``steam_saturated_iapws_if97.json`` (IAPWS-IF97, linear interpolation). With no
  condensate return stated the line takes none (32 °F, the gross enthalpy): the conservative choice, shown as an
  assumption until a reviewer confirms or changes it. Superheated steam is not in the table: enter its net enthalpy;
* the heat content entered for the facility under Recalculation inputs (``steam_heat_content``), what the category has
  always used;
* none: a line with steam billed by weight is blocked ("Awaiting review") and counts only its energy-billed steam.

With no decision a line is the category's own working, number for number (Table 7, the facility's heat content).
``rework`` builds the trace again with the decided values and the chosen option and returns the decided figures.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services.calc_trace import _thermal_ef as ef
from backend.app.services.calc_trace import ops
from backend.app.services.calc_trace._line import GAS_LABEL, GASES, _annotate, reference_source
from backend.app.services.calc_trace.model import (
    Blocking, Choice, ChoiceOption, Column, InputRow, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock,
    TraceInput, TraceResult, TraceStep,
)

TABLE = Path(__file__).resolve().parents[4] / "reference-data" / "emission-factors" / "steam_saturated_iapws_if97.json"
MASS, ENERGY = "mass", "energy"
NET_ENTHALPY, PRESSURE, CONDENSATE = "net_enthalpy", "pressure_psig", "condensate_f"
H_G, H_F = "steam_table.h_g", "steam_table.h_f"
INPUTS = (MASS, ENERGY, NET_ENTHALPY, PRESSURE, CONDENSATE, *ef.INPUTS)  # what a line can decide
NO_RETURN_F = 32.0  # condensate "returned" at 32 °F: none returned, the gross enthalpy
ENTHALPY_RANGE = (500.0, 1600.0)  # Btu per lb, as the facility's heat content (Recalculation inputs)
MMBTU_PER_MLB_BTU_LB = 0.001  # 1,000 lb × Btu/lb = 1,000 Btu = 0.001 MMBtu
CONVERSION_UNIT = "lb·MMBtu/Mlb·Btu"  # MMBtu per (Mlb × Btu/lb)
ENTHALPY_FLAG = "steam_enthalpy_needed"
METHOD = "location_based"
EQUATION = "Emissions (t CO₂e) = Σ per gas [ Steam energy (MMBtu) × emission factor × GWP ]"
ROUTE = "Location-based: steam energy (MMBtu) × emission factor, per gas, × GWP"
HEAT_CONTENT_SOURCE = "Steam heat content entered under Recalculation inputs"
DECIDED = ("accepted", "edited")
KG_PER_T, G_PER_T = 1000.0, 1_000_000.0


def _per_t(unit: str) -> float:
    return KG_PER_T if unit.startswith("kg") else G_PER_T


# --- the steam tables (R2) -------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def table() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(TABLE.read_text(encoding="utf-8"))
    return data


def _interpolate(rows: list[dict[str, Any]], key: str, at: float, *columns: str) -> tuple[float, ...] | None:
    """Linear interpolation of ``columns`` at ``key`` = ``at``; None outside the table (never extrapolated)."""

    if not math.isfinite(at) or not rows or at < rows[0][key] or at > rows[-1][key]:
        return None
    for low, high in zip(rows, rows[1:], strict=False):
        if low[key] <= at <= high[key]:
            if at == low[key]:
                return tuple(float(low[c]) for c in columns)
            if at == high[key]:
                return tuple(float(high[c]) for c in columns)
            share = (at - low[key]) / (high[key] - low[key])
            return tuple(float(low[c]) + share * (float(high[c]) - float(low[c])) for c in columns)
    return tuple(float(rows[0][c]) for c in columns)  # a one-row table


def saturated(psig: float) -> tuple[float, float] | None:
    """(saturation temperature °F, h_g Btu/lb) of dry saturated steam at ``psig``; None outside the table."""

    found = _interpolate(table()["saturated_steam_by_gauge_pressure"]["rows"], "psig", psig, "t_sat_f", "h_g_btu_lb")
    return (found[0], found[1]) if found else None


def liquid(t_f: float) -> float | None:
    """h_f (Btu/lb) of water at ``t_f`` °F; None outside the table."""

    found = _interpolate(table()["saturated_water_by_temperature"]["rows"], "t_f", t_f, "h_f_btu_lb")
    return found[0] if found else None


def pressure_range() -> tuple[float, float]:
    rows = table()["saturated_steam_by_gauge_pressure"]["rows"]
    return float(rows[0]["psig"]), float(rows[-1]["psig"])


def net_enthalpy(psig: float, condensate_f: float = NO_RETURN_F) -> float | None:
    """Saturated steam at ``psig`` less water at ``condensate_f`` (Btu/lb); None when either is outside the table or
    the condensate is not below the steam's own temperature."""

    steam, water = saturated(psig), liquid(condensate_f)
    if steam is None or water is None or condensate_f >= steam[0]:
        return None
    return steam[1] - water


def _table_source(what: str) -> SourceRef:
    data = table()
    return SourceRef("reference", dataset=str(data["dataset"]), table=what, edition=str(data["edition"]),
                     citation=f"{data['source']} ({data['url']}): {what}, linear interpolation")


def check(input_id: str, number: float, pressure: float | None) -> str | None:
    """Why a decided value cannot be used (it is reported, never worked in), or None."""

    if input_id == NET_ENTHALPY and not ENTHALPY_RANGE[0] <= number <= ENTHALPY_RANGE[1]:
        return (f"Not applied: a net enthalpy of {number:,.6g} Btu/lb is outside {ENTHALPY_RANGE[0]:,.0f} to "
                f"{ENTHALPY_RANGE[1]:,.0f} Btu/lb. Check the supplier's statement.")
    if input_id == PRESSURE and saturated(number) is None:
        low, high = pressure_range()
        return (f"Not applied: {number:,.6g} psig is outside the steam table ({low:,.0f} to {high:,.0f} psig). Enter "
                "the net enthalpy instead.")
    if input_id == CONDENSATE:
        if liquid(number) is None:
            rows = table()["saturated_water_by_temperature"]["rows"]
            return (f"Not applied: {number:,.6g} °F is outside the condensate table ({rows[0]['t_f']} to "
                    f"{rows[-1]['t_f']} °F).")
        steam = saturated(pressure) if pressure is not None else None
        if steam is not None and number >= steam[0]:
            return (f"Not applied: condensate at {number:,.6g} °F is not below the steam's own temperature "
                    f"({steam[0]:,.2f} °F at {pressure:,.6g} psig).")
    if input_id == ef.EFFICIENCY and number > ef.EFFICIENCY_RANGE[1]:
        return f"Not applied: a thermal efficiency of {number:,.6g}% is above 100%."
    return None


# --- the line (``recalculation_lines``) ------------------------------------------------------------------------------
def _is_mass(unit: str) -> bool:
    return fuel_units.dimension_of(unit) == fuel_units.MASS


def line_parts(contribs: list[Any], *, facility: str, heat_content: float | None, ref: EmissionFactorReference,
               gwp: Mapping[str, Mapping[str, Any]], gwp_set: str, share_pct: float,
               iso: Callable[[Any], str | None]) -> dict[str, Any]:
    """The line's Steps 1 to 3 and results from its bills (``Contribution``): what the purchased steam category counts
    of them, the same way (Table 7, the facility's heat content). Steam billed by weight with no heat content counts
    nothing (the category does not count it either), and the line says it awaits the enthalpy."""

    rows: list[dict[str, Any]] = []
    for c in sorted(contribs, key=lambda c: (iso(c.start) or "9999", c.record.file_name or "")):
        mass = _is_mass(c.unit)
        main = c.record.fields.get("activity_quantity")
        rows.append({
            "period_start": iso(c.start), "period_end": iso(c.end or c.start), "document_id": c.record.document_id,
            "evidence_code": None, "file_name": c.record.file_name, "record": c.record.label,
            "candidate_id": getattr(main, "candidate_id", None), "review": getattr(main, "status", None),
            "quantity": c.quantity, "unit": c.unit, "share_in_period": c.share, "counted_quantity": c.counted,
            "counted_in_base": fuel_units.convert_exact(c.counted, c.unit, "klb" if mass else "MMBtu"),
            "kind": MASS if mass else ENERGY})
    mass_rows = [r for r in rows if r["kind"] == MASS]
    energy_rows = [r for r in rows if r["kind"] == ENERGY]
    mass_mlb = sum(r["counted_in_base"] for r in mass_rows)
    energy_mmbtu = sum(r["counted_in_base"] for r in energy_rows)
    usable = heat_content is not None and math.isfinite(heat_content) and heat_content > 0
    mass_mmbtu = mass_mlb * heat_content * MMBTU_PER_MLB_BTU_LB if usable and heat_content is not None else 0.0
    waiting = bool(mass_rows) and not usable
    mmbtu = energy_mmbtu + mass_mmbtu
    factors = ref.steam_heat()
    gases, mass_t, co2e = [], {}, {}
    for gas in GASES:
        factor = factors[gas]
        unit = "kg/MMBtu" if gas == "CO2" else "g/MMBtu"
        tons = mmbtu * factor.value / _per_t(unit)
        mass_t[gas], co2e[gas] = tons, tons * float(gwp[gas]["value"])
        gases.append({"gas": gas, "activity": {"value": mmbtu, "unit": "MMBtu"},
                      "ef": {"value": factor.value, "unit": factor.unit, "source": factor.source},
                      "unit_conversion": 1 / _per_t(unit), "mass_t": tons, "gwp": dict(gwp[gas]),
                      "co2e_t": co2e[gas], "biogenic": False, "driven": True})
    total = sum(co2e.values())
    if mass_rows and not energy_rows:
        step1_total = {"quantity": mass_mlb, "unit": "Mlb"}
        step2 = {"from_unit": "Mlb", "to_unit": "MMBtu", "factor": heat_content * MMBTU_PER_MLB_BTU_LB if usable
                 and heat_content is not None else None, "source": "net enthalpy (Btu/lb) × 0.001"}
    elif energy_rows and not mass_rows and len({r["unit"] for r in energy_rows}) == 1:
        unit = energy_rows[0]["unit"]
        step1_total = {"quantity": sum(r["counted_quantity"] for r in energy_rows), "unit": unit}
        step2 = {"from_unit": unit, "to_unit": "MMBtu", "factor": fuel_units.convert_exact(1, unit, "MMBtu"),
                 "source": "fuel_units conversion table"}
    else:
        step1_total = {"quantity": mmbtu, "unit": "MMBtu"}
        step2 = {"from_unit": "MMBtu", "to_unit": "MMBtu", "factor": 1.0, "source": "fuel_units conversion table"}
    table7 = ef.table7(ref)
    return {
        "method": {"route": ROUTE, "equations": {gas: "Emissions = MMBtu x EF" for gas in GASES}},
        "step1": {"rows": rows, "total": step1_total},
        "step2": {**step2, "result": {"quantity": mmbtu, "unit": "MMBtu"}, "distance": None,
                  "implied_fuel_economy": None},
        "step3": {"gases": gases},
        "results": {"mass_t": mass_t, "gas_co2e_t": co2e, "sum_co2e_t": total, "total_co2e_t": total * share_pct / 100,
                    "biogenic_co2_t": 0.0},
        "steam": {"facility": facility, "mass_mlb": mass_mlb, "energy_mmbtu": energy_mmbtu, "mmbtu": mmbtu,
                  "enthalpy": {"value": float(heat_content), "source": HEAT_CONTENT_SOURCE} if usable
                  and heat_content is not None else None,
                  "option": ef.TABLE7, "factors": {gas: table7[gas][0] for gas in GASES}, "gwp_set": gwp_set,
                  **({"awaiting": "the steam's net enthalpy"} if waiting else {})},
        "flags": [ENTHALPY_FLAG] if waiting else [],
    }


def company_values(records: Mapping[str, Mapping[str, Any]] | None) -> dict[str, float]:
    """The company's own values a reviewer entered or accepted (``input|net_enthalpy|company``, its factors): shown, and
    worked on the company's side only."""

    out: dict[str, float] = {}
    for input_id in (NET_ENTHALPY, *ef.INPUTS):
        record = (records or {}).get(f"input|{input_id}|company")
        decision = record.get("decision") if isinstance(record, Mapping) else None
        if not isinstance(decision, Mapping) or decision.get("status") not in DECIDED:
            continue
        value = decision.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(float(value)) and 0 < float(value) <= 1e15:
            out[input_id] = float(value)
    return out


def company_parts(given: Mapping[str, Any], line: Mapping[str, Any], company: Mapping[str, float],
                  ref: EmissionFactorReference) -> dict[str, Any] | str:
    """The company's side from the steam it reported for the line (``reported_activity``: 15,800 Mlb, or MMBtu), its
    net enthalpy and factors when a reviewer entered them, else the line's (ours, as on every panel). A message when
    the quantity is neither a mass nor an energy."""

    entered = str(given.get("unit", "")).strip()
    unit = fuel_units.canonical_unit(entered, True) or fuel_units.find_unit(entered, True)
    try:
        quantity = float(given["quantity"])
        if unit is None or not math.isfinite(quantity) or fuel_units.dimension_of(unit) not in (
                fuel_units.MASS, fuel_units.ENERGY):
            raise fuel_units.UnitError(entered)
        mass = _is_mass(unit)
        base = fuel_units.convert_exact(quantity, unit, "klb" if mass else "MMBtu")
    except (fuel_units.UnitError, KeyError, TypeError, ValueError):
        return f"'{entered}' is not steam by weight or energy. Enter the steam the company reports in Mlb, lb or MMBtu."
    steam = line["steam"]
    enthalpy: float | None = None
    if mass:
        own = company.get(NET_ENTHALPY)
        enthalpy = own if own is not None else (float(steam["enthalpy"]["value"]) if steam.get("enthalpy") else None)
    mmbtu = base * enthalpy * MMBTU_PER_MLB_BTU_LB if mass and enthalpy is not None else (None if mass else base)
    option = ef.company_option(company) or ef.TABLE7
    worked = ef.factors(option, company, {}, ref)
    share = float(line["consolidated_share_pct"])
    if mmbtu is None:
        return {"activity": {"quantity": quantity, "unit": entered}, "enthalpy": None, "option": option,
                "step2": {"from_unit": unit, "to_unit": "MMBtu", "factor": None, "source": None, "distance": None,
                          "implied_fuel_economy": None, "result": {"quantity": None, "unit": "MMBtu"}},
                "step3": {"gases": []}, "counted": False,
                "results": {"mass_t": {}, "gas_co2e_t": {}, "sum_co2e_t": 0.0, "total_co2e_t": 0.0,
                            "biogenic_co2_t": 0.0}}
    mass_t = {gas: mmbtu * float(worked[gas].value or 0.0) / _per_t(worked[gas].unit) for gas in GASES}
    gwp = {gas: float(row["gwp"]["value"]) for gas, row in ((r["gas"], r) for r in line["step3"]["gases"])}
    co2e = {gas: mass_t[gas] * gwp[gas] for gas in GASES}
    total = sum(co2e.values())
    factor = enthalpy * MMBTU_PER_MLB_BTU_LB if mass and enthalpy is not None else fuel_units.convert_exact(
        1, unit, "MMBtu")
    return {
        "activity": {"quantity": quantity, "unit": entered}, "enthalpy": enthalpy, "option": option,
        "step2": {"from_unit": unit, "to_unit": "MMBtu", "factor": factor, "source": None, "distance": None,
                  "implied_fuel_economy": None, "result": {"quantity": mmbtu, "unit": "MMBtu"}},
        "step3": {"gases": [{"gas": gas, "activity": {"value": mmbtu, "unit": "MMBtu"},
                             "ef": {"value": worked[gas].value, "unit": worked[gas].unit}, "mass_t": mass_t[gas],
                             "co2e_t": co2e[gas]} for gas in GASES]},
        "results": {"mass_t": mass_t, "gas_co2e_t": co2e, "sum_co2e_t": total, "total_co2e_t": total * share / 100,
                    "biogenic_co2_t": 0.0},
        "counted": True,
    }


def write_summary(line: dict[str, Any], summary: Mapping[str, Any]) -> None:
    """The decided working on the line's summary (``DecidedLine.write``): its MMBtu, enthalpy and option."""

    line["steam"] = {**line["steam"], **summary}
    line["steam"].pop("awaiting", None)
    line["flags"] = sorted(set(line["flags"]) - {ENTHALPY_FLAG})


# --- the trace -------------------------------------------------------------------------------------------------------
Decided = Mapping[str, tuple[float, Side]]  # input id (or "<input>/<row id>") -> the decided value and its side


def _single(column: str, value: float | str | None, unit: str | None, **kw: Any) -> Operation:
    return Operation([Term(None, Operand(column, value, unit, **kw))], Operand(column, value, unit, **kw))


def _open(terms: list[Term], column: str, unit: str | None) -> Operation:
    return Operation(terms, Operand(column, None, unit))


def _sum(values: list[float], column: str, unit: str, input_id: str) -> Operation:
    return ops.make_operation([Term(None if i == 0 else "+", Operand(column, v, unit, input_id=input_id))
                               for i, v in enumerate(values)], column, unit, input_id=input_id)


def _num(op: Operation | None) -> float | None:
    value = op.result.value if op is not None else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _shown_unit(unit: str) -> str:
    return "Mlb" if unit == "klb" else unit


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    """The line's working, checked against the line's own numbers; None when the line holds nothing to trace or the
    working does not reproduce them (never repaired)."""

    if not line.get("key") or not isinstance(line.get("steam"), Mapping):
        return None
    try:
        return _build(line, context or {}, {}, None)
    except (ops.TraceError, KeyError, TypeError, ValueError, LookupError):
        return None


def rework(trace: LineTrace, line_context: tuple[dict[str, Any], dict[str, Any]], decided: Decided,
           pick: str | None) -> dict[str, Any] | None:
    """The trace built again with the decided values and the reviewer's option (``trace`` is changed in place), and the
    line's decided figures, or None when the line still cannot be worked (an input is awaited)."""

    line, context = line_context
    again = _build(line, context, decided, pick)
    for name in ("state", "blocking", "choices", "inputs", "steps", "result", "flags"):
        setattr(trace, name, getattr(again, name))
    if again.state == "blocked":
        return None
    blocks = {b.id: b for s in again.steps for b in s.blocks}
    out: dict[str, Any] = {"mass_t": {}, "gas_co2e_t": {}, "rows": {}}
    mmbtu = _num(blocks["mmbtu"].recomputed)
    assert mmbtu is not None
    chosen = next(c.chosen for c in again.choices if c.id == ef.CHOICE_ID)
    for gas in GASES:
        emitted = blocks[f"emissions.{gas}"].recomputed
        co2e = _num(blocks[f"gwp.{gas}"].recomputed)
        assert emitted is not None and co2e is not None
        tons = _num(emitted)
        factor = emitted.terms[1].operand
        assert tons is not None and isinstance(factor.value, (int, float))
        out["mass_t"][gas], out["gas_co2e_t"][gas] = tons, co2e
        source = trace.inputs[factor.input_id].recomputed if factor.input_id in trace.inputs else None
        out["rows"][gas] = {"activity": mmbtu, "ef": float(factor.value), "mass_t": tons, "co2e_t": co2e,
                            "activity_unit": "MMBtu", "ef_unit": str(factor.unit).replace("/", " per "),
                            "ef_source": f"{ef.LABEL[chosen]}" + (
                                f": {source.source.citation}" if source and source.source and source.source.citation
                                else ""),
                            "unit_conversion": 1 / _per_t(str(factor.unit)), "equation": "Emissions = MMBtu x EF"}
    enthalpy = trace.inputs[NET_ENTHALPY].recomputed
    out["sum"] = _num(blocks["results.sum"].recomputed)
    out["total"] = _num(blocks["results.total"].recomputed)
    out["mmbtu"] = mmbtu
    unit = str(line["step1"]["total"]["unit"])
    mass_block, energy_block = blocks.get(f"input.{MASS}"), blocks.get(f"input.{ENERGY}")
    out["activity_total"] = (_num(mass_block.recomputed) if unit == "Mlb" and mass_block is not None else
                             mmbtu if unit == "MMBtu" or energy_block is None else _num(energy_block.recomputed))
    out["summary"] = {
        "mmbtu": mmbtu, "mass_mlb": _num(blocks[f"input.{MASS}"].recomputed) if f"input.{MASS}" in blocks else 0.0,
        "option": chosen, "factors": {g: out["rows"][g]["ef"] for g in GASES},
        "enthalpy": {"value": enthalpy.value, "source": _cite(enthalpy)} if enthalpy is not None
        and isinstance(enthalpy.value, (int, float)) else None}
    return out


def _cite(side: Side) -> str | None:
    source = side.source
    if source is None:
        return None
    return source.citation or source.reason or source.label or None


def _rows(line: dict[str, Any], kind: str, unit: str, decided: Decided, input_id: str
          ) -> tuple[list[InputRow], list[float]]:
    rows: list[InputRow] = []
    values: list[float] = []
    seen: set[str] = set()
    for i, r in enumerate(line["step1"]["rows"]):
        if r.get("kind") != kind:
            continue
        row_id = f"{r['document_id']}/{r.get('candidate_id') or i}"
        if row_id in seen:
            row_id = f"{row_id}#{i}"
        seen.add(row_id)
        value = float(r["counted_in_base"]) if unit in ("Mlb", "MMBtu") and not (
            kind == ENERGY and unit == r["unit"]) else float(r["counted_quantity"])
        side = Side(value, unit, "edited" if r.get("review") in ("edited", "corrected") else "accepted",
                    SourceRef("document", document_id=r["document_id"], candidate_id=r.get("candidate_id"),
                              file_name=r.get("file_name")))
        if f"{input_id}/{row_id}" in decided:
            value, side = decided[f"{input_id}/{row_id}"]
        label = " · ".join(str(x) for x in (r.get("file_name") or r["document_id"], r.get("period_start")) if x)
        rows.append(InputRow(row_id, label, recomputed=side))
        values.append(value)
    return rows, values


def _build(line: dict[str, Any], context: dict[str, Any], decided: Decided, pick: str | None) -> LineTrace:
    steam = line["steam"]
    ref: EmissionFactorReference = context["ref"]
    company_given: Mapping[str, float] = context.get("company") or {}
    company = line.get("company") if isinstance(line.get("company"), Mapping) else None
    check_line = not decided and pick is None  # the default working must reproduce the line's numbers
    inputs: dict[str, TraceInput] = {}
    step1: list[TraceBlock] = []
    values = {k: v for k, (v, _) in decided.items()}
    sides = {k: s for k, (_, s) in decided.items()}

    # --- Step 1: the bills, by weight and by energy ------------------------------------------------------------------
    energy_rows = [r for r in line["step1"]["rows"] if r.get("kind") == ENERGY]
    energy_units = {str(r["unit"]) for r in energy_rows}
    energy_unit = next(iter(energy_units)) if len(energy_units) == 1 else "MMBtu"
    totals: dict[str, float | None] = {}
    for kind, unit, label in ((MASS, "Mlb", "Steam purchased by weight"),
                              (ENERGY, energy_unit, "Steam purchased as energy")):
        rows, parts = _rows(line, kind, unit, decided, kind)
        if kind in decided:
            total, side = decided[kind]
            op = _single(kind, total, unit, input_id=kind)
        elif parts:
            op = _sum(parts, kind, unit, kind)
            total = float(op.result.value)  # type: ignore[arg-type]
            side = Side(total, unit, "accepted", SourceRef("derived", from_=[r.id for r in rows]))
        else:
            total, op, side = 0.0, _single(kind, 0.0, unit, input_id=kind), Side(0.0, unit, "derived", SourceRef(
                "derived", from_=["no bill of this kind on the line"]))
        theirs = None
        if company is not None:
            c_unit = fuel_units.canonical_unit(str(company["activity"]["unit"]), True) or fuel_units.find_unit(
                str(company["activity"]["unit"]), True)
            if c_unit is not None and (_is_mass(c_unit) == (kind == MASS)):
                c_value = fuel_units.convert_exact(float(company["activity"]["quantity"]), c_unit, "klb") \
                    if kind == MASS else (float(company["activity"]["quantity"]) if c_unit == energy_unit else
                                          fuel_units.convert_exact(float(company["activity"]["quantity"]), c_unit,
                                                                   "MMBtu") if energy_unit == "MMBtu" else None)
                if c_value is not None:
                    theirs = _single(kind, c_value, unit, input_id=kind)
                    _annotate(op, theirs)
        item = TraceInput(kind, label, "evidence_sum", symbol="Mlb" if kind == MASS else "E", required_for=[METHOD],
                          recomputed=side, rows=rows,
                          company=Side(theirs.result.value, unit, "accepted") if theirs is not None else None)
        if theirs is not None:
            item.difference = total - float(theirs.result.value)  # type: ignore[arg-type]
            item.differs = ops.differs(item.difference, total)
        inputs[kind] = item
        totals[kind] = total
        if rows or kind in decided or theirs is not None:
            step1.append(TraceBlock(f"input.{kind}", label, [Column(kind, "Total", unit, True, {"dp": 2})],
                                    recomputed=op, company=theirs))
    has_mass = bool(totals[MASS]) or MASS in decided or any(r.get("kind") == MASS for r in line["step1"]["rows"])
    has_energy = bool(totals[ENERGY]) or ENERGY in decided or bool(energy_rows)

    # --- the net enthalpy: decided, from the steam tables, as entered for the facility, or awaited ----------------
    enthalpy: float | None
    pressure = values.get(PRESSURE)
    condensate = values.get(CONDENSATE)
    from_tables: tuple[float, float, float, float] | None = None  # (psig, h_g, condensate °F, h_f)
    if NET_ENTHALPY in decided:
        enthalpy, enthalpy_side = decided[NET_ENTHALPY]
    elif pressure is not None:
        sat = saturated(pressure)
        cond = condensate if condensate is not None else NO_RETURN_F
        water = liquid(cond)
        if sat is None or water is None:
            raise ops.TraceError("steam conditions outside the table")  # ``check`` refuses these first
        from_tables = (pressure, sat[1], cond, water)
        enthalpy = sat[1] - water
        enthalpy_side = Side(enthalpy, "Btu/lb", "derived", SourceRef("derived", from_=[H_G, H_F]))
    elif steam.get("enthalpy"):
        enthalpy = float(steam["enthalpy"]["value"])
        enthalpy_side = Side(enthalpy, "Btu/lb", "accepted", SourceRef(
            "methodology", field="steam_heat_content", label=HEAT_CONTENT_SOURCE,
            reason=f"{steam['facility']}: heat content as entered (gross unless the supplier says otherwise)"))
    else:
        enthalpy, enthalpy_side = None, Side(None, "Btu/lb", "awaiting_review")
    their_enthalpy = company.get("enthalpy") if company is not None else None
    stated = company_given.get(NET_ENTHALPY)
    inputs[NET_ENTHALPY] = TraceInput(
        NET_ENTHALPY, "Net steam enthalpy", "reviewer_entered", symbol="h", required_for=[METHOD] if has_mass else [],
        recomputed=enthalpy_side, company=Side(stated, "Btu/lb", "accepted") if stated is not None else None)
    if stated is not None and enthalpy is not None:
        inputs[NET_ENTHALPY].difference = enthalpy - stated
        inputs[NET_ENTHALPY].differs = ops.differs(enthalpy - stated, enthalpy)
    inputs[PRESSURE] = TraceInput(PRESSURE, "Steam pressure (saturated)", "reviewer_entered", symbol="p",
                                  recomputed=sides.get(PRESSURE) or Side(None, "psig", "awaiting_review"))
    cond_item = TraceInput(CONDENSATE, "Condensate returned at", "reviewer_entered", symbol="T",
                           recomputed=sides.get(CONDENSATE) or Side(NO_RETURN_F, "°F", "reference", SourceRef(
                               "reference", dataset=str(table()["dataset"]),
                               citation="No condensate return stated: none returned (gross enthalpy)")))
    if from_tables is not None and condensate is None:
        cond_item.assumption = "Default: no condensate return, gross enthalpy (32 °F) · not confirmed"
    inputs[CONDENSATE] = cond_item
    if has_mass:
        conditions = (f"{_g(from_tables[0])} psig saturated, " + (
            f"condensate at {_g(from_tables[2])} °F" if condensate is not None else "no condensate return")
                      ) if from_tables is not None else (
            "as decided for this line" if NET_ENTHALPY in decided else
            "heat content entered under Recalculation inputs" if steam.get("enthalpy") else "not stated yet")
        mine = _single("h", enthalpy, "Btu/lb", input_id=NET_ENTHALPY)
        theirs_h = _single("h", their_enthalpy, "Btu/lb", input_id=NET_ENTHALPY) if their_enthalpy is not None \
            and stated is not None else None
        if theirs_h is not None and enthalpy is not None:
            _annotate(mine, theirs_h)
        step1.append(TraceBlock("input.net_enthalpy", f"Net steam enthalpy · {conditions}",
                                [Column("h", "Net enthalpy", "Btu/lb", True, {"dp": 2})], recomputed=mine,
                                company=theirs_h))
        step1.append(TraceBlock("input.pressure", "Steam pressure", [Column("p", "Gauge pressure", "psig", True)],
                                recomputed=_single("p", pressure, "psig", input_id=PRESSURE)))
        step1.append(TraceBlock("input.condensate", "Condensate return", [
            Column("t", "Returned at", "°F", True)], recomputed=_single(
                "t", condensate if condensate is not None else NO_RETURN_F, "°F", input_id=CONDENSATE)))

    # --- Step 2: to MMBtu --------------------------------------------------------------------------------------------
    step2: list[TraceBlock] = []
    if from_tables is not None:
        psig, h_g, cond, h_f = from_tables
        inputs[H_G] = TraceInput(H_G, f"Saturated steam enthalpy at {_g(psig)} psig", "reference", symbol="h_g",
                                 recomputed=Side(h_g, "Btu/lb", "reference", _table_source(
                                     f"saturated steam at {_g(psig)} psig")))
        inputs[H_F] = TraceInput(H_F, f"Water enthalpy at {_g(cond)} °F", "reference", symbol="h_f",
                                 recomputed=Side(h_f, "Btu/lb", "reference", _table_source(
                                     f"saturated water at {_g(cond)} °F")))
        step2.append(TraceBlock("net_enthalpy", "Net enthalpy from the steam tables", [
            Column("h_g", "Steam (h_g)", "Btu/lb"), Column("h_f", "Condensate (h_f)", "Btu/lb"),
            Column("h", "Net enthalpy", "Btu/lb", True, {"dp": 2})], recomputed=ops.make_operation([
                Term(None, Operand("h_g", h_g, "Btu/lb", input_id=H_G)),
                Term("−", Operand("h_f", h_f, "Btu/lb", input_id=H_F))], "h", "Btu/lb", input_id=NET_ENTHALPY)))
    # Energy
    factor_e = fuel_units.convert_exact(1, energy_unit, "MMBtu")
    inputs["energy_conversion"] = TraceInput("energy_conversion", "Unit conversion", "constant", recomputed=Side(
        factor_e, f"MMBtu/{energy_unit}", "reference", SourceRef(
            "reference", dataset="fuel_units conversion table", citation=f"1 {energy_unit} = {_g(factor_e)} MMBtu")))
    e_cols = [Column("energy", "Activity data", energy_unit), Column("factor", "Unit conversion"),
              Column("mmbtu", "Steam energy", "MMBtu", True, {"dp": 1})]

    def energy_op(value: float | None) -> Operation:
        terms = [Term(None, Operand("energy", value, energy_unit, step_ref=f"input.{ENERGY}")),
                 Term("×", Operand("factor", factor_e, f"MMBtu/{energy_unit}", input_id="energy_conversion"))]
        return ops.make_operation(terms, "mmbtu", "MMBtu") if value is not None else _open(terms, "mmbtu", "MMBtu")

    energy_total = totals[ENERGY] or 0.0
    energy_mine = energy_op(energy_total) if has_energy else _unused(e_cols)
    energy_theirs = None
    their_energy_side = inputs[ENERGY].company
    their_energy = their_energy_side.value if their_energy_side is not None else None
    if company is not None and has_energy and isinstance(their_energy, (int, float)):
        energy_theirs = energy_op(float(their_energy))
        _annotate(energy_mine, energy_theirs)
    step2.append(TraceBlock("energy", "Energy", e_cols, recomputed=energy_mine, company=energy_theirs,
                            tag="detected_from_evidence" if has_energy else "not_used_for_this_line"))
    # Mass
    inputs["unit_conversion"] = TraceInput("unit_conversion", "Unit conversion", "constant", recomputed=Side(
        MMBTU_PER_MLB_BTU_LB, CONVERSION_UNIT, "reference", SourceRef(
            "reference", dataset="fuel_units conversion table",
            citation="1 Mlb = 1,000 lb; 1 MMBtu = 1,000,000 Btu: 0.001 MMBtu per Mlb·Btu/lb")))
    m_cols = [Column("mass", "Activity data", "Mlb"), Column("h", "Net enthalpy", "Btu/lb"),
              Column("factor", "Unit conversion"), Column("mmbtu", "Steam energy", "MMBtu", True,
                                                          {"dp": 1})]

    def mass_op(mass: float | None, h: float | None) -> Operation:
        terms = [Term(None, Operand("mass", mass, "Mlb", step_ref=f"input.{MASS}")),
                 Term("×", Operand("h", h, "Btu/lb", input_id=NET_ENTHALPY)),
                 Term("×", Operand("factor", MMBTU_PER_MLB_BTU_LB, CONVERSION_UNIT, input_id="unit_conversion"))]
        return ops.make_operation(terms, "mmbtu", "MMBtu") if mass is not None and h is not None \
            else _open(terms, "mmbtu", "MMBtu")

    mass_total = totals[MASS] or 0.0
    mass_mine = mass_op(mass_total, enthalpy) if has_mass else _unused(m_cols)
    mass_theirs = None
    their_mass_side = inputs[MASS].company
    their_mass = their_mass_side.value if their_mass_side is not None else None
    if company is not None and has_mass and isinstance(their_mass, (int, float)):
        mass_theirs = mass_op(float(their_mass), their_enthalpy)
        if _num(mass_mine) is not None:
            _annotate(mass_mine, mass_theirs)
    step2.append(TraceBlock("mass", "Mass", m_cols, recomputed=mass_mine, company=mass_theirs,
                            tag="detected_from_evidence" if has_mass else "not_used_for_this_line"))
    step2.append(TraceBlock("cost_only", "Cost only · not usable", [
        Column("billed", "Amount billed", "$"), Column("mmbtu", "Steam energy", "MMBtu", True)],
        recomputed=_cost_only(), company=_cost_only(), tag="not_used_for_this_line"))
    worked: list[tuple[str, Operation]] = [(b, op) for b, op, used in (("energy", energy_mine, has_energy),
                                                                        ("mass", mass_mine, has_mass)) if used]
    if not worked:
        worked = [("energy", energy_op(0.0))]
    sum_terms_2 = [Term(None if i == 0 else "+", Operand("mmbtu", _num(op), "MMBtu", step_ref=b))
                   for i, (b, op) in enumerate(worked)]
    mmbtu_op = _open(sum_terms_2, "mmbtu", "MMBtu") if any(_num(op) is None for _, op in worked) \
        else ops.make_operation(sum_terms_2, "mmbtu", "MMBtu")
    theirs_parts = [op for op in (energy_theirs, mass_theirs) if op is not None and _num(op) is not None]
    mmbtu_theirs = ops.make_operation([Term(None if i == 0 else "+", Operand("mmbtu", _num(op), "MMBtu"))
                                       for i, op in enumerate(theirs_parts)], "mmbtu", "MMBtu") \
        if theirs_parts and len(theirs_parts) == len([c for c in (energy_theirs, mass_theirs) if c is not None]) \
        else None
    if mmbtu_theirs is not None and _num(mmbtu_op) is not None:
        _annotate(mmbtu_op, mmbtu_theirs)
    step2.append(TraceBlock("mmbtu", "Steam energy", [Column("mmbtu", "Steam energy", "MMBtu", True, {"dp": 1})],
                            recomputed=mmbtu_op, company=mmbtu_theirs))
    mmbtu = _num(mmbtu_op)
    if check_line:
        if mmbtu is not None:
            ops.verify(mmbtu_op, float(line["step2"]["result"]["quantity"]))
        if totals[MASS] and steam.get("mass_mlb") is not None:
            ops.verify(_single("m", totals[MASS], "Mlb"), float(steam["mass_mlb"]))

    # --- Step 3: the emission factor options -------------------------------------------------------------------------
    chosen = pick if pick in ef.OPTIONS else ef.default_option(values)
    their_option = (company.get("option") if company is not None else None) or None
    if their_option is not None and their_option not in ef.OPTIONS:
        their_option = None
    for k, item in ef.inputs(chosen, values, sides, ref, company_given).items():
        inputs[k] = item
    step3 = ef.blocks(chosen, values, sides, ref, company_given, their_option if company is not None else None)
    used = ef.factors(chosen, values, sides, ref)
    note3 = ef.TABLE7_NOTE
    if chosen == ef.CHP:
        note3 = "CHP allocation method: as stated by the supplier. " + note3

    # --- Step 4: emissions by gas ------------------------------------------------------------------------------------
    gwps = {r["gas"]: float(r["gwp"]["value"]) for r in line["step3"]["gases"]}
    gwp_sources = {r["gas"]: r["gwp"].get("source") for r in line["step3"]["gases"]}
    step4: list[TraceBlock] = []
    sum_terms: list[Term] = []
    their_sum_terms: list[Term] = []
    their_rows = {r["gas"]: r for r in (company or {}).get("step3", {}).get("gases", [])} if company else {}
    for gas in GASES:
        factor = used[gas]
        to_t = ef.TO_T[factor.unit]
        inputs[f"to_t.{gas}"] = TraceInput(f"to_t.{gas}", "Unit conversion", "constant", recomputed=Side(
            to_t, f"t/{factor.unit.split('/')[0]}", "reference", SourceRef(
                "reference", dataset="fuel_units conversion table",
                citation="1 t = 1,000 kg = 1,000,000 g")))
        gwp_id = f"gwp.{gas}"
        inputs[gwp_id] = TraceInput(gwp_id, f"{GAS_LABEL[gas]} GWP", "reference", symbol="GWP", recomputed=Side(
            gwps[gas], "t CO2e/t", "reference", reference_source(str(gwp_sources[gas] or "")) or None))

        def emission_terms(energy: float | None, value: float | None, factor_id: str | None,
                           factor_unit: str = factor.unit, to_t: float = to_t, gas: str = gas) -> list[Term]:
            return [Term(None, Operand("mmbtu", energy, "MMBtu", step_ref="mmbtu")),
                    Term("×", Operand("ef", value, factor_unit, input_id=factor_id)),
                    Term("×", Operand("to_t", to_t, f"t/{factor_unit.split('/')[0]}", input_id=f"to_t.{gas}"))]

        terms = emission_terms(mmbtu, factor.value, factor.input_id)
        emitted = ops.make_operation(terms, "mass", "t") if mmbtu is not None and factor.value is not None \
            else _open(terms, "mass", "t")
        if check_line and _num(emitted) is not None:
            ops.verify(emitted, float(line["results"]["mass_t"][gas]))
        their = their_rows.get(gas)
        their_emitted = None
        if their is not None and company is not None and company.get("counted"):
            their_emitted = ops.make_operation(emission_terms(float(their["activity"]["value"]), float(
                their["ef"]["value"]), factor.input_id, str(their["ef"]["unit"])), "mass", "t")
            if _num(emitted) is not None:
                _annotate(emitted, their_emitted)
        tons = _num(emitted)
        gwp_terms = [Term(None, Operand("mass", tons, "t", step_ref=f"emissions.{gas}")),
                     Term("×", Operand("gwp", gwps[gas], "t CO2e/t", input_id=gwp_id))]
        co2e_op = ops.make_operation(gwp_terms, "co2e", "t CO2e") if tons is not None else _open(gwp_terms, "co2e",
                                                                                                  "t CO2e")
        their_co2e = None
        if their_emitted is not None:
            their_co2e = ops.make_operation([Term(None, Operand("mass", _num(their_emitted), "t",
                                                                step_ref=f"emissions.{gas}")),
                                             Term("×", Operand("gwp", gwps[gas], "t CO2e/t", input_id=gwp_id))],
                                            "co2e", "t CO2e")
            if tons is not None:
                _annotate(co2e_op, their_co2e)
            their_sum_terms.append(Term("+" if their_sum_terms else None, Operand(
                "co2e", _num(their_co2e), "t CO2e", step_ref=f"gwp.{gas}")))
        sum_terms.append(Term("+" if sum_terms else None, Operand("co2e", _num(co2e_op), "t CO2e",
                                                                  step_ref=f"gwp.{gas}")))
        step4.append(TraceBlock(f"emissions.{gas}", GAS_LABEL[gas], [
            Column("mmbtu", "Steam energy", "MMBtu"), Column("ef", "Emission factor", factor.unit),
            Column("to_t", "Unit conversion"), Column("mass", "Mass", "t", True, {"sig": 6})],
            recomputed=emitted, company=their_emitted))
        step4.append(TraceBlock(f"gwp.{gas}", f"{GAS_LABEL[gas]} in CO₂e", [
            Column("mass", "Mass", "t"), Column("gwp", "GWP"), Column("co2e", "CO₂e", "t CO2e",
                                                                       True, {"dp": 2})],
            recomputed=co2e_op, company=their_co2e))

    # --- Results --------------------------------------------------------------------------------------------------
    open_sum = any(t.operand.value is None for t in sum_terms)
    summed = _open(sum_terms, "sum", "t CO2e") if open_sum else ops.make_operation(sum_terms, "sum", "t CO2e")
    their_summed = ops.make_operation(their_sum_terms, "sum", "t CO2e") if len(their_sum_terms) == 3 else None
    if their_summed is not None and not open_sum:
        _annotate(summed, their_summed)
    share = float(line.get("consolidated_share_pct", 100.0))
    inputs["share"] = TraceInput("share", "Consolidated share", "methodology", symbol="share", recomputed=Side(
        share, "%", "accepted" if share != 100.0 else "derived",
        SourceRef("methodology", field="consolidated_share", label="Consolidated share")))

    def total_terms(value: float | None) -> list[Term]:
        return [Term(None, Operand("sum", value, "t CO2e", step_ref="results.sum")),
                Term("×", Operand("share", share / 100.0, None, input_id="share"))]

    total_op = _open(total_terms(None), "total", "t CO2e") if open_sum else ops.make_operation(
        total_terms(_num(summed)), "total", "t CO2e")
    if check_line and not open_sum:
        ops.verify(total_op, float(line["results"]["total_co2e_t"]))
    their_total = ops.make_operation(total_terms(_num(their_summed)), "total", "t CO2e") \
        if their_summed is not None else None
    if their_total is not None and not open_sum:
        _annotate(total_op, their_total)
    results = TraceStep("results", None, "Results", [
        TraceBlock("results.sum", "Gases added", [Column("co2e", "CO₂e", "t CO2e"),
                                                   Column("sum", "Emissions", "t CO2e", True, {"dp": 2})],
                   recomputed=summed, company=their_summed),
        TraceBlock("results.total", "Line total", [Column("sum", "Emissions", "t CO2e"),
                                                   Column("share", "Consolidated share"),
                                                   Column("total", "Total", "t CO2e", True, {"dp": 2})],
                   recomputed=total_op, company=their_total)])

    steps = [
        TraceStep("inputs", 1, "Step 1 · Inputs", step1, note="The reviewed steam bills, the enthalpy and the steam "
                                                                "conditions"),
        TraceStep("conversion", 2, "Step 2 · Conversion", step2, note="To MMBtu: energy as billed, or mass × net "
                                                                       "enthalpy"),
        TraceStep("factor", 3, "Step 3 · Emission factor", step3, note=note3),
        TraceStep("emissions", 4, "Step 4 · Emissions by gas", step4, note="MMBtu × emission factor, then × GWP"),
        results]

    blocking: list[Blocking] = []
    flags = set(line.get("flags") or [])
    if has_mass and enthalpy is None:
        blocking.append(Blocking(NET_ENTHALPY, (
            "the steam's net enthalpy. Enter it for this line (Btu per lb, from the supplier's statement), or the steam "
            "pressure and condensate return, or the facility's heat content under Recalculation inputs.")))
        flags.add(ENTHALPY_FLAG)
    else:
        flags.discard(ENTHALPY_FLAG)
    missing = [gas for gas in GASES if used[gas].value is None]
    if missing:
        what = {ef.SUPPLIER: "the supplier's emission factors", ef.CHP: "the CHP allocated emission factors",
                ef.FUEL: "the boiler's thermal efficiency"}.get(chosen, "the emission factors")
        first = ef.EFFICIENCY if chosen == ef.FUEL else f"{ef.PREFIX[chosen]}{missing[0]}"
        blocking.append(Blocking(first, f"{what} ({ef.LABEL[chosen]} is chosen for this line). Enter them, with the "
                                        "document they come from, or choose another option."))
    if chosen == ef.CHP:
        flags.add(ef.CHP_FLAG)
    else:
        flags.discard(ef.CHP_FLAG)
    recomputed_total = _num(total_op)
    their = _num(their_total)
    trace = LineTrace(
        line_key=str(line["key"]), panel="steam", state="blocked" if blocking else "complete", blocking=blocking,
        choices=[Choice("method", "Calculation method", [ChoiceOption(METHOD, "Location-based", equation=EQUATION)],
                        chosen=METHOD),
                 ef.choice(chosen, "reviewer" if pick in ef.OPTIONS else "default", values, their_option)],
        inputs=inputs, steps=steps, flags=sorted(flags),
        result=TraceResult("t CO2e", their, recomputed_total,
                           ops.difference(recomputed_total, their, "t CO2e", "t CO2e")))
    return trace


def held(values: Mapping[str, float]) -> dict[str, str]:
    """Decided steam conditions the line does not work with, and why (reported with the decision as ``uses``)."""

    out: dict[str, str] = {}
    if PRESSURE in values and NET_ENTHALPY in values:
        out[PRESSURE] = "held: the net enthalpy is decided, so the steam tables are not used"
    if CONDENSATE in values and NET_ENTHALPY in values:
        out[CONDENSATE] = "held: the net enthalpy is decided, so the steam tables are not used"
    elif CONDENSATE in values and PRESSURE not in values:
        out[CONDENSATE] = "held: no steam pressure is decided, so the steam tables are not used"
    return out


def _unused(columns: list[Column]) -> Operation:
    """A block the line does not use: its operands shown as "—"."""

    *terms, result = columns
    return Operation([Term(None if i == 0 else "×", Operand(c.key, "—", None)) for i, c in enumerate(terms)],
                     Operand(result.key, "—", None))


def _cost_only() -> Operation:
    return Operation([Term(None, Operand("billed", "—", None))], Operand("mmbtu", "Request quantities", None))


def _g(value: float) -> str:
    return format(value, ",.6g")
