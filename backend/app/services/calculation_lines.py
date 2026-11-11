"""Calculation lines: the unit the Evidence page files documents into and Verification calculates.

A line is one row of the Evidence tree's last level: Scope > Category > fuel or energy type
(level 2) > one facility (one vehicle group for mobile, the company for contractual
instruments). Its key comes from ``line_key`` and nowhere else.

Pure functions, no I/O: the caller passes in reviewed records, Setup facilities, the
engagement's settings and the reference tables. Placement reuses the recalculation
service's own fuel mapping, facility matching and vehicle groups, so a record lands on the
line the recalculation will count it in.

Where a document is filed
    default placement   ``place_record`` (one per record), then ``document_slots``
    reviewer's moves    ``apply_placements`` over the document's workpaper item payload
                        ``placements: [{"from": <key or block>, "to": <key or block>}]``
    anything unknown    ``resolve_target`` sends it to "Unassigned supporting evidence"
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.app.domain import fuel_units
from backend.app.domain.refrigerants import find_refrigerant
from backend.app.reference.emission_factor_loader import EmissionFactorReference
from backend.app.services import emissions_calculator as calc
from backend.app.services.reviewed_evidence import (
    ELECTRICITY,
    MOBILE,
    REFRIGERANT,
    REVIEWED,
    STATIONARY,
    THERMAL,
    ReviewedRecord,
    resolve_fuel_name,
    resolve_setup_facility,
    to_date,
)
from backend.app.services.refrigerant_extractor import DISPOSAL, service_type_of
from backend.app.services.thermal_extractor import thermal_kind

# --- fixed levels (Global Constraint 4) ---------------------------------------------------
BLOCK_SUMMARY = "block:summary"  # Block 1: Summary documents and workbook
BLOCK_UNASSIGNED = "block:unassigned"  # Block 2: Unassigned documents
SUPPORTING_UNASSIGNED = "supporting:unassigned"  # Block 3: Unassigned supporting evidence
FIXED_TARGETS = frozenset({BLOCK_SUMMARY, BLOCK_UNASSIGNED, SUPPORTING_UNASSIGNED})

SCOPES: tuple[tuple[str, str], ...] = (("s1", "Scope 1"), ("s2", "Scope 2"), ("biogenic", "Biogenic"))
CATEGORIES: tuple[tuple[str, str, str], ...] = (  # (key, label, scope)
    ("stationary", "Stationary combustion", "s1"),
    ("mobile", "Mobile combustion", "s1"),
    ("fugitive", "Fugitive emissions", "s1"),
    ("process", "Process emissions", "s1"),
    ("purchased_energy", "Purchased energy", "s2"),
    ("contractual", "Contractual instruments", "s2"),
    ("biogenic", "Biogenic CO₂", "biogenic"),
)
CATEGORY_LABEL = {key: label for key, label, _ in CATEGORIES}
CATEGORY_SCOPE = {key: scope for key, _, scope in CATEGORIES}
ANCHOR_KINDS = ("facility", "vehicle_group", "company")
COMPANY_ANCHOR = "company"
MAX_EVIDENCE_LINES = 200
MAX_LABEL = 120
LINE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._\-]{0,199}$")  # the workpaper-item key rule

# Documents the client prepared for its own inventory (Block 1), by canonical type. The
# frontend's CLIENT_PREPARED_TYPES are these types' display names: one list, here.
SUMMARY_TYPES: dict[str, str] = {
    "CT-GHG-WORKBOOK": "Inventory workbook",
    "CT-GHG-ORGBOUND": "Organizational boundary statement",
    "CT-S1-METHODDOC": "Inventory methodology statement",
    "CT-GHG-FACSRCLIST": "Facility list",
    "CT-S1-EFREF": "Emission factor source list",
    "CT-GHG-BASEYEAR": "Prior-year inventory or report",
}
# Display names of the source-evidence types that have a default line.
LINE_TYPE_NAMES: dict[str, str] = {
    STATIONARY: "Stationary fuel consumption record",
    MOBILE: "Mobile fuel consumption record",
    REFRIGERANT: "Refrigerant service record",
    ELECTRICITY: "Purchased electricity record",
    THERMAL: "Purchased steam, heat or cooling record",
}
THERMAL_LEVEL2 = {"steam": ("steam", "Steam"), "hot_water": ("heating", "Heating"), "chilled_water": ("cooling", "Cooling")}


def type_name(canonical_type_id: str | None) -> str | None:
    """Display name for a canonical type id (the id itself when it has no friendlier name)."""

    if not canonical_type_id:
        return None
    return SUMMARY_TYPES.get(canonical_type_id) or LINE_TYPE_NAMES.get(canonical_type_id) or canonical_type_id


# --- keys ---------------------------------------------------------------------------------
def slug(text: Any) -> str:
    """Lowercase ``[a-z0-9-]``, at most 60 characters; "none" for text with nothing usable."""

    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:60].strip("-") or "none"


def line_key(scope: str, category: str, level2: str, anchor_kind: str, anchor_id: str) -> str:
    """``<scope>:<category>:<level2-slug>:<anchor-slug>``, e.g. ``s1:stationary:natural-gas:fac-kc01``.
    The company anchor is always ``company``. The only place a line key is built."""

    anchor = COMPANY_ANCHOR if anchor_kind == "company" else slug(anchor_id)
    return f"{scope}:{category}:{slug(level2)}:{anchor}"


# --- the line -----------------------------------------------------------------------------
@dataclass(frozen=True)
class CalculationLine:
    key: str
    scope: str
    category: str
    level2: str
    level2_label: str
    anchor_kind: str
    anchor_id: str
    label: str
    facility_id: str | None
    created_by_user: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_line(category: str, level2: str, level2_label: str, anchor_kind: str, anchor_id: str, label: str,
              *, created_by_user: bool) -> CalculationLine:
    scope = CATEGORY_SCOPE[category]
    return CalculationLine(
        key=line_key(scope, category, level2, anchor_kind, anchor_id), scope=scope, category=category,
        level2=slug(level2), level2_label=level2_label, anchor_kind=anchor_kind,
        anchor_id=COMPANY_ANCHOR if anchor_kind == "company" else anchor_id, label=label,
        facility_id=anchor_id if anchor_kind == "facility" else None, created_by_user=created_by_user)


def facility_anchor_id(facility: dict[str, Any]) -> str:
    return str(facility.get("facilityId") or f"name-{slug(facility.get('name'))}")


def vehicle_group_label(group: dict[str, Any]) -> str:
    return str(group.get("label") or f"{group.get('vehicle_type')} ({group.get('factor_fuel_type')})")


def vehicle_group_anchors(groups: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(anchor id, group) for each vehicle group in settings: ``vg-<label slug>``, numbered
    when two groups share a label."""

    seen: dict[str, int] = {}
    out: list[tuple[str, dict[str, Any]]] = []
    for group in groups:
        base = f"vg-{slug(vehicle_group_label(group))}"
        seen[base] = seen.get(base, 0) + 1
        out.append((base if seen[base] == 1 else f"{base}-{seen[base]}", group))
    return out


