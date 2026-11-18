"""Per-calculation-line recalculation: the response's ``calculation_lines``.

The category results (stationary, mobile, electricity) are built per fuel or per facility. This
module re-adds the very same reviewed records per *calculation line* (``calculation_lines``:
fuel x facility, fuel x vehicle group), runs the same calculator on each line's quantity, and
lays each line out as Step 1 (activity data) -> Step 2 (unit conversion) -> Step 3 (per gas) ->
Results, with the company's side run through the same steps when it gave its annual activity.

Nothing here changes a calculator number or a category result. The records and quantities come
from the recalculation's ledger (what the categories counted), the line of a record from
``calculation_lines.place_record`` and the reviewer's moves (``file_documents``), the numbers from
``emissions_calculator`` and unit conversions from ``fuel_units``. A record with no line is reported
under ``unplaced`` with its quantity and its own result, so lines plus unplaced add up to the
category (on ``sum_co2e_t``: a consolidated share below 100% scales ``total_co2e_t`` only).

Biomass: a biomass fuel's record sits on a ``biogenic`` line. Its CO2 row is marked ``biogenic``
and carries ``co2e_t`` 0 (the CO2 is reported apart, in ``results.biogenic_co2_t``); its CH4 and N2O
count as usual. ``counts_toward`` names the category those CH4 and N2O roll into.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorNotFoundError, EmissionFactorReference
from backend.app.services import calculation_lines as cl
from backend.app.services import emissions_calculator as calc
from backend.app.services.recalculation_ledger import BASE_UNIT, Contribution, Ledger
from backend.app.services.reviewed_evidence import ReviewedRecord, to_date

if TYPE_CHECKING:
    from backend.app.services.engagement_recalculation_service import RecalculationInputs

COUNTS_TOWARD = {"stationary": "stationary", "mobile": "mobile", "electricity": "purchased_energy"}
ROLLUP_SOURCE = {"stationary": "stationary_combustion", "mobile": "mobile_combustion",
                 "electricity": "purchased_electricity"}
FAMILY_CATEGORIES = {"stationary": {"stationary", "biogenic"}, "mobile": {"mobile", "biogenic"},
                     "electricity": {"purchased_energy"}}
ELECTRICITY_LEVEL2 = "Electricity"
UNIT_SOURCE = "fuel_units conversion table"
DISTANCE_SOURCE = "Vehicle group distance entered under Recalculation inputs"
BIOGENIC_FLAG = "biogenic_co2_reported_separately"


@dataclass
class Built:
    lines: list[dict[str, Any]] = field(default_factory=list)
    unplaced: list[dict[str, Any]] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    needs_input: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Sub:
    """One calculator run inside a line: one fuel and base unit, or one facility."""

    sub: tuple[str, ...]
    rows: list[dict[str, Any]]  # step 3 rows; "driven" rows follow the line's activity quantity
    result: calc.LineResult
    to_unit: str  # the unit the factors are applied in (Step 2's target)
    activity: float  # that activity, in ``to_unit``


@dataclass
class _Bucket:
    family: str
    line: cl.CalculationLine | None
    level2: str
    anchor: str | None
    target: str | None = None
    reason: str | None = None
    no_evidence: bool = False
    contribs: list[Contribution] = field(default_factory=list)
    groups: dict[tuple[str, ...], calc.VehicleGroup] = field(default_factory=dict)
    # Facility lines only: where a zero-evidence electricity line finds its eGRID subregion.
    facility: dict[str, Any] | None = None


# --- unit and step helpers -----------------------------------------------------------------------
def _display_unit(text: str) -> str:
    for old, new in (("mmBtu", "MMBtu"), ("miles", "mi"), ("gallon", "gal"), ("short ton", "short_ton")):
        text = re.sub(rf"(?<![A-Za-z]){old}(?![A-Za-z])", new, text)
    return text


def _to_tons(ef_unit: str) -> float:
    """Multiplier from the factor's mass (kg, g, lb) to metric tons."""

    first = ef_unit.split()[0]
    return {"kg": 1 / calc.KG_PER_METRIC_TON, "g": 1 / calc.G_PER_METRIC_TON,
            "lb": 1 / calc.LB_PER_METRIC_TON}[first]


def _eq(text: str) -> str:
    return re.sub(r"\bEq (\d)", r"Eq. \1", text)


def _iso(value: Any) -> str | None:
    found = to_date(value)
    return found.isoformat() if found else None


