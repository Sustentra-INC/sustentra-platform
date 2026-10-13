"""Engagement recalculation: reviewed evidence -> emissions -> reported vs recalculated.

Implements Structure Breakdown steps 3 and 4 of the GHG Required Data workbook for one
engagement:

1. Collect what the reviewer signed off on: the latest *accepted* or *edited* review
   decision for each extracted value. Unreviewed values never reach a number; they are
   listed under ``awaiting_review``.
2. Group the way the workbook asks: one total quantity per fuel type (Scope 1) and one
   total electricity quantity per facility (Scope 2), each prorated to the engagement's
   reporting period by the share of the bill's service period inside it.
3. Apply the engagement's recalculation inputs (settings["recalculation"]): GWP set, eGRID
   subregion per facility, EPA fuel for ambiguous fuel codes, renewable-energy
   certificates and the company's reported totals. Anything still missing is listed under
   ``needs_input`` with the choices that would resolve it; nothing is defaulted silently.
4. Run ``emissions_calculator`` and compare each reported data point with its
   recalculated value (difference and % against a 5% tolerance).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    GWP_SETS,
    EmissionFactorNotFoundError,
    EmissionFactorReference,
    default_emission_factor_reference,
)
from backend.app.services import emissions_calculator as calc

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REVIEWED = ("accepted", "edited")

# Unambiguous extractor fuel codes -> EPA names. Everything else asks the reviewer.
STATIONARY_AUTO = {"natural_gas": "Natural Gas", "kerosene": "Kerosene", "diesel": "Distillate Fuel Oil No. 2"}
MOBILE_AUTO = {
    "diesel": "Diesel Fuel",
    "gasoline": "Motor Gasoline",
    "cng": "Compressed Natural Gas (CNG)",
    "lng": "Liquefied Natural Gas (LNG)",
    "jet_fuel": "Kerosene-Type Jet Fuel",
}
# Base unit per dimension used to sum quantities of one fuel across bills.
BASE_UNIT = {
    fuel_units.ENERGY: "MMBtu",
    fuel_units.GAS_VOLUME: "scf",
    fuel_units.LIQUID_VOLUME: "gal",
    fuel_units.MASS: "short_ton",
}

# Reported data points (workbook "Data from summary documents", with its row numbers).
DATA_POINTS: tuple[tuple[str, str, int, str], ...] = (
    ("scope1_total", "Scope 1 (Total)", 22, "t CO2e"),
    ("scope1_co2", "Scope 1 CO2", 23, "t"),
    ("scope1_ch4", "Scope 1 CH4", 24, "t"),
    ("scope1_n2o", "Scope 1 N2O", 25, "t"),
    ("scope1_hfcs", "Scope 1 HFCs", 26, "t"),
    ("scope1_pfcs", "Scope 1 PFCs", 27, "t"),
    ("scope1_sf6", "Scope 1 SF6", 28, "t"),
    ("scope2_location_total", "Scope 2 (Total), location-based", 29, "t CO2e"),
    ("scope2_market_total", "Scope 2 (Total), market-based", 29, "t CO2e"),
    ("scope2_co2", "Scope 2 CO2 (location-based)", 30, "t"),
    ("scope2_ch4", "Scope 2 CH4 (location-based)", 31, "t"),
    ("scope2_n2o", "Scope 2 N2O (location-based)", 32, "t"),
    ("biogenic_co2", "CO2 emissions from biogenic combustion", 37, "t CO2e"),
    ("stationary_combustion_total", "Direct emissions from stationary combustion", 42, "t CO2e"),
    ("mobile_combustion_total", "Direct emissions from mobile combustion", 43, "t CO2e"),
    ("purchased_electricity_total", "Indirect emissions from purchased electricity (location-based)", 47,
     "t CO2e"),
)
DATA_POINT_KEYS = frozenset(key for key, *_ in DATA_POINTS)


# =========================================================================================
# Engagement inputs (settings["recalculation"])
# =========================================================================================
@dataclass
class RecalculationInputs:
    gwp_set: str = DEFAULT_GWP_SET
    grid_regions: dict[str, str] = field(default_factory=dict)  # facility key -> eGRID subregion
    fuel_choices: dict[str, str] = field(default_factory=dict)  # "stationary:fuel_oil" -> EPA name
    certificates: list[dict[str, Any]] = field(default_factory=list)  # [{label, mwh}]
    reported: dict[str, float] = field(default_factory=dict)  # data point key -> value


def validate_recalculation_settings(value: Any) -> None:
    """Raise ValueError when settings["recalculation"] is malformed."""

    if not isinstance(value, dict):
        raise ValueError("recalculation must be an object")
    unknown = set(value) - {"gwp_set", "grid_regions", "fuel_choices", "certificates", "reported"}
    if unknown:
        raise ValueError(f"unknown recalculation settings: {', '.join(sorted(unknown))}")
    if "gwp_set" in value and value["gwp_set"] not in GWP_SETS:
        raise ValueError(f"gwp_set must be one of {', '.join(GWP_SETS)}")
    for key in ("grid_regions", "fuel_choices"):
        mapping = value.get(key, {})
        if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in mapping.items()):
            raise ValueError(f"{key} must map text to text")
    certificates = value.get("certificates", [])
    if not isinstance(certificates, list):
        raise ValueError("certificates must be a list")
    for item in certificates:
        if not isinstance(item, dict) or not isinstance(item.get("mwh"), (int, float)) or item["mwh"] < 0:
            raise ValueError("each certificate needs a non-negative mwh")
    reported = value.get("reported", {})
    if not isinstance(reported, dict):
        raise ValueError("reported must be an object")
    for key, number in reported.items():
        if key not in DATA_POINT_KEYS:
            raise ValueError(f"unknown reported data point: {key}")
        if number is not None and not isinstance(number, (int, float)):
            raise ValueError(f"reported {key} must be a number")


def materiality_tolerance(settings: dict[str, Any] | None) -> float:
    """The engagement's materiality threshold in percent (Setup stores "5%" / "10%"); 5% by default."""

    raw = (settings or {}).get("materialityThreshold")
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*%?\s*", str(raw)) if raw is not None else None
    return float(match.group(1)) if match else calc.COMPARISON_TOLERANCE_PCT


