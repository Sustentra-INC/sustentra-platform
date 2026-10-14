"""Engagement recalculation: reviewed evidence -> emissions -> reported vs recalculated.

Implements Structure Breakdown steps 3 and 4 of the GHG Required Data workbook for one
engagement:

1. Collect what the reviewer signed off on: the latest *accepted* or *edited* review
   decision for each extracted value. Unreviewed values never reach a number; they are
   listed under ``awaiting_review``.
2. Group the way the workbook asks: one total quantity per fuel type (Scope 1) and one
   total electricity quantity per facility (Scope 2), each prorated to the engagement's
   reporting period by the share of the bill's service period inside it. Refrigerant
   service records are grouped once per refrigerant (Simplified Material Balance).
3. Apply the engagement's recalculation inputs (settings["recalculation"]): GWP set, eGRID
   subregion per facility, EPA fuel for ambiguous fuel codes, renewable-energy
   certificates and the company's reported totals. Anything still missing is listed under
   ``needs_input`` with the choices that would resolve it; nothing is defaulted silently.
4. Run ``emissions_calculator`` and compare each reported data point with its
   recalculated value (difference and % against a 5% tolerance).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.domain.refrigerants import find_refrigerant, mass_unit
from backend.app.reference import egrid_zip
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    GWP_SETS,
    EmissionFactorNotFoundError,
    EmissionFactorReference,
    default_emission_factor_reference,
)
from backend.app.services import emissions_calculator as calc
from backend.app.services import emissions_rollup as rollup
from backend.app.services.data_quality_checks import EvidenceRecord, run_checks
from backend.app.services.refrigerant_extractor import DISPOSAL, INSTALLATION, service_type_of

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REFRIGERANT = "CT-S1-REFRSVC"
THERMAL = "CT-S2-THERMAL"
RECALCULATED_TYPES = (STATIONARY, MOBILE, ELECTRICITY, REFRIGERANT, THERMAL)
# A thermal bill's energy type -> its roll-up source (workbook rows 48, 49, 50).
THERMAL_SOURCE = {"steam": "purchased_steam", "hot_water": "purchased_heating", "chilled_water": "purchased_cooling"}
STEAM_BTU_PER_LB_RANGE = (500.0, 1600.0)  # saturated and superheated steam, as delivered
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
    ("fugitive_total", "Direct emissions from fugitive sources", 45, "t CO2e"),
    ("purchased_electricity_total", "Indirect emissions from purchased electricity (location-based)", 47,
     "t CO2e"),
    ("purchased_steam_total", "Indirect emissions from purchased steam", 48, "t CO2e"),
    ("purchased_heating_total", "Indirect emissions from purchased heating", 49, "t CO2e"),
)
DATA_POINT_KEYS = frozenset(key for key, *_ in DATA_POINTS)

# Every reported data point in the workbook's "Data from summary documents" (rows 22-50),
# for Setup's in-scope list: (key, label, row, unit, layer, Required/Optional, how it is
# checked). "recalculated" rows are in DATA_POINTS; the others are listed, not compared.
DATA_POINT_CATALOGUE: tuple[tuple[str, str, int, str, str, str, str], ...] = (
    ("scope1_total", "Scope 1 (Total)", 22, "t CO2e", "scope1", "Required", "recalculated"),
    ("scope1_co2", "Scope 1 CO2", 23, "t", "scope1", "Required", "recalculated"),
    ("scope1_ch4", "Scope 1 CH4", 24, "t", "scope1", "Required", "recalculated"),
    ("scope1_n2o", "Scope 1 N2O", 25, "t", "scope1", "Required", "recalculated"),
    ("scope1_hfcs", "Scope 1 HFCs", 26, "t", "scope1", "Required", "compared_under_fugitive"),
    ("scope1_pfcs", "Scope 1 PFCs", 27, "t", "scope1", "Required", "compared_under_fugitive"),
    ("scope1_sf6", "Scope 1 SF6", 28, "t", "scope1", "Required", "compared_under_fugitive"),
    ("scope2_location_total", "Scope 2 (Total), location-based", 29, "t CO2e", "scope2", "Required", "recalculated"),
    ("scope2_market_total", "Scope 2 (Total), market-based", 29, "t CO2e", "scope2", "Required", "recalculated"),
    ("scope2_co2", "Scope 2 CO2 (location-based)", 30, "t", "scope2", "Required", "recalculated"),
    ("scope2_ch4", "Scope 2 CH4 (location-based)", 31, "t", "scope2", "Required", "recalculated"),
    ("scope2_n2o", "Scope 2 N2O (location-based)", 32, "t", "scope2", "Required", "recalculated"),
    ("scope2_hfcs", "Scope 2 HFCs", 33, "t", "scope2", "Required", "not_recalculated"),
    ("scope2_pfcs", "Scope 2 PFCs", 34, "t", "scope2", "Required", "not_recalculated"),
    ("scope2_sf6", "Scope 2 SF6", 35, "t", "scope2", "Required", "not_recalculated"),
    ("scope2_nf3", "Scope 2 NF3", 36, "t", "scope2", "Required", "not_recalculated"),
    ("biogenic_co2", "CO2 emissions from biogenic combustion", 37, "t CO2e", "scope1", "Required", "recalculated"),
    ("stationary_combustion_total", "Direct emissions from stationary combustion", 42, "t CO2e", "scope1", "Optional",
     "recalculated"),
    ("mobile_combustion_total", "Direct emissions from mobile combustion", 43, "t CO2e", "scope1", "Optional",
     "recalculated"),
    ("process_total", "Direct emissions from process sources", 44, "t CO2e", "scope1", "Optional",
     "not_recalculated"),
    ("fugitive_total", "Direct emissions from fugitive sources", 45, "t CO2e", "scope1", "Optional", "recalculated"),
    ("agricultural_total", "Direct emissions from agricultural sources", 46, "t CO2e", "scope1", "Optional",
     "not_recalculated"),
    ("purchased_electricity_total", "Indirect emissions from purchased electricity (location-based)", 47, "t CO2e",
     "scope2", "Optional", "recalculated"),
    ("purchased_steam_total", "Indirect emissions from purchased steam", 48, "t CO2e", "scope2", "Optional",
     "recalculated"),
    ("purchased_heating_total", "Indirect emissions from purchased heating", 49, "t CO2e", "scope2", "Optional",
     "recalculated"),
    ("purchased_cooling_total", "Indirect emissions from purchased cooling", 50, "t CO2e", "scope2", "Optional",
     "not_recalculated"),
)
CATALOGUE_KEYS = frozenset(key for key, *_ in DATA_POINT_CATALOGUE)


def validate_out_of_scope(value: Any) -> None:
    """settings["outOfScopeDataPoints"]: the catalogue keys the engagement does not cover."""

    if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
        raise ValueError("outOfScopeDataPoints must be a list of data point keys")
    unknown = sorted(set(value) - CATALOGUE_KEYS)
    if unknown:
        raise ValueError(f"unknown data points: {', '.join(unknown)}")


def out_of_scope(settings: dict[str, Any] | None) -> frozenset[str]:
    return frozenset((settings or {}).get("outOfScopeDataPoints") or [])


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
    # Refrigerant -> GWP the reviewer entered (from the safety data sheet) for gases the EPA Hub lacks.
    refrigerant_gwps: dict[str, float] = field(default_factory=dict)
    # Mobile CH4/N2O (workbook Eq 4 / Eq 5): [{fuel, vehicle_type, factor_fuel_type, on_road,
    # model_year?, distance?, distance_unit?, fuel_quantity?, fuel_unit?, label?}]
    vehicle_groups: list[dict[str, Any]] = field(default_factory=list)
    # Roll-up source -> the reviewer's reason the company has no such source (a true 0).
    absent_sources: dict[str, str] = field(default_factory=dict)
    # Per-gas data point -> the unit the company reported it in ("t" of gas or "t CO2e").
    reported_units: dict[str, str] = field(default_factory=dict)
    # Facility -> heat content of the steam it buys (Btu per lb), for steam billed by weight.
    steam_heat_content: dict[str, float] = field(default_factory=dict)


def validate_recalculation_settings(value: Any) -> None:
    """Raise ValueError when settings["recalculation"] is malformed."""

    if not isinstance(value, dict):
        raise ValueError("recalculation must be an object")
    unknown = set(value) - {"gwp_set", "grid_regions", "fuel_choices", "certificates", "reported",
                            "refrigerant_gwps", "vehicle_groups", "absent_sources", "reported_units",
                            "steam_heat_content"}
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
    gwps = value.get("refrigerant_gwps", {})
    if not isinstance(gwps, dict) or not all(
            isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
            for k, v in gwps.items()):
        raise ValueError("refrigerant_gwps must map each refrigerant to a non-negative number")
    _validate_vehicle_groups(value.get("vehicle_groups", []))
    reported = value.get("reported", {})
    if not isinstance(reported, dict):
        raise ValueError("reported must be an object")
    for key, number in reported.items():
        if key not in rollup.FINAL_OUTPUT_KEYS:
            raise ValueError(f"unknown reported data point: {key}")
        if number is not None and (not isinstance(number, (int, float)) or isinstance(number, bool) or number < 0):
            raise ValueError(f"reported {key} must be a number of 0 or more")
    absent = value.get("absent_sources", {})
    if not isinstance(absent, dict):
        raise ValueError("absent_sources must be an object")
    for key, reason in absent.items():
        if key not in rollup.SOURCE_KEYS:
            raise ValueError(f"unknown emission source: {key}")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError(f"absent_sources {key} needs a reason of at most 500 characters")
    steam = value.get("steam_heat_content", {})
    low, high = STEAM_BTU_PER_LB_RANGE
    if not isinstance(steam, dict) or not all(
            isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and low <= v <= high
            for k, v in steam.items()):
        raise ValueError(f"steam_heat_content maps each facility to Btu per lb between {low:.0f} and {high:.0f}")
    units = value.get("reported_units", {})
    if not isinstance(units, dict):
        raise ValueError("reported_units must be an object")
    for key, unit in units.items():
        if key not in rollup.UNIT_KEYS:
            raise ValueError(f"reported_units does not apply to {key}")
        if unit not in ("t", "t CO2e"):
            raise ValueError(f"reported_units {key} must be t or t CO2e")


VEHICLE_GROUP_KEYS = {"fuel", "vehicle_type", "factor_fuel_type", "on_road", "model_year", "distance",
                      "distance_unit", "fuel_quantity", "fuel_unit", "label"}


def _validate_vehicle_groups(groups: Any) -> None:
    if not isinstance(groups, list) or len(groups) > 200:
        raise ValueError("vehicle_groups must be a list of at most 200 groups")

    def number(value: Any) -> bool:
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0)

    for group in groups:
        if not isinstance(group, dict) or set(group) - VEHICLE_GROUP_KEYS:
            raise ValueError(f"each vehicle group takes only: {', '.join(sorted(VEHICLE_GROUP_KEYS))}")
        for key in ("fuel", "vehicle_type", "factor_fuel_type"):
            if not isinstance(group.get(key), str) or not group[key].strip():
                raise ValueError(f"each vehicle group needs {key}")
        if not isinstance(group.get("on_road"), bool):
            raise ValueError("each vehicle group needs on_road (true or false)")
        year = group.get("model_year")
        if year is not None and (not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 2100):
            raise ValueError("model_year must be a year")
        if not number(group.get("distance")) or not number(group.get("fuel_quantity")):
            raise ValueError("distance and fuel_quantity must be numbers of 0 or more")
        if group.get("distance_unit") not in (None, "mi", "km") or group.get("fuel_unit") not in (None, "gal", "L"):
            raise ValueError("distance_unit is mi or km; fuel_unit is gal or L")
        if group.get("label") is not None and (not isinstance(group["label"], str) or len(group["label"]) > 200):
            raise ValueError("label must be text of at most 200 characters")


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
        refrigerant_gwps={k: float(v) for k, v in (raw.get("refrigerant_gwps") or {}).items()},
        vehicle_groups=[dict(g) for g in raw.get("vehicle_groups") or []],
        absent_sources={k: str(v) for k, v in (raw.get("absent_sources") or {}).items()},
        reported_units={k: str(v) for k, v in (raw.get("reported_units") or {}).items()},
        steam_heat_content={k: float(v) for k, v in (raw.get("steam_heat_content") or {}).items()},
    )


# =========================================================================================
# Setup facilities and the reviewer's document decisions
# =========================================================================================
def _norm_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower()).split())


def match_facility(name: Any, address: Any, facilities: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The Setup facility a bill belongs to: same name, or the same street address
    (one address containing the other, so "15 State Street" matches "15 State Street,
    Albany, NY 12207"). None when nothing matches clearly."""

    bill_name, bill_address = _norm_text(name), _norm_text(address)
    for facility in facilities:
        if bill_name and _norm_text(facility.get("name")) == bill_name:
            return facility
    if len(bill_address) >= 8:
        for facility in facilities:
            setup_address = _norm_text(facility.get("address"))
            if len(setup_address) >= 8 and (setup_address in bill_address or bill_address in setup_address):
                return facility
    return None


