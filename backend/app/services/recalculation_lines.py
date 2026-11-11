"""Per-calculation-line recalculation: the response's ``calculation_lines``.

The category results (stationary, mobile, electricity) are built per fuel or per facility. This
module re-adds the very same reviewed records per *calculation line* (``calculation_lines``:
fuel x facility, fuel x vehicle group), runs the same calculator on each line's quantity, and
lays each line out as Step 1 (activity data) -> Step 2 (unit conversion) -> Step 3 (per gas) ->
Results, with the company's side run through the same steps when it gave its annual activity.

Nothing here changes a calculator number or a category result. The records and quantities come
from the service's own ledger (what the categories counted), the line of a record from
``calculation_lines.place_record`` and the reviewer's moves, the numbers from ``emissions_calculator``
and unit conversions from ``fuel_units``. A record with no line is reported under ``unplaced``
with its quantity and its own result, so the lines plus the unplaced groups add up to the category.

Biomass: a biomass fuel's record sits on a ``biogenic`` line. The line shows its biogenic CO2
(``results.biogenic_co2_t``) and its CH4 and N2O; ``counts_toward`` names the category those
CH4 and N2O roll into (stationary or mobile), as the category result does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorNotFoundError
from backend.app.services import calculation_lines as cl
from backend.app.services import emissions_calculator as calc
from backend.app.services.engagement_recalculation_service import (
    Contribution,
    EngagementRecalculationService,
    RecalculationInputs,
    ReviewedRecord,
    _date,
    materiality_tolerance,
    setup_facilities,
)

COUNTS_TOWARD = {"stationary": "stationary", "mobile": "mobile", "electricity": "purchased_energy"}
FAMILY_CATEGORIES = {"stationary": {"stationary", "biogenic"}, "mobile": {"mobile", "biogenic"},
                     "electricity": {"purchased_energy"}}
ELECTRICITY_LEVEL2 = "Electricity"
UNIT_SOURCE = "fuel_units conversion table"
# The reported data point each line's category is compared against (the existing comparisons').
BASE_DATA_POINT = {"stationary": "stationary_combustion_total", "mobile": "mobile_combustion_total",
                   "purchased_energy": "purchased_electricity_total"}


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
    contribs: list[Contribution] = field(default_factory=list)
    groups: dict[tuple[str, ...], calc.VehicleGroup] = field(default_factory=dict)


# --- where each record belongs ----------------------------------------------------------------
def _targets(records: list[ReviewedRecord], placements: dict[int, cl.RecordPlacement],
             known: set[str], decisions: dict[str, dict[str, Any]]) -> dict[int, str]:
    """id(record) -> the line (or block) the record is filed under, the reviewer's moves applied."""

    by_document: dict[str, list[ReviewedRecord]] = {}
    for record in records:
        by_document.setdefault(record.document_id, []).append(record)
    out: dict[int, str] = {}
    for document_id, recs in by_document.items():
        default = cl.document_slots(recs[0].canonical_type_id, [placements[id(r)] for r in recs])
        moved = cl.apply_placements(default, (decisions.get(document_id) or {}).get("placements"))
        for slot in cl.merge_slots([cl.resolve_target(s, known) for s in moved]):
            for index in slot.records:
                out[id(recs[index])] = slot.target
    return out


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
    found = _date(value)
    return found.isoformat() if found else None


