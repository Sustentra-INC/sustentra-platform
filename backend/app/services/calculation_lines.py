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
import uuid
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
    place_on_facility,
    resolve_fuel_name,
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
    created_by: str | None = None  # the user id the server stamped on a reviewer's line (None on system lines)
    created_at: str | None = None  # when, ISO 8601 UTC

    @property
    def family(self) -> str | None:
        """The calculation this line feeds: "stationary", "mobile" or "electricity"; None for a line
        no calculation reads (fugitive, process, steam and the like). Same rule as the recalculation."""

        if self.category == "purchased_energy":
            return "electricity" if self.level2 == "electricity" else None
        if self.category == "mobile" or self.anchor_kind == "vehicle_group":
            return "mobile"
        if self.category in ("stationary", "biogenic") and self.anchor_kind == "facility":
            return "stationary"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "family": self.family}


def record_family(canonical_type_id: str | None) -> str | None:
    """The calculation a record's value belongs to, from its document type; None when none reads it."""

    return {STATIONARY: "stationary", MOBILE: "mobile", ELECTRICITY: "electricity"}.get(canonical_type_id or "")


def make_line(category: str, level2: str, level2_label: str, anchor_kind: str, anchor_id: str, label: str,
              *, created_by_user: bool, created_by: str | None = None,
              created_at: str | None = None) -> CalculationLine:
    scope = CATEGORY_SCOPE[category]
    return CalculationLine(
        key=line_key(scope, category, level2, anchor_kind, anchor_id), scope=scope, category=category,
        level2=slug(level2), level2_label=level2_label, anchor_kind=anchor_kind,
        anchor_id=COMPANY_ANCHOR if anchor_kind == "company" else anchor_id, label=label,
        facility_id=anchor_id if anchor_kind == "facility" else None, created_by_user=created_by_user,
        created_by=created_by, created_at=created_at)


def facility_anchor_id(facility: dict[str, Any]) -> str:
    return str(facility.get("facilityId") or f"name-{slug(facility.get('name'))}")


def vehicle_group_label(group: dict[str, Any]) -> str:
    return str(group.get("label") or f"{group.get('vehicle_type')} ({group.get('factor_fuel_type')})")


GROUP_ID = re.compile(r"^vg-[a-z0-9](?:[a-z0-9-]{0,66}[a-z0-9])?$")  # a vehicle group's id: also its line anchor


def new_group_id(taken: set[str]) -> str:
    """A fresh, opaque id for a vehicle group (``vg-`` and 12 hex digits), unlike every id in ``taken``."""

    while True:
        candidate = f"vg-{uuid.uuid4().hex[:12]}"
        if candidate not in taken:
            return candidate


def legacy_group_anchors(groups: list[dict[str, Any]]) -> list[str]:
    """The anchor a group had before groups carried an id: ``vg-<label slug>``, numbered by order among
    the groups whose labels give the same slug. Kept for groups with no ``group_id`` (older data, a demo)
    and by the migration that gave existing groups their ids (so no key, line or placement changed)."""

    seen: dict[str, int] = {}
    out: list[str] = []
    for group in groups:
        base = f"vg-{slug(vehicle_group_label(group))}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return out