def _fuel_rows(result: calc.LineResult, gwp: dict[str, Any], mobile: bool) -> list[dict[str, Any]]:
    biogenic = BIOGENIC_FLAG in result.flags
    rows: list[dict[str, Any]] = []
    for gas in calc.GASES:
        for step in result.steps:
            if not step.label.startswith(f"{gas} (") or "metric tons" in step.label:
                continue
            activity, ef = list(step.inputs.values())[:2]
            kept_apart = biogenic and gas == "CO2"  # biomass CO2 is shown, and not counted in CO2e
            rows.append({
                "gas": gas, "activity": {"value": activity["value"], "unit": _display_unit(str(activity["unit"]))},
                "ef": {"value": ef["value"], "unit": _display_unit(str(ef["unit"])), "source": ef["source"]},
                "unit_conversion": _to_tons(str(ef["unit"])), "mass_t": step.result,
                "gwp": gwp[gas], "co2e_t": 0.0 if kept_apart else step.result * gwp[gas]["value"],
                "biogenic": kept_apart,
                # CO2 follows the fuel; a vehicle group's CH4 and N2O follow its distance or fuel.
                "driven": not mobile or gas == "CO2"})
    return rows


def _group_miles(sub: _Sub) -> float | None:
    row = next((r for r in sub.rows if r["gas"] == "CH4"), None)
    return float(row["activity"]["value"]) if row is not None and row["activity"]["unit"] == "mi" else None


