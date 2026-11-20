"""Reviewed evidence, as the recalculation and the Evidence page both read it.

A leaf module (it imports nothing of the services): the canonical types the recalculation
handles, a document's extracted values grouped into records with their latest review decision,
the reviewer's per-document decisions (set aside, facility), the Setup facility match and the
EPA fuel name for an extracted fuel code.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services.facility_identifiers import clean_account, match_by_identifier

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REFRIGERANT = "CT-S1-REFRSVC"
THERMAL = "CT-S2-THERMAL"
REVIEWED = ("accepted", "edited")
NOT_FOR_PLACEMENT = ("rejected", "needs_more_evidence")  # a decision that says do not use this value
AI_SUGGESTED = "ai_suggested"  # validation flag of a value Claude read (services/ai_extraction.py)
# Validation flag on a field whose edit or reject carried over a re-read where the extracted value changed.
VALUE_CHANGED = "extracted_value_changed_since_review"
# The review screen's words for a decision that no longer applies to the re-read value.
REREAD_NOTE = "The document was re-read and this value changed. Review it again."
PERIOD_FIELDS = ("service_period_start", "service_period_end")
# Identifier fields never feed a number (spec A13), so the schedule's Source identifiers counts what Claude read
# in them before a reviewer has decided. Nothing else reads these values: best() and reviewed() stay blank.
AI_IDENTIFIER_FIELDS = ("meter_number", "account_number", "service_address", "statement_date")

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
    """The Setup facility a bill belongs to by name or address, or None (see ``match_facility_state``)."""

    return match_facility_state(name, address, facilities, company)[0]


def match_facility_state(name: Any, address: Any, facilities: list[dict[str, Any]],
                         company: Any = None) -> tuple[dict[str, Any] | None, bool]:
    """(facility, ambiguous): a match, or no facility and whether the name or address pointed at more than one.
    A match is (facility, False); nothing at all is (None, False); a name on several facilities that the address
    does not settle, or a street two sites share, is (None, True). The account step never runs on ambiguous.

    The Setup facility a bill belongs to, by the same name or the same street address, never by a near miss.

    Names are compared after case, punctuation and whitespace are set aside, and a leading "Company - " is
    dropped when the company is the engagement's own (``company``). Addresses are compared word for word after
    the USPS spellings (Road/Rd, Boulevard/Blvd, East/E) are made the same; a unit on the bill that Setup does
    not have is ignored, and the house number must be the same. Every facility that fits is collected: the one
    whose unit agrees is preferred, and when more than one is still left (a street-only bill on a street two
    sites share) nothing is matched. None when nothing matches clearly."""

    bill_names = _facility_names(name, company)
    narrowed = False
    if bill_names:
        named = [f for f in facilities if _norm_text(f.get("name")) in bill_names]
        if len(named) == 1:
            return named[0], False
        if named:  # one name on several facilities ("Plant #1", "Plant 1"): the address chooses among them
            facilities = named
            narrowed = True
    if address:
        bill = _Address(address)
        ranked = [(rank, f) for f in facilities if f.get("address")
                  if (rank := _address_rank(bill, _Address(f.get("address")))) is not None]
        if ranked:
            best = min(rank for rank, _ in ranked)
            top = [f for rank, f in ranked if rank == best]
            return (top[0], False) if len(top) == 1 else (None, True)
    return None, narrowed


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
                      record: ReviewedRecord, company: Any = None) -> FacilityPlacement:
    """The one place a record's Setup facility is decided: the reviewer's choice, else the facility name and
    address (``match_facility_state``, with the engagement's ``company``), else (PROVISIONAL, see
    ``facility_identifiers``) the account or meter number.

    The number is used only when the name and address steps found nothing at all (not when they were ambiguous)
    and the bill gives no name and no address. A bill whose name or address matched nothing is never placed by
    its number: it gets a note that names the facility the number is listed on and asks for a choice. Values a
    reviewer rejected, or that only Claude read, are not read here."""

    chosen = (decisions.get(document_id) or {}).get("facilityId")
    if chosen:
        for facility in facilities:
            if facility.get("facilityId") == chosen:
                return FacilityPlacement(facility, "Chosen by the reviewer")
    name, address = record.for_placement("facility_name"), record.for_placement("service_address")
    found, ambiguous = match_facility_state(name, address, facilities, company)
    if found is not None:
        by_name = match_facility(name, None, facilities, company) is found
        return FacilityPlacement(found, "Facility name in Setup" if by_name else "Service address in Setup")
    if ambiguous:
        return FacilityPlacement()
    account = record.for_placement("account_number")  # a bill saved before the label was dropped still matches
    by_number = match_by_identifier(clean_account(account) if account is not None else None,
                                    record.for_placement("meter_number"), facilities)
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
    # A reviewer's decision exists on an earlier read of this value but no longer applies (the document
    # was re-read and the record or its value changed): the field is unreviewed until it is reviewed again.
    reread_changed: bool = False
    flags: list[str] = field(default_factory=list)  # e.g. VALUE_CHANGED
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
    """The latest review decision per candidate id (later entries win). This is the raw per-id
    lookup; what applies to an extracted item is ``resolve_decisions`` / ``effective_decision``."""

    return {str(d.get("candidate_id")): d for d in decisions}


# ---------------------------------------------------------------------------------------------
# Which decision applies to an extracted item
#
# A decision is stored under a candidate id built from the field and the record's *index*
# (``...::{field}::r{n}``). A re-read can renumber the records, so the id alone cannot say the
# decision was made on this value. ``effective_decision`` is the one place that decides.
# ---------------------------------------------------------------------------------------------
_RECORD_INDEX_SEGMENT = re.compile(r"^r\d+(?::|$)")
# ``...::r2`` and Claude's alternative candidates ``...::r2::ai2``
_INDEX_SUFFIX = re.compile(r"::r(\d+)(?:::ai\d+)?$")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_THOUSANDS_NUMBER = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


@dataclass
class EffectiveDecision:
    """``decision`` is the stored decision when it applies to the item, else None. ``same_record``: the
    decision was made on this record (an accept whose value changed is the same record, but does not apply)."""

    decision: dict | None
    applies: bool
    value_changed: bool = False  # an edit/reject carried over although the extracted value changed
    same_record: bool = False


@dataclass
class Resolution:
    """What a re-read left of the reviewer's decisions on one extracted item."""

    decision: dict | None = None  # the latest decision that applies, else None (unreviewed)
    value_changed: bool = False
    reread_changed: bool = False  # decisions exist on this record but none applies any more
    # Every decision made on this record, oldest first. The ones a re-read made void are copies marked
    # ``superseded_by_reread: True``; the stored decisions are never changed or removed.
    history: list[dict] = field(default_factory=list)


