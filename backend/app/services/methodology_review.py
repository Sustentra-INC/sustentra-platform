"""Methodology review (the page that checks the client's stated boundary and methods): the
fixed list of decision fields and the rules for a reviewer's actions on them, as pure
functions (``save_suggestion`` is the one database call, for the AI task).
``backend/app/api/methodology_review.py`` locks, saves and audits.

Each field is one ``workpaper_items`` row (kind ``methodology``, item_key = field id):

    {field_id, suggestion: null | {value, quote, document_id, file_name, source_reference,
                                   origin: "ai", model, request_id, suggested_at, reason?},
     decision: null | {status: pending|accepted|edited|rejected, value, reason?, by, at},
     history: [{at, by, action, to?}] (newest 50),
     value_history: [decision, ...] (the decisions before the current one, oldest first, at most 10),
     user_added?: true, removed?: true}

A suggestion is only a proposal (written by the AI task through ``save_suggestion``). The workpaper value
of a field is its decision's ``value`` when the status is accepted or edited; a rejected
decision keeps no value.

    from \\ action        accept     edit     reject     revert
    none / pending        accepted   edited   rejected   409
    accepted / edited     409        edited   409        the decision before this one
    rejected              409        edited   409        the decision before this one

Revert goes back to the PREVIOUS value: every accept, edit or reject pushes the decision it replaces onto
``value_history``, and a revert pops the last one and makes it the decision again (its own status and value). With no
previous decision it restores the detected value (the suggestion stays on the field, pending, ready to accept), and with
no suggestion either the field is empty (a reviewer-added row goes back to its blank value). A previous decision that
was saved but cannot be restored (it no longer validates, or was too large to keep: ``previous_lost``) refuses the
revert with a 409 sentence; it never quietly falls back. The history event of a revert says what was actually
restored: ``restored`` is previous, detected or empty.

Rows (entities, emission-factor sources) are added by the reviewer under a server-made id
and removed only if the reviewer added them; a removed row is marked, never deleted, so the
record stays complete. Refusals are plain sentences, because the frontend shows them as is.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services import workpaper_item_service
from backend.app.services.request_service import Actor, stamp
from backend.app.services.workpaper_item_service import MAX_PAYLOAD_BYTES, payload_size

KIND = "methodology"

CONSOLIDATION_APPROACHES = ("Equity Share", "Financial Control", "Operational Control")
INCLUSIONS = ("Yes", "No", "Not detected")
GWP_SETS = ("AR4", "AR5", "AR6")
# "Not stated": the set is named and the document gives no horizon for it ("AR5" alone).
GWP_HORIZONS = ("100-year", "20-year", "500-year", "Not stated")
GWP_SET_LABELS = {
    "AR4": "IPCC Fourth Assessment Report (AR4)",
    "AR5": "IPCC Fifth Assessment Report (AR5)",
    "AR6": "IPCC Sixth Assessment Report (AR6)",
}
YES_NO = ("Yes", "No")
# The gas rows have their own value set; it is kept apart from the category Yes / No / Not detected.
GAS_STATUSES = ("Included", "Declared absent", "Not mentioned")
GASES = (("co2", "CO2"), ("ch4", "CH4"), ("n2o", "N2O"), ("hfcs", "HFCs"), ("pfcs", "PFCs"), ("sf6", "SF6"),
         ("nf3", "NF3"))
GAS_IDS = tuple(f"gas:{key}" for key, _ in GASES)

PENDING, ACCEPTED, EDITED, REJECTED = "pending", "accepted", "edited", "rejected"
STATUSES = (PENDING, ACCEPTED, EDITED, REJECTED)

MAX_TEXT = 2000
MAX_REASON = 500
BOUNDARY_SENTENCE_ID = "boundary:entities"
MAX_APPLIES_TO = 200  # a GWP set's use note, in the company's words
MAX_FACILITIES = 20
MAX_FACILITY = 100
MAX_HISTORY = 50
MAX_VALUE_HISTORY = 10  # earlier decisions kept per field, for Revert
HISTORY_ROOM = 10 * 1024  # bytes of event history a record keeps room for before it keeps earlier decisions
MAX_ADDED_ROWS = 200
MAX_SUGGESTION_BYTES = 8 * 1024  # the value and its quote; the per-entry quotes have their own room
MAX_ENTRIES = 10  # entries in an entry_list value
MAX_SOURCE_TYPE = 60
MAX_METHOD = 300
MAX_EVIDENCE = 20  # per-entry quotes on one suggestion
MAX_OPTION = 60
MAX_WORDING = 200  # the company's own wording beside a selected option
MAX_FREE_OPTIONS = 10  # free additions beside the listed options
INSTRUMENT_OPTIONS = ("RECs or other energy attribute certificates", "PPA or VPPA",
                      "Green tariff or utility program", "Supplier-specific rate", "Residual mix", "None")
SOURCE_RECORD_OPTIONS = ("Utility invoices", "Meter readings", "Fuel cards", "Fuel receipts or logs",
                         "Landlord reports", "Lease agreements")
SCOPE_OPTIONS = ("Scope 1", "Scope 2", "Scope 3", "Not stated")
# Options that stand alone: the explicit answer for "the document names none", chosen by the reviewer (there is
# nothing to quote for it), never together with another option and never one of the reviewer's own additions.
STANDALONE_OPTIONS = ("None", "Not stated")
SCOPES_ID = "scopes:covered"
MARKET_CATEGORY_IDS = tuple(f"category:market:{key}" for key in ("electricity", "heating", "steam", "cooling"))
MAX_EVIDENCE_QUOTE = 1000  # as long as the quote Claude is checked against
# The quotes of one list suggestion. Sized so the record always fits MAX_PAYLOAD_BYTES with a decision of the
# same field: when the quotes do not fit, the suggestion carries fewer entries, never an entry without its quote.
MAX_EVIDENCE_BYTES = 12 * 1024
MAX_QUOTE = 1000
# What a suggestion may carry: key -> longest text. Anything else is dropped.
_SUGGESTION_TEXT = {"quote": MAX_QUOTE, "document_id": 100, "file_name": 255, "model": 100, "request_id": 100,
                    "origin": 20, "suggested_at": 40, "reason": 240}
# source_reference keeps the keys of contracts/source_reference.schema.json that are plain text or a page.
_SOURCE_REFERENCE_TEXT = ("source_reference_id", "document_id", "sheet_name", "cell_or_range", "text_snippet",
                          "source_kind")
MAX_SOURCE_REFERENCE_TEXT = 200
# Sizes are bounded so a record always fits MAX_PAYLOAD_BYTES (32 KB, counted in UTF-8): in the
# worst case a decision and a suggestion each hold at most about 9 KB, a quote about 4 KB, and
# the history is trimmed (oldest events first) to whatever room is left, so a field can never
# become too big to change.

GROUPS = (
    ("boundary", "Organizational boundary"),
    ("gases", "Gases covered"),
    ("scope1", "Scope 1 emission categories"),
    ("scope2", "Scope 2 emission categories"),
    ("biogenic", "Biogenic emissions"),
    ("exclusions", "Exclusions"),
    ("factors", "Emission factors source"),
    ("gwp", "GWP factors source"),
    ("calculation", "Calculation methodology"),
)

# Row groups, where a reviewer can add rows: (field id prefix, kind, page group, label).
ROW_GROUPS: dict[str, tuple[str, str, str, str]] = {
    "entities": ("entity", "entity", "boundary", "Entity"),
    "factor:scope1": ("factor:scope1", "factor", "factors", "Scope 1 emission factor source"),
    "factor:scope2": ("factor:scope2", "factor", "factors", "Scope 2 emission factor source"),
    # A report may name more than one GWP set: the first is the fixed "gwp" field, each other is a row.
    "gwp": ("gwp", "gwp", "gwp", "GWP set"),
}
_ROW_ID = re.compile(r"^(entity|factor:scope1|factor:scope2|gwp):[a-z0-9]{4,32}$")


class MethodologyConflict(Exception):
    """The field's state does not allow the action (HTTP 409). The message is for the user."""