# --- user-created lines: settings["evidenceLines"] ------------------------------------------
_LINE_FIELDS = {"key", "scope", "category", "level2", "level2_label", "anchor_kind", "anchor_id", "label"}


def _normalize_entry(entry: Any) -> dict[str, Any]:
    """One evidenceLines entry checked and completed; ValueError (a message for the user) otherwise."""

    if not isinstance(entry, dict) or set(entry) - _LINE_FIELDS:
        raise ValueError(f"each line takes only: {', '.join(sorted(_LINE_FIELDS))}")
    for name in ("category", "level2_label", "anchor_kind", "label"):
        if not isinstance(entry.get(name), str) or not entry[name].strip():
            raise ValueError(f"each line needs {name}")
    category, kind = entry["category"], entry["anchor_kind"]
    if category not in CATEGORY_SCOPE:
        raise ValueError(f"category must be one of: {', '.join(CATEGORY_SCOPE)}")
    scope = entry.get("scope", CATEGORY_SCOPE[category])
    if scope != CATEGORY_SCOPE[category]:
        raise ValueError(f"{category} belongs to scope {CATEGORY_SCOPE[category]}")
    if kind not in ANCHOR_KINDS:
        raise ValueError(f"anchor_kind must be one of: {', '.join(ANCHOR_KINDS)}")
    if len(entry["label"]) > MAX_LABEL or len(entry["level2_label"]) > MAX_LABEL:
        raise ValueError(f"labels must be at most {MAX_LABEL} characters")
    anchor_id = entry.get("anchor_id") or (COMPANY_ANCHOR if kind == "company" else None)
    if not isinstance(anchor_id, str) or not anchor_id.strip():
        raise ValueError("each facility or vehicle group line needs anchor_id")
    level2 = entry.get("level2") or slug(entry["level2_label"])
    if not isinstance(level2, str) or not level2.strip():
        raise ValueError("each line needs level2")
    key = line_key(scope, category, level2, kind, anchor_id)
    if entry.get("key") not in (None, key):
        raise ValueError(f"key must be {key}")
    return {"key": key, "scope": scope, "category": category, "level2": slug(level2),
            "level2_label": entry["level2_label"].strip(), "anchor_kind": kind,
            "anchor_id": COMPANY_ANCHOR if kind == "company" else anchor_id.strip(),
            "label": entry["label"].strip()}