def record_key_of(container: Any) -> str | None:
    """The ``record_key`` of an extracted item or a decision's candidate snapshot."""

    if not isinstance(container, dict):
        return None
    key = container.get("record_key")
    if not key and isinstance(container.get("source_reference"), dict):
        key = container["source_reference"].get("record_key")
    return str(key) if key else None


def record_identity(record_key: str | None) -> str | None:
    """A record key without its leading ``r{index}`` segment: the hint and the service period,
    which stay the same when a re-read renumbers the records. None when nothing is left."""

    if not record_key:
        return None
    rest = _RECORD_INDEX_SEGMENT.sub("", str(record_key), count=1).strip()
    return rest or None


def _index_of(decision: dict[str, Any]) -> int | None:
    """The record index a decision was made on: the snapshot's ``record_index`` when it has one, else
    the ``::r{n}`` (or ``::r{n}::ai{m}``) end of its candidate id. None for a single-record document."""

    snapshot = decision.get("candidate_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("record_index"), int) \
            and not isinstance(snapshot.get("record_index"), bool):
        return int(snapshot["record_index"])
    found = _INDEX_SUFFIX.search(str(decision.get("candidate_id") or ""))
    return int(found.group(1)) if found else None


def _doc_of(record: dict[str, Any]) -> str:
    return str(record.get("document_id"))


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: Any) -> float | None:
    """A number, or text that is one: digits, an optional decimal part, and commas only as thousands
    separators ("1,234.5"). "12 34" is not a number, so it never equals 1234."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        text = value.strip()
        if _THOUSANDS_NUMBER.match(text):
            text = text.replace(",", "")
        if _PLAIN_NUMBER.match(text):
            return float(text)
    return None


def same_value(a: Any, b: Any) -> bool:
    """Numbers compare numerically (58.92 equals "58.92"), the rest as trimmed text; blank equals only blank."""

    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def _same_unit(a: Any, b: Any) -> bool:
    def norm(u: Any) -> str | None:
        return None if _blank(u) else str(u).strip().casefold()

    return norm(a) == norm(b)


def _keys_by_record(records: list[dict[str, Any]]) -> dict[tuple[str, int | None], str]:
    """A record's key as its items carry it, by document and record index: Claude's alternative
    candidates (``::ai2``) have none of their own, so they take the key of the record they sit in."""

    out: dict[tuple[str, int | None], str] = {}
    for rec in records:
        key = record_key_of(rec)
        if key:
            index = rec.get("record_index") if "record_index" in rec else _index_of(rec)
            out.setdefault((_doc_of(rec), index), key)
    return out


def item_periods(items: Iterable[dict[str, Any]]) -> dict[tuple[str, Any], tuple[Any, Any]]:
    """Each record's service period as the re-read extracted it, by document and ``record_index``."""

    found: dict[tuple[str, Any], dict[str, Any]] = {}
    for item in items:
        name = item.get("field_name")
        if name in PERIOD_FIELDS:
            found.setdefault((_doc_of(item), item.get("record_index")), {})[name] = item.get("normalized_value")
    return {k: (p.get("service_period_start"), p.get("service_period_end")) for k, p in found.items()}