class _Builder:
    def __init__(self, ref: EmissionFactorReference, ledger: Ledger, inputs: RecalculationInputs,
                 tolerance: float, open_sources: dict[str, bool]) -> None:
        self.ref = ref
        self.ledger = ledger
        self.inputs = inputs
        self.tolerance = tolerance
        self.open_sources = open_sources
        self.gwp = {gas: self._gwp(gas) for gas in calc.GASES}
        self.needs_input: list[dict[str, Any]] = []
        # (fuel, base) -> everything the category counted of it, to tell a line that holds all of a fuel
        self.fuel_totals: dict[tuple[str, ...], float] = {}
        for c in ledger.contributions:
            if c.family == "mobile":
                self.fuel_totals[c.sub] = self.fuel_totals.get(c.sub, 0.0) + fuel_units.convert_exact(
                    c.counted, c.unit, c.sub[1])

    def _gwp(self, gas: str) -> dict[str, Any]:
        factor = self.ref.gwp(gas, self.inputs.gwp_set)
        return {"value": factor.value, "source": factor.source}

    # --- one calculator run ---------------------------------------------------------------------
    def run_sub(self, bucket: _Bucket, sub: tuple[str, ...], contribs: list[Contribution],
                group: calc.VehicleGroup | None) -> _Sub:
        gwp_set = self.inputs.gwp_set
        family = bucket.family
        if family == "electricity":
            mwh = sum(c.counted / 1000 if c.unit == "kWh" else c.counted for c in contribs)
            region = self.ledger.regions.get(sub[0]) or self._region_of(bucket, sub[0])
            if region is None:
                raise calc.CalculationError(f"No eGRID subregion is known for {sub[0]}.")
            result = calc.electricity_location_based(
                [calc.FacilityElectricity(sub[0], calc.Measure(mwh, "MWh"), region)], self.ref,
                gwp_set=gwp_set).lines[0]
            factors = self.ref.electricity(region)
            rows = [{
                "gas": gas, "activity": {"value": mwh, "unit": "MWh"},
                "ef": {"value": factors[gas].value, "unit": factors[gas].unit, "source": factors[gas].source},
                "unit_conversion": 1 / calc.LB_PER_METRIC_TON, "mass_t": result.mass_t[gas],
                "gwp": self.gwp[gas], "co2e_t": result.mass_t[gas] * self.gwp[gas]["value"],
                "biogenic": False, "driven": True,
            } for gas in calc.GASES]
            return _Sub(sub, rows, result, "MWh", mwh)
        fuel, base = sub
        quantity = sum(fuel_units.convert_exact(c.counted, c.unit, base) for c in contribs)
        if family == "stationary":
            result = calc.stationary_combustion(
                [calc.StationaryFuel(fuel, calc.Measure(quantity, base))], self.ref, gwp_set=gwp_set).lines[0]
        else:
            result = calc.mobile_combustion(
                [calc.MobileFuel(fuel, calc.Measure(quantity, base), vehicle_groups=[group] if group else [])],
                self.ref, gwp_set=gwp_set).lines[0]
        rows = _fuel_rows(result, self.gwp, family == "mobile")
        first = next((r for r in rows if r["gas"] == "CO2"), None)
        to_unit = str(first["activity"]["unit"]) if first else base
        return _Sub(sub, rows, result, to_unit, float(first["activity"]["value"]) if first else 0.0)

    def _region_of(self, bucket: _Bucket, name: str) -> str | None:
        found = self.inputs.grid_regions.get(name) or (bucket.facility or {}).get("gridRegion")
        if not found:
            return None
        try:
            self.ref.electricity(str(found))
        except EmissionFactorNotFoundError:
            return None
        return str(found)

    # --- a whole line --------------------------------------------------------------------------
    def assemble(self, bucket: _Bucket, share_pct: float) -> dict[str, Any]:
        family = bucket.family
        subs_order: list[tuple[str, ...]] = []
        for sub in [c.sub for c in bucket.contribs] + list(bucket.groups):
            if sub not in subs_order:
                subs_order.append(sub)
        flags = {f for c in bucket.contribs for f in c.flags}
        if bucket.no_evidence:
            flags.add("no_evidence")
            subs_order = subs_order or [self._empty_sub(bucket)]
        subs: list[_Sub] = []
        for sub in subs_order:
            try:
                subs.append(self.run_sub(bucket, sub, [c for c in bucket.contribs if c.sub == sub],
                                         bucket.groups.get(sub)))
            except (calc.CalculationError, EmissionFactorNotFoundError, fuel_units.UnitError, KeyError):
                flags.add("calculation_failed")  # the line stays, with what could be calculated
        line = bucket.line
        for s in subs:
            flags |= set(s.result.flags)
        if len(subs) > 1:
            flags.add("mixed_units_or_fuels")
        primary = subs[0] if subs else None
        step1 = self._step1(bucket, primary)
        step2 = self._step2(step1["total"], primary)
        step2["distance"], step2["implied_fuel_economy"] = self._distance(bucket, primary, subs)
        rows = [{k: v for k, v in r.items() if k != "driven"} for s in subs for r in s.rows]
        out: dict[str, Any] = {
            "key": line.key if line else None,
            "scope": line.scope if line else ("s2" if family == "electricity" else "s1"),
            "category": line.category if line else COUNTS_TOWARD[family],
            "counts_toward": COUNTS_TOWARD[family],
            "level2": line.level2_label if line else bucket.level2,
            "level2_key": line.level2 if line else cl.slug(bucket.level2),
            "label": bucket.anchor or (line.label if line else bucket.level2),
            "facility_id": line.facility_id if line else None,
            "consolidated_share_pct": share_pct,
            "method": {"route": self._route(family, primary, bucket),
                       "equations": {gas: _eq(eq) for gas, eq in (primary.result.equations.items() if primary
                                                                  else []) if eq}},
            "step1": step1, "step2": step2, "step3": {"gases": rows},
            "results": self._results([s.result for s in subs], share_pct),
            "company": None, "reported_total_co2e_t": None, "difference_t": None,
            "difference_pct_of_base": None, "status": "not_reported",
            "inputs_incomplete": self.open_sources.get(ROLLUP_SOURCE[family], False), "flags": [],
        }
        if line is None:
            out["reason"] = bucket.reason or "no_calculation_line"
            out["target"] = bucket.target
        else:
            self._company_and_reported(out, bucket, subs, share_pct)
        out["flags"] = sorted(flags | set(out["flags"]))
        return out

    def _empty_sub(self, bucket: _Bucket) -> tuple[str, ...]:
        """The run a line with no evidence stands on: its fuel in the unit the company gave (or the
        fuel's usual one), or its facility."""

        if bucket.family == "electricity":
            return (bucket.anchor or bucket.level2,)
        fuel = bucket.level2
        given = self.inputs.reported_activity.get(bucket.line.key if bucket.line else "", {})
        unit = fuel_units.canonical_unit(str(given.get("unit", ""))) or fuel_units.find_unit(str(given.get("unit", "")))
        if unit is not None:
            return (fuel, BASE_UNIT.get(fuel_units.dimension_of(unit), "MMBtu"))
        if bucket.family == "mobile":
            try:
                epa = self.ref.mobile_co2(fuel)["unit"]
                return (fuel, {"gallon": "gal", "scf": "scf", "short ton": "short_ton"}.get(epa, "gal"))
            except EmissionFactorNotFoundError:
                return (fuel, "gal")
        return (fuel, "MMBtu")

    def _step1(self, bucket: _Bucket, primary: _Sub | None) -> dict[str, Any]:
        mine = [c for c in bucket.contribs if primary is not None and c.sub == primary.sub]
        base = "MWh" if bucket.family == "electricity" else (primary.sub[1] if primary else "MMBtu")
        units = {c.unit for c in mine}
        if len(units) == 1:
            total_unit = next(iter(units))
        else:
            total_unit = base
        total = sum(c.counted if c.unit == total_unit else fuel_units.convert_exact(c.counted, c.unit, total_unit)
                    for c in mine)
        rows = []
        for c in sorted(bucket.contribs, key=lambda c: (_iso(c.start) or "9999", c.record.file_name or "")):
            field_ = c.record.fields["activity_quantity"]
            try:
                in_total = c.counted if c.unit == total_unit else fuel_units.convert_exact(c.counted, c.unit,
                                                                                           total_unit)
            except fuel_units.UnitError:  # another run of the line, in a unit of another kind
                in_total = None
            rows.append({
                "period_start": _iso(c.start), "period_end": _iso(c.end or c.start),
                "document_id": c.record.document_id, "evidence_code": None, "file_name": c.record.file_name,
                "candidate_id": field_.candidate_id, "review": field_.status, "quantity": c.quantity,
                "unit": c.unit, "share_in_period": c.share, "counted_quantity": c.counted,
                "counted_in_base": in_total})
        return {"rows": rows, "total": {"quantity": total, "unit": total_unit}}

    @staticmethod
    def _step2(total: dict[str, Any], primary: _Sub | None) -> dict[str, Any]:
        from_unit = str(total["unit"])
        to_unit = primary.to_unit if primary else from_unit
        factor = 1.0 if from_unit == to_unit else fuel_units.convert_exact(1, from_unit, to_unit)
        return {"from_unit": from_unit, "to_unit": to_unit, "factor": factor,
                "source": None if from_unit == to_unit else UNIT_SOURCE,
                "result": {"quantity": primary.activity if primary else 0.0, "unit": to_unit}}

    def _distance(self, bucket: _Bucket, primary: _Sub | None, subs: list[_Sub]
                  ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """On-road mobile: the distance the vehicle group states (an input, not a conversion), and
        the fuel economy it implies against the fuel on the line, as a reasonableness check only."""

        group = bucket.groups.get(primary.sub) if primary else None
        if bucket.family != "mobile" or primary is None or group is None or not group.on_road:
            return None, None
        miles = _group_miles(primary)
        if miles is None:
            return None, None
        distance = {"quantity": miles, "unit": "mi", "source": DISTANCE_SOURCE}
        holds_all_fuel = (len(subs) == 1 and primary.to_unit == "gal" and primary.activity > 0
                          and not bucket.no_evidence
                          and math.isclose(self.fuel_totals.get(primary.sub, 0.0), primary.activity, rel_tol=1e-9)
                          and len(self.ledger.mobile_groups.get((primary.sub[0], primary.sub[1]), [])) == 1)
        implied = ({"value": miles / primary.activity, "unit": "mi/gal", "role": "reasonableness_check"}
                   if holds_all_fuel else None)
        return distance, implied

    @staticmethod
    def _route(family: str, primary: _Sub | None, bucket: _Bucket) -> str:
        if family == "electricity":
            return "Electricity (MWh) × eGRID factor (lb per MWh) ÷ 2,204.62, location-based"
        if family == "stationary":
            if primary is not None and primary.to_unit == "MMBtu":
                return "Energy content × per-MMBtu factor (Eq. 1)"
            return "Fuel quantity × per-unit factor (Eq. 1)"
        text = "Fuel × CO₂ factor (Eq. 1)"
        group = bucket.groups.get(primary.sub) if primary else None
        if group is None:
            return text
        if group.on_road:
            return text + "; distance × CH₄ and N₂O factors (Eq. 4, on-road)"
        return text + "; fuel × CH₄ and N₂O factors (Eq. 5, non-road)"

    def _results(self, lines: list[calc.LineResult], share_pct: float) -> dict[str, Any]:
        mass = {gas: sum(r.mass_t.get(gas, 0.0) for r in lines) for gas in calc.GASES}
        gas_co2e = {g: mass[g] * self.gwp[g]["value"] for g in calc.GASES}
        total = sum(gas_co2e.values())
        return {"mass_t": mass, "gas_co2e_t": gas_co2e, "sum_co2e_t": total, "total_co2e_t": total * share_pct / 100,
                "biogenic_co2_t": sum(r.biogenic_co2_t for r in lines)}

    # --- the company's side -----------------------------------------------------------------------
    def _company_and_reported(self, out: dict[str, Any], bucket: _Bucket, subs: list[_Sub], share_pct: float) -> None:
        key = out["key"]
        reported = self.inputs.reported_lines.get(key)
        if reported is not None:
            recomputed = out["results"]["total_co2e_t"]
            out["reported_total_co2e_t"] = reported
            out["difference_t"] = recomputed - reported
            # The line's own reported value is the base, judged as the comparisons judge (R8).
            verdict = calc.compare(key, reported, recomputed, self.tolerance)
            out["difference_pct_of_base"] = verdict["difference_pct"]
            out["status"] = "within" if verdict["status"] == "within_tolerance" else "above"
        given = self.inputs.reported_activity.get(key)
        if given is None:
            return

        def ask(message: str) -> None:
            self.needs_input.append({"kind": "company_activity", "key": key,
                                     "message": f"{out['level2']}, {out['label']}: {message}"})

        if len(subs) != 1:
            ask("the company's activity cannot be run on this line: it mixes units or fuels, or it cannot be "
                "calculated. Move the other records to their own line first.")
            return
        sub = subs[0]
        entered = str(given["unit"]).strip()
        unit = fuel_units.canonical_unit(entered) or fuel_units.find_unit(entered)
        try:
            if unit is None:
                raise fuel_units.UnitError(entered)
            quantity = float(given["quantity"])
            factor = 1.0 if unit == sub.to_unit else fuel_units.convert_exact(1, unit, sub.to_unit)
            converted = quantity if unit == sub.to_unit else fuel_units.convert_exact(quantity, unit, sub.to_unit)
        except fuel_units.UnitError:
            ask(f"'{entered}' cannot be converted to {sub.to_unit}. Enter the company's activity in a unit of "
                f"the same kind as {sub.to_unit}.")
            return
        rows = []
        for row in sub.rows:
            row = dict(row)
            if row.pop("driven"):
                mass = converted * row["ef"]["value"] * row["unit_conversion"]
                row.update(activity={"value": converted, "unit": sub.to_unit}, mass_t=mass,
                           co2e_t=0.0 if row["biogenic"] else mass * row["gwp"]["value"])
            rows.append(row)
        company_mass = {gas: sum(r["mass_t"] for r in rows if r["gas"] == gas) for gas in calc.GASES}
        biogenic = 0.0
        if BIOGENIC_FLAG in sub.result.flags:  # as the category: the CO2 is kept apart
            biogenic, company_mass["CO2"] = company_mass["CO2"], 0.0
        gas_co2e = {g: company_mass[g] * self.gwp[g]["value"] for g in calc.GASES}
        total = sum(gas_co2e.values())
        for mine, theirs in zip(out["step3"]["gases"], rows, strict=True):
            mine["company_co2e_t"] = theirs["co2e_t"]
            mine["difference_to_company_t"] = mine["co2e_t"] - theirs["co2e_t"]
        out["results"]["company_total_co2e_t"] = total * share_pct / 100
        out["results"]["difference_to_company_t"] = out["results"]["total_co2e_t"] - total * share_pct / 100
        out["results"]["company_gas_co2e_t"] = gas_co2e
        out["company"] = {
            "activity": {"quantity": quantity, "unit": entered},
            "step2": {"from_unit": entered, "to_unit": sub.to_unit, "factor": factor,
                      "source": None if unit == sub.to_unit else UNIT_SOURCE, "distance": None,
                      "implied_fuel_economy": None,
                      "result": {"quantity": converted, "unit": sub.to_unit}},
            "step3": {"gases": rows},
            "results": {"mass_t": company_mass, "gas_co2e_t": gas_co2e, "sum_co2e_t": total,
                        "total_co2e_t": total * share_pct / 100, "biogenic_co2_t": biogenic}}
        if bucket.family == "mobile" and bucket.groups.get(sub.sub) is not None:
            out["flags"] = sorted({*out["flags"], "company_ch4_n2o_use_vehicle_group"})


# --- lines the company has figures for but that have no evidence ---------------------------------------
def _resolve_key(key: str, known: dict[str, cl.CalculationLine], facilities: list[dict[str, Any]],
                 anchors: list[tuple[str, dict[str, Any]]], ref: EmissionFactorReference
                 ) -> tuple[cl.CalculationLine, str, dict[str, Any] | None] | None:
    """A line key as a (line, family, facility) when it is a known line or names a Setup facility or
    vehicle group with a fuel the calculator knows; None when it matches nothing."""

    line = known.get(key)
    parts = key.split(":")
    if line is None:
        if len(parts) != 4 or cl.CATEGORY_SCOPE.get(parts[1]) != parts[0]:
            return None
        _, category, level2, anchor = parts
        facility = next((f for f in facilities if cl.slug(cl.facility_anchor_id(f)) == anchor), None)
        group = next(((a, g) for a, g in anchors if cl.slug(a) == anchor), None)
        if category == "purchased_energy":
            if level2 != "electricity" or facility is None:
                return None
            line = cl.facility_line(category, "electricity", ELECTRICITY_LEVEL2, facility)
        elif category in ("stationary", "mobile", "biogenic"):
            stationary = [n for n in ref.stationary_fuel_types() if cl.slug(n) == level2]
            mobile = [r["fuel_type"] for r in ref.data["mobile_co2"] if cl.slug(r["fuel_type"]) == level2]
            if facility is not None and stationary and category != "mobile":
                line = cl.facility_line(category, level2, stationary[0], facility)
            elif group is not None and mobile and category != "stationary" and str(
                    group[1].get("fuel", "")).strip().lower() == mobile[0].lower():
                line = cl.vehicle_group_line(category, level2, mobile[0], group[0], group[1])
            else:
                return None
        else:
            return None
        if line.key != key:
            return None
    if line.category == "purchased_energy":
        if line.level2 != "electricity":
            return None
        family = "electricity"
    elif line.category == "mobile" or line.anchor_kind == "vehicle_group":
        family = "mobile"
    elif line.category in ("stationary", "biogenic") and line.anchor_kind == "facility":
        family = "stationary"
    else:
        return None
    facility = next((f for f in facilities if cl.facility_anchor_id(f) == line.anchor_id), None)
    return line, family, facility


def build(ref: EmissionFactorReference, ledger: Ledger, records: list[ReviewedRecord],
          inputs: RecalculationInputs, settings: dict[str, Any], decisions: dict[str, dict[str, Any]],
          tolerance: float, open_sources: dict[str, bool], facilities: list[dict[str, Any]]) -> Built:
    """The calculation lines of one recalculation, from what its categories counted (``ledger``)."""

    placements = {
        id(r): cl.place_record(r, ref=ref, facilities=facilities, decisions=decisions,
                               vehicle_groups=inputs.vehicle_groups, fuel_choices=inputs.fuel_choices)
        for r in records}
    system = cl.default_lines(placements.values(), facilities, inputs.vehicle_groups)
    known = {line.key: line for line in cl.merge_lines(system, cl.user_lines(settings))}
    by_document: dict[str, list[ReviewedRecord]] = {}
    for record in records:
        by_document.setdefault(record.document_id, []).append(record)
    filed = cl.file_documents(
        ((doc, recs[0].canonical_type_id, [placements[id(r)] for r in recs]) for doc, recs in by_document.items()),
        decisions, set(known))
    slot_of: dict[int, cl.Slot] = {}
    for doc, slots in filed.items():
        for slot in slots:
            for index in slot.records:
                slot_of[id(by_document[doc][index])] = slot

    builder = _Builder(ref, ledger, inputs, tolerance, open_sources)
    facility_names = {cl.facility_anchor_id(f): str(f.get("name")) for f in facilities}
    anchors = cl.vehicle_group_anchors(inputs.vehicle_groups)
    biogenic_fuels = calc.biogenic_fuel_names(ref)
    groups_using: dict[str, int] = {}
    for _, group in anchors:
        name = str(group.get("fuel", "")).strip().lower()
        groups_using[name] = groups_using.get(name, 0) + 1

    def anchor_label(line: cl.CalculationLine) -> str | None:
        if line.anchor_kind == "facility":
            return facility_names.get(line.anchor_id, line.label)
        if line.anchor_kind == "vehicle_group":
            return next((cl.vehicle_group_label(g) for a, g in anchors if a == line.anchor_id), line.label)
        return line.label

    def reason_for(c: Contribution, slot: cl.Slot, line: cl.CalculationLine | None) -> str:
        if "unknown_line" in slot.flags:
            return "unknown_line"
        if line is not None or slot.target in cl.FIXED_TARGETS and slot.target != cl.SUPPORTING_UNASSIGNED:
            return "moved_to_another_place"
        place = placements[id(c.record)]
        if c.family == "mobile" and place.level2_label:
            count = groups_using.get(place.level2_label.lower(), 0)
            return "fuel_shared_by_vehicle_groups" if count > 1 else "no_vehicle_group"
        if place.anchor_id is None and place.facility is None:
            return "no_facility_match"
        return "no_calculation_line"

    buckets: dict[Any, _Bucket] = {}
    for c in ledger.contributions:
        slot = slot_of.get(id(c.record), cl.Slot(cl.SUPPORTING_UNASSIGNED))
        line = known.get(slot.target)
        if line is not None and line.category in FAMILY_CATEGORIES[c.family]:
            bucket = buckets.setdefault(line.key, _Bucket(c.family, line, line.level2_label, anchor_label(line)))
        else:  # no line, or moved out of its family: reported on its own, never dropped
            name = c.sub[0]
            reason = reason_for(c, slot, line)
            bucket = buckets.setdefault(("unplaced", c.family, name, reason), _Bucket(
                c.family, None, ELECTRICITY_LEVEL2 if c.family == "electricity" else name,
                name if c.family == "electricity" else None, slot.target, reason))
        bucket.contribs.append(c)
    # Each vehicle group carries its own CH4 and N2O, with or without a fuel record placed on it.
    for (fuel, base), indexed in ledger.mobile_groups.items():
        category = "biogenic" if fuel.lower() in biogenic_fuels else "mobile"
        for settings_index, vg in indexed:
            made = cl.vehicle_group_line(category, cl.slug(fuel), fuel, anchors[settings_index][0],
                                         inputs.vehicle_groups[settings_index])
            line = known.get(made.key, made)
            bucket = buckets.setdefault(line.key, _Bucket("mobile", line, line.level2_label, anchor_label(line)))
            bucket.groups[(fuel, base)] = vg

    # The company's figures for a line with no evidence: a line of zero, so the gap shows.
    wanted = sorted(set(inputs.reported_lines) | set(inputs.reported_activity))
    unknown: list[dict[str, str]] = []
    for key in wanted:
        if key in buckets:
            continue
        found = _resolve_key(key, known, facilities, anchors, ref)
        if found is None:
            unknown.extend({"setting": name, "key": key} for name, mapping in
                           (("reported_lines", inputs.reported_lines), ("reported_activity", inputs.reported_activity))
                           if key in mapping)
            continue
        line, family, facility = found
        buckets[key] = _Bucket(family, line, ELECTRICITY_LEVEL2 if family == "electricity" else line.level2_label,
                               anchor_label(line), no_evidence=True, facility=facility)

    built = Built()
    for bucket in buckets.values():
        share = 100.0
        if bucket.line is not None and bucket.line.anchor_kind == "facility":
            share = inputs.consolidated_shares.get(bucket.line.anchor_id, 100.0)
        item = builder.assemble(bucket, share)
        if bucket.no_evidence and "calculation_failed" in item["flags"]:
            builder.needs_input.append({
                "kind": "company_activity", "key": item["key"],
                "message": f"{item['level2']}, {item['label']}: there is no evidence for this line and it could not "
                           "be calculated from the company's figures alone. Check its fuel, unit and grid region."})
        (built.lines if bucket.line is not None else built.unplaced).append(item)
    order = {name: i for i, (name, _, _) in enumerate(cl.CATEGORIES)}
    built.lines.sort(key=lambda ln: (order.get(ln["category"], 99), ln["level2"].lower(), str(ln["label"]).lower(),
                                     ln["key"]))
    built.unplaced.sort(key=lambda ln: (ln["counts_toward"], ln["level2"].lower(), str(ln["label"]), ln["reason"]))
    known_facilities = set(facility_names)
    built.inputs = {
        "consolidated_shares": dict(inputs.consolidated_shares),
        "unknown_line_keys": sorted(unknown, key=lambda e: (e["setting"], e["key"])),
        "unknown_facility_ids": sorted(set(inputs.consolidated_shares) - known_facilities),
    }
    built.needs_input = builder.needs_input
    return built