def normalize_evidence_lines(value: Any) -> list[dict[str, Any]]:
    """settings["evidenceLines"] checked and completed; ValueError (a message for the user) otherwise.

    ``key`` may be left out and ``level2`` may be left out (it is then the slug of
    ``level2_label``): the server fills them in, so no client builds a key. A key that is
    given must equal ``line_key`` of the line's parts.
    """

    if not isinstance(value, list) or len(value) > MAX_EVIDENCE_LINES:
        raise ValueError(f"evidenceLines must be a list of at most {MAX_EVIDENCE_LINES} lines")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        normal = _normalize_entry(entry)
        if normal["key"] in seen:
            raise ValueError(f"line {normal['key']} is listed twice")
        seen.add(normal["key"])
        out.append(normal)
    return out


def user_lines(settings: dict[str, Any] | None) -> list[CalculationLine]:
    """The lines reviewers created. Stored data is trusted less than a request: an entry that
    fails the check (or repeats a key) is skipped, the others stay."""

    raw = (settings or {}).get("evidenceLines")
    lines: dict[str, CalculationLine] = {}
    for entry in raw[:MAX_EVIDENCE_LINES] if isinstance(raw, list) else []:
        try:
            e = _normalize_entry(entry)
        except ValueError:
            continue
        lines.setdefault(e["key"], make_line(e["category"], e["level2"], e["level2_label"], e["anchor_kind"],
                                             e["anchor_id"], e["label"], created_by_user=True))
    return list(lines.values())


# --- where a record belongs by default ------------------------------------------------------
@dataclass(frozen=True)
class RecordPlacement:
    """Where one record belongs by default. ``line_key`` is None when it has a category but
    no level 2 or no anchor: it goes to "Unassigned supporting evidence"."""

    category: str | None
    level2: str | None = None
    level2_label: str | None = None
    anchor_kind: str | None = None
    anchor_id: str | None = None
    facility: dict[str, Any] | None = None

    @property
    def line_key(self) -> str | None:
        if not (self.category and self.level2 and self.anchor_kind and self.anchor_id):
            return None
        return line_key(CATEGORY_SCOPE[self.category], self.category, self.level2, self.anchor_kind, self.anchor_id)