def decision_period(decisions: list[dict], position: int) -> tuple[Any, Any]:
    """The service period a decision was made on, from the snapshots of the decisions on the same
    record's period fields (the nearest in the list, which is time order). ``(None, None)`` when the
    reviewer never decided them. Used only when a record key is missing."""

    index, doc = _index_of(decisions[position]), _doc_of(decisions[position])
    out: list[Any] = []
    for name in PERIOD_FIELDS:
        best: tuple[int, Any] | None = None
        for i, other in enumerate(decisions):
            snap = other.get("candidate_snapshot")
            if not isinstance(snap, dict) or (snap.get("field_name") or other.get("field_name")) != name \
                    or _index_of(other) != index or _doc_of(other) != doc:
                continue
            distance = abs(i - position)
            if best is None or distance <= best[0]:
                best = (distance, snap.get("normalized_value"))
        out.append(None if best is None else best[1])
    return out[0], out[1]


def _decision_key(decisions: list[dict], position: int) -> str | None:
    """The record key a decision was made on: its own snapshot's, else the nearest decision on the same
    record (same document and index) that has one."""

    own = record_key_of(decisions[position].get("candidate_snapshot"))
    if own:
        return own
    index, doc = _index_of(decisions[position]), _doc_of(decisions[position])
    best: tuple[int, str] | None = None
    for i, other in enumerate(decisions):
        key = record_key_of(other.get("candidate_snapshot"))
        if key and _index_of(other) == index and _doc_of(other) == doc \
                and (best is None or abs(i - position) <= best[0]):
            best = (abs(i - position), key)
    return None if best is None else best[1]