def vehicle_group_anchors(groups: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(anchor id, group) for each vehicle group in settings: the group's own ``group_id``, which the
    server gave it when it was created and keeps through renames, removals and reordering. A group with no
    ``group_id`` (data from before ids) takes its legacy anchor, moved on if an id already uses it."""

    taken = {str(g["group_id"]) for g in groups if isinstance(g.get("group_id"), str) and GROUP_ID.match(g["group_id"])}
    legacy = legacy_group_anchors(groups)
    out: list[tuple[str, dict[str, Any]]] = []
    for group, old in zip(groups, legacy, strict=True):
        own = group.get("group_id")
        if isinstance(own, str) and GROUP_ID.match(own):
            out.append((own, group))
            continue
        anchor, n = old, 1
        while anchor in taken:
            n += 1
            anchor = f"{old}-x{n}"
        taken.add(anchor)
        out.append((anchor, group))
    return out


def assign_group_ids(groups: list[dict[str, Any]], stored: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The vehicle groups of a save, each with a ``group_id`` the server chose or kept.

    A group keeps the id it already has when that id belongs to one of the engagement's stored groups
    (so a rename, a reorder or a removal of another group changes nothing). A group that sends no id is
    matched to a stored group that is unchanged in its fuel, vehicle type, fuel type and name and not yet
    matched (a client that does not send ids back), and otherwise is new. A group that sends an id the
    engagement never had is new too, whatever the id says. A new group gets a fresh id, never the id of
    a group that was removed.
    """

    stored = [g for g in stored or [] if isinstance(g, dict)]
    stored_anchors = vehicle_group_anchors(stored)  # a group saved before ids is known by its legacy anchor
    known = {anchor for anchor, _ in stored_anchors}
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    pending: list[int] = []  # groups with no usable id yet; the ones that sent an id the engagement never had
    for group in groups:
        given = group.get("group_id")
        if isinstance(given, str) and given in known and given not in used:
            used.add(given)
            out.append(dict(group))
        else:
            out.append({k: v for k, v in group.items() if k != "group_id"})
            pending.append(len(out) - 1)
    # a client that sends no ids back: an unchanged group is still the same group
    same = ("fuel", "vehicle_type", "factor_fuel_type", "on_road", "label")
    for index in pending:
        if "group_id" in groups[index]:
            continue  # it named an id this engagement never had: not trusted, so it is a new group
        match = next((anchor for anchor, g in stored_anchors
                      if anchor not in used and all(g.get(k) == out[index].get(k) for k in same)), None)
        if match is not None:
            used.add(match)
            out[index]["group_id"] = match
    taken = known | used
    for group in out:
        if "group_id" not in group:
            group["group_id"] = new_group_id(taken)
            taken.add(group["group_id"])
    return out


# --- user-created lines: settings["evidenceLines"] ------------------------------------------
_LINE_FIELDS = {"key", "scope", "category", "level2", "level2_label", "anchor_kind", "anchor_id", "label",
                "created_by", "created_at"}
# Stamped by the server (``stamp_new_lines``); whatever a client sends for them is replaced, never trusted.
_STAMP_FIELDS = ("created_by", "created_at")


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
    normal = {"key": key, "scope": scope, "category": category, "level2": slug(level2),
              "level2_label": entry["level2_label"].strip(), "anchor_kind": kind,
              "anchor_id": COMPANY_ANCHOR if kind == "company" else anchor_id.strip(),
              "label": entry["label"].strip()}
    for name in _STAMP_FIELDS:
        if isinstance(entry.get(name), str) and entry[name]:
            normal[name] = entry[name][:64]
    return normal


def normalize_line(entry: Any) -> dict[str, Any]:
    """One line entry checked and completed (``normalize_evidence_lines`` for a single line)."""

    return _normalize_entry(entry)


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


def stamp_new_lines(lines: list[dict[str, Any]], stored: Any, *, user_id: str, now: str) -> list[dict[str, Any]]:
    """Who made each line, and when: set by the server, once. A line whose key is already stored keeps
    exactly what is stored (a rename or a re-save never changes it); a new key gets ``user_id`` and
    ``now``. Whatever the client sent for ``created_by`` and ``created_at`` is dropped first."""

    kept: dict[str, dict[str, Any]] = {}
    for entry in stored if isinstance(stored, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("key"), str):
            kept.setdefault(entry["key"], {n: entry[n] for n in _STAMP_FIELDS if isinstance(entry.get(n), str)})
    out: list[dict[str, Any]] = []
    for line in lines:
        clean = {k: v for k, v in line.items() if k not in _STAMP_FIELDS}
        stamp = kept[line["key"]] if line["key"] in kept else {"created_by": user_id, "created_at": now}
        out.append({**clean, **stamp})
    return out


def check_new_lines(lines: list[dict[str, Any]], *, stored_keys: set[str], facilities: list[dict[str, Any]],
                    vehicle_groups: list[dict[str, Any]]) -> None:
    """The lines a request adds (keys not already stored) must sit on something Setup has: a
    facility, a vehicle group, or the company (contractual instruments only; they may also sit on a facility). ValueError with a
    sentence for the user otherwise. Lines already stored are never re-checked, so saving other
    settings never fails over an old line whose facility was later removed from Setup.

    ``lines`` are normalized (``normalize_evidence_lines``). The read path (``user_lines``) does
    not use this: a stored line with an orphan anchor stays visible with its documents.
    """

    added = [line for line in lines if line["key"] not in stored_keys]
    if not added:
        return
    facility_ids = {facility_anchor_id(f) for f in facilities}
    group_ids = {anchor for anchor, _ in vehicle_group_anchors(vehicle_groups)}
    for line in added:
        if line["level2"] == "none" and not re.search(r"[A-Za-z0-9]", line["level2_label"]):
            raise ValueError("Use letters or numbers in the name of the fuel or energy type.")
        kind, anchor = line["anchor_kind"], line["anchor_id"]
        if kind == "company" and line["category"] != "contractual":
            raise ValueError("Only contractual instruments can apply to the whole company.")
        if kind == "facility" and not facilities:
            raise ValueError("Add a facility in Setup first, then add the line.")
        if kind == "facility" and anchor not in facility_ids:
            raise ValueError("That facility isn't in Setup. Pick a facility from the list, or add it in Setup first.")
        if kind == "vehicle_group" and anchor not in group_ids:
            raise ValueError("That vehicle group isn't in Setup. Pick one from the list, or add it in Setup first.")


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
                                             e["anchor_id"], e["label"], created_by_user=True,
                                             created_by=e.get("created_by"), created_at=e.get("created_at")))
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
                 fuel_choices: dict[str, str], company: str | None = None) -> RecordPlacement:
    """The line a record belongs on, from what the backend already knows of it.

    The fuel is the EPA name the recalculation resolves (``fuel_choices`` included); a biomass
    fuel goes under Biogenic. The facility is the document decision's, else the name/address
    match. A mobile record takes the vehicle group when exactly one group uses its fuel.
    """

    kind = record.canonical_type_id
    facility = place_on_facility(facilities, decisions, record.document_id, record, company).facility
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


