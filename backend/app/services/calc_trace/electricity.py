"""Electricity trace, location-based: MWh x eGRID subregion factor (lb per MWh) x metric tons per lb.

The grid region is a line of its own in Step 1 (board 04): the company's region (a company-side input a reviewer
enters or accepts: ``input|grid_region|company``) against the region the recomputed side works on (a Recalculation
input, Setup, or the facility's ZIP code), with ``differs`` when they are not the same subregion. We recompute on
the ZIP region unless the reviewer chooses otherwise. A ZIP code EPA gives two subregions is a *choice* of the line
(``grid_region``, one option per subregion): the reviewer picks, and the pick is worked into the line's totals as the
factors of the picked subregion (``calc_trace/decisions``). The recomputed ``grid_region`` input stays set for the
whole engagement (not decidable); only the choice changes it for one line.

The company's own per-gas factors are the factors of the company's region, applied to the company's activity.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from backend.app.reference import egrid_zip
from backend.app.reference.emission_factor_loader import EmissionFactorNotFoundError, EmissionFactorReference
from backend.app.services.calc_trace._common import trace_for
from backend.app.services.calc_trace._line import reference_source
from backend.app.services.calc_trace.model import (
    Blocking, Choice, ChoiceOption, Column, LineTrace, Operand, Operation, Side, SourceRef, Term, TraceBlock,
    TraceInput,
)

REGION_CHOICE = "grid_region"
REGION_INPUT = "grid_region"
COMPANY_REGION_STREAM = "input|grid_region|company"
GASES = ("CO2", "CH4", "N2O")
# "NWPP", "NWPP · WECC Northwest", "NWPP - WECC Northwest", "NWPP (WECC Northwest)": a code, then at most its name.
_CODE_THEN_NAME = re.compile(r"([A-Za-z0-9]{3,8})(?:\s*[-–—·:(]?\s*(.*?)\)?)?")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
DECIDED = ("accepted", "edited")


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def code_of(text: Any, ref: EmissionFactorReference) -> str | None:
    """The eGRID subregion a text names ("NWPP", "nwpp", "NWPP - WECC Northwest", "WECC Northwest"), as the
    reference spells it; None when it names none (never a guess, never a partial match on a name)."""

    if not isinstance(text, str) or not text.strip() or len(text) > 200 or _CONTROL.search(text):
        return None
    normal = unicodedata.normalize("NFKC", text).strip()
    rows = ref.egrid_subregions()
    found = _CODE_THEN_NAME.fullmatch(normal)
    if found is not None:
        for row in rows:
            if row["egrid_subregion"].casefold() != found.group(1).casefold():
                continue
            rest = found.group(2)
            if not rest or _fold(rest) == _fold(str(row["name"])):  # a code, with at most its own name after it
                return str(row["egrid_subregion"])
    folded = _fold(normal)
    for row in rows:
        if _fold(str(row["name"])) == folded:
            return str(row["egrid_subregion"])
    return None


def canonical(region: Any, ref: EmissionFactorReference) -> str | None:
    """The reference's spelling of a subregion code the engine used, or None when the reference has no such one."""

    if not isinstance(region, str):
        return None
    for row in ref.egrid_subregions():
        if row["egrid_subregion"].casefold() == region.strip().casefold():
            return str(row["egrid_subregion"])
    return None


def name_of(code: str, ref: EmissionFactorReference) -> str | None:
    return next((str(r["name"]) for r in ref.egrid_subregions() if r["egrid_subregion"] == code), None)


def _label(code: str, ref: EmissionFactorReference) -> str:
    name = name_of(code, ref)
    return f"{code} · {name}" if name else code


