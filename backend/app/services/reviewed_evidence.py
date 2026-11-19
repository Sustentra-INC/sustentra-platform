"""Reviewed evidence, as the recalculation and the Evidence page both read it.

A leaf module (it imports nothing of the services): the canonical types the recalculation
handles, a document's extracted values grouped into records with their latest review decision,
the reviewer's per-document decisions (set aside, facility), the Setup facility match and the
EPA fuel name for an extracted fuel code.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REFRIGERANT = "CT-S1-REFRSVC"
THERMAL = "CT-S2-THERMAL"
REVIEWED = ("accepted", "edited")
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
    """Case, punctuation (dashes included), accents' form and whitespace removed, so only the words and numbers
    are compared. Letters of any script are kept."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


# USPS street-suffix, directional and unit abbreviations (Publication 28), written out -> abbreviated. Both sides
# of a comparison are put in the abbreviated form, so "Road" and "Rd", "East" and "E" are the same word.
_STREET_ABBREVIATIONS = {
    "alley": "aly", "avenue": "ave", "av": "ave", "boulevard": "blvd", "circle": "cir", "court": "ct",
    "drive": "dr", "expressway": "expy", "freeway": "fwy", "highway": "hwy", "lane": "ln", "parkway": "pkwy",
    "place": "pl", "plaza": "plz", "road": "rd", "square": "sq", "street": "st", "terrace": "ter", "trail": "trl",
    "turnpike": "tpke", "way": "way", "mall": "mall", "loop": "loop", "pike": "pike", "crossing": "xing",
    "center": "ctr", "centre": "ctr", "route": "rte", "suite": "ste", "apartment": "apt", "floor": "fl",
    "room": "rm", "north": "n", "south": "s", "east": "e", "west": "w", "northeast": "ne", "northwest": "nw",
    "southeast": "se", "southwest": "sw",
}
_STREET_SUFFIXES = frozenset(_STREET_ABBREVIATIONS.values()) - {"ste", "apt", "fl", "rm", "n", "s", "e", "w", "ne",
                                                                  "nw", "se", "sw", "hwy", "rte"}
_ROUTE_WORDS = frozenset({"hwy", "rte"})  # "Highway 99", "State Route 9": the route number ends the street
_DIRECTIONS = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})
# Read as a unit only right after the street ("Ste 300", "# 4", "Unit 4") and only when a short token follows that
# is not a postal code: "FL 33101" is Florida and "Ste. Genevieve" is a town.
_UNIT_WORDS = frozenset({"ste", "apt", "unit", "rm", "fl"})
_CORPORATE_SUFFIXES = frozenset({"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
                                 "company", "plc", "gmbh", "ag", "sa"})
_NAME_SEPARATOR = re.compile(r"\s[-\u2010-\u2015\u2212]\s")  # " - ", " \u2013 ", " \u2014 ": a dash with spaces round it
_PO_BOX = re.compile(r"\bp\.?\s?o\.?\s*box\s*\w+|\bpost\s+office\s+box\s*\w+")
_HOUSE_NUMBER = re.compile(r"^\d+[a-z]?$")


def _company_key(value: Any) -> str:
    words = _norm_text(value).split()
    while words and words[-1] in _CORPORATE_SUFFIXES:
        words.pop()
    return " ".join(words)


def _facility_names(name: Any, company: Any) -> set[str]:
    """What a bill's facility name may be called: as written, and without a leading "Company - " when that
    company is the engagement's own (the site name is what follows the dash)."""

    names = {_norm_text(name)} - {""}
    company_key = _company_key(company)
    if company_key and name:
        parts = _NAME_SEPARATOR.split(str(name), maxsplit=1)
        if len(parts) == 2 and _company_key(parts[0]) == company_key and _norm_text(parts[1]):
            names.add(_norm_text(parts[1]))
    return names


def _segments(address: Any, drop_po_box: bool) -> list[list[str]]:
    """The address as comma-separated segments of lower-case words in the USPS spelling. "#" is a unit word.
    A PO box is dropped when asked: its number is never a house number."""

    text = unicodedata.normalize("NFKC", str(address or "")).casefold().replace("#", " unit ")
    if drop_po_box:
        text = _PO_BOX.sub(" ", text)
    out = []
    for part in re.split(r"[,;\n]", text):
        words = [_STREET_ABBREVIATIONS.get(w, w) for w in re.findall(r"\w+", part)]
        if words:
            out.append(words)
    return out


def _is_street_line(words: list[str]) -> bool:
    return bool(words) and bool(_HOUSE_NUMBER.match(words[0])) and any(w in _STREET_SUFFIXES for w in words[2:])


