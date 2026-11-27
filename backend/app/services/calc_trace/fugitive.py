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

The screening method (C5, EPA's guidance on direct fugitive emissions, December 2023: ``SCREENING_FACTORS``) is the
method a reviewer may pick instead (``choice|method|`` = ``screening``); the balance stays the default, so with no
decision every number is as before:

    Emitted = C_N × k + Σ (C × T) × x + C_D × y × (1 − z)      (fire suppression: Σ (C × T) × x, x the EPA rate)

C_N is the charge into new equipment (the balance's P_N), C_D the retired capacity (its C_D). The equipment in use is
one unit per equipment ID on the line's records (``screening_units``), its capacity C the reviewed one the records
give (or entered: ``C.<unit>``), its time in use T 1.00 unless entered (``T.<unit>``: months in use ÷ 12). k, x, y, z
come from the equipment type a reviewer picks (``choice|equipment_type|``), the upper end of the IPCC range as EPA
prints it; each is shown as "Default: … · not confirmed" until a reviewer enters it, and may be entered without a type.
Every screening input is on every trace of the line (a decision is checked against the automatic working).

The material balance (C6, EPA's guidance on direct fugitive emissions; terms as ruled in Q8) is the third method a reviewer
may pick (``choice|method|`` = ``material_balance``):

    Emitted = (I_B − I_E) + (P − S) + (C_B − C_E)

I_B / I_E the gas held in storage (not in equipment) at the start and end of the year, P what was purchased or acquired,
S what was sold or sent off-site (returned, recycled, destroyed), C_B / C_E the total full charge of the equipment at the
start and end. No record gives these, so each is entered by a reviewer (``MB_TERMS``, 0 allowed); until all six are, a
term is shown "not reported" and the method is blocked, and the line counts its simplified material balance (with its
decisions) meanwhile. A negative result is kept and flagged, as for the simplified balance.

Decisions (``calc_trace/decisions``): a term (or one record of it) and a component GWP Table 11 lacks can be decided for
the line; the composition, the blend's GWP, the conversion and the consolidated share cannot (set for the whole
engagement or by the reference data). ``rework`` builds the trace again with the decided values in and returns the
line's decided figures.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.domain import fuel_units
from backend.app.domain.refrigerants import mass_unit
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


# --- the screening method (C5) -----------------------------------------------------------------------------------------
SCREENING = "screening"
SCREENING_EQUATION = "Emitted = C_N × k + Σ (C × T) × x + C_D × y × (1 − z)"
FIRE_EQUATION = "Emitted = Σ (C × T) × x"
SCREENING_ROUTE = "Screening (EPA): C_N × k + Σ (C × T) × x + C_D × y × (1 − z), to metric tons, × GWP"
FIRE_ROUTE = "Screening (EPA), fire suppression: Σ (C × T) × rate, to metric tons, × GWP"
EQUIPMENT_CHOICE = "equipment_type"
FACTORS = ("k", "x", "y", "z")
FACTOR_LABEL = {"k": "Installation loss", "x": "Annual leak rate", "y": "Left at disposal", "z": "Recovery"}
UNIT_C, UNIT_T = "C.", "T."  # one equipment unit's capacity and its time in use: "C.<unit id>", "T.<unit id>"
DECIDABLE_IDS: tuple[str, ...] = (*TERMS, *FACTORS)
DECIDABLE_PREFIXES = (UNIT_C, UNIT_T)
DEFAULT_T = 1.0
CAPACITY_CONFLICT_FLAG = "equipment_capacity_differs"

# --- the material balance (C6) ------------------------------------------------------------------------------------------
MATERIAL_BALANCE = "material_balance"
MB_TERMS = ("I_B", "I_E", "P", "S", "C_B", "C_E")
MB_LABEL = {"I_B": "In storage at the start of the year", "I_E": "In storage at the end of the year",
            "P": "Purchased or acquired", "S": "Sold or sent off-site",
            "C_B": "Full charge of equipment at the start of the year",
            "C_E": "Full charge of equipment at the end of the year"}
MB_HINT = {"I_B": "inventory count", "I_E": "inventory count", "P": "purchase invoice",
           "S": "sales, return or disposal record", "C_B": "equipment register (full charge)",
           "C_E": "equipment register (full charge)"}
_MB_OP = {"I_B": None, "I_E": "−", "P": "+", "S": "−", "C_B": "+", "C_E": "−"}
MB_EQUATION = "Emitted = (I_B − I_E) + (P − S) + (C_B − C_E)"
MB_ROUTE = "Material balance: (I_B − I_E) + (P − S) + (C_B − C_E), to metric tons, × GWP"
MB_NOT_REPORTED = "not reported. Enter it from the company's records, or 0 if there was none"
MB_NEGATIVE = "negative balance: check the inventory, purchase and capacity figures. The negative value is kept"
METHOD_NAME = {METHOD: "the simplified material balance", SCREENING: "the screening method",
               MATERIAL_BALANCE: "the material balance"}
METHOD_LABEL = {METHOD: "Simplified material balance", SCREENING: "Screening", MATERIAL_BALANCE: "Material balance"}
DECIDABLE_IDS = (*DECIDABLE_IDS, *MB_TERMS)


def zero_allowed(input_id: str) -> bool:
    """A balance term (or one record of it) may be decided as 0: no new equipment, nothing recovered. So may a
    screening factor other than the leak rate (no assembly loss, nothing left, nothing recovered) and a unit's time in
    use (not in use this period), and a material balance term (nothing in storage, nothing bought or sold). A GWP, a
    capacity and the leak rate may not."""

    base = input_id.split("/", 1)[0]
    return base in TERMS or base in MB_TERMS or base in ("k", "y", "z") or base.startswith(UNIT_T)


def used_by(input_id: str, method: str) -> bool | None:
    """Whether the method the line is worked by (``METHOD``, ``SCREENING`` or ``MATERIAL_BALANCE``) reads this input
    (or one record of it); None for one every method reads or none names (a GWP)."""

    base = input_id.split("/", 1)[0]
    if base in FACTORS or base.startswith(DECIDABLE_PREFIXES):
        return method == SCREENING
    if base in MB_TERMS:
        return method == MATERIAL_BALANCE
    if base in ("P_S", "C_N", "R_D"):
        return method == METHOD
    if base in ("P_N", "C_D"):
        return method != MATERIAL_BALANCE
    return None


def users(input_id: str) -> str:
    """The one method that reads an input no other does: "the screening method" or "the material balance"."""

    return METHOD_NAME[MATERIAL_BALANCE if input_id.split("/", 1)[0] in MB_TERMS else SCREENING]


def check_value(input_id: str, number: float) -> str | None:
    """Why a decided screening value cannot be used, or None: a percentage above 100, a time in use above a year."""

    if input_id in FACTORS and number > 100:
        return "Not applied: a percentage is at most 100."
    if input_id.startswith(UNIT_T) and number > 1:
        return "Not applied: the time in use is at most 1 (months in use ÷ 12)."
    return None


DECIDED = ("accepted", "edited")
NOT_IN_HUB = Path(__file__).resolve().parents[4] / "reference-data" / "emission-factors" / \
    "refrigerant_blends_not_in_hub.json"
SCREENING_FACTORS = Path(__file__).resolve().parents[4] / "reference-data" / "emission-factors" / \
    "epa_fugitive_screening_factors.json"
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


@dataclass(frozen=True)
class EquipmentType:
    """One row of EPA's screening factors: k, x, y, z in percent (None where EPA gives no factor: fire suppression has
    only a rate, x)."""

    id: str
    label: str
    fire: bool
    factors: Mapping[str, float | None]
    short: str  # "EPA Table 1"
    citation: str  # the guidance, its edition, table and page, and the row
    page: int
    # IPCC 2019 Table 7.9's range per factor, [lower, upper] in percent (EPA's value is the upper end); None where the
    # table prints none (fire suppression; the buses' operating loss)
    ranges: Mapping[str, tuple[float, float] | None]


@lru_cache(maxsize=1)
def screening_factors() -> dict[str, EquipmentType]:
    data: dict[str, Any] = json.loads(SCREENING_FACTORS.read_text(encoding="utf-8"))
    out: dict[str, EquipmentType] = {}
    for part, fire in (("refrigeration", False), ("fire_suppression", True)):
        section = data[part]
        where = section.get("table") or section["section"]
        short = "EPA Table 1" if not fire else "EPA fugitive guidance §2.1.2"
        for row in section["rows"]:
            factors = {f: (float(row[f]) if row.get(f) is not None else None) for f in FACTORS}
            given = row.get("ipcc_range") or {}
            ranges = {f: (float(given[f][0]), float(given[f][1])) if given.get(f) else None for f in FACTORS}
            out[row["id"]] = EquipmentType(
                row["id"], row["label"], fire, factors, short,
                f"{data['dataset']} ({data['edition']}), {where}, page {section['page']}: {row['label']}",
                int(section["page"]), ranges)
    return out


def _equipment(record: Any, unit: str) -> tuple[str | None, float | None, str | None]:
    """A record's equipment: its identifier (as placed: reviewed or read by the rules, never a rejected one), its
    reviewed capacity in ``unit`` (None when not reviewed or not a mass), and the capacity's candidate."""

    ident = record.for_placement("equipment_id") if hasattr(record, "for_placement") else None
    name = " ".join(str(ident).split())[:120] if ident not in (None, "") else None
    fields = getattr(record, "fields", None) or {}
    field = fields.get("equipment_capacity")
    candidate = getattr(field, "candidate_id", None)
    value = record.reviewed("equipment_capacity") if hasattr(record, "reviewed") else None
    if isinstance(value, bool) or value is None:
        return name, None, candidate
    try:
        number = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return name, None, candidate
    found = mass_unit(record.unit_of("equipment_capacity"))
    if found == "oz":
        number, found = number / 16, "lb"
    elif found == "g":
        number, found = number / 1000, "kg"
    if found not in ("lb", "kg") or not math.isfinite(number) or not 0 < number <= 1e15:
        return name, None, candidate
    return name, (number if found == unit else fuel_units.convert_exact(number, found, unit)), candidate


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
    for term in (*TERMS, *FACTORS, *MB_TERMS):
        record = (records or {}).get(f"input|{term}|company")
        decision = record.get("decision") if isinstance(record, Mapping) else None
        if not isinstance(decision, Mapping) or decision.get("status") not in DECIDED:
            continue
        value = decision.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if math.isfinite(float(value)) and 0 <= float(value) <= (100 if term in FACTORS else 1e15):
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
        equipment, capacity, capacity_candidate = _equipment(c.record, unit)
        rows.append({
            # the record's equipment, for the screening method's units in use (``screening_units``)
            "equipment_id": equipment, "equipment_capacity": capacity, "equipment_candidate": capacity_candidate,
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


_GUIDANCE = "EPA GHG Inventory Guidance: Direct Fugitive Emissions (December 2023)"
T_DEFAULT_TAG = "Default 1.00 (in use the whole reporting period) · not confirmed. Enter months in use ÷ 12"


# Fire-suppression agents: the screening's fire-suppression rows only. Gases used both ways take either kind; every
# other refrigerant (the blends, HFC-134a, HFC-32 ...) is refrigeration and A/C only.
FIRE_AGENTS = ("HFC-227ea", "HFC-236fa", "FK-5-1-12")
EITHER_USE = ("HFC-125", "HFC-23", "CO2")


def gas_use(gas: str) -> str:
    """``"fire"``, ``"refrigerant"`` or ``"either"``: which equipment types the gas can be screened under."""

    key = _norm(gas)
    if any(key.startswith(_norm(a)) for a in FIRE_AGENTS):
        return "fire"
    if key in {_norm(a) for a in EITHER_USE}:
        return "either"
    return "refrigerant"


def type_refusal(gas: str, kind: EquipmentType) -> str | None:
    """Why the equipment type cannot be used for this gas, or None."""

    use = gas_use(gas)
    if kind.fire and use == "refrigerant":
        return f"{gas} is a refrigerant, not a fire-suppression agent: pick a refrigeration or A/C type."
    if not kind.fire and use == "fire":
        return f"{gas} is a fire-suppression agent: pick fire suppression, fixed or portable."
    return None


def _choices(units: list[ScreenUnit], why_not: str | None = None, gas: str = "") -> list[Choice]:
    """The method (simplified material balance by default; screening once a reviewer picks it, where the line has
    equipment to screen) and, with screening, the equipment type whose EPA factors it uses (none until picked)."""

    why = why_not or (None if units else "No reviewed records of equipment on this line.")
    guidance = SourceRef("reference", dataset=_GUIDANCE, edition="December 2023", citation=f"{_GUIDANCE}, Section 2.1")
    method = Choice("method", "Calculation method", [
        ChoiceOption(SCREENING, "Screening", available=why is None, why_unavailable=why, equation=SCREENING_EQUATION,
                     required_inputs=[EQUIPMENT_CHOICE, *FACTORS], citation=guidance),
        ChoiceOption(METHOD, "Simplified material balance", equation=EQUATION, required_inputs=list(TERMS)),
        ChoiceOption(MATERIAL_BALANCE, "Material balance", available=why_not is None, why_unavailable=why_not,
                     equation=MB_EQUATION, required_inputs=list(MB_TERMS), citation=SourceRef(
                         "reference", dataset=_GUIDANCE, edition="December 2023",
                         citation=f"{_GUIDANCE}, material balance method")),
    ], chosen=METHOD)
    if why is not None:
        return [method]
    types = Choice(EQUIPMENT_CHOICE, "Equipment type", [
        ChoiceOption(t.id, t.label, available=type_refusal(gas, t) is None, why_unavailable=type_refusal(gas, t),
                     equation=FIRE_EQUATION if t.fire else SCREENING_EQUATION, citation=SourceRef(
                         "reference", dataset=_GUIDANCE, table=t.short, edition="December 2023", citation=t.citation))
        for t in screening_factors().values()], chosen="")
    return [method, types]


def _g(value: float) -> str:
    return format(value, ",.6g")


def default_tag(kind: EquipmentType, factor: str, pct: float) -> str:
    """"Default 10% (EPA Table 1; IPCC range 1–10%) · not confirmed": the value, where it is from, and IPCC's range."""

    where = kind.short
    if not kind.fire:
        found = kind.ranges.get(factor)
        where += f"; IPCC range {_g(found[0])}–{_g(found[1])}%" if found else "; no IPCC range printed"
    return f"Default {_g(pct)}% ({where}) · not confirmed"


@dataclass(frozen=True)
class ScreenUnit:
    """One piece of equipment on the line: an equipment ID the records share, or one record that names none."""

    uid: str
    name: str
    capacity: float | None
    source: SourceRef | None
    conflict: bool
    capacities: tuple[float, ...] = ()  # every capacity the records give, when they differ


def screening_units(line: Mapping[str, Any]) -> list[ScreenUnit]:
    """The line's equipment in use, from its records: one unit per equipment ID (a record naming none is its own
    unit). Its capacity is the reviewed one the records give (an installation's or retirement's full charge, or a
    service record's reviewed capacity); when they differ the largest is used, and flagged."""

    groups: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(line["step1"]["rows"]):
        ident = r.get("equipment_id")
        key = f"id:{_norm(ident)}" if ident else f"record:{r['document_id']}/{r.get('candidate_id') or i}#{i}"
        name = str(ident) if ident else " · ".join(
            str(x) for x in (r.get("file_name") or r["document_id"], r.get("period_start")) if x)
        group = groups.setdefault(key, {"name": name, "caps": []})
        terms, candidates = r.get("terms") or {}, r.get("candidates") or {}
        for term in ("C_N", "C_D"):
            if term in terms and float(terms[term]) > 0:
                group["caps"].append((float(terms[term]), r, candidates.get(term)))
        if r.get("equipment_capacity") is not None:
            group["caps"].append((float(r["equipment_capacity"]), r, r.get("equipment_candidate")))
    out: list[ScreenUnit] = []
    for key, group in groups.items():
        caps = group["caps"]
        best = max(caps, key=lambda c: c[0]) if caps else None
        source = SourceRef("document", document_id=best[1]["document_id"], candidate_id=best[2],
                           file_name=best[1].get("file_name")) if best else None
        out.append(ScreenUnit("u" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10], group["name"],
                              best[0] if best else None, source,
                              len({round(c[0], 9) for c in caps}) > 1,
                              tuple(sorted({round(c[0], 9) for c in caps}))))
    return sorted(out, key=lambda u: (_norm(u.name), u.uid))


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


def rework(trace: LineTrace, line_context: tuple[dict[str, Any], dict[str, Any]], decided: Decided,
           picks: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """The trace built again with the decided values and the picked method and equipment type (``trace`` is changed
    in place) and the line's decided figures ({emitted, emitted_t, gwp, co2e, total, route}), or None when the line
    still cannot be worked (a GWP, a capacity or a screening factor is awaited)."""

    line, context = line_context
    again = _build(line, context, decided, picks)
    for name in ("state", "blocking", "inputs", "steps", "result", "flags"):
        setattr(trace, name, getattr(again, name))
    if again.state == "blocked":
        return None
    return _figures(again, line, picks)


def balance_figures(line_context: tuple[dict[str, Any], dict[str, Any]], decided: Decided
                    ) -> dict[str, Any] | None:
    """The simplified material balance with the decided values it reads (the terms, their records, a component GWP),
    for a line whose screening is chosen but blocked: what the line counts until the screening can be worked. None
    when no decided value moves the balance (the line's own numbers stand) or the balance is blocked too."""

    line, context = line_context
    mine = {k: v for k, v in decided.items() if used_by(k, METHOD) is not False}
    if not mine:
        return None
    again = _build(line, context, mine, {})
    return None if again.state == "blocked" else _figures(again, line, {})


def _figures(again: LineTrace, line: Mapping[str, Any], picks: Mapping[str, str] | None) -> dict[str, Any]:
    blocks = {b.id: b for s in again.steps for b in s.blocks}

    def result(block_id: str) -> float:
        op = blocks[block_id].recomputed
        assert op is not None and isinstance(op.result.value, (int, float))
        return float(op.result.value)

    gwp = again.inputs[f"gwp.{line['smb']['gas']}"].recomputed
    assert gwp is not None and isinstance(gwp.value, (int, float))
    route = ROUTE
    if (picks or {}).get("method") == MATERIAL_BALANCE:
        route = MB_ROUTE
    elif (picks or {}).get("method") == SCREENING:
        kind = screening_factors().get((picks or {}).get(EQUIPMENT_CHOICE) or "")
        route = FIRE_ROUTE if kind is not None and kind.fire else SCREENING_ROUTE
    return {"emitted": result("emitted"), "emitted_t": result("emitted_t"), "gwp": float(gwp.value),
            "co2e": result("co2e"), "total": result("results.total"), "route": route}


def _screening_inputs(inputs: dict[str, TraceInput], units: list[ScreenUnit], kind: EquipmentType | None,
                      decided: Decided, company_terms: Mapping[str, float], unit: str) -> None:
    """Every input the screening method reads, on every trace of the line (a decision is checked against the line's
    automatic working, whichever method it uses): each unit's capacity C and time in use T, and k, x, y, z."""

    for u in units:
        c_id, t_id = f"{UNIT_C}{u.uid}", f"{UNIT_T}{u.uid}"
        c_side = Side(u.capacity, unit, "accepted", u.source) if u.capacity is not None \
            else Side(None, unit, "awaiting_review")
        if c_id in decided:
            c_side = decided[c_id][1]
        inputs[c_id] = TraceInput(c_id, f"{u.name} capacity", "evidence_sum" if u.capacity is not None
                                  else "reviewer_entered", symbol="C", required_for=[SCREENING], recomputed=c_side,
                                  source_hint="equipment nameplate or register")
        t_side = decided[t_id][1] if t_id in decided else Side(DEFAULT_T, None, "derived", SourceRef(
            "derived", from_=["default: in use the whole reporting period"]))
        inputs[t_id] = TraceInput(t_id, f"{u.name} time in use", "reviewer_entered", symbol="T",
                                  required_for=[SCREENING], recomputed=t_side,
                                  source_hint="equipment register (months in use)")
    for f in FACTORS:
        default = kind.factors.get(f) if kind is not None else None
        if f in decided:
            side = decided[f][1]
        elif default is not None and kind is not None:
            side = Side(default, "%", "reference", SourceRef("reference", dataset=_GUIDANCE, table=kind.short,
                                                             edition="December 2023", citation=kind.citation))
        else:
            side = Side(None, "%", "awaiting_review")
        given = company_terms.get(f)
        item = TraceInput(f, FACTOR_LABEL[f], "reference", symbol=f, required_for=[SCREENING], recomputed=side,
                          company=Side(given, "%", "accepted") if given is not None else None)
        if given is not None and isinstance(side.value, (int, float)):
            item.difference = float(side.value) - given
            item.differs = ops.differs(item.difference, float(side.value))
        inputs[f] = item


def _number_of(item: TraceInput) -> float | None:
    side = item.recomputed
    value = side.value if side is not None else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _screening(units: list[ScreenUnit], kind: EquipmentType | None, inputs: dict[str, TraceInput],
               values: Mapping[str, float], decided: Decided, company_terms: Mapping[str, float], unit: str
               ) -> tuple[list[TraceBlock], list[TraceBlock], float | None, list[Blocking], str]:
    """Steps 1 and 2 of the screening method, to the refrigerant emitted in the line's unit: Step 1's blocks, Step
    2's, the emitted mass (None while an operand is awaited), what blocks it, and Step 2's equation."""

    fire = kind is not None and kind.fire
    blocking: list[Blocking] = []
    step1: list[TraceBlock] = []
    in_use_terms: list[Term] = []
    for u in units:
        c_id, t_id = f"{UNIT_C}{u.uid}", f"{UNIT_T}{u.uid}"
        c_value, t_value = _number_of(inputs[c_id]), _number_of(inputs[t_id])
        terms = [Term(None, Operand("C", c_value, unit, input_id=c_id)),
                 Term("×", Operand("T", t_value, None, input_id=t_id))]
        op = ops.make_operation(terms, "CT", unit) if c_value is not None and t_value is not None \
            else _open(terms, "CT", unit)
        warning = None
        if u.conflict and c_id not in decided:
            warning = (f"Capacities differ between records ({', '.join(f'{_g(v)} {unit}' for v in u.capacities)}): "
                       "the largest is used. Check it, or enter the capacity.")
        step1.append(TraceBlock(f"unit.{u.uid}", f"{u.name} · equipment in use", [
            Column("C", "Capacity · C", unit), Column("T", "Time in use · T", None, display={"dp": 2}),
            Column("CT", "C × T", unit, True, {"sig": 6})], recomputed=op, warning=warning))
        # the default time in use is an assumption of its input, shown on the block until a reviewer decides it
        inputs[t_id].assumption = None if t_id in decided else T_DEFAULT_TAG
        if c_value is None:
            blocking.append(Blocking(c_id, f"equipment capacity. Enter the refrigerant capacity (C) of {u.name}, "
                                           "from the equipment register or its nameplate."))
        in_use_terms.append(Term("+" if in_use_terms else None, Operand("CT", op.result.value, unit,
                                                                         step_ref=f"unit.{u.uid}")))
    known = all(t.operand.value is not None for t in in_use_terms)
    in_use = ops.make_operation(in_use_terms, "in_use", unit) if known else _open(in_use_terms, "in_use", unit)
    step1.append(TraceBlock("in_use", "Total in use · Σ (C × T)", [
        Column("CT", "C × T", unit), Column("in_use", "Σ (C × T)", unit, True, {"sig": 6})], recomputed=in_use))

    need_k = not fire and values["P_N"] != 0
    need_yz = not fire and values["C_D"] != 0
    needed = [f for f in FACTORS if f == "x" or (f == "k" and need_k) or (f in ("y", "z") and need_yz)]
    if need_k:
        step1.append(TraceBlock("term.P_N", "New equipment charge · C_N", [
            Column("amount", "Total", unit, True, {"sig": 6})],
            recomputed=_single("amount", values["P_N"], unit, input_id="P_N")))
    if need_yz:
        step1.append(TraceBlock("term.C_D", "Retired equipment capacity · C_D", [
            Column("amount", "Total", unit, True, {"sig": 6})],
            recomputed=_single("amount", values["C_D"], unit, input_id="C_D")))
    fraction: dict[str, float | None] = {}
    for f in needed:
        pct = _number_of(inputs[f])
        fraction[f] = pct / 100.0 if pct is not None else None
        name = "Annual emission rate" if fire and f == "x" else FACTOR_LABEL[f]
        mine = _single(f, fraction[f], None, input_id=f) if pct is not None \
            else _open([Term(None, Operand(f, None, None, input_id=f))], f, None)
        given = company_terms.get(f)
        theirs = _single(f, given / 100.0, None, input_id=f) if given is not None else None
        tag = None
        if f not in decided and pct is not None and kind is not None:
            tag = default_tag(kind, f, pct)
        inputs[f].assumption = tag  # EPA's default factor, until a reviewer decides it
        step1.append(TraceBlock(f"factor.{f}", f"{name} · {f}", [Column(f, name, "%", True)], recomputed=mine,
                                company=theirs))
    missing = [f for f in needed if fraction[f] is None]
    if missing:
        if kind is None:
            blocking.append(Blocking(EQUIPMENT_CHOICE, (
                "the equipment type. Pick it under Equipment type to use EPA's screening factors, or enter "
                f"{', '.join(missing)} for this line.")))
        elif fire:
            blocking.append(Blocking("x", "fire-suppression rate. EPA gives none for this equipment: enter it."))
        else:
            blocking.append(Blocking(missing[0], f"screening factors. EPA gives no {', '.join(missing)} for "
                                                 f"{kind.label}: enter {'it' if len(missing) == 1 else 'them'}."))

    def worked(terms: list[Term], column: str, out_unit: str | None) -> Operation:
        if all(t.operand.value is not None for t in terms):
            return ops.make_operation(terms, column, out_unit)
        return _open(terms, column, out_unit)

    step2: list[TraceBlock] = []
    parts: list[Term] = []
    if need_k:
        install = worked([Term(None, Operand("C_N", values["P_N"], unit, step_ref="term.P_N")),
                          Term("×", Operand("k", fraction["k"], None, input_id="k"))], "installation", unit)
        step2.append(TraceBlock("installation", "Installation", [
            Column("C_N", "New equipment charge · C_N", unit), Column("k", "Installation loss · k", "%"),
            Column("installation", "Installation", unit, True, {"sig": 6})], recomputed=install))
        parts.append(Term(None, Operand("installation", install.result.value, unit, step_ref="installation")))
    operation = worked([Term(None, Operand("in_use", in_use.result.value, unit, step_ref="in_use")),
                        Term("×", Operand("x", fraction["x"], None, input_id="x"))], "operation", unit)
    x_name = "Annual emission rate · x" if fire else "Annual leak rate · x"
    step2.append(TraceBlock("operation", "Operation", [
        Column("in_use", "Σ (C × T)", unit), Column("x", x_name, "%"),
        Column("operation", "Operation", unit, True, {"sig": 6})], recomputed=operation))
    parts.append(Term("+" if parts else None, Operand("operation", operation.result.value, unit,
                                                      step_ref="operation")))
    if need_yz:
        not_recovered = worked([Term(None, Operand("all", 1.0, None)),
                                Term("−", Operand("z", fraction["z"], None, input_id="z"))], "not_recovered", None)
        step2.append(TraceBlock("not_recovered", "Not recovered", [
            Column("all", "All", "%"), Column("z", "Recovery · z", "%"),
            Column("not_recovered", "Not recovered · 1 − z", "%", True)], recomputed=not_recovered))
        disposal = worked([Term(None, Operand("C_D", values["C_D"], unit, step_ref="term.C_D")),
                           Term("×", Operand("y", fraction["y"], None, input_id="y")),
                           Term("×", Operand("not_recovered", not_recovered.result.value, None,
                                             step_ref="not_recovered"))], "disposal", unit)
        step2.append(TraceBlock("disposal", "Disposal", [
            Column("C_D", "Retired capacity · C_D", unit), Column("y", "Left at disposal · y", "%"),
            Column("not_recovered", "Not recovered · 1 − z", "%"),
            Column("disposal", "Disposal", unit, True, {"sig": 6})], recomputed=disposal))
        parts.append(Term("+", Operand("disposal", disposal.result.value, unit, step_ref="disposal")))
    emitted = worked(parts, "emitted", unit)
    step2.append(TraceBlock("emitted", "Refrigerant emitted", [
        *[Column(t.operand.column, t.operand.column.replace("_", " ").capitalize(), unit) for t in parts],
        Column("emitted", "Emitted", unit, True, {"sig": 6})], recomputed=emitted))
    value = emitted.result.value
    equation = FIRE_EQUATION if fire else SCREENING_EQUATION
    return step1, step2, float(value) if isinstance(value, (int, float)) else None, blocking, equation


def _material_inputs(inputs: dict[str, TraceInput], decided: Decided, company_terms: Mapping[str, float],
                     unit: str) -> None:
    """The material balance's six terms, on every trace of the line: no record gives them, so each awaits a reviewer
    (``awaiting_review``, "not reported") until entered."""

    for term in MB_TERMS:
        side = decided[term][1] if term in decided else Side(None, unit, "awaiting_review")
        given = company_terms.get(term)
        item = TraceInput(term, MB_LABEL[term], "reviewer_entered", symbol=term, required_for=[MATERIAL_BALANCE],
                          recomputed=side, company=Side(given, unit, "accepted") if given is not None else None,
                          source_hint=MB_HINT[term])
        if given is not None and isinstance(side.value, (int, float)):
            item.difference = float(side.value) - given
            item.differs = ops.differs(item.difference, float(side.value))
        inputs[term] = item


def _material(inputs: dict[str, TraceInput], company_terms: Mapping[str, float], unit: str
              ) -> tuple[list[TraceBlock], list[TraceBlock], float | None, list[Blocking], Operation | None]:
    """Steps 1 and 2 of the material balance, to the refrigerant emitted in the line's unit: Step 1's blocks (one per
    term), Step 2's balance, the emitted mass (None while a term is not reported), what blocks it, and the company's
    balance when the company's six terms were entered."""

    values = {t: _number_of(inputs[t]) for t in MB_TERMS}
    step1: list[TraceBlock] = []
    for term in MB_TERMS:
        value = values[term]
        mine = _single("amount", value, unit, input_id=term) if value is not None \
            else _open([Term(None, Operand("amount", None, unit, input_id=term))], "amount", unit)
        given = company_terms.get(term)
        theirs = _single("amount", given, unit, input_id=term) if given is not None else None
        if theirs is not None and value is not None:
            _annotate(mine, theirs)
        step1.append(TraceBlock(f"term.{term}", f"{MB_LABEL[term]} · {term}",
                                [Column("amount", "Total", unit, True, {"sig": 6})], recomputed=mine, company=theirs,
                                warning=MB_NOT_REPORTED if value is None else None))

    def balance(source: Mapping[str, float | None]) -> Operation:
        terms = [Term(_MB_OP[t], Operand(t, source.get(t), unit, step_ref=f"term.{t}")) for t in MB_TERMS]
        if any(t.operand.value is None for t in terms):
            return _open(terms, "emitted", unit)
        return ops.make_operation(terms, "emitted", unit)

    emitted_op = balance(values)
    theirs = balance(company_terms) if all(t in company_terms for t in MB_TERMS) else None
    worked = emitted_op.result.value
    emitted = float(worked) if isinstance(worked, (int, float)) else None
    if theirs is not None and emitted is not None:
        _annotate(emitted_op, theirs)
    step2 = [TraceBlock("emitted", "Refrigerant emitted", [
        *[Column(t, t, unit) for t in MB_TERMS], Column("emitted", "Emitted", unit, True, {"sig": 6})],
        recomputed=emitted_op, company=theirs, warning=MB_NEGATIVE if emitted is not None and emitted < 0 else None)]
    missing = [t for t in MB_TERMS if values[t] is None]
    blocking = [Blocking(missing[0], (
        f"material balance terms. Not reported: {', '.join(missing)}. Enter each from the company's inventory, "
        "purchase and equipment records; enter 0 for a term that was nil."))] if missing else []
    return step1, step2, emitted, blocking, theirs


def _build(line: dict[str, Any], context: dict[str, Any], decided: Decided,
           picks: Mapping[str, str] | None = None) -> LineTrace:
    smb = line["smb"]
    gas, unit, gwp_set = str(smb["gas"]), str(smb["unit"]), str(smb["gwp_set"])
    ref: EmissionFactorReference | None = context.get("ref")
    company_terms: Mapping[str, float] = context.get("company_terms") or {}
    company = line.get("company")
    picks = picks or {}
    units = screening_units(line)
    screening = picks.get("method") == SCREENING and bool(units)
    material = picks.get("method") == MATERIAL_BALANCE
    kind = screening_factors().get(picks.get(EQUIPMENT_CHOICE) or "")
    if kind is not None and type_refusal(gas, kind) is not None:
        kind = None  # never the factors of a type the gas cannot be screened under (``decisions`` refuses it first)
    check = not decided and not screening and not material  # the default working must reproduce the line's numbers
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
    if units:
        _screening_inputs(inputs, units, kind, decided, company_terms, unit)
    _material_inputs(inputs, decided, company_terms, unit)

    # --- Step 2: the balance (or the screening, or the material balance), then metric tons -----------------------
    screen_blocking: list[Blocking] = []
    emitted: float | None
    company_emitted: Operation | None = None
    if screening:
        step1, step2_head, emitted, screen_blocking, equation = _screening(units, kind, inputs, values, decided,
                                                                          company_terms, unit)
    elif material:
        step1, step2_head, emitted, screen_blocking, company_emitted = _material(inputs, company_terms, unit)
        equation = MB_EQUATION
    else:
        columns = [Column(t, t, unit) for t in TERMS] + [Column("emitted", "Emitted", unit, True, {"sig": 6})]

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
        step2_head = [TraceBlock("emitted", "Refrigerant emitted", columns, recomputed=emitted_op,
                                 company=company_emitted)]
        equation = EQUATION
    factor = float(smb["factor"])
    inputs["unit_conversion"] = TraceInput(
        "unit_conversion", "Unit conversion", "constant",
        recomputed=Side(factor, f"t/{unit}", "reference", SourceRef(
            "reference", dataset=UNIT_SOURCE, citation=f"{UNIT_SOURCE}: 1 lb = 0.45359237 kg exactly; 1 t = 1,000 kg")))
    to_t_terms = [Term(None, Operand("emitted", emitted, unit, step_ref="emitted")),
                  Term("×", Operand("factor", factor, f"t/{unit}", input_id="unit_conversion"))]
    to_t = ops.make_operation(to_t_terms, "emitted_t", "t") if emitted is not None \
        else _open(to_t_terms, "emitted_t", "t")
    if check:
        ops.verify(to_t, float(smb["emitted_t"]))
    emitted_t = float(to_t.result.value) if isinstance(to_t.result.value, (int, float)) else None
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
        if emitted_t is not None:
            _annotate(to_t, company_to_t)
    step2 = [
        *step2_head,
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
                                      required_for=[METHOD], recomputed=side, source_hint="the safety data sheet, say")
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
    if gwp_value is not None and emitted_t is not None:
        co2e_op = ops.make_operation(gwp_terms(emitted_t, gwp_value), "co2e", "t CO2e")
        if check:
            ops.verify(co2e_op, float(line["results"]["sum_co2e_t"]))
    else:
        co2e_op = _open(gwp_terms(emitted_t, gwp_value), "co2e", "t CO2e")
    company_co2e = ops.make_operation(gwp_terms(company_t, gwp_value), "co2e", "t CO2e") \
        if company_t is not None and gwp_value is not None else None
    if company_co2e is not None and gwp_value is not None and emitted_t is not None:
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
            mine = ops.make_operation(terms(emitted_t), "co2e", "t CO2e") \
                if part_gwp is not None and emitted_t is not None \
                else _open(terms(emitted_t), "co2e", "t CO2e")
            theirs = ops.make_operation(terms(company_t), "co2e", "t CO2e") \
                if part_gwp is not None and company_t is not None else None
            if theirs is not None and emitted_t is not None:
                _annotate(mine, theirs)
                company_terms_sum.append(Term("+" if company_terms_sum else None, Operand(
                    "co2e", theirs.result.value, "t CO2e", step_ref=f"component.{c.name}")))
            if part_gwp is not None and emitted_t is not None:
                component_terms.append(Term("+" if component_terms else None, Operand(
                    "co2e", mine.result.value, "t CO2e", step_ref=f"component.{c.name}")))
            step3.append(TraceBlock(f"component.{c.name}", f"{c.name} · {_g(c.pct)}% of the blend", [
                Column("emitted_t", "Emitted", "t"), Column("share", "Share of blend"), Column("gwp", "GWP", GWP_UNIT),
                Column("co2e", "CO₂e", "t CO2e", True, {"dp": 2})], recomputed=mine, company=theirs))
        if not missing and emitted_t is not None:
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

    if screening:
        inputs_note = ("Each piece of equipment's capacity × its time in use, and EPA's screening factors for "
                       f"{kind.label}" if kind is not None else
                       "Each piece of equipment's capacity × its time in use. Pick the equipment type for EPA's "
                       "screening factors")
    elif material:
        inputs_note = ("The gas in storage, bought and sold, and the equipment's full charge at the start and end of "
                       "the year, as entered by a reviewer")
    else:
        inputs_note = "The reviewed service records, added up per term"
    steps = [
        TraceStep("inputs", 1, "Step 1 · Inputs", step1, note=inputs_note),
        TraceStep("emitted", 2, "Step 2 · Refrigerant emitted", step2,
                  note=f"{equation}, then to metric tons"),
        TraceStep("gwp", 3, "Step 3 · Emissions by gas", step3, note=note),
        results]

    blocking: list[Blocking] = list(screen_blocking)
    flags = set(line.get("flags") or [])
    if screening and any(u.conflict for u in units if f"{UNIT_C}{u.uid}" not in decided):
        flags.add(CAPACITY_CONFLICT_FLAG)
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
    if emitted is not None and emitted < 0:
        flags.add(NEGATIVE_FLAG)
    else:
        flags.discard(NEGATIVE_FLAG)
    recomputed_total = float(total_op.result.value) if isinstance(total_op.result.value, (int, float)) else None
    their_total = float(company_total.result.value) if company_total is not None else None  # type: ignore[arg-type]
    return LineTrace(
        line_key=str(line["key"]), panel="fugitive", state="blocked" if blocking else "complete", blocking=blocking,
        choices=_choices(units, gas=gas), inputs=inputs, steps=steps, flags=sorted(flags),
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
        blocking=[Blocking("P_S", mixed_message(smb))],
        choices=_choices([], why_not="this line mixes refrigerants: move the other records to their own line first"),
        inputs=inputs, steps=[],
        flags=sorted({*(line.get("flags") or []), MIXED_FLAG}),
        result=TraceResult("t CO2e", None, None, None))


def _cited(gwp: Mapping[str, Any]) -> str:
    source = str(gwp.get("source") or "")
    found = re.search(r"Table \d+", source)
    return f"EPA {found.group(0)}" if found and "Hub" in source else (source or "entered")
