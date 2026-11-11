"""Methodology review (the page that checks the client's stated boundary and methods): the
fixed list of decision fields and the rules for a reviewer's actions on them, as pure
functions. ``backend/app/api/methodology_review.py`` locks, saves and audits.

Each field is one ``workpaper_items`` row (kind ``methodology``, item_key = field id):

    {field_id, suggestion: null | {value, quote, document_id, file_name, source_reference,
                                   origin: "ai", model, request_id, suggested_at},
     decision: null | {status: pending|accepted|edited|rejected, value, reason?, by, at},
     history: [{at, by, action, from?, to?}], user_added?: true, removed?: true}

A suggestion is only a proposal (written by the AI task, never here). The workpaper value
of a field is its decision's ``value`` when the status is accepted or edited; a rejected
decision keeps no value.

    from \\ action        accept     edit     reject     revert
    none / pending        accepted   edited   rejected   409
    accepted / edited     409        edited   409        pending
    rejected              409        edited   409        pending

Rows (entities, emission-factor sources) are added by the reviewer under a server-made id
and removed only if the reviewer added them; a removed row is marked, never deleted, so the
record stays complete. Refusals are plain sentences, because the frontend shows them as is.
"""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from backend.app.services.request_service import Actor, stamp

KIND = "methodology"

CONSOLIDATION_APPROACHES = ("Equity Share", "Financial Control", "Operational Control")
INCLUSIONS = ("Yes", "No", "Not detected")
GWP_SETS = ("AR4", "AR5", "AR6")
GWP_HORIZONS = ("100-year", "20-year")
GWP_SET_LABELS = {
    "AR4": "IPCC Fourth Assessment Report (AR4)",
    "AR5": "IPCC Fifth Assessment Report (AR5)",
    "AR6": "IPCC Sixth Assessment Report (AR6)",
}
YES_NO = ("Yes", "No")

PENDING, ACCEPTED, EDITED, REJECTED = "pending", "accepted", "edited", "rejected"
STATUSES = (PENDING, ACCEPTED, EDITED, REJECTED)

MAX_TEXT = 4000
MAX_REASON = 500

GROUPS = (
    ("boundary", "Organizational boundary"),
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
}
_ROW_ID = re.compile(r"^(entity|factor:scope1|factor:scope2):[a-z0-9]{4,32}$")


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
        {"key": "equity_share_pct", "label": "Equity share (%)", "kind": "percent"},
        {"key": "financial_control", "label": "Financial control (%)", "kind": "percent"},
        {"key": "operational_control", "label": "Operational control", "kind": "enum", "allowed": list(YES_NO)},
    ],
    "factor": [
        {"key": "database", "label": "Database", "kind": "text"},
        {"key": "edition", "label": "Edition", "kind": "text"},
    ],
    "gwp": [
        {"key": "set", "label": "GWP set", "kind": "enum", "allowed": list(GWP_SETS)},
        {"key": "horizon", "label": "Time horizon", "kind": "enum", "allowed": list(GWP_HORIZONS)},
    ],
}


def _field(field_id: str, group: str, label: str, kind: str, allowed: Any = None) -> dict[str, Any]:
    field: dict[str, Any] = {"field_id": field_id, "group": group, "group_label": _GROUP_LABELS[group],
                             "label": label, "kind": kind, "user_added": False}
    if allowed is not None:
        field["allowed"] = allowed
    if kind in _PARTS:
        field["parts"] = copy.deepcopy(_PARTS[kind])
    return field


def _static_fields() -> list[dict[str, Any]]:
    fields = [
        _field("reporting_period", "boundary", "Reporting period", "text"),
        _field("consolidation_approach", "boundary", "Consolidation approach", "enum",
               list(CONSOLIDATION_APPROACHES)),
    ]
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
    ]
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
    field = _field(field_id, group, label, kind, {"operational_control": list(YES_NO)} if kind == "entity" else None)
    field["user_added"] = True
    return field


def new_row_id(group: str) -> str:
    """A fresh id for a row in ``group`` (entities, factor:scope1, factor:scope2)."""

    if group not in ROW_GROUPS:
        raise MethodologyInvalid("Rows can be added to the entities and to the Scope 1 or Scope 2 emission factor sources.")
    return f"{ROW_GROUPS[group][0]}:{uuid.uuid4().hex[:12]}"