class _Address:
    """A street address split into street (house number to its end), unit, and the rest (city, state, postal
    code). ``street`` is None when no house number could be found."""

    def __init__(self, address: Any) -> None:
        self.full = _segments(address, drop_po_box=False)  # with its commas: "St, West Sacramento" is not "St W, Sacramento"
        self.street: list[str] | None = None
        self.unit: str | None = None
        self.rest: list[str] = []
        segments = _segments(address, drop_po_box=True)
        starts = [(si, wi) for si, seg in enumerate(segments) for wi, w in enumerate(seg)
                  if _HOUSE_NUMBER.match(w) and wi + 1 < len(seg) and not seg[wi + 1][0].isdigit()]
        if not starts:
            return
        # the house number is the one on a line with a street suffix ("3M Company, 100 Main St"). With none, there
        # is no street: a postal code is not a house number ("Hauptstrasse 5, 8001 Zürich"), so only equal text matches
        found = next(((a, b) for a, b in starts if any(w in _ROUTE_WORDS for w in segments[a][b + 1:])
                      or any(w in _STREET_SUFFIXES for w in segments[a][b + 2:])), None)
        if found is None:
            return
        si, wi = found
        words = segments[si][wi:]
        end = len(words)
        route = next((i for i, w in enumerate(words) if i >= 1 and w in _ROUTE_WORDS), None)
        suffix = next((i for i, w in enumerate(words) if i >= 2 and w in _STREET_SUFFIXES), None)
        if route is not None and (suffix is None or route < suffix):
            end = route + 2 if route + 1 < len(words) and words[route + 1].isdigit() else route + 1
        elif suffix is not None:
            end = suffix + 1
            if end < len(words) and words[end] in _DIRECTIONS:  # only with no comma between: "St W", not "St, West ..."
                end += 1
        self.street = words[:end]
        rest = words[end:]
        for seg in segments[si + 1:]:
            if not _is_street_line(seg):  # two street lines: the first is the address
                rest += seg
        if len(rest) >= 2 and rest[0] in _UNIT_WORDS and len(rest[1]) <= 4 and not re.fullmatch(r"\d{5}", rest[1]):
            self.unit = rest[1]
            rest = rest[2:]
        self.rest = rest


def _names_a_place(segments: list[list[str]]) -> bool:
    """Equal text identifies a place only when it has a number or at least three words: "Fresno, CA" is a city."""

    words = [w for seg in segments for w in seg]
    return len(words) >= 3 or any(w[0].isdigit() for w in words)


def _address_rank(bill: _Address, setup: _Address) -> int | None:
    """How well a bill's address fits a Setup address: 0 the same (unit too), 1 the same with a unit the bill has and
    Setup has not; None when they are not the same place. Word for word, once spelled the same way, with the house
    number never optional. One side may stop after the street (or its unit); what both give must agree."""

    if bill.full and bill.full == setup.full and _names_a_place(setup.full):
        return 0
    if bill.street is None or setup.street is None or bill.street != setup.street:
        return None
    short, long = sorted((bill.rest, setup.rest), key=len)
    if long[:len(short)] != short:
        return None
    if setup.unit is not None:
        return 0 if bill.unit == setup.unit else None  # Setup names a suite: the bill must name the same one
    return 0 if bill.unit is None else 1  # a suite on the bill that Setup does not have is ignored


def match_facility(name: Any, address: Any, facilities: list[dict[str, Any]],
                   company: Any = None) -> dict[str, Any] | None:
    """The Setup facility a bill belongs to, by the same name or the same street address, never by a near miss.

    Names are compared after case, punctuation and whitespace are set aside, and a leading "Company - " is
    dropped when the company is the engagement's own (``company``). Addresses are compared word for word after
    the USPS spellings (Road/Rd, Boulevard/Blvd, East/E) are made the same; a unit on the bill that Setup does
    not have is ignored, and the house number must be the same. Every facility that fits is collected: the one
    whose unit agrees is preferred, and when more than one is still left (a street-only bill on a street two
    sites share) nothing is matched. None when nothing matches clearly."""

    bill_names = _facility_names(name, company)
    if bill_names:
        named = [f for f in facilities if _norm_text(f.get("name")) in bill_names]
        if len(named) == 1:
            return named[0]
        if named:  # one name on several facilities ("Plant #1", "Plant 1"): the address chooses among them
            facilities = named
    if address:
        bill = _Address(address)
        ranked = [(rank, f) for f in facilities if f.get("address")
                  if (rank := _address_rank(bill, _Address(f.get("address")))) is not None]
        if ranked:
            best = min(rank for rank, _ in ranked)
            top = [f for rank, f in ranked if rank == best]
            return top[0] if len(top) == 1 else None
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
                           document_id: str, facility_name: Any, address: Any,
                           company: Any = None) -> dict[str, Any] | None:
    """The reviewer's facility for a document, else a clear name/address match."""

    chosen = (decisions.get(document_id) or {}).get("facilityId")
    if chosen:
        for facility in facilities:
            if facility.get("facilityId") == chosen:
                return facility
    return match_facility(facility_name, address, facilities, company)


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