def vehicle_group_line(category: str, level2: str, level2_label: str, anchor_id: str,
                       group: dict[str, Any]) -> CalculationLine:
    """The system line of one vehicle group for one fuel: the one constructor ``default_lines``
    and the recalculation both use, so their keys are the same."""

    return make_line(category, level2, level2_label, "vehicle_group", anchor_id,
                     f"{level2_label}, {vehicle_group_label(group)}", created_by_user=False)


def facility_line(category: str, level2: str, level2_label: str, facility: dict[str, Any]) -> CalculationLine:
    return make_line(category, level2, level2_label, "facility", facility_anchor_id(facility),
                     f"{level2_label}, {facility.get('name')}", created_by_user=False)


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
                line = facility_line(category, level2, level2_label, facility)
                lines.setdefault(line.key, line)
        elif anchor_kind == "vehicle_group":
            for anchor_id, group in vehicle_group_anchors(vehicle_groups):
                if str(group.get("fuel", "")).strip().lower() == level2_label.lower():
                    line = vehicle_group_line(category, level2, level2_label, anchor_id, group)
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


MAX_PLACEMENT_MOVES = 200  # a document's saved chain of moves never grows past this


def raw_filing(slots: list[Slot]) -> dict[str, frozenset[int]]:
    """Where each place's records are, one entry per place, with no unknown line resolved to unassigned."""

    return {s.target: frozenset(s.records) for s in merge_slots(slots)}