def place_record(record: ReviewedRecord, *, ref: EmissionFactorReference, facilities: list[dict[str, Any]],
                 decisions: dict[str, dict[str, Any]], vehicle_groups: list[dict[str, Any]],
                 fuel_choices: dict[str, str]) -> RecordPlacement:
    """The line a record belongs on, from what the backend already knows of it.

    The fuel is the EPA name the recalculation resolves (``fuel_choices`` included); a biomass
    fuel goes under Biogenic. The facility is the document decision's, else the name/address
    match. A mobile record takes the vehicle group when exactly one group uses its fuel.
    """

    kind = record.canonical_type_id
    facility = resolve_setup_facility(facilities, decisions, record.document_id,
                                      record.best("facility_name"), record.best("service_address"))
    facility_anchor = facility_anchor_id(facility) if facility else None
    if kind in (STATIONARY, MOBILE):
        source = "stationary" if kind == STATIONARY else "mobile"
        code = str(record.best("fuel_type") or "").strip()
        unit = record.unit_of("activity_quantity") or record.best("activity_unit")
        quantity_unit = (fuel_units.canonical_unit(str(unit)) if unit else None)
        fuel = resolve_fuel_name(ref, source, code, quantity_unit, fuel_choices)[0] if code else None
        category = "biogenic" if fuel and fuel.lower() in calc.biogenic_fuel_names(ref) else source
        if source == "stationary":
            return RecordPlacement(category, slug(fuel) if fuel else None, fuel, "facility", facility_anchor, facility)
        anchor = None
        if fuel:
            using = [anchor_id for anchor_id, group in vehicle_group_anchors(vehicle_groups)
                     if str(group.get("fuel", "")).strip().lower() == fuel.lower()]
            anchor = using[0] if len(using) == 1 else None
        return RecordPlacement(category, slug(fuel) if fuel else None, fuel, "vehicle_group", anchor, facility)
    if kind == ELECTRICITY:
        return RecordPlacement("purchased_energy", "electricity", "Electricity", "facility", facility_anchor, facility)
    if kind == THERMAL:
        found = THERMAL_LEVEL2.get(thermal_kind(record.best("energy_type")) or "")
        level2, label = found if found else (None, None)
        return RecordPlacement("purchased_energy", level2, label, "facility", facility_anchor, facility)
    if kind == REFRIGERANT:
        text = str(record.best("refrigerant_type") or "").strip()
        found_gas = find_refrigerant(text) if text else None
        gas = found_gas.name if found_gas is not None else text
        return RecordPlacement("fugitive", slug(gas) if gas else None, gas or None, "facility", facility_anchor,
                               facility)
    return RecordPlacement(None)


def default_lines(placements: Iterable[RecordPlacement], facilities: list[dict[str, Any]],
                  vehicle_groups: list[dict[str, Any]]) -> list[CalculationLine]:
    """The system lines: for each level 2 that has at least one record, one line per Setup
    facility (per vehicle group that uses the fuel, for mobile)."""

    groups = {(p.category, p.level2, p.level2_label, p.anchor_kind) for p in placements
              if p.category and p.level2 and p.level2_label and p.anchor_kind}
    lines: dict[str, CalculationLine] = {}
    for category, level2, level2_label, anchor_kind in sorted(groups, key=lambda g: tuple(str(x) for x in g)):
        assert category and level2 and level2_label  # filtered above
        if anchor_kind == "facility":
            for facility in facilities:
                line = make_line(category, level2, level2_label, "facility", facility_anchor_id(facility),
                                 f"{level2_label}, {facility.get('name')}", created_by_user=False)
                lines.setdefault(line.key, line)
        elif anchor_kind == "vehicle_group":
            for anchor_id, group in vehicle_group_anchors(vehicle_groups):
                if str(group.get("fuel", "")).strip().lower() == level2_label.lower():
                    line = make_line(category, level2, level2_label, "vehicle_group", anchor_id,
                                     f"{level2_label}, {vehicle_group_label(group)}", created_by_user=False)
                    lines.setdefault(line.key, line)
    return list(lines.values())


def merge_lines(system: list[CalculationLine], created: list[CalculationLine]) -> list[CalculationLine]:
    """System lines plus the reviewers' own, in tree order. A reviewer's line that duplicates
    a system line is the system line (system lines are not the reviewer's to edit)."""

    merged = {line.key: line for line in [*created, *system]}
    order = {key: i for i, (key, _, _) in enumerate(CATEGORIES)}
    return sorted(merged.values(), key=lambda ln: (order[ln.category], ln.level2_label.lower(), ln.label.lower(),
                                                   ln.key))


# --- a document's placements ----------------------------------------------------------------
@dataclass
class Slot:
    """One place a document sits: a line, a block, or unassigned supporting evidence, with the
    records (positions in the document's record list) shown there."""

    target: str
    records: set[int] = field(default_factory=set)
    flags: list[str] = field(default_factory=list)