def company_region_of(records: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """The company's region the reviewer entered or accepted: ``{"text", "by", "at", "reason", "status"}``."""

    record = (records or {}).get(COMPANY_REGION_STREAM)
    decision = record.get("decision") if isinstance(record, Mapping) else None
    if not isinstance(decision, Mapping) or decision.get("status") not in DECIDED:
        return None
    text = decision.get("value")
    if not isinstance(text, str) or not text.strip():
        return None
    by = decision.get("by")
    return {"text": text.strip(), "status": str(decision["status"]),
            "by": str(by.get("name") if isinstance(by, Mapping) else by or ""), "at": str(decision.get("at") or ""),
            "reason": str(decision.get("reason") or "")}


def company_factors(ref: EmissionFactorReference, records: Mapping[str, Mapping[str, Any]] | None
                    ) -> dict[str, dict[str, Any]] | None:
    """Per gas ``{value, unit, source}`` of the company's region, or None when the reviewer gave none that names a
    subregion (the company's side then keeps working on our region's factors, as it did)."""

    entered = company_region_of(records)
    code = code_of(entered["text"], ref) if entered else None
    if code is None:
        return None
    try:
        factors = ref.electricity(code)
    except EmissionFactorNotFoundError:
        return None
    return {gas: {"value": factors[gas].value, "unit": factors[gas].unit, "source": factors[gas].source}
            for gas in GASES}


def context(ref: EmissionFactorReference, *, region: str | None, chosen: str | None, setup_region: str | None,
            addresses: list[Any], records: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    """What the builder needs besides the line: the region the line was calculated on and where it came from, the
    facility's ZIP code and the subregions EPA gives it, and the company's region when a reviewer entered one."""

    zip_code = next((z for z in (egrid_zip.zip_from_address(a) for a in addresses) if z), None)
    candidates = egrid_zip.subregions_for_zip(zip_code)
    used = canonical(region, ref)
    source: str | None = None
    if used is not None:
        if canonical(chosen, ref) == used:
            source = "chosen under Recalculation inputs"
        elif canonical(setup_region, ref) == used:
            source = "set in Setup"
        elif len(candidates) == 1 and candidates[0] == used:
            source = f"ZIP {zip_code} ({egrid_zip.DATASET})"
    return {"grid_region": used, "grid_region_source": source, "zip": zip_code, "zip_regions": candidates,
            "company_region": company_region_of(records)}


def _region_input(ctx: Mapping[str, Any], ref: EmissionFactorReference) -> TraceInput:
    region = ctx.get("grid_region")
    source = ctx.get("grid_region_source")
    if region is None:
        recomputed = Side(None, None, "awaiting_review")
    elif isinstance(source, str) and source.startswith("ZIP"):
        recomputed = Side(str(region), None, "reference", SourceRef(
            "reference", dataset=egrid_zip.DATASET, citation=source, edition="2023"))
    else:
        recomputed = Side(str(region), None, "derived", SourceRef(
            "derived", from_=[str(source or "facility grid region")]))
    entered = ctx.get("company_region")
    company: Side
    differs: bool | None = None
    if entered is None:
        company = Side(None, None, "not_reported")
    else:
        code = code_of(entered["text"], ref)
        company = Side(code or entered["text"], None, entered["status"], SourceRef(
            "entered", by=entered["by"], at=entered["at"], reason=entered["reason"]))
        if region is not None:
            differs = (code or _fold(entered["text"])) != (str(region) if code else _fold(str(region)))
    return TraceInput(REGION_INPUT, "Grid region", "reference", required_for=["location_based"],
                      recomputed=recomputed, company=company, differs=differs)


def _single(column: str, value: str | None, input_id: str) -> Operation:
    operand = Operand(column, value, None, input_id=input_id)
    return Operation([Term(None, Operand(column, value, None, input_id=input_id))], operand)


def _choice(ctx: Mapping[str, Any], ref: EmissionFactorReference) -> Choice | None:
    """One option per subregion EPA gives the facility's ZIP code, and the region in use when it is none of them (a
    region chosen under Recalculation inputs or set in Setup). Only a ZIP code with two or more is a choice."""

    used = ctx.get("grid_region")
    candidates = [c for c in ctx.get("zip_regions") or [] if canonical(c, ref) is not None]
    if used is None or len(candidates) < 2:
        return None
    zip_code = ctx.get("zip")
    cite = SourceRef("reference", dataset=egrid_zip.DATASET, citation=f"ZIP {zip_code} ({egrid_zip.DATASET})",
                     edition="2023")
    options = [ChoiceOption(c, _label(c, ref), citation=cite) for c in candidates]
    if used not in candidates:
        options.append(ChoiceOption(used, _label(used, ref)))
    return Choice(REGION_CHOICE, "Grid region", options, chosen=used)


def build(line: dict[str, Any], context: dict[str, Any] | None = None) -> LineTrace | None:
    """``context`` is what ``electricity.context`` gives (and ``ref``, the reference the engine ran on). With none,
    the trace is what it was before the region was compared: the region in use, when known."""

    ctx = dict(context or {})
    ref: EmissionFactorReference | None = ctx.pop("ref", None)
    region, entered = ctx.get("grid_region"), ctx.get("company_region")
    if ref is None:
        legacy = {"grid_region": region} if region else {}
        return _plain(line, legacy)
    trace_context: dict[str, Any] = {"inputs": {REGION_INPUT: _region_input(ctx, ref)}}
    trace = trace_for("electricity", line, "location_based", trace_context)
    if trace is None:
        return None
    choice = _choice(ctx, ref)
    if choice is not None:
        trace.choices.append(choice)
    if trace.state == "blocked":
        if region is None:
            candidates = ctx.get("zip_regions") or []
            where = (f" ZIP {ctx['zip']} is served by {' or '.join(candidates)}: choose by the facility's electric "
                     "utility." if len(candidates) > 1 else "")
            trace.blocking = [Blocking(REGION_INPUT, "No eGRID subregion is known for this facility. Choose it under "
                                                     f"Recalculation inputs.{where}")]
        return trace
    step = next((s for s in trace.steps if s.id == "activity"), None)
    if step is not None:
        mine = trace.inputs[REGION_INPUT]
        recomputed_value = mine.recomputed.value if mine.recomputed else None
        company_value = mine.company.value if mine.company else None
        block = TraceBlock(
            "grid_region", "Grid region", [Column("grid_region", "Grid region", None, True)],
            company=_single("grid_region", company_value if isinstance(company_value, str) else None, REGION_INPUT),
            recomputed=_single("grid_region", recomputed_value if isinstance(recomputed_value, str) else None,
                               REGION_INPUT),
            choice_id=REGION_CHOICE if choice is not None else None)
        if block.recomputed is not None and isinstance(company_value, str) and mine.differs is not None:
            block.recomputed.result.differs = mine.differs
            block.recomputed.terms[0].operand.differs = mine.differs
        step.blocks.append(block)
    _company_factors(trace, line)
    if entered is not None and code_of(entered["text"], ref) is None:
        trace.flags = sorted({*trace.flags, "company_grid_region_not_recognised"})
    return trace


def _plain(line: dict[str, Any], context: dict[str, Any]) -> LineTrace | None:
    """The trace without the region comparison: the region in use as a derived input, as before."""

    region = context.get("grid_region")
    ctx: dict[str, Any] = {}
    if region:
        ctx["inputs"] = {REGION_INPUT: TraceInput(
            REGION_INPUT, "eGRID subregion", "reference", required_for=["location_based"],
            recomputed=Side(str(region), None, "derived", SourceRef("derived", from_=["facility grid region"])))}
    return trace_for("electricity", line, "location_based", ctx)


def _company_factors(trace: LineTrace, line: dict[str, Any]) -> None:
    """The company's factor of each gas on its input, beside ours, with the difference."""

    company = line.get("company")
    if not company:
        return
    for row in company["step3"]["gases"]:
        item = trace.inputs.get(f"ef.{row['gas']}")
        if item is None or item.recomputed is None:
            continue
        cited = str(row["ef"].get("source") or "")
        item.company = Side(float(row["ef"]["value"]), item.recomputed.unit, "reference",
                            reference_source(cited))
        if isinstance(item.recomputed.value, (int, float)):
            item.difference = float(item.recomputed.value) - float(row["ef"]["value"])
            item.differs = abs(item.difference) > 0.0


def decided_region(trace: LineTrace, code: str, side: Side) -> None:
    """A reviewer chose another subregion for the line (its factors are already in the trace as the decided ``ef``
    values): the region input and its block now say so, and ``differs`` is judged against the company's region."""

    item = trace.inputs.get(REGION_INPUT)
    if item is not None:
        item.recomputed = side
        company = item.company.value if item.company is not None else None
        if isinstance(company, str):
            item.differs = _fold(company) != _fold(code)
    block = next((b for s in trace.steps for b in s.blocks if b.id == "grid_region"), None)
    if block is not None and block.recomputed is not None:
        block.recomputed.result.value = code
        block.recomputed.terms[0].operand.value = code
        if item is not None and item.differs is not None:
            block.recomputed.result.differs = block.recomputed.terms[0].operand.differs = item.differs