def derive_placements(default: list[Slot], filing: list[Slot]) -> list[dict[str, str]] | None:
    """The saved chain for a document, derived from where it is filed now, not from its history.

    ``default`` is where the document's records go before any reviewer move, ``filing`` where they are
    now (``apply_placements`` over the full chain, nothing resolved: a record parked on a line that no
    longer exists is still on that line's key, so it returns there if the line comes back).
    Records of one default slot always travel together, so the filing is a map from each default slot
    to its current place. The chain is one move for each default slot that is not where it started, so
    it never has more moves than the document has default slots, however many times it was moved.

    The moves are ordered so a move out of a place runs before a move into it (``apply_placements``
    moves everything that is in a place). Slots that swap places (A to B and B to A, which a reviewer
    reaches through a third place) go through a free fixed place: A to the free place, B to A, the free
    place to B. ``None`` when a default slot's records ended up in different places, or when a swap needs
    a free place and all three fixed ones are taken: the caller then keeps the full chain.
    """

    where: dict[int, str] = {}
    for slot in filing:
        for record in slot.records:
            where[record] = slot.target
    pairs: list[tuple[str, str]] = []
    for slot in default:
        places = {where.get(record) for record in slot.records}
        if len(places) != 1 or None in places:
            return None
        (place,) = places
        if place != slot.target:
            pairs.append((slot.target, str(place)))
    used = {t for pair in pairs for t in pair} | {slot.target for slot in default} | set(where.values())
    free = next((t for t in (BLOCK_SUMMARY, BLOCK_UNASSIGNED, SUPPORTING_UNASSIGNED) if t not in used), None)
    ordered: list[dict[str, str]] = []
    while pairs:
        ready = next((p for p in pairs if not any(q is not p and q[0] == p[1] for q in pairs)), None)
        if ready is None:  # every pair waits on another: a cycle. Park one slot on the free place, finish it last.
            if free is None:
                return None
            ready = pairs[0]
            pairs.remove(ready)
            ordered.append({"from": ready[0], "to": free})
            pairs.append((free, ready[1]))
            continue
        pairs.remove(ready)
        ordered.append({"from": ready[0], "to": ready[1]})
    return ordered


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


def date_label(canonical_type_id: str | None) -> str:
    """What the document calls its date: a bill's service period, a fuel purchase's
    transaction date, a service visit's service date."""

    return {MOBILE: "Transaction date", REFRIGERANT: "Service date"}.get(canonical_type_id or "", "Service period")


def facility_match(facilities: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], document_id: str,
                   record: ReviewedRecord, company: str | None = None) -> tuple[dict[str, Any], str] | None:
    """The Setup facility of a record and how it was matched: the reviewer's choice, the facility name, the
    service address, or (provisional) the account or meter number; None when nothing matches. It is the
    same decision ``place_record`` makes (``place_on_facility``), with the reason."""

    placement = place_on_facility(facilities, decisions, document_id, record, company)
    return (placement.facility, str(placement.how)) if placement.facility is not None else None


def unplaced_note(facilities: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], document_id: str,
                  record: ReviewedRecord, company: str | None = None) -> str | None:
    """Why a record with no Setup facility was not placed by its account or meter number, in a plain
    sentence; None when it has a facility or its numbers say nothing."""

    placement = place_on_facility(facilities, decisions, document_id, record, company)
    return placement.note if placement.facility is None else None


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
    waiting: tuple[str, ...] = ()  # labels of other fields still awaited: the value does not count


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
        waiting_on: list[str] = []
        for start, end, value in dated:
            span = {start + timedelta(days=i) for i in range((end - start).days + 1)}
            overlap = span & all_days
            if not overlap:
                continue
            present |= overlap
            waiting_on.extend(w for w in value.waiting if w not in waiting_on)
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
                    "flags": ["unconverted"] if unconverted else [], "waiting_on": waiting_on})
    return out