def effective_decision(item: dict[str, Any], decision: dict[str, Any], *,
                       item_key: str | None = None, decided_key: str | None = None,
                       item_period: tuple[Any, Any] | None = None,
                       decided_period: tuple[Any, Any] | None = None,
                       twin: bool = False) -> EffectiveDecision:
    """Whether a stored review decision applies to an extracted item of the latest read.

    It applies only when it was made on the same document, field and record:
      * the record keys, without their ``r{index}`` segment (hint and service period), are equal.
        ``item_key`` / ``decided_key`` are the keys of the record the item / decision sits in (given by
        ``resolve_decisions``; they default to the ones the item and the snapshot carry). When either
        side has no key the service periods are compared instead (``item_period`` and ``decided_period``:
        ``(start, end)`` as the read and the review saw them), and the decision must sit under the item's
        own candidate id. A decision with no period evidence at all cannot be told apart from its record:
        it is kept (the value rule below still protects an accept);
      * an accept also needs the accepted value to be unchanged (value and unit, numbers numerically);
      * an edit, a reject or "needs more evidence" carries over when the record is the same, even
        if the extracted value changed (``value_changed`` says so, for a validation flag). On ``twin``
        records (the read has several with the same hint and period) it carries over only if the value
        is unchanged, since the record cannot be told from its twin.
    A decision with no candidate snapshot cannot be compared: it applies by candidate id on a
    single-record document and never on a multi-record one. Nothing is ever deleted: a decision that
    does not apply stays in the history."""

    none = EffectiveDecision(None, False)
    same_id = str(decision.get("candidate_id")) == str(item.get("candidate_id"))
    snapshot = decision.get("candidate_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        single = item.get("record_index") is None and _index_of(decision) is None
        ok = same_id and single
        return EffectiveDecision(decision if ok else None, ok, same_record=ok)
    if _doc_of(decision) != _doc_of(item) and decision.get("document_id") is not None \
            and item.get("document_id") is not None:
        return none
    field_name = snapshot.get("field_name") or decision.get("field_name")
    if field_name is not None and str(field_name) != str(item.get("field_name")):
        return none
    decided_key = decided_key if decided_key is not None else record_key_of(snapshot)
    item_key = item_key if item_key is not None else record_key_of(item)
    decided_id, read_id = record_identity(decided_key), record_identity(item_key)
    if decided_id and read_id:
        same_record = decided_id == read_id
    elif not decided_key and not item_key and _index_of(decision) is None and item.get("record_index") is None:
        same_record = True  # a single-record document before and after
    else:
        no_evidence = decided_period in (None, (None, None))
        same_record = same_id and (no_evidence or (item_period or (None, None)) == decided_period)
    if not same_record:
        return none
    unchanged = same_value(snapshot.get("normalized_value"), item.get("normalized_value")) \
        and _same_unit(snapshot.get("unit"), item.get("unit"))
    if decision.get("decision") == "accepted":
        return EffectiveDecision(decision if unchanged else None, unchanged, same_record=True)
    if twin and not unchanged:
        return EffectiveDecision(None, False, same_record=True)
    return EffectiveDecision(decision, True, value_changed=not unchanged, same_record=True)


def resolve_decisions(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> list[Resolution]:
    """For each extracted item (same order), the reviewer decision that applies to it.

    The candidate id finds the decisions made on the same field and record index; a decision whose
    record moved to another index in a re-read is found through its record key (hint and period), when
    that identifies one record of the read. Decisions are matched within their own document only.
    The latest decision that applies wins."""

    decisions = [d for d in reviews]
    by_id: dict[str, list[int]] = {}
    by_field: dict[tuple[str, str], list[int]] = {}
    for i, d in enumerate(decisions):
        by_id.setdefault(str(d.get("candidate_id")), []).append(i)
        snap = d.get("candidate_snapshot")
        named = snap.get("field_name") if isinstance(snap, dict) else None
        by_field.setdefault((_doc_of(d), str(named or d.get("field_name"))), []).append(i)
    periods = item_periods(items)
    read_keys = _keys_by_record(items)
    decided_keys = [_decision_key(decisions, i) for i in range(len(decisions))]
    decided_periods: dict[int, tuple[Any, Any]] = {}
    item_key_of = [record_key_of(i) or read_keys.get((_doc_of(i), i.get("record_index"))) for i in items]
    identities = Counter((_doc_of(i), str(i.get("field_name")), record_identity(k))
                         for i, k in zip(items, item_key_of) if record_identity(k))
    out: list[Resolution] = []
    for item, item_key in zip(items, item_key_of):
        direct = [] if item.get("candidate_id") is None else by_id.get(str(item.get("candidate_id")), [])
        read_id = record_identity(item_key)
        twin = bool(read_id) and identities[(_doc_of(item), str(item.get("field_name")), read_id)] > 1
        moved: list[int] = []
        if read_id and not twin:
            moved = [i for i in by_field.get((_doc_of(item), str(item.get("field_name"))), [])
                     if i not in direct and record_identity(decided_keys[i]) == read_id]
        considered = sorted(set(direct) | set(moved))
        applying: list[tuple[int, EffectiveDecision]] = []
        history: list[dict] = []
        for i in considered:
            if i not in decided_periods:
                decided_periods[i] = decision_period(decisions, i)
            verdict = effective_decision(
                item, decisions[i], item_key=item_key, decided_key=decided_keys[i],
                item_period=periods.get((_doc_of(item), item.get("record_index"))),
                decided_period=decided_periods[i], twin=twin)
            if verdict.applies:
                applying.append((i, verdict))
                history.append(decisions[i])
            elif verdict.same_record:
                history.append({**decisions[i], "superseded_by_reread": True})
        if applying:
            out.append(Resolution(applying[-1][1].decision, applying[-1][1].value_changed, False, history))
        else:
            out.append(Resolution(None, False, bool(considered), history))
    return out


def all_decisions(decisions: Any) -> dict[str, list[dict]]:
    """Every review decision per candidate id, in the order given (oldest first)."""

    out: dict[str, list[dict]] = {}
    for decision in decisions:
        out.setdefault(str(decision.get("candidate_id")), []).append(decision)
    return out


def applicable_decisions(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]],
                         read_documents: set[str] | None = None) -> list[dict[str, Any]]:
    """The stored decisions (oldest first) that apply to some item of the latest read: every decision
    on a record that still matches, not only the latest (the superseded copies are not the stored objects).
    ``read_documents``: the documents the items come from; a decision on another document is kept as it
    is (there is no read to judge it by). None judges every decision."""

    decisions = [d for d in reviews]
    kept = {id(h) for r in resolve_decisions(items, decisions) if r.decision is not None for h in r.history}
    return [d for d in decisions
            if id(d) in kept or (read_documents is not None and _doc_of(d) not in read_documents)]