def document_slots(canonical_type_id: str | None, placements: list[RecordPlacement]) -> list[Slot]:
    """A document's default slots. No type yet: Block 2. A summary type: Block 1. Otherwise one
    slot per line its records map to, and one for the records that map to none."""

    everything = set(range(len(placements)))
    if not canonical_type_id:
        return [Slot(BLOCK_UNASSIGNED, everything)]
    if canonical_type_id in SUMMARY_TYPES:
        return [Slot(BLOCK_SUMMARY, everything)]
    slots: dict[str, Slot] = {}
    for index, placement in enumerate(placements):
        slots.setdefault(placement.line_key or SUPPORTING_UNASSIGNED, Slot(placement.line_key or SUPPORTING_UNASSIGNED)
                         ).records.add(index)
    return list(slots.values()) or [Slot(SUPPORTING_UNASSIGNED)]


def _effective(slot: Slot, known_lines: set[str]) -> str:
    """Where a slot shows: a slot on a line that does not exist shows as unassigned supporting evidence."""

    return slot.target if slot.target in FIXED_TARGETS or slot.target in known_lines else SUPPORTING_UNASSIGNED


def apply_placements(slots: list[Slot], overrides: Any, known_lines: set[str] | None = None) -> list[Slot]:
    """The reviewer's moves, in order: each ``{"from", "to"}`` moves the document's placement
    named ``from`` to ``to`` (its records with it). ``from`` is what the row showed
    (``DocRow.placement_from``): a line key, a block, or ``supporting:unassigned``, which also
    covers placements on a line that no longer exists (given ``known_lines``). A move whose
    ``from`` the document no longer has is ignored; a move onto a place the document already
    has merges the two."""

    known = known_lines if known_lines is not None else {s.target for s in slots} - FIXED_TARGETS
    out = [Slot(s.target, set(s.records), list(s.flags)) for s in slots]
    for move in overrides if isinstance(overrides, list) else []:
        if not isinstance(move, dict):
            continue
        source, target = move.get("from"), move.get("to")
        if not isinstance(source, str) or not isinstance(target, str) or source == target:
            continue
        moving = [s for s in out if s.target == source or _effective(s, known) == source]
        if not moving:
            continue
        stay = [s for s in out if s not in moving]
        records = {r for s in moving for r in s.records}
        existing = next((s for s in stay if s.target == target or _effective(s, known) == target), None)
        if existing is not None:
            existing.records |= records
            out = stay
        else:
            out = [*stay, Slot(target, records)]
    return out


def resolve_target(slot: Slot, known_lines: set[str]) -> Slot:
    """A slot that names a line that does not exist (deleted after documents moved to it, or
    never there) is filed under unassigned supporting evidence, flagged ``unknown_line``."""

    if slot.target in FIXED_TARGETS or slot.target in known_lines:
        return slot
    return Slot(SUPPORTING_UNASSIGNED, slot.records, [*slot.flags, "unknown_line"])


def merge_slots(slots: list[Slot]) -> list[Slot]:
    """One slot per target (documents never show twice in one place)."""

    merged: dict[str, Slot] = {}
    for slot in slots:
        into = merged.setdefault(slot.target, Slot(slot.target))
        into.records |= slot.records
        into.flags = sorted({*into.flags, *slot.flags})
    return list(merged.values())


def file_documents(documents: Iterable[tuple[str, str | None, list[RecordPlacement]]],
                   decisions: dict[str, dict[str, Any]], known_lines: set[str]) -> dict[str, list[Slot]]:
    """Where each document is filed: ``(document id, canonical type id, its records' default
    placements)`` in, the effective slots out (default slots, then the reviewer's ``placements``
    from the document decision, then unknown lines to unassigned, one slot per place)."""

    out: dict[str, list[Slot]] = {}
    for document_id, canonical_type_id, placements in documents:
        default = document_slots(canonical_type_id, placements)
        moved = apply_placements(default, (decisions.get(document_id) or {}).get("placements"), known_lines)
        out[document_id] = merge_slots([resolve_target(slot, known_lines) for slot in moved])
    return out


# --- numbers of a set of records ------------------------------------------------------------
def tally(records: Iterable[ReviewedRecord]) -> dict[str, int]:
    """values / accepted / to_review / issues over every extracted field of the records."""

    counts = {"values": 0, "accepted": 0, "to_review": 0, "issues": 0}
    for record in records:
        for item in record.fields.values():
            counts["values"] += 1
            if item.status in REVIEWED:
                counts["accepted"] += 1
            elif item.status == "unreviewed":
                counts["to_review"] += 1
            else:  # rejected, needs more evidence
                counts["issues"] += 1
    return counts