def parse_inputs(settings: dict[str, Any] | None) -> RecalculationInputs:
    raw = (settings or {}).get("recalculation") or {}
    return RecalculationInputs(
        gwp_set=raw.get("gwp_set") or DEFAULT_GWP_SET,
        grid_regions=dict(raw.get("grid_regions") or {}),
        fuel_choices=dict(raw.get("fuel_choices") or {}),
        certificates=list(raw.get("certificates") or []),
        reported={k: float(v) for k, v in (raw.get("reported") or {}).items() if v is not None},
    )


# =========================================================================================
# Reviewed evidence
# =========================================================================================
@dataclass
class ReviewedField:
    name: str
    extracted: Any
    unit: str | None
    status: str  # accepted | edited | rejected | needs_more_evidence | unreviewed
    value: Any  # the value to use: reviewed value, else None
    source_reference: dict[str, Any] | None


@dataclass
class ReviewedRecord:
    document_id: str
    file_name: str | None
    canonical_type_id: str
    record_index: int | None
    fields: dict[str, ReviewedField]

    @property
    def label(self) -> str:
        name = self.file_name or self.document_id
        return name if self.record_index is None else f"{name} (record {self.record_index})"

    def reviewed(self, name: str) -> Any:
        item = self.fields.get(name)
        return item.value if item is not None and item.status in REVIEWED else None

    def best(self, name: str) -> Any:
        """Reviewed value when there is one, else the extracted value (descriptive fields)."""

        item = self.fields.get(name)
        if item is None:
            return None
        return item.value if item.status in REVIEWED else item.extracted

    def unit_of(self, name: str) -> str | None:
        item = self.fields.get(name)
        return item.unit if item is not None else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[,\s$]", "", value)
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _proration(start: Any, end: Any, period: tuple[date | None, date | None]) -> tuple[float, str | None]:
    """Share of a service period inside the reporting period (workbook: prorate to reporting year)."""

    if period[0] is None or period[1] is None:
        return 1.0, "no_reporting_period"
    first, last = _date(start), _date(end)
    if first is None and last is None:
        return 1.0, "no_service_period"
    first = first or last
    last = last or first
    assert first is not None and last is not None
    days = (last - first).days + 1
    if days <= 0:
        return 1.0, "service_period_reversed"
    overlap = (min(last, period[1]) - max(first, period[0])).days + 1
    share = max(0, overlap) / days
    if share == 0:
        return 0.0, "outside_reporting_period"
    return share, None if share == 1 else "prorated_to_reporting_period"