def validate_facilities(value: Any) -> None:
    """Raise ValueError when Setup facilities are malformed or name an unknown eGRID subregion."""

    if not isinstance(value, list):
        raise ValueError("facilities must be a list")
    ref = default_emission_factor_reference()
    for facility in value:
        if not isinstance(facility, dict):
            raise ValueError("each facility must be an object")
        region = facility.get("gridRegion")
        if region:
            try:
                ref.electricity(str(region))
            except EmissionFactorNotFoundError as exc:
                raise ValueError(f"facility {facility.get('name')!r}: unknown eGRID subregion {region!r}") from exc


def setup_facilities(settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = (settings or {}).get("facilities") or []
    return [f for f in raw if isinstance(f, dict) and f.get("name")]


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


def rollup_category(canonical_type_id: str, energy_type: Any = None) -> str | None:
    """The roll-up source a recalculated document type belongs to (a thermal bill: by what it bought)."""

    if canonical_type_id == THERMAL:
        return THERMAL_SOURCE.get(str(energy_type or ""), "purchased_steam")
    return {STATIONARY: "stationary_combustion", MOBILE: "mobile_combustion", REFRIGERANT: "fugitive_refrigerants",
            ELECTRICITY: "purchased_electricity"}.get(canonical_type_id)


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
        # Set per recalculation: the engagement's Setup facilities and document decisions.
        self._facilities: list[dict[str, Any]] = []
        self._decisions: dict[str, dict[str, Any]] = {}

    @property
    def reference(self) -> EmissionFactorReference:
        if self._reference is None:
            self._reference = default_emission_factor_reference()
        return self._reference

    # ---------------------------------------------------------------------------------
    def evidence_register(self, engagement_id: str, can_see: Callable[[dict], bool]) -> dict[str, list[dict[str, Any]]]:
        """Every document of the engagement and every extracted value with its latest review,
        for the workpaper export (what was read, what the reviewer decided, who and when)."""

        documents: list[dict[str, Any]] = []
        values: list[dict[str, Any]] = []
        for document in self._upload.list_documents(engagement_id):
            if not can_see(document):
                continue
            document_id = str(document.get("document_id"))
            results = [r for r in self._pipeline.list_extraction_results_by_document(document_id) if can_see(r)]
            latest = results[-1] if results else {}
            documents.append({
                "document_id": document_id, "file_name": document.get("file_name"),
                "uploaded_at": document.get("uploaded_at"), "uploaded_by": document.get("uploaded_by"),
                "canonical_type_id": latest.get("canonical_type_id"),
                "candidate_count": len(latest.get("items") or []),
            })
            decisions: dict[str, dict] = {}
            for decision in self._reviews.list_by_document(document_id):
                if can_see(decision):
                    decisions[str(decision.get("candidate_id"))] = decision
            for item in latest.get("items") or []:
                review = decisions.get(str(item.get("candidate_id"))) or {}
                values.append({
                    "file_name": document.get("file_name"), "record_index": item.get("record_index"),
                    "field": item.get("display_label") or item.get("field_name"),
                    "extracted": item.get("normalized_value"), "unit": item.get("unit"),
                    "decision": review.get("decision") or "not reviewed",
                    "reviewed_value": review.get("reviewed_value"),
                    "reviewed_unit": review.get("reviewed_unit"),
                    "reviewer": review.get("reviewer_id"), "reviewed_at": review.get("reviewed_at"),
                    "page": (item.get("source_reference") or {}).get("page_number"),
                    "snippet": (item.get("source_reference") or {}).get("text_snippet"),
                })
        return {"documents": documents, "values": values}

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
            if canonical_type_id not in RECALCULATED_TYPES:
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
    def recalculate(self, engagement: dict[str, Any], can_see: Callable[[dict], bool],
                    decisions: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        """``decisions``: the reviewer's per-document decisions (facility, withdrawn,
        duplicate / supersedes), keyed by document id."""

        engagement_id = str(engagement.get("id") or engagement.get("engagement_id"))
        inputs = parse_inputs(engagement.get("settings"))
        period = (_date(engagement.get("reporting_period_start")), _date(engagement.get("reporting_period_end")))
        decisions = decisions or {}
        records, set_aside = self._apply_decisions(self.reviewed_records(engagement_id, can_see), decisions)
        self._facilities = setup_facilities(engagement.get("settings"))
        self._decisions = decisions

        needs_input: list[dict[str, Any]] = []
        awaiting: list[dict[str, Any]] = []

        def tag(source: str, asked: int, waiting: int) -> None:
            """The roll-up source each open item belongs to (it marks only that source partial)."""
            for item in needs_input[asked:] + awaiting[waiting:]:
                item.setdefault("category", source)

        mark = (len(needs_input), len(awaiting))
        stationary = self._stationary(records, inputs, period, needs_input, awaiting)
        tag("stationary_combustion", *mark)
        mark = (len(needs_input), len(awaiting))
        mobile = self._mobile(records, inputs, period, needs_input, awaiting)
        tag("mobile_combustion", *mark)
        bills: dict[str, list[dict[str, Any]]] = {}
        region_sources: dict[str, str] = {}
        mark = (len(needs_input), len(awaiting))
        electricity = self._electricity(records, inputs, period, needs_input, awaiting, bills, region_sources)
        tag("purchased_electricity", *mark)
        not_counted: list[dict[str, Any]] = []
        mark = (len(needs_input), len(awaiting))
        fugitive = self._refrigerants(records, inputs, period, needs_input, awaiting, not_counted)
        tag("fugitive_refrigerants", *mark)
        thermal_bills: dict[str, list[dict[str, Any]]] = {}
        thermal = self._thermal(records, inputs, period, needs_input, awaiting, thermal_bills)

        categories: dict[str, calc.CategoryResult | None] = {
            "stationary_combustion": stationary,
            "mobile_combustion": mobile,
            "fugitive_refrigerants": fugitive,
            "purchased_electricity_location_based": None,
            "purchased_electricity_market_based": None,
        }
        for source, facilities in thermal.items():
            location = calc.purchased_thermal(f"{source}_location_based", facilities, self.reference,
                                              gwp_set=inputs.gwp_set)
            # No supplier-specific factor or contract is read yet: market-based uses the same factor.
            market = calc.purchased_thermal(f"{source}_market_based", facilities, self.reference,
                                            gwp_set=inputs.gwp_set, flags=["no_supplier_factor_market_equals_location"])
            for result in (location, market):
                result.details["inputs"] = [{"fuel": f.facility, "unit": "MMBtu", "quantity": f.energy.value,
                                           "documents": thermal_bills.get(f"{source}:{f.facility}", [])}
                                          for f in facilities]
            categories[f"{source}_location_based"] = location
            categories[f"{source}_market_based"] = market
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
                                "documents": bills.get(f.facility, []), "grid_region": f.egrid_subregion,
                                "grid_region_source": region_sources.get(f.facility)} for f in electricity]
            for name in ("purchased_electricity_location_based", "purchased_electricity_market_based"):
                part = categories[name]
                if part is not None:
                    part.details["inputs"] = facility_inputs
                    for line in part.lines:
                        if (region_sources.get(line.key) or "").startswith("ZIP"):
                            line.flags.append("grid_region_from_zip")
                    part.flags = sorted({*part.flags, *(f for line in part.lines for f in line.flags)})

        totals = self._scope_totals(categories)
        incomplete = bool(needs_input or awaiting)
        tolerance = materiality_tolerance(engagement.get("settings"))
        not_in_scope = out_of_scope(engagement.get("settings"))
        open_items = Counter(str(item.get("category")) for item in needs_input + awaiting)
        return {
            "engagement_id": engagement_id,
            "gwp_set": inputs.gwp_set,
            "reporting_period": {"start": period[0].isoformat() if period[0] else None,
                                 "end": period[1].isoformat() if period[1] else None},
            "categories": {k: (v.to_dict() if v is not None else None) for k, v in categories.items()},
            "scope_totals": totals,
            "tolerance_pct": tolerance,
            "comparisons": self._comparisons(inputs, totals, categories, incomplete, tolerance, not_in_scope),
            "needs_input": needs_input,
            "awaiting_review": awaiting,
            "excluded": set_aside + self._outside_period(records, period) + not_counted,
            "not_recalculated": ["Scope 1 fugitive sources other than refrigerants and fire suppression",
                                 "Scope 1 process sources", "Scope 2 cooling"],
            "documents_considered": len({r.document_id for r in records}),
            # Missing months, duplicates, overlapping and cross-year bills (formula library Q-001..Q-005).
            "quality_checks": run_checks([e for r in records if (e := self._evidence_record(r)) is not None], period),
            "rollup": rollup.build_rollup(categories, open_items=open_items, absent=inputs.absent_sources,
                                          reported=inputs.reported, reported_units=inputs.reported_units,
                                          out_of_scope=not_in_scope, tolerance=tolerance, gwp_set=inputs.gwp_set,
                                          ref=self.reference),
        }

    @staticmethod
    def _apply_decisions(records: list[ReviewedRecord], decisions: dict[str, dict[str, Any]]
                         ) -> tuple[list[ReviewedRecord], list[dict[str, Any]]]:
        """Leave out documents the reviewer withdrew, marked as a duplicate, or replaced
        with a superseding one; list them (once per document) with the reason."""

        superseded = {
            str(rel.get("otherDocumentId"))
            for decision in decisions.values()
            for rel in decision.get("relationships") or []
            if isinstance(rel, dict) and rel.get("kind") == "supersedes"
        }
        keep: list[ReviewedRecord] = []
        set_aside: dict[str, dict[str, Any]] = {}
        for record in records:
            decision = decisions.get(record.document_id) or {}
            relationships = [r for r in decision.get("relationships") or [] if isinstance(r, dict)]
            if decision.get("disposition") == "withdrawn":
                reason = "withdrawn"
            elif any(r.get("kind") == "duplicate" for r in relationships):
                reason = "duplicate"
            elif record.document_id in superseded:
                reason = "superseded"
            else:
                keep.append(record)
                continue
            set_aside.setdefault(record.document_id, {
                "document_id": record.document_id, "record": record.file_name or record.document_id,
                "canonical_type_id": record.canonical_type_id, "period": "", "reason": reason})
        return keep, list(set_aside.values())

    @staticmethod
    def _outside_period(records: list[ReviewedRecord], period: tuple[date | None, date | None]
                        ) -> list[dict[str, Any]]:
        """Records whose dates fall entirely outside the reporting period, so nothing of them
        is counted. Listed so the cutoff is visible instead of the record silently vanishing."""

        out: list[dict[str, Any]] = []
        for record in records:
            if record.canonical_type_id == MOBILE:
                start = end = record.best("transaction_date")
            elif record.canonical_type_id == REFRIGERANT:
                start = end = record.best("service_date")
            elif record.canonical_type_id in (STATIONARY, ELECTRICITY):
                start, end = record.best("service_period_start"), record.best("service_period_end")
            else:
                continue
            if _proration(start, end, period)[1] == "outside_reporting_period":
                out.append({"document_id": record.document_id, "record": record.label,
                            "canonical_type_id": record.canonical_type_id,
                            "period": str(start) if start == end else f"{start} to {end}",
                            "reason": "outside_reporting_period"})
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
        lines = {fuel.lower() for fuel, _ in totals}
        for group in inputs.vehicle_groups:  # a group for a fuel with no reviewed records adds nothing
            fuel_name = str(group.get("fuel", "")).strip()
            if fuel_name.lower() not in lines:
                needs_input.append({
                    "kind": "vehicle_group", "key": f"{fuel_name}|unused",
                    "message": f"{fuel_name}, {group.get('label') or group.get('vehicle_type')}: there are no reviewed "
                               f"{fuel_name} records in the reporting period, so this vehicle group is not used.",
                })
        if not totals:
            return None
        fuels = []
        for (fuel, base), entry in totals.items():
            measure = calc.Measure(entry["quantity"], base, f"{len(entry['documents'])} reviewed record(s)")
            groups, group_flags = self._vehicle_groups(fuel, measure, inputs, needs_input)
            entry["flags"].update(group_flags)
            fuels.append(calc.MobileFuel(fuel, measure, vehicle_groups=groups))
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

    def _vehicle_groups(self, fuel: str, fuel_total: calc.Measure, inputs: RecalculationInputs,
                        needs_input: list[dict[str, Any]]) -> tuple[list[calc.VehicleGroup], list[str]]:
        """The reviewer's vehicle groups for one fuel, checked against the EPA tables.

        On-road groups need distance (Eq 4) and, where the factor depends on it, a model
        year; a model year newer than the table uses its newest year. A non-road group
        needs the fuel it used (Eq 5), except when it is the fuel's only group: then it
        used all of it. A group that cannot be used is asked about and left out.
        """

        mine = [g for g in inputs.vehicle_groups if str(g.get("fuel", "")).strip().lower() == fuel.lower()]
        types = {(t["vehicle_type"].lower(), t["fuel_type"].lower(), t["on_road"]): t
                 for t in self.reference.vehicle_types()}
        groups: list[calc.VehicleGroup] = []
        flags: list[str] = []
        for index, group in enumerate(mine, start=1):
            label = str(group.get("label") or f"{group['vehicle_type']} ({group['factor_fuel_type']})")
            key = f"{fuel}|{index}"

            def ask(message: str, group_label: str = label, ask_key: str = key) -> None:
                needs_input.append({"kind": "vehicle_group", "key": ask_key,
                                    "message": f"{fuel}, {group_label}: {message}"})

            on_road = bool(group["on_road"])
            known = types.get((str(group["vehicle_type"]).lower(), str(group["factor_fuel_type"]).lower(), on_road))
            if known is None:
                ask(f"no {'on-road' if on_road else 'non-road'} CH4/N2O factor for this vehicle type and fuel "
                    f"in the EPA Hub ({'Tables 3-4' if on_road else 'Table 5'}).")
                continue
            source = f"vehicle group: {label}"
            if on_road:
                if group.get("distance") is None:
                    ask("enter the distance driven in the reporting period (Eq 4).")
                    continue
                year = group.get("model_year")
                if known["by_model_year"]:
                    if year is None:
                        ask("enter the model year: this factor depends on it.")
                        continue
                    first, last = known["first_model_year"], known["last_model_year"]
                    if last is not None and year > last:
                        year = last
                        flags.append("model_year_newer_than_table")
                    elif first is not None and year < first:
                        year = first
                        flags.append("model_year_older_than_table")
                unit = "km" if group.get("distance_unit") == "km" else "mi"
                groups.append(calc.VehicleGroup(known["vehicle_type"], known["fuel_type"], True, year,
                                                distance=calc.Measure(float(group["distance"]), unit, source)))
            else:
                quantity = group.get("fuel_quantity")
                if quantity is None:
                    if len(mine) > 1:
                        ask("enter the fuel this group used (Eq 5): the fuel has more than one vehicle group.")
                        continue
                    if fuel_units.dimension_of(fuel_total.unit) != fuel_units.LIQUID_VOLUME:
                        ask("enter the fuel this group used in gallons or litres (Eq 5).")
                        continue
                    measure = calc.Measure(fuel_total.value, fuel_total.unit, "all of this fuel (its only group)")
                else:
                    measure = calc.Measure(float(quantity), "L" if group.get("fuel_unit") == "L" else "gal", source)
                groups.append(calc.VehicleGroup(known["vehicle_type"], known["fuel_type"], False,
                                                fuel_quantity=measure))
        return groups, flags

    # =================================================================================
    # Scope 2 electricity
    # =================================================================================
    def _electricity(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                     period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                     awaiting: list[dict[str, Any]], bills: dict[str, list[dict[str, Any]]] | None = None,
                     region_sources: dict[str, str] | None = None) -> list[calc.FacilityElectricity]:
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
            setup = self._setup_facility(record)
            key = setup["name"] if setup else " ".join(
                str(record.best("facility_name") or record.best("service_address") or "Unnamed facility").split())
            entry = facilities.setdefault(key, {"mwh": 0.0, "documents": [], "address": record.best("service_address"),
                                                "setup_region": (setup or {}).get("gridRegion"),
                                                "setup_address": (setup or {}).get("address")})
            entry["mwh"] += mwh
            entry["documents"].append({"document_id": record.document_id, "record": record.label,
                                       "quantity": quantity, "unit": unit, "share_in_period": prorate[0]})
        out: list[calc.FacilityElectricity] = []
        for key, entry in facilities.items():
            # A choice on the results screen wins, then the facility's region from Setup, then
            # its ZIP code when EPA maps that ZIP code to a single subregion.
            region = inputs.grid_regions.get(key)
            source = "chosen under Recalculation inputs"
            if not region and entry.get("setup_region"):
                region, source = entry["setup_region"], "set in Setup"
            if region:
                try:
                    self.reference.electricity(region)
                except EmissionFactorNotFoundError:
                    region = None
            zip_code = egrid_zip.zip_from_address(entry.get("setup_address")) or egrid_zip.zip_from_address(
                entry.get("address"))
            candidates = egrid_zip.subregions_for_zip(zip_code)
            if not region and len(candidates) == 1:
                region, source = candidates[0], f"ZIP {zip_code} ({egrid_zip.DATASET})"
            if not region:
                where = f" ({entry['address']})" if entry.get("address") else ""
                if len(candidates) > 1:
                    message = (f"Choose the eGRID subregion for {key}{where}: ZIP {zip_code} is served by "
                               f"{' or '.join(candidates)}. Choose by the facility's electric utility.")
                else:
                    message = f"Choose the eGRID subregion for {key}{where}."
                needs_input.append({
                    "kind": "grid_region", "key": key, "message": message,
                    "options": candidates if len(candidates) > 1 else [
                        r["egrid_subregion"] for r in self.reference.egrid_subregions()],
                })
                continue
            if region_sources is not None:
                region_sources[key] = source
            if bills is not None:
                bills[key] = entry["documents"]
            out.append(calc.FacilityElectricity(key, calc.Measure(entry["mwh"], "MWh",
                                                                  f"{len(entry['documents'])} reviewed bill(s)"),
                                                region))
        return out

    # =================================================================================
    # Scope 2 purchased steam, heat and cooling
    # =================================================================================
    def _thermal(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                 period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                 awaiting: list[dict[str, Any]], bills: dict[str, list[dict[str, Any]]]
                 ) -> dict[str, list[calc.FacilityThermal]]:
        """MMBtu of purchased steam and of purchased heat (hot water) per facility, prorated to
        the reporting period. Steam billed by weight needs its heat content (Btu per lb) from
        the reviewer. Cooling (chilled water) is listed, not calculated: the EPA Hub has no
        default factor for it."""

        totals: dict[tuple[str, str], dict[str, Any]] = {}
        for record in (r for r in records if r.canonical_type_id == THERMAL):
            source = rollup_category(THERMAL, record.best("energy_type")) or "purchased_steam"
            before = len(awaiting)
            if not self._require_reviewed(record, ("activity_quantity", "energy_type"), awaiting):
                for item in awaiting[before:]:
                    item["category"] = source
                continue
            source = rollup_category(THERMAL, record.reviewed("energy_type")) or source
            prorate = _proration(record.best("service_period_start"), record.best("service_period_end"), period)
            if prorate[0] == 0:  # entirely outside the reporting period: listed under "excluded"
                continue
            setup = self._setup_facility(record)
            facility = setup["name"] if setup else " ".join(
                str(record.best("facility_name") or record.best("service_address") or "Unnamed facility").split())
            if source == "purchased_cooling":
                needs_input.append({
                    "kind": "cooling_factor", "key": record.label, "category": source,
                    "message": f"{record.label}: purchased cooling (chilled water) is not calculated yet. The EPA "
                    "Hub has no default factor; it needs the supplier's emission factor or the chiller's efficiency.",
                })
                continue
            amount = self._quantity(record, prorate)
            if amount is None:
                needs_input.append({"kind": "quantity", "key": record.label, "category": source,
                                    "message": f"{record.label}: the thermal quantity must be a number with its unit."})
                continue
            quantity, unit = amount
            if fuel_units.dimension_of(unit) == fuel_units.MASS:
                btu_per_lb = inputs.steam_heat_content.get(facility)
                if btu_per_lb is None:
                    if not any(i.get("kind") == "steam_heat_content" and i.get("key") == facility for i in needs_input):
                        needs_input.append({
                            "kind": "steam_heat_content", "key": facility, "category": source,
                            "message": f"{facility}: steam is billed by weight ({unit}). Enter its heat content "
                            "in Btu per lb from the supplier (often 1,000 to 1,200).",
                        })
                    continue
                pounds = fuel_units.convert(quantity, unit, "lb")
                mmbtu = pounds * btu_per_lb / 1_000_000
            elif fuel_units.dimension_of(unit) == fuel_units.ENERGY:
                mmbtu = fuel_units.convert(quantity, unit, "MMBtu")
            else:
                needs_input.append({"kind": "quantity", "key": record.label, "category": source,
                                    "message": f"{record.label}: {unit} is not a thermal energy unit."})
                continue
            entry = totals.setdefault((source, facility), {"mmbtu": 0.0, "documents": []})
            entry["mmbtu"] += mmbtu
            entry["documents"].append({"document_id": record.document_id, "record": record.label,
                                       "quantity": quantity, "unit": unit, "share_in_period": prorate[0]})
        out: dict[str, list[calc.FacilityThermal]] = {}
        for (source, facility), entry in totals.items():
            bills[f"{source}:{facility}"] = entry["documents"]
            out.setdefault(source, []).append(calc.FacilityThermal(
                facility, calc.Measure(entry["mmbtu"], "MMBtu", f"{len(entry['documents'])} reviewed bill(s)")))
        return out

    # =================================================================================
    # Scope 1 fugitive: refrigerants and fire suppression
    # =================================================================================
    def _refrigerants(self, records: list[ReviewedRecord], inputs: RecalculationInputs,
                      period: tuple[date | None, date | None], needs_input: list[dict[str, Any]],
                      awaiting: list[dict[str, Any]], not_counted: list[dict[str, Any]]
                      ) -> calc.CategoryResult | None:
        """Simplified Material Balance per refrigerant from reviewed service records.

        service: P_S += added; installation: P_N += added, C_N += full charge;
        disposal: C_D += full charge, R_D += recovered. CFCs and HCFCs (Montreal Protocol
        gases) are listed as not counted; a gas without a Hub GWP asks for one.
        """

        needed = {INSTALLATION: ("refrigerant_added", "equipment_capacity"),
                  DISPOSAL: ("equipment_capacity", "refrigerant_recovered")}
        totals: dict[str, dict[str, Any]] = {}
        for record in (r for r in records if r.canonical_type_id == REFRIGERANT):
            kind = service_type_of(record.best("service_type"))
            names = ("refrigerant_type",) + needed.get(kind, ("refrigerant_added",))
            if record.best("service_type") is not None:
                names += ("service_type",)
            if not self._require_reviewed(record, names, awaiting):
                continue
            day = record.best("service_date")
            if _proration(day, day, period)[0] == 0:  # listed under "excluded"
                continue
            text = str(record.reviewed("refrigerant_type") or "").strip()
            if not text:
                needs_input.append({"kind": "refrigerant_record", "key": f"{record.label}:refrigerant_type",
                                    "message": f"{record.label}: the refrigerant is blank. Enter it in Extraction "
                                               "Review to include this record."})
                continue
            found = find_refrigerant(text)
            gas = found.name if found is not None else text
            if found is not None and found.montreal:
                not_counted.append({"document_id": record.document_id, "record": record.label,
                                    "canonical_type_id": REFRIGERANT, "period": str(day or ""),
                                    "reason": "montreal_protocol_gas", "gas": gas})
                continue
            amounts: dict[str, float] = {}
            unit = None
            for name in names[1:]:
                if name == "service_type":
                    continue
                mass = self._mass(record, name)
                if mass is None:
                    needs_input.append({"kind": "quantity", "key": f"{record.label}:{name}",
                                        "message": f"{record.label}: the {name.replace('_', ' ')} or its unit "
                                                   "(lb or kg) is not a usable number."})
                    break
                amounts[name] = mass[0] if unit is None or mass[1] == unit else fuel_units.convert_exact(
                    mass[0], mass[1], unit)
                unit = unit or mass[1]
            else:
                # A term that would come out negative is a data question, not an emission:
                # equipment charged below its full charge usually came pre-charged (EPA: leave
                # both out), and more recovered than the equipment held is a misread amount.
                if kind == INSTALLATION and amounts["refrigerant_added"] < amounts["equipment_capacity"]:
                    needs_input.append({
                        "kind": "refrigerant_record", "key": f"{record.label}:installation",
                        "message": f"{record.label}: {amounts['refrigerant_added']:g} {unit} charged into new "
                                   f"equipment with a full charge of {amounts['equipment_capacity']:g} {unit}. If it "
                                   "came pre-charged, set the service type to service and the amount to what was "
                                   "added on site; otherwise correct the amounts."})
                    continue
                if kind == DISPOSAL and amounts["refrigerant_recovered"] > amounts["equipment_capacity"]:
                    needs_input.append({
                        "kind": "refrigerant_record", "key": f"{record.label}:disposal",
                        "message": f"{record.label}: {amounts['refrigerant_recovered']:g} {unit} recovered from "
                                   f"equipment with a full charge of {amounts['equipment_capacity']:g} {unit}. "
                                   "Check both amounts in Extraction Review."})
                    continue
                entry = totals.setdefault(gas, {"unit": unit, "terms": dict.fromkeys(
                    ("P_N", "C_N", "P_S", "C_D", "R_D"), 0.0), "documents": []})
                if entry["unit"] != unit:
                    amounts = {k: fuel_units.convert_exact(v, str(unit), entry["unit"]) for k, v in amounts.items()}
                terms = entry["terms"]
                if kind == INSTALLATION:
                    terms["P_N"] += amounts["refrigerant_added"]
                    terms["C_N"] += amounts["equipment_capacity"]
                elif kind == DISPOSAL:
                    terms["C_D"] += amounts["equipment_capacity"]
                    terms["R_D"] += amounts["refrigerant_recovered"]
                else:
                    terms["P_S"] += amounts["refrigerant_added"]
                entry["documents"].append({
                    "document_id": record.document_id, "record": record.label, "service_type": kind,
                    "quantity": amounts.get("refrigerant_added", amounts.get("refrigerant_recovered", 0.0)),
                    "unit": entry["unit"]})
        uses: list[calc.RefrigerantUse] = []
        for gas, entry in totals.items():
            override = next((v for k, v in inputs.refrigerant_gwps.items() if k.strip().lower() == gas.lower()), None)
            if override is None:
                try:
                    self.reference.gwp(gas, inputs.gwp_set)
                except EmissionFactorNotFoundError:
                    needs_input.append({
                        "kind": "refrigerant_gwp", "key": gas,
                        "message": f"No {inputs.gwp_set} GWP for {gas} in the EPA GHG Emission Factors Hub "
                                   "(Tables 11-12). Enter it from the refrigerant's safety data sheet.",
                    })
                    continue
            terms = entry["terms"]
            uses.append(calc.RefrigerantUse(
                gas, entry["unit"], new_charged=terms["P_N"], new_capacity=terms["C_N"], serviced=terms["P_S"],
                retired_capacity=terms["C_D"], recovered=terms["R_D"],
                source=f"{len(entry['documents'])} reviewed record(s)", gwp_override=override,
                gwp_override_source="entered by the reviewer (safety data sheet)" if override is not None else None))
        if not uses:
            return None
        result = calc.refrigerants(uses, self.reference, gwp_set=inputs.gwp_set)
        result.details["inputs"] = [
            {"fuel": use.gas, "unit": use.unit, "quantity": result.lines[i].steps[0].result,
             "documents": totals[use.gas]["documents"]}
            for i, use in enumerate(uses)
        ]
        return result

    @staticmethod
    def _mass(record: ReviewedRecord, name: str) -> tuple[float, str] | None:
        """A reviewed refrigerant amount in lb or kg (ounces and grams converted)."""

        number = _number(record.reviewed(name))
        if number is None:
            return None
        unit = mass_unit(record.unit_of(name))
        if unit == "oz":
            return number / 16, "lb"
        if unit == "g":
            return number / 1000, "kg"
        return (number, unit) if unit in ("lb", "kg") else None

    def _evidence_record(self, record: ReviewedRecord) -> EvidenceRecord | None:
        """A record as the data quality checks see it (extracted values count before review:
        the checks are about the documents, not the numbers)."""

        category = rollup_category(record.canonical_type_id, record.best("energy_type"))
        if category is None:
            return None
        setup = self._setup_facility(record)
        facility = setup["name"] if setup else " ".join(
            str(record.best("facility_name") or record.best("service_address") or "Facility not known").split())
        amounts: tuple[float | None, ...]
        if record.canonical_type_id == REFRIGERANT:
            start = end = _date(record.best("service_date"))
            item = " ".join(str(x) for x in (record.best("refrigerant_type"), record.best("equipment_id")) if x) or None
            amounts = tuple(_number(record.best(n)) for n in
                            ("refrigerant_added", "refrigerant_recovered", "equipment_capacity"))
            unit = record.unit_of("refrigerant_added")
        else:
            if record.canonical_type_id == MOBILE:
                start = end = _date(record.best("transaction_date"))
            else:
                start, end = _date(record.best("service_period_start")), _date(record.best("service_period_end"))
            item = None if record.canonical_type_id == ELECTRICITY else (str(record.best("fuel_type") or "") or None)
            amounts = (_number(record.best("activity_quantity")),)
            unit = record.unit_of("activity_quantity")
        # A bill covers a service period; a delivery or purchase on one day is an event.
        periodic = record.canonical_type_id in (STATIONARY, ELECTRICITY, THERMAL) and not (start and end and start == end)
        account = record.best("account_number")
        return EvidenceRecord(category=category, document_id=record.document_id,
                              file_name=record.file_name or record.document_id, label=record.label,
                              facility=facility, item=item, account=str(account) if account else None,
                              start=start, end=end, amounts=amounts, unit=unit, periodic=periodic)

    def _setup_facility(self, record: ReviewedRecord) -> dict[str, Any] | None:
        """The reviewer's facility for the bill's document, else a clear name/address match."""

        facilities = self._facilities
        chosen = (self._decisions.get(record.document_id) or {}).get("facilityId")
        if chosen:
            for facility in facilities:
                if facility.get("facilityId") == chosen:
                    return facility
        return match_facility(record.best("facility_name"), record.best("service_address"), facilities)

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
            "scope1": combine(("stationary_combustion", "mobile_combustion", "fugitive_refrigerants")),
            "scope2_location": combine(("purchased_electricity_location_based", "purchased_steam_location_based",
                                        "purchased_heating_location_based")),
            "scope2_market": combine(("purchased_electricity_market_based", "purchased_steam_market_based",
                                      "purchased_heating_market_based")),
        }

    @staticmethod
    def _comparisons(inputs: RecalculationInputs, totals: dict[str, Any],
                     categories: dict[str, calc.CategoryResult | None], incomplete: bool,
                     tolerance: float = calc.COMPARISON_TOLERANCE_PCT,
                     not_in_scope: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
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
            "fugitive_total": category("fugitive_refrigerants"),
            "purchased_electricity_total": category("purchased_electricity_location_based"),
            "purchased_steam_total": category("purchased_steam_location_based"),
            "purchased_heating_total": category("purchased_heating_location_based"),
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
            if key in not_in_scope:  # Setup says the engagement does not cover it: shown, never judged
                item["status"] = "not_in_scope"
            item.update({"key": key, "workbook_row": row, "unit": unit,
                         "inputs_incomplete": incomplete and item["status"] not in ("not_recalculated", "not_in_scope")})
            out.append(item)
        return out