class MethodologyInvalid(ValueError):
    """The action's input does not fit the field (HTTP 422). The message is for the user."""


_GROUP_LABELS = dict(GROUPS)

# The editors of a row kind, so a blank row can be drawn: key in the value, label, part kind.
_PARTS: dict[str, list[dict[str, Any]]] = {
    "entity": [
        {"key": "name", "label": "Entity name", "kind": "text"},
        {"key": "facilities", "label": "Facilities", "kind": "list"},
        {"key": "equity_share_pct", "label": "Equity share (%, if stated)", "kind": "percent"},
        {"key": "financial_control", "label": "Financial control (%, if stated)", "kind": "percent"},
        # Claire C-M2: the per-entity Yes / No is "Included". It has its own key: before this change
        # ``operational_control`` held what the report quoted about operational control, which must not read as Included.
        {"key": "included", "label": "Included", "kind": "enum", "allowed": list(YES_NO), "optional": True},
        # What the report quoted about operational control, shown separately and only when it was quoted.
        {"key": "control_quoted", "label": "Operational control (as quoted)", "kind": "enum", "allowed": list(YES_NO),
         "optional": True, "show_if_present": True},
    ],
    "factor": [
        {"key": "database", "label": "Database", "kind": "text"},
        {"key": "edition", "label": "Edition", "kind": "text"},
    ],
    "multiselect": [
        {"key": "option", "label": "Option", "kind": "text"},
        {"key": "wording", "label": "The company's wording", "kind": "text"},
    ],
    "entry_list": [
        {"key": "source_type", "label": "Source type", "kind": "text"},
        {"key": "method", "label": "Estimation method", "kind": "text"},
    ],
    "gwp": [
        {"key": "set", "label": "GWP set", "kind": "enum", "allowed": list(GWP_SETS)},
        {"key": "horizon", "label": "Time horizon", "kind": "enum", "allowed": list(GWP_HORIZONS)},
        {"key": "applies_to", "label": "Applies to (use note)", "kind": "text"},
    ],
}


def _field(field_id: str, group: str, label: str, kind: str, allowed: Any = None,
           required: bool = True) -> dict[str, Any]:
    """A field definition. ``required`` is Claire's "Must appear" (always on the page); false is
    "Only if the company has a value" (hidden until a suggestion or decision exists, or the
    reviewer adds it). Every field in the spec's sheet today is "Must appear"; so is every row
    and anything the spec does not list."""

    field: dict[str, Any] = {"field_id": field_id, "group": group, "group_label": _GROUP_LABELS[group],
                             "label": label, "kind": kind, "user_added": False, "required": required}
    if allowed is not None:
        field["allowed"] = allowed
    if kind in _PARTS:
        field["parts"] = copy.deepcopy(_PARTS[kind])
    return field


