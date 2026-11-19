"""Reviewed evidence, as the recalculation and the Evidence page both read it.

A leaf module (it imports nothing of the services): the canonical types the recalculation
handles, a document's extracted values grouped into records with their latest review decision,
the reviewer's per-document decisions (set aside, facility), the Setup facility match and the
EPA fuel name for an extracted fuel code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services.facility_identifiers import match_by_identifier

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REFRIGERANT = "CT-S1-REFRSVC"
THERMAL = "CT-S2-THERMAL"
REVIEWED = ("accepted", "edited")
NOT_FOR_PLACEMENT = ("rejected", "needs_more_evidence")  # a decision that says do not use this value
AI_SUGGESTED = "ai_suggested"  # validation flag of a value Claude read (services/ai_extraction.py)
# Identifier fields never feed a number (spec A13), so the schedule's Source identifiers counts what Claude read
# in them before a reviewer has decided. Nothing else reads these values: best() and reviewed() stay blank.
AI_IDENTIFIER_FIELDS = ("meter_number", "account_number", "service_address")

# Unambiguous extractor fuel codes -> EPA names. Everything else asks the reviewer.
STATIONARY_AUTO = {"natural_gas": "Natural Gas", "kerosene": "Kerosene", "diesel": "Distillate Fuel Oil No. 2"}
MOBILE_AUTO = {
    "diesel": "Diesel Fuel",
    "gasoline": "Motor Gasoline",
    "cng": "Compressed Natural Gas (CNG)",
    "lng": "Liquefied Natural Gas (LNG)",
    "jet_fuel": "Kerosene-Type Jet Fuel",
}


def to_number(value: Any) -> float | None:
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


def to_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None




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


def resolve_fuel_name(ref: EmissionFactorReference, kind: str, code: str, quantity_unit: str | None,
                      fuel_choices: dict[str, str]) -> tuple[str | None, list[str]]:
    """The EPA fuel name for an extracted fuel code (kind: "stationary" or "mobile") and the
    flags that say how it was found; None when only the reviewer can choose it."""

    chosen = fuel_choices.get(f"{kind}:{code}")
    names = ref.stationary_fuel_types() if kind == "stationary" else [r["fuel_type"] for r in ref.data["mobile_co2"]]
    lower = {n.lower(): n for n in names}
    if chosen and chosen.lower() in lower:
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
    return None, []


def resolve_setup_facility(facilities: list[dict[str, Any]], decisions: dict[str, dict[str, Any]],
                           document_id: str, facility_name: Any, address: Any) -> dict[str, Any] | None:
    """The reviewer's facility for a document, else a clear name/address match."""

    chosen = (decisions.get(document_id) or {}).get("facilityId")
    if chosen:
        for facility in facilities:
            if facility.get("facilityId") == chosen:
                return facility
    return match_facility(facility_name, address, facilities)


@dataclass(frozen=True)
class FacilityPlacement:
    """Where one record's facility comes from. ``how`` says which step placed it. ``note`` says, in a plain
    sentence, why nothing was placed when the account or meter number had something to say about it;
    ``ambiguous`` is set when the numbers point at two or more facilities."""

    facility: dict[str, Any] | None = None
    how: str | None = None
    note: str | None = None
    ambiguous: bool = False


def place_on_facility(facilities: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], document_id: str,
                      record: ReviewedRecord) -> FacilityPlacement:
    """The one place a record's Setup facility is decided: the reviewer's choice, else the facility name,
    else the service address, else (PROVISIONAL, see ``facility_identifiers``) the account or meter number.

    The number is used only when the bill gives no name and no address at all. A bill whose name or address
    matched nothing is never placed by its number: it gets a note that names the facility the number is
    listed on and asks for a choice. Values a reviewer rejected, or that only Claude read, are not read here."""

    chosen = (decisions.get(document_id) or {}).get("facilityId")
    if chosen:
        for facility in facilities:
            if facility.get("facilityId") == chosen:
                return FacilityPlacement(facility, "Chosen by the reviewer")
    name, address = record.for_placement("facility_name"), record.for_placement("service_address")
    if (found := match_facility(name, None, facilities)) is not None:
        return FacilityPlacement(found, "Facility name in Setup")
    if (found := match_facility(None, address, facilities)) is not None:
        return FacilityPlacement(found, "Service address in Setup")
    by_number = match_by_identifier(record.for_placement("account_number"), record.for_placement("meter_number"),
                                    facilities)
    if by_number.ambiguous:
        return FacilityPlacement(note=by_number.ambiguous + ". Choose the facility.", ambiguous=True)
    if by_number.facility is None:
        return FacilityPlacement()
    given = _norm_text(address) and ("address", address) or _norm_text(name) and ("facility name", name) or None
    if given is None:
        return FacilityPlacement(by_number.facility, by_number.reason)
    shown = " ".join(str(given[1]).split())
    return FacilityPlacement(note=f"{by_number.what} is listed on {by_number.facility.get('name')}, but this bill's "
                                  f"{given[0]} ({shown}) is not in Setup. Choose the facility.")