def latest_items_per_document(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The items of each document's latest extraction result (``results`` oldest first, any documents)."""

    latest: dict[str, dict[str, Any]] = {}
    for result in results:
        latest[str(result.get("document_id"))] = result
    return [item for result in latest.values() for item in result.get("items") or []]


def stale_decision_ids(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]],
                       read_documents: set[str] | None = None) -> set[str]:
    """Ids of the stored decisions that no longer apply to any item of the latest read."""

    decisions = [d for d in reviews]
    kept = {id(d) for d in applicable_decisions(items, decisions, read_documents)}
    return {str(d.get("review_decision_id")) for d in decisions if id(d) not in kept and d.get("review_decision_id")}


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def reviews_for_latest_type(results: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The decisions that can apply to the document's latest read. A read as another document type
    (a re-read after a move onto a line of another type, or a type the reviewer set) is a new set of values:
    a decision made before it was stored does not apply to it, whatever record index or field name it shares.
    It stays in the record. ``results`` oldest first. A decision or read with no usable time is kept, and a read
    that had no type (nothing was identified) is not a type change."""

    cutoff = None
    for earlier, later in zip(results, results[1:]):
        before, after = earlier.get("canonical_type_id"), later.get("canonical_type_id")
        if before and after and before != after:
            cutoff = _moment(later.get("created_at")) or cutoff
    if cutoff is None:
        return reviews
    out = []
    for decision in reviews:
        made = _moment(decision.get("reviewed_at"))
        if made is not None and made.tzinfo is None and cutoff.tzinfo is not None:
            made = made.replace(tzinfo=cutoff.tzinfo)
        if made is not None and cutoff.tzinfo is None and made.tzinfo is not None:
            made = made.replace(tzinfo=None)
        if made is None or made >= cutoff:
            out.append(decision)
    return out


def reviews_for_latest_types(results: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``reviews_for_latest_type`` for the reads of several documents (an evidence's): each document's decisions are
    judged by that document's own reads. Decisions on a document with no read here are kept."""

    by_document: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_document.setdefault(str(result.get("document_id")), []).append(result)
    kept = []
    for document_id, own in by_document.items():
        theirs = [d for d in reviews if str(d.get("document_id")) == document_id]
        kept.extend(reviews_for_latest_type(own, theirs))
    kept_ids = {id(d) for d in kept}
    return [d for d in reviews if id(d) in kept_ids or str(d.get("document_id")) not in by_document]


def mark_reread_items(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of the extracted items for the review screen. An item whose earlier decision no longer
    applies gets ``review_reread_changed: true`` (the screen says "Review it again"); an item whose
    edit or reject carried over although the value changed gets VALUE_CHANGED in ``validation_flags``.
    Items nobody re-read come back unchanged."""

    out: list[dict[str, Any]] = []
    for item, resolved in zip(items, resolve_decisions(items, reviews)):
        if resolved.reread_changed:
            out.append({**item, "review_reread_changed": True})
        elif resolved.value_changed:
            out.append({**item, "validation_flags": [*(item.get("validation_flags") or []), VALUE_CHANGED]})
        else:
            out.append(item)
    return out


def mark_review_targets(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stored decisions (every one, oldest first, none removed) for the review screen. A decision that
    applies to an item under another candidate id (its record moved in a re-read) carries
    ``applies_to_candidate_id``; one that applies to no item of the latest read (it matches nothing, or its
    record is the same but a re-read changed the accepted value) carries it as None.
    A decision that applies to its own candidate is returned as stored."""

    decisions = [d for d in reviews]
    target: dict[int, str] = {}
    for item, resolved in zip(items, resolve_decisions(items, decisions)):
        if resolved.decision is not None:  # every decision on the record, not only the latest one
            for held in resolved.history:
                target[id(held)] = str(item.get("candidate_id"))
    out: list[dict[str, Any]] = []
    for decision in decisions:
        goes_to = target.get(id(decision))
        out.append(decision if goes_to == str(decision.get("candidate_id"))
                   else {**decision, "applies_to_candidate_id": goes_to})
    return out


def group_reviewed_records(document: dict[str, Any], canonical_type_id: str, items: list[dict[str, Any]],
                           reviews: Iterable[dict[str, Any]], with_history: bool = False) -> list[ReviewedRecord]:
    """One document's extracted items grouped into records (by ``record_index``), each field
    carrying the review decision that applies to it (and, with ``with_history``, every decision on it).
    ``reviews``: the document's stored decisions, oldest first."""

    document_id = str(document.get("document_id"))
    candidates: dict[int | None, dict[str, list[ReviewedField]]] = {}
    for item, resolved in zip(items, resolve_decisions(items, reviews)):
        review = resolved.decision
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
            history=list(resolved.history) if with_history else [],
            reread_changed=resolved.reread_changed,
            flags=[VALUE_CHANGED] if resolved.value_changed else [], ai_reads=ai_reads))
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