# =========================================================================================
# Service
# =========================================================================================
class EngagementRecalculationService:
    def __init__(self, upload_service: Any, pipeline_service: Any, review_service: Any,
                 reference: EmissionFactorReference | None = None) -> None:
        self._upload = upload_service
        self._pipeline = pipeline_service
        self._reviews = review_service
        self._reference = reference

    @property
    def reference(self) -> EmissionFactorReference:
        if self._reference is None:
            self._reference = default_emission_factor_reference()
        return self._reference

    # ---------------------------------------------------------------------------------
    def reviewed_records(self, engagement_id: str, can_see: Callable[[dict], bool]) -> list[ReviewedRecord]:
        records: list[ReviewedRecord] = []
        for document in self._upload.list_documents(engagement_id):
            if not can_see(document):
                continue
            document_id = str(document.get("document_id"))
            results = [r for r in self._pipeline.list_extraction_results_by_document(document_id) if can_see(r)]
            if not results:
                continue
            latest = results[-1]
            canonical_type_id = str(latest.get("canonical_type_id") or "")
            if canonical_type_id not in (STATIONARY, MOBILE, ELECTRICITY):
                continue
            decisions: dict[str, dict] = {}
            for decision in self._reviews.list_by_document(document_id):
                if can_see(decision):
                    decisions[str(decision.get("candidate_id"))] = decision  # latest wins
            grouped: dict[int | None, dict[str, ReviewedField]] = {}
            for item in latest.get("items") or []:
                review = decisions.get(str(item.get("candidate_id")))
                status = str(review.get("decision")) if review else "unreviewed"
                value = None
                unit = item.get("unit")
                if review and status in REVIEWED:
                    value = review.get("reviewed_value")
                    unit = review.get("reviewed_unit") or unit
                grouped.setdefault(item.get("record_index"), {})[str(item.get("field_name"))] = ReviewedField(
                    name=str(item.get("field_name")), extracted=item.get("normalized_value"), unit=unit,
                    status=status, value=value, source_reference=item.get("source_reference"))
            for record_index, fields in grouped.items():
                records.append(ReviewedRecord(document_id, document.get("file_name"), canonical_type_id,
                                              record_index, fields))
        return records

    # ---------------------------------------------------------------------------------
    def recalculate(self, engagement: dict[str, Any], can_see: Callable[[dict], bool]) -> dict[str, Any]:
        engagement_id = str(engagement.get("id") or engagement.get("engagement_id"))
        inputs = parse_inputs(engagement.get("settings"))
        period = (_date(engagement.get("reporting_period_start")), _date(engagement.get("reporting_period_end")))
        records = self.reviewed_records(engagement_id, can_see)

        needs_input: list[dict[str, Any]] = []
        awaiting: list[dict[str, Any]] = []
        stationary = self._stationary(records, inputs, period, needs_input, awaiting)
        mobile = self._mobile(records, inputs, period, needs_input, awaiting)
        bills: dict[str, list[dict[str, Any]]] = {}
        electricity = self._electricity(records, inputs, period, needs_input, awaiting, bills)

        categories: dict[str, calc.CategoryResult | None] = {
            "stationary_combustion": stationary,
            "mobile_combustion": mobile,
            "purchased_electricity_location_based": None,
            "purchased_electricity_market_based": None,
        }
        if electricity:
            categories["purchased_electricity_location_based"] = calc.electricity_location_based(
                electricity, self.reference, gwp_set=inputs.gwp_set)
            certificates = [calc.Certificate(str(c.get("label") or f"Certificate {i}"), float(c["mwh"]),
                                             c.get("source"))
                            for i, c in enumerate(inputs.certificates, start=1)]
            categories["purchased_electricity_market_based"] = calc.electricity_market_based(
                electricity, certificates, self.reference, gwp_set=inputs.gwp_set)
            # Which reviewed bills each facility's MWh came from, as for the fuel categories.
            facility_inputs = [{"fuel": f.facility, "unit": "MWh", "quantity": f.consumption.value,
                                "documents": bills.get(f.facility, [])} for f in electricity]
            for name in ("purchased_electricity_location_based", "purchased_electricity_market_based"):
                part = categories[name]
                if part is not None:
                    part.details["inputs"] = facility_inputs

        totals = self._scope_totals(categories)
        incomplete = bool(needs_input or awaiting)
        tolerance = materiality_tolerance(engagement.get("settings"))
        return {
            "engagement_id": engagement_id,
            "gwp_set": inputs.gwp_set,
            "reporting_period": {"start": period[0].isoformat() if period[0] else None,
                                 "end": period[1].isoformat() if period[1] else None},
            "categories": {k: (v.to_dict() if v is not None else None) for k, v in categories.items()},
            "scope_totals": totals,
            "tolerance_pct": tolerance,
            "comparisons": self._comparisons(inputs, totals, categories, incomplete, tolerance),
            "needs_input": needs_input,
            "awaiting_review": awaiting,
            "excluded": self._outside_period(records, period),
            "not_recalculated": ["Scope 1 fugitive sources", "Scope 1 process sources",
                                 "Scope 2 steam, heat and cooling"],
            "documents_considered": len({r.document_id for r in records}),
        }

    @staticmethod
    def _outside_period(records: list[ReviewedRecord], period: tuple[date | None, date | None]
                        ) -> list[dict[str, Any]]:
        """Records whose dates fall entirely outside the reporting period, so nothing of them
        is counted. Listed so the cutoff is visible instead of the record silently vanishing."""

        out: list[dict[str, Any]] = []
        for record in records:
            if record.canonical_type_id == MOBILE:
                start = end = record.best("transaction_date")
            elif record.canonical_type_id in (STATIONARY, ELECTRICITY):
                start, end = record.best("service_period_start"), record.best("service_period_end")
            else:
                continue
            if _proration(start, end, period)[1] == "outside_reporting_period":
                out.append({"document_id": record.document_id, "record": record.label,
                            "canonical_type_id": record.canonical_type_id,
                            "period": str(start) if start == end else f"{start} to {end}"})
        return out

    # =================================================================================
    # Scope 1 stationary
    # =================================================================================
    def _fuel_choice(self, kind: str, code: str, quantity_unit: str | None, inputs: RecalculationInputs,
                     needs_input: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
        """EPA fuel name for an extracted fuel code, or None with a needs_input entry."""

        ref = self.reference
        chosen = inputs.fuel_choices.get(f"{kind}:{code}")
        names = ref.stationary_fuel_types() if kind == "stationary" else [r["fuel_type"] for r in ref.data["mobile_co2"]]
        lower = {n.lower(): n for n in names}
        if chosen:
            if chosen.lower() in lower:
                return lower[chosen.lower()], ["fuel_chosen_by_reviewer"]
        if code.lower() in lower:  # reviewer typed an EPA name while editing
            return lower[code.lower()], []
        auto = (STATIONARY_AUTO if kind == "stationary" else MOBILE_AUTO).get(code)
        if kind == "stationary" and code == "propane" and quantity_unit:
            dimension = fuel_units.dimension_of(quantity_unit)
            auto = {fuel_units.LIQUID_VOLUME: "Propane", fuel_units.GAS_VOLUME: "Propane Gas"}.get(dimension)
        if auto:
            flags = ["fuel_auto_matched"]
            if code == "diesel" and kind == "stationary":
                flags.append("diesel_matched_to_distillate_fuel_oil_no_2")
            return auto, flags
        key = f"{kind}:{code}"
        if not any(item.get("key") == key for item in needs_input):
            needs_input.append({
                "kind": "fuel_choice", "key": key,
                "message": f"Choose the EPA fuel for '{code.replace('_', ' ')}' ({kind} combustion).",
                "options": self._fuel_options(kind, code),
            })
        return None, []

    def _fuel_options(self, kind: str, code: str) -> list[str]:
        ref = self.reference
        if kind == "mobile":
            return [r["fuel_type"] for r in ref.data["mobile_co2"]]
        rows = ref.data["stationary_combustion"]
        family = {
            "fuel_oil": lambda r: "Fuel Oil" in r["fuel_type"],
            "coal": lambda r: r["category"] == "Coal and Coke",
            "biomass": lambda r: str(r["category"]).startswith("Biomass Fuels - Solid"),
            "biogas": lambda r: str(r["category"]).startswith("Biomass Fuels - Gaseous"),
            "biodiesel": lambda r: r["fuel_type"].startswith("Biodiesel"),
            "propane": lambda r: r["fuel_type"].startswith("Propane"),
        }.get(code)
        options = [r["fuel_type"] for r in rows if family(r)] if family else []
        return options or [r["fuel_type"] for r in rows]

    def _quantity(self, record: ReviewedRecord, prorate: tuple[float, str | None]
                  ) -> tuple[float, str] | None:
        number = _number(record.reviewed("activity_quantity"))
        unit_text = record.unit_of("activity_quantity") or record.best("activity_unit")
        if number is None or not unit_text:
            return None
        unit = fuel_units.canonical_unit(str(unit_text)) or fuel_units.find_unit(str(unit_text))
        if unit is None:
            return None
        return number * prorate[0], unit

    def _require_reviewed(self, record: ReviewedRecord, names: tuple[str, ...], awaiting: list[dict[str, Any]]
                          ) -> bool:
        missing = [n for n in names if n in record.fields and record.fields[n].status not in REVIEWED]
        absent = [n for n in names if n not in record.fields]
        if missing or absent:
            awaiting.append({"document_id": record.document_id, "record": record.label,
                             "canonical_type_id": record.canonical_type_id,
                             "fields": missing + absent})
            return False
        return True

    def _stationary(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                    period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                    awaiting: list[dict[str, Any]]) -> calc.CategoryResult | None:
        totals: dict[tuple[str, str], dict[str, Any]] = {}
        for record in (r for r in records if r.canonical_type_id == STATIONARY):
            if not self._require_reviewed(record, ("fuel_type", "activity_quantity"), awaiting):
                continue
            prorate = _proration(record.best("service_period_start"), record.best("service_period_end"), period)
            amount = self._quantity(record, prorate)
            if amount is None:
                needs_input.append({"kind": "quantity", "key": record.label,
                                    "message": f"{record.label}: the fuel quantity or its unit is not a usable number."})
                continue
            quantity, unit = amount
            code = str(record.reviewed("fuel_type"))
            fuel, flags = self._fuel_choice("stationary", code, unit, inputs, needs_input)
            if fuel is None or prorate[0] == 0:
                continue
            dimension = fuel_units.dimension_of(unit)
            base = BASE_UNIT.get(dimension)
            if base is None:
                needs_input.append({"kind": "quantity", "key": record.label,
                                    "message": f"{record.label}: {unit} cannot be used without a heat content."})
                continue
            entry = totals.setdefault((fuel, base), {"quantity": 0.0, "documents": [], "flags": set()})
            entry["quantity"] += fuel_units.convert_exact(quantity, unit, base)
            entry["documents"].append({"document_id": record.document_id, "record": record.label,
                                       "quantity": quantity, "unit": unit, "share_in_period": prorate[0]})
            entry["flags"].update(flags + ([prorate[1]] if prorate[1] else []))
        if not totals:
            return None
        usable: dict[tuple[str, str], dict[str, Any]] = {}
        for (fuel, base), entry in totals.items():
            try:  # one unusable fuel line must not stop the others
                calc.stationary_combustion([calc.StationaryFuel(fuel, calc.Measure(entry["quantity"], base))],
                                           self.reference, gwp_set=inputs.gwp_set)
            except (calc.CalculationError, EmissionFactorNotFoundError) as exc:
                needs_input.append({"kind": "fuel_line", "key": f"stationary:{fuel}", "message": str(exc)})
                continue
            usable[(fuel, base)] = entry
        if not usable:
            return None
        totals = usable
        fuels = [calc.StationaryFuel(fuel, calc.Measure(entry["quantity"], base,
                                                        f"{len(entry['documents'])} reviewed record(s)"))
                 for (fuel, base), entry in totals.items()]
        result = calc.stationary_combustion(fuels, self.reference, gwp_set=inputs.gwp_set)
        for line, entry in zip(result.lines, totals.values()):
            line.flags.extend(sorted(entry["flags"]))
        result.details["inputs"] = [{"fuel": fuel, "unit": base, **{k: v for k, v in e.items() if k != "flags"}}
                                    for (fuel, base), e in totals.items()]
        result.flags = sorted({*result.flags, *(f for line in result.lines for f in line.flags)})
        return result

    # =================================================================================
    # Scope 1 mobile
    # =================================================================================
    def _mobile(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                awaiting: list[dict[str, Any]]) -> calc.CategoryResult | None:
        totals: dict[tuple[str, str], dict[str, Any]] = {}
        for record in (r for r in records if r.canonical_type_id == MOBILE):
            if not self._require_reviewed(record, ("fuel_type", "activity_quantity"), awaiting):
                continue
            day = record.best("transaction_date")
            prorate = _proration(day, day, period)
            amount = self._quantity(record, prorate)
            if amount is None:
                needs_input.append({"kind": "quantity", "key": record.label,
                                    "message": f"{record.label}: the fuel quantity or its unit is not a usable number."})
                continue
            quantity, unit = amount
            fuel, flags = self._fuel_choice("mobile", str(record.reviewed("fuel_type")), unit, inputs, needs_input)
            if fuel is None or prorate[0] == 0:
                continue
            base = BASE_UNIT.get(fuel_units.dimension_of(unit))
            if base is None:
                continue
            entry = totals.setdefault((fuel, base), {"quantity": 0.0, "documents": [], "flags": set()})
            entry["quantity"] += fuel_units.convert_exact(quantity, unit, base)
            entry["documents"].append({"document_id": record.document_id, "record": record.label,
                                       "quantity": quantity, "unit": unit})
            entry["flags"].update(flags)
        if not totals:
            return None
        fuels = [calc.MobileFuel(fuel, calc.Measure(entry["quantity"], base,
                                                    f"{len(entry['documents'])} reviewed record(s)"))
                 for (fuel, base), entry in totals.items()]
        try:
            result = calc.mobile_combustion(fuels, self.reference, gwp_set=inputs.gwp_set)
        except (calc.CalculationError, EmissionFactorNotFoundError) as exc:
            needs_input.append({"kind": "mobile", "key": "mobile_combustion", "message": str(exc)})
            return None
        for line, entry in zip(result.lines, totals.values()):
            line.flags.extend(sorted(entry["flags"]))
        result.details["inputs"] = [{"fuel": fuel, "unit": base, **{k: v for k, v in e.items() if k != "flags"}}
                                    for (fuel, base), e in totals.items()]
        result.flags = sorted({*result.flags, *(f for line in result.lines for f in line.flags)})
        return result

    # =================================================================================
    # Scope 2 electricity
    # =================================================================================
    def _electricity(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                     period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                     awaiting: list[dict[str, Any]], bills: dict[str, list[dict[str, Any]]] | None = None,
                     ) -> list[calc.FacilityElectricity]:
        facilities: dict[str, dict[str, Any]] = {}
        for record in (r for r in records if r.canonical_type_id == ELECTRICITY):
            if not self._require_reviewed(record, ("activity_quantity",), awaiting):
                continue
            prorate = _proration(record.best("service_period_start"), record.best("service_period_end"), period)
            if prorate[0] == 0:  # entirely outside the reporting period: listed under "excluded"
                continue
            amount = self._quantity(record, prorate)
            if amount is None or amount[1] not in ("kWh", "MWh"):
                needs_input.append({"kind": "quantity", "key": record.label,
                                    "message": f"{record.label}: electricity must be a number in kWh or MWh."})
                continue
            quantity, unit = amount
            mwh = quantity / 1000 if unit == "kWh" else quantity
            key = " ".join(str(record.best("facility_name") or record.best("service_address")
                               or "Unnamed facility").split())
            entry = facilities.setdefault(key, {"mwh": 0.0, "documents": [], "address": record.best("service_address")})
            entry["mwh"] += mwh
            entry["documents"].append({"document_id": record.document_id, "record": record.label,
                                       "quantity": quantity, "unit": unit, "share_in_period": prorate[0]})
        out: list[calc.FacilityElectricity] = []
        for key, entry in facilities.items():
            region = inputs.grid_regions.get(key)
            if region:
                try:
                    self.reference.electricity(region)
                except EmissionFactorNotFoundError:
                    region = None
            if not region:
                needs_input.append({
                    "kind": "grid_region", "key": key,
                    "message": f"Choose the eGRID subregion for {key}"
                               + (f" ({entry['address']})." if entry.get("address") else "."),
                    "options": [r["egrid_subregion"] for r in self.reference.egrid_subregions()],
                })
                continue
            if bills is not None:
                bills[key] = entry["documents"]
            out.append(calc.FacilityElectricity(key, calc.Measure(entry["mwh"], "MWh",
                                                                  f"{len(entry['documents'])} reviewed bill(s)"),
                                                region))
        return out

    # =================================================================================
    # Totals and comparison
    # =================================================================================
    @staticmethod
    def _scope_totals(categories: dict[str, calc.CategoryResult | None]) -> dict[str, Any]:
        def combine(names: tuple[str, ...]) -> dict[str, Any] | None:
            parts = [(name, part) for name in names if (part := categories.get(name)) is not None]
            if not parts:
                return None
            return {
                "total_co2e": sum(part.total_co2e for _, part in parts),
                "mass_t": {g: sum(part.total_mass_t.get(g, 0.0) for _, part in parts) for g in calc.GASES},
                "co2e_t": {g: sum(part.total_co2e_t.get(g, 0.0) for _, part in parts) for g in calc.GASES},
                "biogenic_co2_t": sum(part.biogenic_co2_t for _, part in parts),
                "categories": [name for name, _ in parts],
            }

        return {
            "scope1": combine(("stationary_combustion", "mobile_combustion")),
            "scope2_location": combine(("purchased_electricity_location_based",)),
            "scope2_market": combine(("purchased_electricity_market_based",)),
        }

    @staticmethod
    def _comparisons(inputs: RecalculationInputs, totals: dict[str, Any],
                     categories: dict[str, calc.CategoryResult | None], incomplete: bool,
                     tolerance: float = calc.COMPARISON_TOLERANCE_PCT) -> list[dict[str, Any]]:
        scope1, s2_location, s2_market = totals["scope1"], totals["scope2_location"], totals["scope2_market"]

        def total_of(part: dict[str, Any] | None) -> float | None:
            return part["total_co2e"] if part else None

        def gas(part: dict[str, Any] | None, name: str) -> float | None:
            return part["mass_t"][name] if part else None

        def category(name: str) -> float | None:
            result = categories.get(name)
            return result.total_co2e if result is not None else None

        recalculated: dict[str, float | None] = {
            "scope1_total": total_of(scope1),
            "scope1_co2": gas(scope1, "CO2"), "scope1_ch4": gas(scope1, "CH4"), "scope1_n2o": gas(scope1, "N2O"),
            "scope2_location_total": total_of(s2_location),
            "scope2_market_total": total_of(s2_market),
            "scope2_co2": gas(s2_location, "CO2"), "scope2_ch4": gas(s2_location, "CH4"),
            "scope2_n2o": gas(s2_location, "N2O"),
            "biogenic_co2": scope1["biogenic_co2_t"] if scope1 else None,
            "stationary_combustion_total": category("stationary_combustion"),
            "mobile_combustion_total": category("mobile_combustion"),
            "purchased_electricity_total": category("purchased_electricity_location_based"),
        }
        out = []
        for key, label, row, unit in DATA_POINTS:
            reported = inputs.reported.get(key)
            value = recalculated.get(key)
            if key in ("scope1_hfcs", "scope1_pfcs", "scope1_sf6"):
                item = {"data_point": label, "reported": reported, "recalculated": None, "difference": None,
                        "difference_pct": None, "status": "not_recalculated"}
            elif value is None:
                item = {"data_point": label, "reported": reported, "recalculated": None, "difference": None,
                        "difference_pct": None, "status": "no_evidence"}
            else:
                item = calc.compare(label, reported, value, tolerance)
            item.update({"key": key, "workbook_row": row, "unit": unit,
                         "inputs_incomplete": incomplete and item["status"] not in ("not_recalculated",)})
            out.append(item)
        return out