def _static_fields() -> list[dict[str, Any]]:
    fields = [
        _field("reporting_period", "boundary", "Reporting period", "date_range"),
        _field("consolidation_approach", "boundary", "Consolidation approach", "enum",
               list(CONSOLIDATION_APPROACHES)),
        # Spec row 17: Scope 1 / Scope 2 / Scope 3 the inventory covers; "Not stated" is the reviewer's answer.
        _field(SCOPES_ID, "boundary", "Scopes covered", "multiselect", list(SCOPE_OPTIONS)),
        # "Only if the company has a value" (spec rows 5 and 6): hidden until there is a value or "Add an item".
        _field("boundary:acquisitions", "boundary", "Acquisitions and divestitures", "text", required=False),
        _field("boundary:leased_space", "boundary", "Treatment of leased space", "text", required=False),
    ]
    # Spec row 9, the fallback: a document that gives only the boundary sentence and names no entity shows that
    # sentence here, marked "Boundary sentence only", instead of Not detected.
    entities = _field(BOUNDARY_SENTENCE_ID, "boundary", "Entities and facilities in the boundary", "text")
    entities["value_note"] = "Boundary sentence only"
    fields.append(entities)
    # Spec row 11: only if the company reports a market-based Scope 2 number, which this page reads
    # as at least one market-based category that is Yes (see ``market_based_reported``).
    instruments = _field("scope2:instruments", "scope2", "Scope 2 instrument types (market-based)", "multiselect",
                         list(INSTRUMENT_OPTIONS), required=False)
    instruments["shown_if_yes"] = list(MARKET_CATEGORY_IDS)
    fields.append(instruments)
    # One row per gas. All seven are always on the page (Claire, 20 Nov: never hide a gas); a gas the
    # documents do not mention reads "Not mentioned" on the page.
    fields += [_field(f"gas:{key}", "gases", f"Gas: {name}", "enum", list(GAS_STATUSES)) for key, name in GASES]
    scope1 = {"stationary": "Stationary Combustion", "mobile": "Mobile Combustion",
              "process": "Process Emissions", "fugitive": "Fugitive Emissions"}
    for key, name in scope1.items():
        fields.append(_field(f"category:scope1:{key}", "scope1", f"Scope 1 {name}", "enum", list(INCLUSIONS)))
    purchased = {"electricity": "Purchased Electricity", "heating": "Purchased Heating",
                 "steam": "Purchased Steam", "cooling": "Purchased Cooling"}
    for basis, prefix in (("location", "Location-based"), ("market", "Market-based")):
        for key, name in purchased.items():
            fields.append(_field(f"category:{basis}:{key}", "scope2", f"{prefix} {name}", "enum", list(INCLUSIONS)))
    fields.append(_field("category:biogenic:direct", "biogenic", "Direct Biogenic", "enum", list(INCLUSIONS)))
    fields.append(_field("category:biogenic:indirect", "biogenic", "Indirect Biogenic", "enum", list(INCLUSIONS)))
    fields += [
        _field("exclusion:boundary", "exclusions", "Excluded from organizational boundary", "text"),
        _field("exclusion:inventory", "exclusions", "Excluded from this inventory", "text"),
        _field("exclusion:materiality", "exclusions", "Excluded under the materiality threshold", "text"),
    ]
    gwp = _field("gwp", "gwp", "GWP factors source", "gwp", {"set": list(GWP_SETS), "horizon": list(GWP_HORIZONS)})
    gwp["allowed_labels"] = {"set": dict(GWP_SET_LABELS)}
    fields.append(gwp)
    fields += [
        _field("calculation:approach", "calculation", "Calculation approach", "text"),
        _field("calculation:process", "calculation", "Process-specific calculations", "text"),
        # "Only if the company has a value" (spec row 19): one entry per source type.
        _field("calculation:estimation", "calculation", "Estimation method for missing data", "entry_list",
               required=False),
    ]
    # Spec row 20: the listed records, and any the company names beyond them.
    records = _field("calculation:source_records", "calculation", "Source records", "multiselect",
                     list(SOURCE_RECORD_OPTIONS), required=False)
    records["free"] = True
    fields.append(records)
    return fields


CATALOG: tuple[dict[str, Any], ...] = tuple(_static_fields())
_BY_ID = {f["field_id"]: f for f in CATALOG}


def catalog_field(field_id: str) -> dict[str, Any] | None:
    """The fixed field with this id, or None (rows are not in the fixed catalog)."""

    field = _BY_ID.get(field_id)
    return copy.deepcopy(field) if field else None


def row_field(field_id: str) -> dict[str, Any] | None:
    """The definition of a reviewer-added row from its id, or None if the id is not a row's."""

    match = _ROW_ID.match(field_id)
    if not match:
        return None
    prefix, kind, group, label = next(g for g in ROW_GROUPS.values() if g[0] == match.group(1))
    allowed: Any = None
    if kind == "entity":
        allowed = {"included": list(YES_NO), "control_quoted": list(YES_NO)}
    elif kind == "gwp":
        allowed = {"set": list(GWP_SETS), "horizon": list(GWP_HORIZONS)}
    field = _field(field_id, group, label, kind, allowed)
    if kind == "gwp":
        field["allowed_labels"] = {"set": dict(GWP_SET_LABELS)}
    field["user_added"] = True
    return field


def new_row_id(group: str) -> str:
    """A fresh id for a row in ``group`` (entities, factor:scope1, factor:scope2)."""

    if group not in ROW_GROUPS:
        raise MethodologyInvalid("Rows can be added to the entities, the emission factor sources and the GWP sets.")
    return f"{ROW_GROUPS[group][0]}:{uuid.uuid4().hex[:12]}"


def upgrade_entity_value(value: Any) -> Any:
    """An entity value saved before "Included" had its own key: its ``operational_control`` was what the report
    quoted about operational control, so it moves to ``control_quoted`` and ``included`` stays null until a reviewer
    confirms it. Anything else is returned unchanged. Applied when a value is read and when it is validated."""

    if not isinstance(value, dict) or "included" in value or "operational_control" not in value:
        return value
    out = {k: v for k, v in value.items() if k != "operational_control"}
    out["included"] = None
    if value["operational_control"] in YES_NO and "control_quoted" not in value:
        out["control_quoted"] = value["operational_control"]
    return out


def blank_value(field_id: str) -> Any:
    """What a new row holds until the reviewer fills it in."""

    if field_id.startswith("entity:"):
        return {"name": "", "facilities": [], "equity_share_pct": None, "financial_control": None,
                "included": None}
    if field_id.startswith("gwp:"):
        return {"set": "", "horizon": ""}
    return {"database": "", "edition": ""}


# --- value validation -------------------------------------------------------------------

def _fail(field: Mapping[str, Any], problem: str) -> MethodologyInvalid:
    return MethodologyInvalid(f"'{field['label']}': {problem}")


