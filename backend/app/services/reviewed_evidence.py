"""Reviewed evidence, as the recalculation and the Evidence page both read it.

A leaf module (it imports nothing of the services): the canonical types the recalculation
handles, a document's extracted values grouped into records with their latest review decision,
the reviewer's per-document decisions (set aside, facility), the Setup facility match and the
EPA fuel name for an extracted fuel code.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from backend.app.domain import fuel_units
from backend.app.reference.emission_factor_loader import EmissionFactorReference

STATIONARY = "CT-S1-FUELQTY"
MOBILE = "CT-S1-MOBFUEL"
ELECTRICITY = "CT-S2-ELEC"
REFRIGERANT = "CT-S1-REFRSVC"
THERMAL = "CT-S2-THERMAL"
REVIEWED = ("accepted", "edited")
AI_SUGGESTED = "ai_suggested"  # validation flag of a value Claude read (services/ai_extraction.py)
# Validation flag on a field whose edit or reject carried over a re-read where the extracted value changed.
VALUE_CHANGED = "extracted_value_changed_since_review"
# The review screen's words for a decision that no longer applies to the re-read value.
REREAD_NOTE = "The document was re-read and this value changed. Review it again."
PERIOD_FIELDS = ("service_period_start", "service_period_end")

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


@dataclass
class EffectiveDecision:
    """``decision`` is the stored decision when it applies to the item, else None."""

    decision: dict | None
    applies: bool
    value_changed: bool = False  # an edit/reject carried over although the extracted value changed


@dataclass
class Resolution:
    """What a re-read left of the reviewer's decisions on one extracted item."""

    decision: dict | None = None  # the latest decision that applies, else None (unreviewed)
    value_changed: bool = False
    reread_changed: bool = False  # decisions exist on this record but none applies any more
    history: list[dict] = field(default_factory=list)  # every decision that applies to it, oldest first


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


_INDEX_SUFFIX = re.compile(r"::r(\d+)$")


def _index_of(decision: dict[str, Any]) -> int | None:
    """The record index a decision was made on: the ``::r{n}`` end of its candidate id (the review
    screen's snapshot does not carry ``record_index``). None for a single-record document."""

    found = _INDEX_SUFFIX.search(str(decision.get("candidate_id") or ""))
    return int(found.group(1)) if found else None


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def same_value(a: Any, b: Any) -> bool:
    """Numbers compare numerically (58.92 equals "58.92"), the rest as trimmed text; blank equals only blank."""

    if _blank(a) or _blank(b):
        return _blank(a) and _blank(b)
    na, nb = to_number(a), to_number(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-9)
    return str(a).strip() == str(b).strip()


def _same_unit(a: Any, b: Any) -> bool:
    return (str(a).strip() if not _blank(a) else None) == (str(b).strip() if not _blank(b) else None)


def item_periods(items: Iterable[dict[str, Any]]) -> dict[Any, tuple[Any, Any]]:
    """Each record's service period as the re-read extracted it, by ``record_index``."""

    found: dict[Any, dict[str, Any]] = {}
    for item in items:
        name = item.get("field_name")
        if name in PERIOD_FIELDS:
            found.setdefault(item.get("record_index"), {})[name] = item.get("normalized_value")
    return {index: (p.get("service_period_start"), p.get("service_period_end")) for index, p in found.items()}


def decision_period(decisions: list[dict], position: int) -> tuple[Any, Any]:
    """The service period a decision was made on, from the snapshots of the decisions on the same
    record's period fields (the nearest in the list, which is time order). ``(None, None)`` when the
    reviewer never decided them. Used only when a record key is missing."""

    index = _index_of(decisions[position])
    out: list[Any] = []
    for name in PERIOD_FIELDS:
        best: tuple[int, Any] | None = None
        for i, other in enumerate(decisions):
            snap = other.get("candidate_snapshot")
            if not isinstance(snap, dict) or (snap.get("field_name") or other.get("field_name")) != name \
                    or _index_of(other) != index:
                continue
            distance = abs(i - position)
            if best is None or distance <= best[0]:
                best = (distance, snap.get("normalized_value"))
        out.append(None if best is None else best[1])
    return out[0], out[1]