def blank_value(field_id: str) -> Any:
    """What a new row holds until the reviewer fills it in."""

    if field_id.startswith("entity:"):
        return {"name": "", "facilities": [], "equity_share_pct": 0, "financial_control": 0,
                "operational_control": "No"}
    return {"database": "", "edition": ""}


# --- value validation -------------------------------------------------------------------

def _fail(field: Mapping[str, Any], problem: str) -> MethodologyInvalid:
    return MethodologyInvalid(f"'{field['label']}': {problem}")


def _text(field: Mapping[str, Any], value: Any, *, required: bool = False, limit: int = MAX_TEXT,
          name: str = "the value") -> str:
    if not isinstance(value, str):
        raise _fail(field, f"{name} must be text.")
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


def _percent(field: Mapping[str, Any], value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 100:
        raise _fail(field, f"{name} must be a number from 0 to 100.")
    return value


def validate_value(field: Mapping[str, Any], value: Any) -> Any:
    """The value cleaned for its field, or MethodologyInvalid with a sentence."""

    kind = field["kind"]
    if kind == "text":
        return _text(field, value)
    if kind == "enum":
        if not isinstance(value, str) or value not in field["allowed"]:
            raise _fail(field, "choose one of " + ", ".join(field["allowed"]) + ".")
        return value
    if kind == "gwp":
        data = _only(field, value, ("set", "horizon"))
        if data["set"] not in GWP_SETS or data["horizon"] not in GWP_HORIZONS:
            raise _fail(field, f"the set must be one of {', '.join(GWP_SETS)} and the horizon one of "
                               f"{', '.join(GWP_HORIZONS)}.")
        return {"set": data["set"], "horizon": data["horizon"]}
    if kind == "factor":
        data = _only(field, value, ("database", "edition"))
        return {"database": _text(field, data["database"], required=True, limit=200, name="the database"),
                "edition": _text(field, data["edition"], limit=100, name="the edition")}
    if kind == "entity":
        data = _only(field, value, ("name", "facilities", "equity_share_pct", "financial_control",
                                    "operational_control"))
        facilities = data["facilities"]
        if not isinstance(facilities, list) or len(facilities) > 50:
            raise _fail(field, "facilities must be a list of at most 50 names.")
        if data["operational_control"] not in YES_NO:
            raise _fail(field, "operational control must be Yes or No.")
        return {
            "name": _text(field, data["name"], required=True, limit=200, name="the name"),
            "facilities": [_text(field, f, required=True, limit=200, name="a facility name") for f in facilities],
            "equity_share_pct": _percent(field, data["equity_share_pct"], "equity share"),
            "financial_control": _percent(field, data["financial_control"], "financial control"),
            "operational_control": data["operational_control"],
        }
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
    before = (record.get("decision") or {}).get("value")
    event: dict[str, Any] = {"at": stamp(now), "by": _by(actor), "action": action}
    if before is not None:
        event["from"] = before
    if to is not None:
        event["to"] = to
    out["decision"] = {**decision, "by": _by(actor), "at": stamp(now)}
    out["history"] = [*record.get("history", []), event]
    return out


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


def revert(record: Mapping[str, Any], field: Mapping[str, Any], actor: Actor, now: datetime) -> dict[str, Any]:
    if status_of(record) == PENDING:
        raise MethodologyConflict(f"'{field['label']}' is already pending, so there is nothing to revert.")
    return _transition(record, "revert", {"status": PENDING, "value": None}, actor, now)


def remove(record: Mapping[str, Any], field: Mapping[str, Any], actor: Actor, now: datetime) -> dict[str, Any]:
    """Mark a reviewer-added row removed. Rows that come from the report can only be rejected."""

    if not record.get("user_added"):
        raise MethodologyConflict(
            f"'{field['label']}' comes from the report, so it can't be removed. Reject it instead.")
    out = copy.deepcopy(dict(record))
    out["removed"] = True
    out["history"] = [*record.get("history", []), {"at": stamp(now), "by": _by(actor), "action": "remove_row"}]
    return out


def public(record: Mapping[str, Any]) -> dict[str, Any]:
    """A stored record as the API returns it."""

    return {"field_id": record["field_id"], "suggestion": record.get("suggestion"),
            "decision": record.get("decision"), "history": record.get("history", []),
            "user_added": bool(record.get("user_added"))}