def with_percentage(counts: dict[str, Any]) -> dict[str, Any]:
    values = counts["values"]
    return {**counts, "pct_accepted": round(100 * counts["accepted"] / values, 1) if values else 0.0}


# --- what a record says about its period and quantity ---------------------------------------
def record_period(record: ReviewedRecord) -> tuple[date | None, date | None]:
    if record.canonical_type_id == MOBILE:
        day = to_date(record.best("transaction_date"))
        return day, day
    if record.canonical_type_id == REFRIGERANT:
        day = to_date(record.best("service_date"))
        return day, day
    start, end = to_date(record.best("service_period_start")), to_date(record.best("service_period_end"))
    return start or end, end or start


def quantity_field(record: ReviewedRecord) -> str | None:
    """The field that carries the record's quantity (what a calculation line adds up)."""

    if record.canonical_type_id == REFRIGERANT:
        return "refrigerant_recovered" if service_type_of(record.best("service_type")) == DISPOSAL \
            else "refrigerant_added"
    return "activity_quantity" if "activity_quantity" in record.fields else None


# --- coverage by month ------------------------------------------------------------------------
@dataclass(frozen=True)
class Covered:
    """One value's claim on days: its service period, its quantity, whether it is accepted."""

    start: date | None
    end: date | None
    quantity: float | None
    unit: str | None
    accepted: bool
    document_id: str


def _months(first: date, last: date) -> list[tuple[int, int]]:
    out, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def month_coverage(period: tuple[date | None, date | None], values: list[Covered]) -> list[dict[str, Any]]:
    """Per month of the reporting period (else the months the values span): counted when
    accepted values cover all its days, counted in part when they cover some, not reviewed
    when a document covers it but no accepted value does, no document otherwise. A value's
    quantity is spread evenly over its service period's days."""

    dated: list[tuple[date, date, Covered]] = []
    for v in values:
        start, end = v.start or v.end, v.end or v.start
        if start is not None and end is not None and start <= end:
            dated.append((start, end, v))
    first: date
    last: date
    clip = period[0] is not None and period[1] is not None
    if period[0] is not None and period[1] is not None:
        first, last = period[0], period[1]
    elif dated:
        first, last = min(d[0] for d in dated), max(d[1] for d in dated)
    else:
        return []
    unit = next((v.unit for _, _, v in dated if v.accepted and v.quantity is not None and v.unit), None)
    out: list[dict[str, Any]] = []
    for year, month in _months(first, last):
        month_start = date(year, month, 1)
        month_end = (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)
        all_days = {month_start + timedelta(days=i) for i in range((month_end - month_start).days + 1)}
        if clip:  # the first and last month count only the days inside the reporting period
            all_days = {d for d in all_days if first <= d <= last}
        counted: set[date] = set()
        present: set[date] = set()
        quantity, has_quantity, unconverted, documents = 0.0, False, False, []
        for start, end, value in dated:
            span = {start + timedelta(days=i) for i in range((end - start).days + 1)}
            overlap = span & all_days
            if not overlap:
                continue
            present |= overlap
            if value.document_id not in documents:
                documents.append(value.document_id)
            if value.accepted:
                counted |= overlap
                if value.quantity is not None:
                    share = value.quantity * len(overlap) / len(span)
                    if value.unit == unit or not unit or not value.unit:
                        quantity, has_quantity = quantity + share, True
                    else:
                        try:
                            quantity, has_quantity = quantity + fuel_units.convert_exact(share, value.unit, unit), True
                        except ValueError:  # another dimension: covered, but it cannot be added to the rest
                            unconverted = True
        if counted >= all_days and not unconverted:
            status = "counted"
        elif counted:
            status = "counted_in_part"
        elif present:
            status = "not_reviewed"
        else:
            status = "no_document"
        out.append({"month": f"{year:04d}-{month:02d}", "status": status,
                    "quantity": round(quantity, 4) if counted and has_quantity else None,
                    "unit": unit if counted and has_quantity else None, "document_ids": documents,
                    "flags": ["unconverted"] if unconverted else []})
    return out