def effective_decision(item: dict[str, Any], decision: dict[str, Any], *,
                       item_period: tuple[Any, Any] | None = None,
                       decided_period: tuple[Any, Any] | None = None) -> EffectiveDecision:
    """Whether a stored review decision applies to an extracted item of the latest read.

    It applies only when it was made on the same field and the same record:
      * the record keys, without their ``r{index}`` segment (hint and service period), are equal;
        when either side has no key the service periods are compared instead (``item_period`` and
        ``decided_period``: ``(start, end)`` as the read and the review saw them), and the decision
        must sit under the item's own candidate id;
      * an accept also needs the accepted value to be unchanged (value and unit, numbers numerically);
      * an edit, a reject or "needs more evidence" carries over when the record is the same, even
        if the extracted value changed (``value_changed`` says so, for a validation flag).
    A decision with no candidate snapshot cannot be compared: it applies by candidate id only,
    as before this check existed. Nothing is ever deleted: a decision that does not apply stays in history."""

    snapshot = decision.get("candidate_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        same_id = str(decision.get("candidate_id")) == str(item.get("candidate_id"))
        return EffectiveDecision(decision if same_id else None, same_id)
    field_name = snapshot.get("field_name") or decision.get("field_name")
    if field_name is not None and str(field_name) != str(item.get("field_name")):
        return EffectiveDecision(None, False)
    decided_key, read_key = record_key_of(snapshot), record_key_of(item)
    decided_id, read_id = record_identity(decided_key), record_identity(read_key)
    if decided_id and read_id:
        same_record = decided_id == read_id
    elif decided_key is None and read_key is None and _index_of(decision) is None \
            and item.get("record_index") is None:
        same_record = True  # a single-record document before and after
    else:
        same_record = (item_period or (None, None)) == (decided_period or (None, None)) \
            and str(decision.get("candidate_id")) == str(item.get("candidate_id"))
    if not same_record:
        return EffectiveDecision(None, False)
    unchanged = same_value(snapshot.get("normalized_value"), item.get("normalized_value")) \
        and _same_unit(snapshot.get("unit"), item.get("unit"))
    if decision.get("decision") == "accepted":
        return EffectiveDecision(decision if unchanged else None, unchanged)
    return EffectiveDecision(decision, True, value_changed=not unchanged)


def resolve_decisions(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> list[Resolution]:
    """For each extracted item (same order), the reviewer decision that applies to it.

    The candidate id finds the decisions made on the same field and record index; a decision whose
    record moved to another index in a re-read is found through its record key (hint and period), when
    that identifies one record of the read. The latest decision that applies wins."""

    decisions = [d for d in reviews]
    by_id: dict[str, list[int]] = {}
    by_field: dict[str, list[int]] = {}
    for i, d in enumerate(decisions):
        by_id.setdefault(str(d.get("candidate_id")), []).append(i)
        snap = d.get("candidate_snapshot")
        named = snap.get("field_name") if isinstance(snap, dict) else None
        by_field.setdefault(str(named or d.get("field_name")), []).append(i)
    periods = item_periods(items)
    identities = Counter((str(i.get("field_name")), record_identity(record_key_of(i))) for i in items
                         if record_identity(record_key_of(i)))
    out: list[Resolution] = []
    for item in items:
        direct = [] if item.get("candidate_id") is None else by_id.get(str(item.get("candidate_id")), [])
        read_id = record_identity(record_key_of(item))
        moved: list[int] = []
        if read_id and identities[(str(item.get("field_name")), read_id)] == 1:
            moved = [i for i in by_field.get(str(item.get("field_name")), [])
                     if i not in direct
                     and record_identity(record_key_of(decisions[i].get("candidate_snapshot"))) == read_id]
        considered = sorted(set(direct) | set(moved))
        applying: list[tuple[int, EffectiveDecision]] = []
        for i in considered:
            verdict = effective_decision(item, decisions[i], item_period=periods.get(item.get("record_index")),
                                         decided_period=decision_period(decisions, i))
            if verdict.applies:
                applying.append((i, verdict))
        applied = {i for i, _ in applying}
        history = [decisions[i] for i in considered if i in applied]
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


def applicable_decisions(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The stored decisions (oldest first) that apply to some item of the latest read."""

    decisions = [d for d in reviews]
    kept = {id(r.decision) for r in resolve_decisions(items, decisions) if r.decision is not None}
    return [d for d in decisions if id(d) in kept]


def stale_decision_ids(items: list[dict[str, Any]], reviews: Iterable[dict[str, Any]]) -> set[str]:
    """Ids of the stored decisions that no longer apply to any item of the latest read."""

    decisions = [d for d in reviews]
    kept = {id(d) for d in applicable_decisions(items, decisions)}
    return {str(d.get("review_decision_id")) for d in decisions if id(d) not in kept and d.get("review_decision_id")}


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
    ``applies_to_candidate_id``; one that applies to no item of the latest read carries it as None.
    A decision that applies to its own candidate is returned as stored."""

    decisions = [d for d in reviews]
    target: dict[int, str] = {}
    for item, resolved in zip(items, resolve_decisions(items, decisions)):
        if resolved.decision is not None:
            target[id(resolved.decision)] = str(item.get("candidate_id"))
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
        extracted = item.get("normalized_value")
        unit = item.get("unit")
        if review and status in REVIEWED:
            value = review.get("reviewed_value")
            unit = review.get("reviewed_unit") or unit
        elif AI_SUGGESTED in (item.get("validation_flags") or []):
            # Claude's suggestion is not evidence until a reviewer accepts or edits it: nothing
            # downstream (best(), unit_of(), the calculation) may read it before then.
            extracted, unit = None, None
        candidates.setdefault(item.get("record_index"), {}).setdefault(str(item.get("field_name")), []).append(ReviewedField(
            name=str(item.get("field_name")), extracted=extracted, unit=unit,
            status=status, value=value, source_reference=item.get("source_reference"),
            candidate_id=None if item.get("candidate_id") is None else str(item.get("candidate_id")),
            reviewer=review.get("reviewer_id") if review else None,
            reviewed_at=review.get("reviewed_at") if review else None,
            history=list(resolved.history) if with_history else [],
            reread_changed=resolved.reread_changed,
            flags=[VALUE_CHANGED] if resolved.value_changed else []))
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
        return same[-1]
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