def _fuel_rows(result: calc.LineResult, gwp: dict[str, Any], mobile: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gas in calc.GASES:
        for step in result.steps:
            if not step.label.startswith(f"{gas} (") or "metric tons" in step.label:
                continue
            activity, ef = list(step.inputs.values())[:2]
            rows.append({
                "gas": gas, "activity": {"value": activity["value"], "unit": _display_unit(str(activity["unit"]))},
                "ef": {"value": ef["value"], "unit": _display_unit(str(ef["unit"])), "source": ef["source"]},
                "unit_conversion": _to_tons(str(ef["unit"])), "mass_t": step.result,
                "gwp": gwp[gas], "co2e_t": step.result * gwp[gas]["value"],
                # CO2 follows the fuel; a vehicle group's CH4 and N2O follow its distance or fuel.
                "driven": not mobile or gas == "CO2"})
    return rows


class _Builder:
    def __init__(self, service: EngagementRecalculationService, inputs: RecalculationInputs,
                 tolerance: float) -> None:
        self.tolerance = tolerance
        self.service = service
        self.ref = service.reference
        self.inputs = inputs
        self.gwp = {gas: self._gwp(gas) for gas in calc.GASES}
        self.needs_input: list[dict[str, Any]] = []

    def _gwp(self, gas: str) -> dict[str, Any]:
        factor = self.ref.gwp(gas, self.inputs.gwp_set)
        return {"value": factor.value, "source": factor.source}

    # --- one calculator run ---------------------------------------------------------------------
    def run_sub(self, family: str, sub: tuple[str, ...], contribs: list[Contribution],
                group: calc.VehicleGroup | None) -> _Sub | None:
        gwp_set = self.inputs.gwp_set
        try:
            if family == "electricity":
                mwh = sum(c.counted / 1000 if c.unit == "kWh" else c.counted for c in contribs)
                region = self.service._regions[sub[0]]
                result = calc.electricity_location_based(
                    [calc.FacilityElectricity(sub[0], calc.Measure(mwh, "MWh"), region)], self.ref,
                    gwp_set=gwp_set).lines[0]
                factors = self.ref.electricity(region)
                rows = [{
                    "gas": gas, "activity": {"value": mwh, "unit": "MWh"},
                    "ef": {"value": factors[gas].value, "unit": factors[gas].unit, "source": factors[gas].source},
                    "unit_conversion": 1 / calc.LB_PER_METRIC_TON, "mass_t": result.mass_t[gas],
                    "gwp": self.gwp[gas], "co2e_t": result.mass_t[gas] * self.gwp[gas]["value"], "driven": True,
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
        except (calc.CalculationError, EmissionFactorNotFoundError, fuel_units.UnitError):
            return None  # the category already asked about it (needs_input); the line shows nothing
        rows = _fuel_rows(result, self.gwp, family == "mobile")
        first = next((r for r in rows if r["gas"] == "CO2"), None)
        to_unit = str(first["activity"]["unit"]) if first else base
        return _Sub(sub, rows, result, to_unit, float(first["activity"]["value"]) if first else 0.0)

    # --- a whole line --------------------------------------------------------------------------
    def assemble(self, bucket: _Bucket, share_pct: float) -> dict[str, Any] | None:
        family = bucket.family
        subs_order: list[tuple[str, ...]] = []
        for sub in [c.sub for c in bucket.contribs] + list(bucket.groups):
            if sub not in subs_order:
                subs_order.append(sub)
        subs = [s for sub in subs_order
                if (s := self.run_sub(family, sub, [c for c in bucket.contribs if c.sub == sub],
                                      bucket.groups.get(sub)))]
        if not subs:
            return None
        primary = subs[0]
        flags = {f for c in bucket.contribs for f in c.flags} | {f for s in subs for f in s.result.flags}
        if len(subs) > 1:
            flags.add("mixed_units_or_fuels")
        step1 = self._step1(bucket, primary)
        step2 = self._step2(step1["total"], primary.to_unit, primary.activity)
        rows = [{k: v for k, v in r.items() if k != "driven"} for s in subs for r in s.rows]
        results = self._results([s.result for s in subs], rows, share_pct)
        equations = {gas: _eq(eq) for gas, eq in primary.result.equations.items() if eq}
        line = bucket.line
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
            "method": {"route": self._route(family, primary, bucket), "equations": equations},
            "step1": step1, "step2": step2, "step3": {"gases": rows}, "results": results,
            "company": None, "reported_total_co2e_t": None, "difference_t": None,
            "difference_pct_of_base": None, "status": "not_reported", "flags": sorted(flags),
        }
        step2["distance"] = self._distance(bucket, primary, subs)
        if line is None:
            out["reason"] = "no_calculation_line"
            out["target"] = bucket.target
        else:
            self._company_and_reported(out, bucket, subs, share_pct)
        return out

    def _step1(self, bucket: _Bucket, primary: _Sub) -> dict[str, Any]:
        rows = []
        for c in sorted(bucket.contribs, key=lambda c: (_iso(c.start) or "9999", c.record.file_name or "")):
            field_ = c.record.fields["activity_quantity"]
            rows.append({
                "period_start": _iso(c.start), "period_end": _iso(c.end or c.start),
                "document_id": c.record.document_id, "file_name": c.record.file_name,
                "evidence_code": c.record.document_id, "candidate_id": field_.candidate_id, "review": field_.status, "quantity": c.quantity,
                "unit": c.unit, "share_in_period": c.share, "counted_quantity": c.counted})
        mine = [c for c in bucket.contribs if c.sub == primary.sub]
        base = "MWh" if bucket.family == "electricity" else primary.sub[1]
        units = {c.unit for c in mine}
        if len(units) == 1:
            total = {"quantity": sum(c.counted for c in mine), "unit": next(iter(units))}
        else:
            total = {"quantity": sum(fuel_units.convert_exact(c.counted, c.unit, base) for c in mine), "unit": base}
        return {"rows": rows, "total": total}

    @staticmethod
    def _step2(total: dict[str, Any], to_unit: str, result_quantity: float) -> dict[str, Any]:
        from_unit = str(total["unit"])
        factor = 1.0 if from_unit == to_unit else fuel_units.convert_exact(1, from_unit, to_unit)
        return {"from_unit": from_unit, "to_unit": to_unit, "factor": factor,
                "source": None if from_unit == to_unit else UNIT_SOURCE,
                "result": {"quantity": result_quantity, "unit": to_unit}}

    @staticmethod
    def _distance(bucket: _Bucket, primary: _Sub, subs: list[_Sub]) -> dict[str, Any] | None:
        """On-road mobile only: the fuel economy the group's distance and this line's fuel imply
        (miles per gallon), and the distance it gives. No fuel economy is read from a document."""

        group = bucket.groups.get(primary.sub)
        if bucket.family != "mobile" or group is None or not group.on_road or primary.to_unit != "gal":
            return None
        row = next((r for r in primary.rows if r["gas"] == "CH4"), None)
        if row is None or primary.activity <= 0:
            return None
        miles = float(row["activity"]["value"])
        return {"fuel_economy": {"value": miles / primary.activity, "unit": "mi/gal",
                                 "source": "implied by the vehicle group's distance and the fuel on this line"},
                "result": {"quantity": miles, "unit": "mi"}}

    @staticmethod
    def _route(family: str, primary: _Sub, bucket: _Bucket) -> str:
        if family == "electricity":
            return "Electricity (MWh) × eGRID factor (lb per MWh) ÷ 2,204.62, location-based"
        if family == "stationary":
            if primary.to_unit == "MMBtu":
                return "Energy content × per-MMBtu factor (Eq. 1)"
            return "Fuel quantity × per-unit factor (Eq. 1)"
        text = "Fuel × CO₂ factor (Eq. 1)"
        group = bucket.groups.get(primary.sub)
        if group is None:
            return text
        if group.on_road:
            return text + "; distance × CH₄ and N₂O factors (Eq. 4, on-road)"
        return text + "; fuel × CH₄ and N₂O factors (Eq. 5, non-road)"

    def _results(self, lines: list[calc.LineResult], rows: list[dict[str, Any]], share_pct: float) -> dict[str, Any]:
        mass = {gas: sum(r.mass_t.get(gas, 0.0) for r in lines) for gas in calc.GASES}
        total = sum(mass[gas] * self.gwp[gas]["value"] for gas in calc.GASES)
        return {"mass_t": mass, "gas_co2e_t": {g: mass[g] * self.gwp[g]["value"] for g in calc.GASES},
                "sum_co2e_t": total, "total_co2e_t": total * share_pct / 100,
                "biogenic_co2_t": sum(r.biogenic_co2_t for r in lines)}

    # --- the company's side -----------------------------------------------------------------------
    def _company_and_reported(self, out: dict[str, Any], bucket: _Bucket, subs: list[_Sub], share_pct: float) -> None:
        key = out["key"]
        reported = self.inputs.reported_lines.get(key)
        if reported is not None:
            recomputed = out["results"]["total_co2e_t"]
            out["reported_total_co2e_t"] = reported
            out["difference_t"] = recomputed - reported
            # Judged as the comparisons do: the difference against the reported total of the line's data
            # point (the category's, when the company reported one), else against the line's own total.
            base = self.inputs.reported.get(BASE_DATA_POINT.get(out["counts_toward"], "")) or reported
            verdict = calc.compare(out["key"], base, base + out["difference_t"], self.tolerance)
            out["difference_pct_of_base"] = verdict["difference_pct"]
            out["status"] = "within" if verdict["status"] == "within_tolerance" else "above"
        given = self.inputs.reported_activity.get(key)
        if given is None:
            return

        def ask(message: str) -> None:
            self.needs_input.append({"kind": "company_activity", "key": key,
                                     "message": f"{out['level2']}, {out['label']}: {message}"})

        if len(subs) != 1:
            ask("the company's activity cannot be run on a line that mixes units or fuels. "
                "Move the other records to their own line first.")
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
                           co2e_t=mass * row["gwp"]["value"])
            rows.append(row)
        company_mass = {gas: sum(r["mass_t"] for r in rows if r["gas"] == gas) for gas in calc.GASES}
        biogenic = 0.0
        if "biogenic_co2_reported_separately" in sub.result.flags:  # as the category: CO2 is kept apart
            biogenic, company_mass["CO2"] = company_mass["CO2"], 0.0
        total = sum(company_mass[gas] * self.gwp[gas]["value"] for gas in calc.GASES)
        for mine, theirs in zip(out["step3"]["gases"], rows, strict=True):
            mine["company_co2e_t"] = theirs["co2e_t"]
            mine["difference_t"] = mine["co2e_t"] - theirs["co2e_t"]
        by_gas = {gas: sum(r["co2e_t"] for r in rows if r["gas"] == gas) for gas in calc.GASES}
        out["results"]["company_total_co2e_t"] = total * share_pct / 100
        out["results"]["difference_t"] = out["results"]["total_co2e_t"] - total * share_pct / 100
        out["results"]["company_gas_co2e_t"] = by_gas
        out["company"] = {
            "activity": {"quantity": quantity, "unit": entered},
            "step2": {"from_unit": entered, "to_unit": sub.to_unit, "factor": factor,
                      "source": None if unit == sub.to_unit else UNIT_SOURCE, "distance": None,
                      "result": {"quantity": converted, "unit": sub.to_unit}},
            "step3": {"gases": rows},
            "results": {"mass_t": company_mass, "sum_co2e_t": total, "total_co2e_t": total * share_pct / 100,
                        "biogenic_co2_t": biogenic}}
        if bucket.family == "mobile" and bucket.groups.get(sub.sub) is not None:
            out["flags"] = sorted({*out["flags"], "company_ch4_n2o_use_vehicle_group"})


def build(service: EngagementRecalculationService, records: list[ReviewedRecord], inputs: RecalculationInputs,
          settings: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> Built:
    """The calculation lines of one recalculation (``service`` has just run it)."""

    facilities = setup_facilities(settings)
    ref = service.reference
    placements = {
        id(r): cl.place_record(r, ref=ref, facilities=facilities, decisions=decisions,
                               vehicle_groups=inputs.vehicle_groups, fuel_choices=inputs.fuel_choices)
        for r in records}
    system = cl.default_lines(placements.values(), facilities, inputs.vehicle_groups)
    known = {line.key: line for line in cl.merge_lines(system, cl.user_lines(settings))}
    target_of = _targets(records, placements, set(known), decisions)
    builder = _Builder(service, inputs, materiality_tolerance(settings))
    facility_names = {cl.facility_anchor_id(f): str(f.get("name")) for f in facilities}
    anchors = cl.vehicle_group_anchors(inputs.vehicle_groups)
    biogenic_fuels = calc.biogenic_fuel_names(ref)

    buckets: dict[Any, _Bucket] = {}

    def anchor_label(line: cl.CalculationLine) -> str | None:
        if line.anchor_kind == "facility":
            return facility_names.get(line.anchor_id, line.label)
        if line.anchor_kind == "vehicle_group":
            return next((cl.vehicle_group_label(g) for a, g in anchors if a == line.anchor_id), line.label)
        return line.label

    for c in service._contributions:
        target = target_of.get(id(c.record), cl.SUPPORTING_UNASSIGNED)
        line = known.get(target)
        if line is not None and line.category in FAMILY_CATEGORIES[c.family]:
            bucket = buckets.setdefault(line.key, _Bucket(c.family, line, line.level2_label, anchor_label(line)))
        else:  # no line, or moved out of its family: reported on its own, never dropped
            name = c.sub[0]
            bucket = buckets.setdefault(("unplaced", c.family, name), _Bucket(
                c.family, None, ELECTRICITY_LEVEL2 if c.family == "electricity" else name,
                name if c.family == "electricity" else None, target))
        bucket.contribs.append(c)
    # Each vehicle group carries its own CH4 and N2O, with or without a fuel record placed on it.
    for (fuel, base), indexed in service._mobile_groups.items():
        category = "biogenic" if fuel.lower() in biogenic_fuels else "mobile"
        for settings_index, group in indexed:
            anchor_id = anchors[settings_index][0]
            made = cl.make_line(category, fuel, fuel, "vehicle_group", anchor_id,
                                f"{fuel}, {cl.vehicle_group_label(inputs.vehicle_groups[settings_index])}",
                                created_by_user=False)
            line = known.get(made.key, made)
            bucket = buckets.setdefault(line.key, _Bucket("mobile", line, line.level2_label, anchor_label(line)))
            bucket.groups[(fuel, base)] = group

    built = Built()
    for key, bucket in buckets.items():
        share = 100.0
        if bucket.line is not None and bucket.line.anchor_kind == "facility":
            share = inputs.consolidated_shares.get(bucket.line.anchor_id, 100.0)
        item = builder.assemble(bucket, share)
        if item is None:
            continue
        (built.lines if bucket.line is not None else built.unplaced).append(item)
    order = {name: i for i, (name, _, _) in enumerate(cl.CATEGORIES)}
    built.lines.sort(key=lambda ln: (order.get(ln["category"], 99), ln["level2"].lower(), str(ln["label"]).lower(),
                                     ln["key"]))
    built.unplaced.sort(key=lambda ln: (ln["counts_toward"], ln["level2"].lower(), str(ln["label"])))
    line_keys = {ln["key"] for ln in built.lines}
    built.inputs = {
        "consolidated_shares": dict(inputs.consolidated_shares),
        "unknown_line_keys": sorted(
            [{"setting": name, "key": k} for name, mapping in
             (("reported_lines", inputs.reported_lines), ("reported_activity", inputs.reported_activity))
             for k in mapping if k not in line_keys],
            key=lambda e: (e["setting"], e["key"])),
    }
    built.needs_input = builder.needs_input
    return built