def _text(field: Mapping[str, Any], value: Any, *, required: bool = False, limit: int = MAX_TEXT,
          name: str = "the value") -> str:
    if not isinstance(value, str):
        raise _fail(field, f"{name} must be text.")
    if "\x00" in value:
        raise _fail(field, f"{name} can't contain a null character.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail(field, f"{name} contains a character that can't be saved.") from None
    clean = value.strip()
    if required and not clean:
        raise _fail(field, f"{name} can't be blank.")
    if len(clean) > limit:
        raise _fail(field, f"{name} is too long (at most {limit} characters).")
    return clean


def _only(field: Mapping[str, Any], value: Any, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise _fail(field, "the value must be an object with exactly " + ", ".join(keys) + ".")
    return value


def _percent(field: Mapping[str, Any], value: Any, name: str, *, optional: bool = False) -> int | float | None:
    """A number from 0 to 100; ``None`` (not stated) only where the percentage is optional."""

    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
        raise _fail(field, f"{name} must be a number from 0 to 100" + (", or left blank." if optional else "."))
    return value


_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def parse_iso_date(text: Any) -> date | None:
    """A real calendar date written YYYY-MM-DD (ASCII digits only), or None."""

    if not isinstance(text, str) or not _ISO_DATE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


PERIOD_BASES = ("Calendar year", "Fiscal year", "Not stated")


def year_start_for(end: date) -> date:
    """The first day of the twelve months that finish on ``end``: the day after the same date a year
    earlier (2024-12-31 gives 2024-01-01; 2025-06-30 gives 2024-07-01)."""

    nxt = end + timedelta(days=1)
    try:
        return nxt.replace(year=nxt.year - 1)
    except ValueError:  # the day after a 28 February in a leap year is 29 February, which the year before lacks
        return date(nxt.year - 1, 3, 1)


def period_basis(start: date, end: date) -> str:
    """What the two dates make of the period: a calendar year (1 January to 31 December), a fiscal
    year (twelve months that are not the calendar year) or not stated (any other length)."""

    if start.year == end.year and (start.month, start.day) == (1, 1) and (end.month, end.day) == (12, 31):
        return PERIOD_BASES[0]
    return PERIOD_BASES[1] if start == year_start_for(end) else PERIOD_BASES[2]


IMPLIED_FROM_TITLE = "calendar year, year from title"


def _date_range(field: Mapping[str, Any], value: Any) -> dict[str, Any]:
    """Start and end dates. ``start_implied`` / ``end_implied`` (true only) mark a date the report does not print;
    ``implied_from`` says how both were worked out (only ``IMPLIED_FROM_TITLE``). ``basis`` is one of PERIOD_BASES:
    the one the caller gives when it is valid (Claude's, from the quote's own words: "fiscal year" gives Fiscal
    year), else worked out from the two dates, so a reviewer's edit of two dates always gets a fresh basis."""

    if (not isinstance(value, dict) or not {"start", "end"} <= set(value)
            or not set(value) <= {"start", "end", "start_implied", "end_implied", "implied_from", "basis"}):
        raise _fail(field, "enter both a start date and an end date, written YYYY-MM-DD.")
    start, end = parse_iso_date(value["start"]), parse_iso_date(value["end"])
    if start is None:
        raise _fail(field, "the start date is not a real date. Write it as YYYY-MM-DD, for example 2025-01-01.")
    if end is None:
        raise _fail(field, "the end date is not a real date. Write it as YYYY-MM-DD, for example 2025-12-31.")
    if end < start:
        raise _fail(field, "the end date can't be before the start date.")
    out: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat()}
    for key in ("start_implied", "end_implied"):
        flag = value.get(key, False)
        if not isinstance(flag, bool):
            raise _fail(field, "an implied flag must be true or false.")
        if flag:
            out[key] = True
    if "implied_from" in value:
        if value["implied_from"] != IMPLIED_FROM_TITLE:
            raise _fail(field, "the implied-from note is not one this page writes.")
        out["implied_from"] = IMPLIED_FROM_TITLE
    given = value.get("basis")
    out["basis"] = given if given in PERIOD_BASES else period_basis(start, end)
    return out


def _entry_list(field: Mapping[str, Any], value: Any) -> list[dict[str, str]]:
    """Entries of {source_type, method}: one per source type (compared ignoring case and spacing)."""

    if not isinstance(value, list) or len(value) > MAX_ENTRIES:
        raise _fail(field, f"enter a list of at most {MAX_ENTRIES} entries.")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in value:
        data = _only(field, entry, ("source_type", "method"))
        source = _text(field, data["source_type"], required=True, limit=MAX_SOURCE_TYPE, name="the source type")
        key = " ".join(source.casefold().split())
        if key in seen:
            raise _fail(field, f"'{source}' appears twice. Keep one entry per source type.")
        seen.add(key)
        out.append({"source_type": source,
                    "method": _text(field, data["method"], required=True, limit=MAX_METHOD, name="the method")})
    return out


def _multiselect(field: Mapping[str, Any], value: Any) -> list[dict[str, str]]:
    """Selected options, each with the company's own wording (may be blank). A field with free
    additions also takes options that are not in its list. "None" stands alone."""

    allowed: list[str] = field["allowed"]
    free = bool(field.get("free"))
    if not isinstance(value, list) or len(value) > len(allowed) + (MAX_FREE_OPTIONS if free else 0):
        raise _fail(field, "choose from the listed options" + (f", and add at most {MAX_FREE_OPTIONS} of your own." if free else "."))
    by_key = {" ".join(a.casefold().split()): a for a in allowed}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    extra = 0
    for entry in value:
        data = _only(field, entry, ("option", "wording"))
        option = _text(field, data["option"], required=True, limit=MAX_OPTION, name="the option")
        key = " ".join(option.casefold().split())
        if key in by_key:
            option = by_key[key]
        elif free:
            alone = next((o for o in STANDALONE_OPTIONS if o.casefold() == key), None)
            if alone:  # a listed answer where the field has it, never a free option
                raise _fail(field, f"'{alone}' can't be added as an option of your own.")
            extra += 1
            if extra > MAX_FREE_OPTIONS:
                raise _fail(field, f"add at most {MAX_FREE_OPTIONS} options of your own.")
        else:
            raise _fail(field, "choose options from the list: " + ", ".join(allowed) + ".")
        if key in seen:
            raise _fail(field, f"'{option}' is chosen twice.")
        seen.add(key)
        out.append({"option": option, "wording": _text(field, data["wording"], limit=MAX_WORDING,
                                                          name="the company's wording")})
    standalone = [a for a in STANDALONE_OPTIONS if a in allowed]
    if not out:  # a decision needs an option: "None" / "Not stated" is the explicit empty answer where the field has it
        raise _fail(field, "choose at least one option" + (f", or {standalone[0]} if " + (
            "there are none." if standalone[0] == "None" else "the document does not say.") if standalone else
            ", or reject this row if the company has none."))
    if len(out) > 1 and any(o["option"] in STANDALONE_OPTIONS for o in out):
        alone = next(o["option"] for o in out if o["option"] in STANDALONE_OPTIONS)
        raise _fail(field, f"'{alone}' can't be chosen together with other options.")
    return out


def validate_value(field: Mapping[str, Any], value: Any) -> Any:
    """The value cleaned for its field, or MethodologyInvalid with a sentence."""

    kind = field["kind"]
    if kind == "multiselect":
        return _multiselect(field, value)
    if kind == "entry_list":
        return _entry_list(field, value)
    if kind == "date_range":
        return _date_range(field, value)
    if kind == "text":
        return _text(field, value)
    if kind == "enum":
        if not isinstance(value, str) or value not in field["allowed"]:
            raise _fail(field, "choose one of " + ", ".join(field["allowed"]) + ".")
        return value
    if kind == "gwp":
        if not isinstance(value, dict) or not {"set", "horizon"} <= set(value) or not set(value) <= {"set", "horizon", "applies_to"}:
            raise _fail(field, "the value must be an object with set and horizon, and optionally applies_to.")
        if value["set"] not in GWP_SETS or value["horizon"] not in GWP_HORIZONS:
            raise _fail(field, f"the set must be one of {', '.join(GWP_SETS)} and the horizon one of "
                               f"{', '.join(GWP_HORIZONS)}.")
        out = {"set": value["set"], "horizon": value["horizon"]}
        note = _text(field, value.get("applies_to", ""), limit=MAX_APPLIES_TO, name="the use note")
        if note:  # left out when blank, so a value without one keeps the shape it always had
            out["applies_to"] = note
        return out
    if kind == "factor":
        data = _only(field, value, ("database", "edition"))
        return {"database": _text(field, data["database"], required=True, limit=200, name="the database"),
                "edition": _text(field, data["edition"], limit=100, name="the edition")}
    if kind == "entity":
        value = upgrade_entity_value(value)
        keys: tuple[str, ...] = ("name", "facilities", "equity_share_pct", "financial_control", "included")
        if isinstance(value, dict) and "control_quoted" in value:
            keys = (*keys, "control_quoted")
        data = _only(field, value, keys)
        facilities = data["facilities"]
        if not isinstance(facilities, list) or len(facilities) > MAX_FACILITIES:
            raise _fail(field, f"facilities must be a list of at most {MAX_FACILITIES} names.")
        if data["included"] is not None and data["included"] not in YES_NO:
            raise _fail(field, "included must be Yes or No, or left blank when the document does not say.")
        if data.get("control_quoted") is not None and data["control_quoted"] not in YES_NO:
            raise _fail(field, "operational control must be Yes or No, or left out when the document does not quote it.")
        entity = {
            "name": _text(field, data["name"], required=True, limit=200, name="the name"),
            "facilities": [_text(field, f, required=True, limit=MAX_FACILITY, name="a facility name") for f in facilities],
            # Both percentages are optional: null means the document does not give it.
            "equity_share_pct": _percent(field, data["equity_share_pct"], "equity share", optional=True),
            "financial_control": _percent(field, data["financial_control"], "financial control", optional=True),
            "included": data["included"],
        }
        if data.get("control_quoted") is not None:  # only when quoted, so a value keeps the shape it always had
            entity["control_quoted"] = data["control_quoted"]
        return entity
    raise AssertionError(f"unknown field kind {kind}")  # pragma: no cover


# --- records and actions ------------------------------------------------------------------

def _by(actor: Actor) -> dict[str, str]:
    return {"name": actor.name, "login": actor.login}


def new_record(field_id: str) -> dict[str, Any]:
    """A field with nothing suggested and nothing decided."""

    return {"field_id": field_id, "suggestion": None, "decision": None, "history": []}


def new_row(field_id: str, actor: Actor, now: datetime) -> dict[str, Any]:
    """A row the reviewer added: a pending decision holding its blank value."""

    record = new_record(field_id)
    record["user_added"] = True
    record["decision"] = {"status": PENDING, "value": blank_value(field_id), "by": _by(actor), "at": stamp(now)}
    record["history"] = [{"at": stamp(now), "by": _by(actor), "action": "add_row"}]
    return record


def status_of(record: Mapping[str, Any]) -> str:
    decision = record.get("decision")
    return str(decision["status"]) if decision else PENDING


def _transition(record: Mapping[str, Any], action: str, decision: dict[str, Any], actor: Actor, now: datetime,
                to: Any = None) -> dict[str, Any]:
    out = copy.deepcopy(dict(record))
    event: dict[str, Any] = {"at": stamp(now), "by": _by(actor), "action": action}
    if to is not None:
        event["to"] = to
    previous = record.get("decision")
    if previous and previous.get("status") != PENDING and action != "revert":  # the decision this one replaces, for Revert
        out["value_history"] = [*record.get("value_history", []), copy.deepcopy(previous)]
    out["decision"] = {**decision, "by": _by(actor), "at": stamp(now)}
    pushed = out.get("value_history", [])[-1:] if previous and previous.get("status") != PENDING and action != "revert" else []
    _trim_value_history(out)
    if pushed:  # the decision just replaced could not be kept (too large): Revert must say so, not go elsewhere
        if out.get("value_history", [])[-1:] == pushed:
            out.pop("previous_lost", None)
        else:
            out["previous_lost"] = True
    out["history"] = _fit([*record.get("history", []), event], out)
    return out


def _trim_value_history(record: dict[str, Any]) -> None:
    """At most MAX_VALUE_HISTORY earlier decisions, fewer (oldest first) if the record would pass MAX_PAYLOAD_BYTES
    once room (HISTORY_ROOM) is left for the event history, so a field can always take one more change."""

    prior: list[dict[str, Any]] = record.get("value_history") or []
    del prior[:-MAX_VALUE_HISTORY]
    while prior and payload_size({**record, "history": []}) + HISTORY_ROOM > MAX_PAYLOAD_BYTES:
        prior.pop(0)
    if prior:
        record["value_history"] = prior
    else:
        record.pop("value_history", None)


def _fit(history: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """The newest MAX_HISTORY events, fewer if the record would not fit MAX_PAYLOAD_BYTES. The
    audit log keeps the full trail."""

    kept = history[-MAX_HISTORY:]
    while kept and payload_size({**record, "history": kept}) > MAX_PAYLOAD_BYTES:
        kept = kept[1:]
    return kept


def _already(field: Mapping[str, Any], status: str) -> MethodologyConflict:
    return MethodologyConflict(
        f"'{field['label']}' is already {status}. Revert it to pending first if you want to decide again.")


def accept(record: Mapping[str, Any], field: Mapping[str, Any], actor: Actor, now: datetime) -> dict[str, Any]:
    """Take the suggestion's value, or the value already set on the field."""

    status = status_of(record)
    if status != PENDING:
        raise _already(field, status)
    suggestion = record.get("suggestion")
    value = suggestion["value"] if suggestion else (record.get("decision") or {}).get("value")
    if value is None:
        raise MethodologyConflict(
            f"There is nothing to accept for '{field['label']}': nothing was suggested and no value is set. "
            "Edit it to enter the value.")
    value = validate_value(field, value)
    return _transition(record, "accept", {"status": ACCEPTED, "value": value}, actor, now, to=value)


def edit(record: Mapping[str, Any], field: Mapping[str, Any], value: Any, actor: Actor,
         now: datetime) -> dict[str, Any]:
    value = validate_value(field, value)
    return _transition(record, "edit", {"status": EDITED, "value": value}, actor, now, to=value)


def reject(record: Mapping[str, Any], field: Mapping[str, Any], reason: Any, actor: Actor,
           now: datetime) -> dict[str, Any]:
    status = status_of(record)
    if status != PENDING:
        raise _already(field, status)
    if not isinstance(reason, str) or not reason.strip():
        raise MethodologyInvalid(f"Say why '{field['label']}' is rejected: a reason is required.")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise MethodologyInvalid(f"The reason is too long: at most {MAX_REASON} characters.")
    return _transition(record, "reject", {"status": REJECTED, "value": None, "reason": reason}, actor, now)


def _cannot_restore(reason: str) -> MethodologyConflict:
    return MethodologyConflict(f"The previous value can no longer be restored ({reason}). Edit the value instead.")


def _restorable(field: Mapping[str, Any], entry: Any) -> dict[str, Any]:
    """An earlier decision as Revert restores it: only its status, value and reason, with the value checked against
    the field again. A stored entry that is not a decision the field accepts is refused (409), never skipped."""

    if not isinstance(entry, Mapping) or entry.get("status") not in (ACCEPTED, EDITED, REJECTED):
        raise _cannot_restore("the saved entry is not a decision")
    if entry["status"] == REJECTED:
        reason = entry.get("reason")
        return {"status": REJECTED, "value": None,
                "reason": reason[:MAX_REASON] if isinstance(reason, str) and "\x00" not in reason else ""}
    try:
        return {"status": entry["status"], "value": validate_value(field, entry.get("value"))}
    except MethodologyInvalid as exc:
        detail = str(exc).split(": ", 1)[-1].rstrip(".")
        raise _cannot_restore(f"it no longer fits the field: {detail}") from None


def revert(record: Mapping[str, Any], field: Mapping[str, Any], actor: Actor, now: datetime) -> dict[str, Any]:
    """Go back to the PREVIOUS value (see the module docstring). When the previous decision was saved but cannot be
    restored (it no longer validates, is not a decision, or was too large to keep) the revert is refused with 409:
    it never quietly falls back to the detected value or to empty."""

    if status_of(record) == PENDING:
        raise MethodologyConflict(f"'{field['label']}' is already pending, so there is nothing to revert.")
    out = copy.deepcopy(dict(record))
    prior: list[dict[str, Any]] = out.get("value_history") or []
    if prior:
        decision = _restorable(field, prior[-1])
        prior.pop()
        source = "previous"
    elif record.get("previous_lost"):
        raise _cannot_restore("it was too large to keep")
    else:
        # No earlier decision was ever saved: the detected value (the suggestion stays, pending) or nothing. A row
        # the reviewer added goes back to its blank value.
        blank = blank_value(field["field_id"]) if record.get("user_added") else None
        decision = {"status": PENDING, "value": blank}
        source = "detected" if record.get("suggestion") else "empty"
    if prior:
        out["value_history"] = prior
    else:
        out.pop("value_history", None)
    event: dict[str, Any] = {"at": stamp(now), "by": _by(actor), "action": "revert", "restored": source}
    if decision.get("value") is not None:
        event["to"] = decision["value"]
    out["decision"] = {**decision, "by": _by(actor), "at": stamp(now)}
    out["history"] = _fit([*record.get("history", []), event], out)
    return out


def remove(record: Mapping[str, Any], field: Mapping[str, Any], actor: Actor, now: datetime) -> dict[str, Any]:
    """Mark a reviewer-added row removed. Rows that come from the report can only be rejected."""

    if not record.get("user_added"):
        raise MethodologyConflict(
            f"'{field['label']}' comes from the report, so it can't be removed. Reject it instead.")
    out = copy.deepcopy(dict(record))
    out["removed"] = True
    out["history"] = _fit([*record.get("history", []), {"at": stamp(now), "by": _by(actor), "action": "remove_row"}],
                          out)
    return out


# Which of the prefill's calls (``methodology_prefill.PART_OUTPUTS``) finds the rows of each group.
ROW_GROUP_PART = {"entities": "boundary", "factor:scope1": "factors", "factor:scope2": "factors", "gwp": "factors"}


def group_of_row(field_id: str) -> str | None:
    """The row group a row id belongs to (``factor:scope1:ab12...`` is ``factor:scope1``), None for a fixed field."""

    match = _ROW_ID.match(field_id)
    return next((g for g, spec in ROW_GROUPS.items() if spec[0] == match.group(1)), None) if match else None


def untouched_suggestion(record: Mapping[str, Any]) -> bool:
    """A row only a read made and nobody has touched: not added by a reviewer, no decision (not even a pending
    one), no history of any reviewer action, no earlier decision to revert to. Only such a row may be replaced
    by a later read."""

    return not (record.get("user_added") or record.get("removed") or record.get("decision")
                or record.get("history") or record.get("value_history") or record.get("previous_lost"))


def replaced_by_read(record: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """The row marked removed, because a later read no longer suggests it (never deleted, like any removed row)."""

    out = copy.deepcopy(dict(record))
    out["removed"] = True
    out["replaced_by_read"] = stamp(now)
    return out


def with_suggestion(record: Mapping[str, Any], field: Mapping[str, Any], suggestion: Mapping[str, Any]
                    ) -> dict[str, Any]:
    """The record with a proposal on it: only ``suggestion`` changes (its value is validated and
    cleaned); the decision and history stay as they are."""

    out = copy.deepcopy(dict(record))
    out["suggestion"] = bound_suggestion(field, suggestion)
    return out


def _clip(value: Any, limit: int) -> str | None:
    """Text cut to ``limit`` characters, without null characters or lone surrogates."""

    if not isinstance(value, str):
        return None
    return value.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")[:limit]


def _bound_reference(reference: Any) -> Any:
    if isinstance(reference, Mapping):
        kept: dict[str, Any] = {k: _clip(reference[k], MAX_SOURCE_REFERENCE_TEXT)
                                for k in _SOURCE_REFERENCE_TEXT if isinstance(reference.get(k), str)}
        page = reference.get("page_number")
        if isinstance(page, int) and not isinstance(page, bool):
            kept["page_number"] = page
        return kept
    return _clip(reference, MAX_SOURCE_REFERENCE_TEXT)


def _bound_evidence(items: list[Any]) -> list[dict[str, Any]]:
    """The quote behind each entry or option of a list suggestion: label, quote and where it was read."""

    out: list[dict[str, Any]] = []
    for item in items[:MAX_EVIDENCE]:
        if not isinstance(item, Mapping):
            continue
        raw_quote = item.get("quote")
        entry: dict[str, Any] = {"label": _clip(item.get("label"), 100) or "",
                                 "quote": _clip(raw_quote, MAX_EVIDENCE_QUOTE) or "",
                                 "document_id": _clip(item.get("document_id"), 100) or "",
                                 "file_name": _clip(item.get("file_name"), 255) or ""}
        if isinstance(raw_quote, str) and len(raw_quote) > MAX_EVIDENCE_QUOTE:
            entry["quote_truncated"] = True
        if isinstance(item.get("reason"), str) and item["reason"].strip():
            entry["reason"] = _clip(item["reason"], 240)
        reference = item.get("source_reference")
        if isinstance(reference, Mapping):  # only where it was read: page, sheet, cell (no snippet or box)
            kept: dict[str, Any] = {k: _clip(reference[k], 100) for k in ("sheet_name", "cell_or_range")
                                    if isinstance(reference.get(k), str)}
            page = reference.get("page_number")
            if isinstance(page, int) and not isinstance(page, bool):
                kept["page_number"] = page
            entry["source_reference"] = kept
        elif isinstance(reference, str):
            entry["source_reference"] = _clip(reference, 100)
        out.append(entry)
    return out


def bound_suggestion(field: Mapping[str, Any], suggestion: Mapping[str, Any]) -> dict[str, Any]:
    """The suggestion with a validated value and every other part bounded: the quote is cut to
    MAX_QUOTE characters (``quote_truncated: true``), the other texts to their limits, the
    source reference to the contract's plain keys, and unknown keys are dropped. MethodologyInvalid
    if the result is still over MAX_SUGGESTION_BYTES."""

    out: dict[str, Any] = {"value": validate_value(field, suggestion["value"])}
    for key, limit in _SUGGESTION_TEXT.items():
        if key in suggestion:
            raw = suggestion[key]
            out[key] = _clip(raw, limit)
            if key == "quote" and isinstance(raw, str) and len(raw) > limit:
                out["quote_truncated"] = True
    if "source_reference" in suggestion:
        out["source_reference"] = _bound_reference(suggestion["source_reference"])
    evidence = suggestion.get("evidence")
    if isinstance(evidence, list) and isinstance(out["value"], list):
        kept_evidence = _bound_evidence(evidence)
        entries: list[Any] = out["value"]
        total = len(entries)
        del entries[len(kept_evidence):]  # an entry without a quote is never kept
        del kept_evidence[len(entries):]
        while kept_evidence and payload_size({"e": kept_evidence}) > MAX_EVIDENCE_BYTES:
            kept_evidence.pop()  # the last entry goes with its quote
            entries.pop()
        if not entries and total:
            raise MethodologyInvalid(f"The suggestion for '{field['label']}' is too long to record.")
        out["evidence"] = kept_evidence
        if len(entries) < total:
            out["entries_omitted"] = total - len(entries)
    elif isinstance(evidence, list) and isinstance(out["value"], dict):
        out["evidence"] = _bound_evidence(evidence)  # a value made from two quotes (a period from its wording and its title)
    if payload_size({k: v for k, v in out.items() if k != "evidence"}) > MAX_SUGGESTION_BYTES:
        raise MethodologyInvalid(f"The suggestion for '{field['label']}' is too long to record.")
    return out


async def save_suggestion(db: AsyncSession, *, org_id: uuid.UUID, engagement_id: uuid.UUID, field_id: str,
                          suggestion: Mapping[str, Any], user_id: uuid.UUID | None) -> dict[str, Any] | None:
    """Put a proposal on a field's stored record under a row lock, so it cannot overwrite a
    reviewer's concurrent decision. A fixed field gets its row if it has none. None when the
    field does not exist (an unknown id, or a row that is missing or removed). Raises
    MethodologyInvalid for a value the field does not allow."""

    field = catalog_field(field_id) or row_field(field_id)
    if field is None:
        return None
    if catalog_field(field_id) is not None:
        await workpaper_item_service.insert_item(
            db, org_id=org_id, engagement_id=engagement_id, kind=KIND, item_key=field_id,
            payload=new_record(field_id), user_id=user_id)
    found = await workpaper_item_service.get_items(db, engagement_id, KIND, [field_id], for_update=True)
    if not found or found[0]["payload"].get("removed"):
        return None
    updated = with_suggestion(found[0]["payload"], field, suggestion)
    if payload_size(updated) > MAX_PAYLOAD_BYTES:
        raise MethodologyInvalid(f"The suggestion for '{field['label']}' is too long to record.")
    row = await workpaper_item_service.update_payload(db, engagement_id, KIND, field_id, updated, user_id)
    return row["payload"]


# --- page state: the prefill marker and the optional rows a reviewer revealed ---------------------

META_KEY = "meta:state"  # one extra item per engagement, never a field: {prefill_ran_at, revealed}
NOT_CHECKED, NOT_DETECTED, HAS_VALUE = "not_checked", "not_detected", "has_value"


# The fields the page had when prefill first shipped. A prefill recorded before it stored which fields
# it covered is taken to have covered these and no others, so a row added later reads "Not checked yet".
LEGACY_PREFILL_COVERED = frozenset({
    "reporting_period", "consolidation_approach",
    *(f"category:scope1:{k}" for k in ("stationary", "mobile", "process", "fugitive")),
    *(f"category:{b}:{k}" for b in ("location", "market") for k in ("electricity", "heating", "steam", "cooling")),
    "category:biogenic:direct", "category:biogenic:indirect",
    "exclusion:boundary", "exclusion:inventory", "exclusion:materiality",
    "gwp", "calculation:approach", "calculation:process",
})


def new_meta() -> dict[str, Any]:
    return {"prefill_ran_at": None, "prefill_covered": [], "revealed": []}


def has_value(record: Mapping[str, Any]) -> bool:
    """Something is on the row: a suggestion, or a decision that carries a value or a verdict
    (a reverted field is back to nothing)."""

    if record.get("suggestion"):
        return True
    decision = record.get("decision")
    if not decision:
        return False
    return bool(decision["status"] != PENDING or decision.get("value") is not None)


def display_state(record: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    """not_checked (no prefill has finished, nothing on the row), not_detected (a prefill
    finished and found nothing, no decision), or has_value."""

    if has_value(record):
        return HAS_VALUE
    if not meta.get("prefill_ran_at"):
        return NOT_CHECKED
    covered = meta.get("prefill_covered")
    covered_ids = set(covered) if covered else LEGACY_PREFILL_COVERED  # a run that did not look at this field says nothing
    return NOT_DETECTED if record.get("field_id") in covered_ids else NOT_CHECKED


def market_based_reported(records: Mapping[str, Mapping[str, Any]], ids: Sequence[str] = MARKET_CATEGORY_IDS) -> bool:
    """Whether the company reports a market-based Scope 2 number, read from the page: at least one
    of the market-based categories is Yes. A category counts when the reviewer accepted or edited
    it to Yes, or, while still undecided, when Claude suggested Yes. A rejected category, or one
    that is No or Not detected, does not."""

    for field_id in ids:
        record = records.get(field_id)
        if not record:
            continue
        decision = record.get("decision")
        if decision and decision.get("status") in (ACCEPTED, EDITED):
            if decision.get("value") == "Yes":
                return True
        elif (not decision or decision.get("status") == PENDING) and (record.get("suggestion") or {}).get("value") == "Yes":
            return True
    return False


def is_shown(field: Mapping[str, Any], record: Mapping[str, Any], meta: Mapping[str, Any],
             records: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """Must-appear rows always show. An optional one shows once it has a value or the reviewer
    revealed it with "Add an item"; a conditional one (``shown_if_yes``) also shows while one of
    the categories it depends on is Yes."""

    if bool(field.get("required", True)) or has_value(record) or field["field_id"] in meta.get("revealed", []):
        return True
    depends: list[str] = field.get("shown_if_yes") or []
    return bool(depends) and market_based_reported(records or {}, depends)


def shown_note(field: Mapping[str, Any], record: Mapping[str, Any], meta: Mapping[str, Any],
               records: Mapping[str, Mapping[str, Any]] | None = None) -> str | None:
    """Why a conditional row is on the page when its condition is not met: only Claude's suggestion
    is there (no decision, not added by the reviewer), so it is shown rather than hidden."""

    depends: list[str] = field.get("shown_if_yes") or []
    if (depends and record.get("suggestion") and not record.get("decision")
            and field["field_id"] not in meta.get("revealed", []) and not market_based_reported(records or {}, depends)):
        return "Shown because Sustentra's AI found it, although no market-based category is Yes."
    return None


def public(record: Mapping[str, Any]) -> dict[str, Any]:
    """A stored record as the API returns it."""

    out = {"field_id": record["field_id"], "suggestion": record.get("suggestion"),
           "decision": record.get("decision"), "history": record.get("history", []),
           "value_history": record.get("value_history", []),
           "user_added": bool(record.get("user_added"))}
    if str(record["field_id"]).startswith("entity:"):  # entity values saved before "Included" had its own key
        for key in ("suggestion", "decision"):
            if isinstance(out[key], dict) and "value" in out[key]:
                out[key] = {**out[key], "value": upgrade_entity_value(out[key]["value"])}
        out["value_history"] = [{**e, "value": upgrade_entity_value(e.get("value"))} if isinstance(e, dict) else e
                                for e in out["value_history"]]
    return out