@dataclass
class ReviewedField:
    name: str
    extracted: Any
    unit: str | None
    status: str  # accepted | edited | rejected | needs_more_evidence | unreviewed
    value: Any  # the value to use: reviewed value, else None
    source_reference: dict[str, Any] | None
    candidate_id: str | None = None
    reviewer: str | None = None  # the latest decision's reviewer (login) and time, when there is one
    reviewed_at: Any = None
    history: list[dict[str, Any]] = field(default_factory=list)  # every decision on it, oldest first
    # Claude read two different values for this field (ai_conflict) and the reviewer accepted both:
    # the field counts as unreviewed until one of them is rejected.
    conflict: bool = False
    # What Claude read here, not yet decided by a reviewer (identifier fields only; see AI_IDENTIFIER_FIELDS).
    # Never an input to a calculation: best(), reviewed() and unit_of() do not see it.
    ai_reads: list[Any] = field(default_factory=list)


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

    def for_placement(self, name: str) -> Any:
        """The value that may decide which facility a bill belongs to: reviewed, or read by the rules
        (``best``), but nothing a reviewer rejected or asked for more evidence on."""

        item = self.fields.get(name)
        if item is None or item.status in NOT_FOR_PLACEMENT:
            return None
        return self.best(name)

    def unit_of(self, name: str) -> str | None:
        item = self.fields.get(name)
        return item.unit if item is not None else None

    def identifiers(self, name: str) -> list[tuple[Any, bool]]:
        """The values of an identifier field for the schedule's Source identifiers, each with whether Claude
        read it: the reviewed or rule-read value, else what Claude read and nobody has decided yet. Only for
        display: use ``best`` for anything that feeds a number."""

        item = self.fields.get(name)
        if item is None:
            return []
        value = self.best(name)
        if value not in (None, ""):
            return [(value, False)]
        return [(read, True) for read in item.ai_reads if read not in (None, "")]


def latest_decisions(decisions: Any) -> dict[str, dict]:
    """The latest review decision per candidate id (later entries win)."""

    return {str(d.get("candidate_id")): d for d in decisions}


def all_decisions(decisions: Any) -> dict[str, list[dict]]:
    """Every review decision per candidate id, in the order given (oldest first)."""

    out: dict[str, list[dict]] = {}
    for decision in decisions:
        out.setdefault(str(decision.get("candidate_id")), []).append(decision)
    return out


def group_reviewed_records(document: dict[str, Any], canonical_type_id: str, items: list[dict[str, Any]],
                           decisions: dict[str, dict],
                           history: dict[str, list[dict]] | None = None) -> list[ReviewedRecord]:
    """One document's extracted items grouped into records (by ``record_index``), each field
    carrying its latest review decision (and, given ``history``, every decision on it)."""

    document_id = str(document.get("document_id"))
    candidates: dict[int | None, dict[str, list[ReviewedField]]] = {}
    for item in items:
        review = decisions.get(str(item.get("candidate_id")))
        status = str(review.get("decision")) if review else "unreviewed"
        value = None
        ai_reads: list[Any] = []
        extracted = item.get("normalized_value")
        unit = item.get("unit")
        if review and status in REVIEWED:
            value = review.get("reviewed_value")
            unit = review.get("reviewed_unit") or unit
        elif AI_SUGGESTED in (item.get("validation_flags") or []):
            # Claude's suggestion is not evidence until a reviewer accepts or edits it: nothing
            # downstream (best(), unit_of(), the calculation) may read it before then.
            if status == "unreviewed" and str(item.get("field_name")) in AI_IDENTIFIER_FIELDS:
                ai_reads = [extracted]  # shown under Source identifiers only, labelled as Claude's reading
            extracted, unit = None, None
        candidates.setdefault(item.get("record_index"), {}).setdefault(str(item.get("field_name")), []).append(ReviewedField(
            name=str(item.get("field_name")), extracted=extracted, unit=unit,
            status=status, value=value, source_reference=item.get("source_reference"),
            candidate_id=None if item.get("candidate_id") is None else str(item.get("candidate_id")),
            reviewer=review.get("reviewer_id") if review else None,
            reviewed_at=review.get("reviewed_at") if review else None,
            history=list((history or {}).get(str(item.get("candidate_id")), [])), ai_reads=ai_reads))
    grouped = {record: {name: _one_field(same) for name, same in fields.items()}
               for record, fields in candidates.items()}
    return [ReviewedRecord(document_id, document.get("file_name"), canonical_type_id, record_index, fields)
            for record_index, fields in grouped.items()]


def _one_field(same: list[ReviewedField]) -> ReviewedField:
    """The field of several candidates that share it (Claude's ai_conflict gives a field two).
    The one with an accepted or edited decision counts, so a rejected sibling never hides an
    accepted value; two reviewed with different values leave the field unreviewed (``conflict``).
    With none reviewed, the last one stands, as before."""

    if len(same) == 1:
        return same[0]
    reviewed = [f for f in same if f.status in REVIEWED]
    if not reviewed:
        last = same[-1]
        if any(f.ai_reads for f in same):  # two Claude readings stay two readings
            last.ai_reads = [read for f in same for read in f.ai_reads]
        return last
    first = reviewed[0]
    if all(f.value == first.value and f.unit == first.unit for f in reviewed):
        return reviewed[-1]
    return ReviewedField(name=first.name, extracted=None, unit=None, status="unreviewed", value=None,
                         source_reference=first.source_reference, candidate_id=first.candidate_id, conflict=True)


def superseded_ids(decisions: dict[str, dict[str, Any]]) -> set[str]:
    """Documents another document's decision says it supersedes."""

    return {
        str(rel.get("otherDocumentId"))
        for decision in decisions.values()
        for rel in decision.get("relationships") or []
        if isinstance(rel, dict) and rel.get("kind") == "supersedes"
    }


def set_aside_reason(decisions: dict[str, dict[str, Any]], document_id: str, superseded: set[str]) -> str | None:
    """Why the reviewer's decisions leave a document out (withdrawn, duplicate, superseded), else None."""

    decision = decisions.get(document_id) or {}
    relationships = [r for r in decision.get("relationships") or [] if isinstance(r, dict)]
    if decision.get("disposition") == "withdrawn":
        return "withdrawn"
    if any(r.get("kind") == "duplicate" for r in relationships):
        return "duplicate"
    if document_id in superseded:
        return "superseded"
    return None
