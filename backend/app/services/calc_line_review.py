"""Reviewer decisions on calculation lines: a method choice, or an input of a line's working (company or recomputed
side), kept add-only. ``api/calculation_line_review.py`` locks, saves and audits; the rules are
``services/review_field`` (the Methodology page's state machine) with this page's checks.

A decision targets one *stream*: a choice of the line's trace (``choice|<choice id>|``), or one side of one input
(``input|<input id>|company`` or ``|recomputed``; a row of an input is ``<input id>/<row id>``). Each stream is a
field in ``review_field``'s record shape. Storage is ``workpaper_items`` kind ``calc_line`` (migration 0028) and
add-only: every action inserts a NEW row (never an update) holding

    {line_key, stream, target: choice|input, target_id, side, seq, record}

where ``record`` is the stream's whole field record after the move and ``seq`` counts up from 1 per stream. The
row with the highest ``seq`` is the stream's current state; the earlier rows are what the reviewer decided before.
``item_key`` is a hash of (line key, stream) and ``seq``: a line key can fill the whole 200-character key limit.

A decision is shown on the trace here (``with_decisions``) and read into the line's working by
``calc_trace/decisions`` (F3b): an accepted or edited value on the recomputed side is an operand, a pending AI
suggestion never is. So a value that would reach the arithmetic is checked here first: a number above 0, in the
input's own unit, on an input a line can decide (the activity, an emission factor, a distance). The GWP, the
consolidated share, the unit conversion and the grid region are set for the whole engagement: 409.

A decision on a line that no longer exists (deleted or renamed) is kept and listed as orphaned, never applied to
another line (``split_orphans``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.services import review_field
from backend.app.services.calc_trace._line import normalise_unit
from backend.app.services.calc_trace.decisions import not_decidable
from backend.app.services.request_service import Actor
from backend.app.services.review_field import ReviewConflict, ReviewInvalid
from backend.app.services.workpaper_item_service import MAX_PAYLOAD_BYTES, _row, insert_item, payload_size

KIND = "calc_line"
CHOICE, INPUT = "choice", "input"
SIDES = ("company", "recomputed")
CHOICE_ACTIONS = ("accept", "choose", "reject", "revert")
INPUT_ACTIONS = ("accept", "edit", "reject", "revert")
MAX_TEXT = 200  # a text value, a choice or input id
MAX_UNIT = 40
MAX_NUMBER = 1e15
EXTRAS = ("reason", "unit", "document_id", "kind", "basis")  # what a revert restores beyond status and value
MAX_CITATION = 200
REVIEWER_ENTERED = "reviewer_entered"  # the recomputed side's value was typed by a reviewer, with the reason
COMPANY_INPUT = "company_input"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class RecordTooLarge(ReviewInvalid):
    """The stream's record would pass the size limit of one stored row (422)."""


class Refused(ReviewConflict):
    """A decision the line's working cannot take (409), with a code for the frontend: ``not_decidable`` (set for the
    whole engagement), ``mixed_line`` (the line mixes fuels or units), ``stale`` (the evidence changed under it),
    ``no_working``, ``not_counted`` (its category cannot count it)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def basis_of(trace: Mapping[str, Any], holder: Mapping[str, Any] | None = None,
             choice: Mapping[str, Any] | None = None) -> str:
    """What a recomputed decision replaces, as stored with it (compact JSON, so a revert restores it as text): the
    automatic value, its unit and factor source, and the line's grid region; for a choice, the default option. When
    any of these is different when the decision is read, the decision is stale (``calc_trace/decisions``)."""

    if choice is not None:
        return json.dumps({"chosen": default_option(choice)}, separators=(",", ":"), ensure_ascii=False)
    side = (holder or {}).get("recomputed") or {}
    source: Mapping[str, Any] = side["source"] if isinstance(side.get("source"), Mapping) else {}
    grid = (((trace.get("inputs") or {}).get("grid_region") or {}).get("recomputed") or {})
    citation = source.get("citation")
    return json.dumps({"value": side.get("value"), "unit": side.get("unit"),
                       "source": str(citation)[:MAX_CITATION] if citation else None,
                       "grid_region": grid.get("value")}, separators=(",", ":"), ensure_ascii=False)


# --- streams and keys ------------------------------------------------------------------------------

def stream_of(target: str, target_id: str, side: str | None = None) -> str:
    return f"{target}|{target_id}|{side or ''}"


def item_key(line_key: str, stream: str, seq: int) -> str:
    digest = hashlib.sha256(f"{line_key}\x00{stream}".encode()).hexdigest()[:40]
    return f"{digest}:{seq}"


def new_record(stream: str) -> dict[str, Any]:
    return {"field_id": stream, "suggestion": None, "decision": None, "history": []}


def clean_id(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT or _CONTROL.search(value):
        raise ReviewInvalid(f"The {what} is not valid.")
    return value


# --- the stored events -------------------------------------------------------------------------------

async def lock(db: AsyncSession, engagement_id: uuid.UUID, line_key: str) -> None:
    """Serialise the decisions on one line until the transaction ends. Add-only rows cannot be locked with
    ``FOR UPDATE`` (it needs UPDATE); a transaction advisory lock needs no grant and holds across workers."""

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:key AS text), 0))"),
        {"key": f"calc-line-decisions:{engagement_id}:{line_key}"},
    )


async def current(db: AsyncSession, engagement_id: uuid.UUID, line_key: str | None = None) -> list[dict[str, Any]]:
    """The current event of every stream (the highest ``seq``) of the engagement, or of one line."""

    where = "engagement_id = :engagement_id AND kind = :kind" + (" AND payload ->> 'line_key' = :line_key"
                                                                  if line_key is not None else "")
    params: dict[str, Any] = {"engagement_id": engagement_id, "kind": KIND}
    if line_key is not None:
        params["line_key"] = line_key
    rows = await db.execute(
        text(
            f"""
            SELECT DISTINCT ON (payload ->> 'line_key', payload ->> 'stream')
                   kind, item_key, payload, created_by, created_at, updated_by, updated_at
              FROM workpaper_items
             WHERE {where}
             ORDER BY payload ->> 'line_key', payload ->> 'stream', (payload ->> 'seq')::int DESC
            """
        ),
        params,
    )
    return [_row(r)["payload"] for r in rows.mappings()]


async def append(db: AsyncSession, *, org_id: uuid.UUID, engagement_id: uuid.UUID, line_key: str, stream: str,
                 target: str, target_id: str, side: str | None, previous_seq: int, record: dict[str, Any],
                 user_id: uuid.UUID | None) -> dict[str, Any]:
    """Insert the next event of the stream. Never an update. Call it under ``lock``."""

    seq = previous_seq + 1
    event = {"line_key": line_key, "stream": stream, "target": target, "target_id": target_id, "side": side,
             "seq": seq, "record": record}
    if payload_size(event) > MAX_PAYLOAD_BYTES:
        raise RecordTooLarge("This decision's history is too long to record another change. Contact support if you "
                             "need more.")
    row = await insert_item(db, org_id=org_id, engagement_id=engagement_id, kind=KIND,
                            item_key=item_key(line_key, stream, seq), payload=event, user_id=user_id)
    if row is None:  # the same sequence number exists: another request got there first
        raise ReviewConflict("This decision was changed by someone else a moment ago. Reload to see the current "
                             "state.")
    return event


def records_of(events: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """``{stream: record}`` of one line's current events."""

    return {str(e["stream"]): e["record"] for e in events}


def split_orphans(events: Iterable[Mapping[str, Any]], line_keys: Iterable[str]
                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The current decisions on lines that exist, and those on lines that do not (deleted or renamed): kept,
    reported, never applied to another line. Each is ``public_event``."""

    known = set(line_keys)
    placed: list[dict[str, Any]] = []
    orphaned: list[dict[str, Any]] = []
    for event in events:
        (placed if event["line_key"] in known else orphaned).append(public_event(event))
    return placed, orphaned


# --- how a decision looks on the wire ----------------------------------------------------------------

def wire_decision(decision: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A stored decision as the trace schema's ``Decision`` (``by`` is the name; the login stays in the record)."""

    if not decision:
        return None
    by = decision.get("by")
    out: dict[str, Any] = {"status": decision["status"], "by": str(by.get("name")) if isinstance(by, Mapping) else
                           str(by or ""), "at": decision.get("at", "")}
    for key in ("value", "unit", "reason", "document_id", "kind"):
        if decision.get(key) is not None or key == "value" and "value" in decision:
            out[key] = decision.get(key)
    return out


def public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"suggestion": record.get("suggestion"), "decision": wire_decision(record.get("decision")),
            "history": record.get("history", []), "value_history": record.get("value_history", [])}


def public_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {"line_key": event["line_key"], "target": event["target"], "id": event["target_id"],
            "side": event.get("side"), **public_record(event["record"])}


def _decide(node: dict[str, Any], record: Mapping[str, Any]) -> None:
    decision = wire_decision(record.get("decision"))
    if decision is not None:
        node["decision"] = decision
    if record.get("suggestion"):
        node["suggestion"] = copy.deepcopy(record["suggestion"])


def with_decisions(trace: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The trace with each choice's and input side's decision state on it (``decision``, ``suggestion``), for the
    frontend to show. Display only: ``chosen`` and every value and status are exactly as the trace had them, so
    no total moves (F3b reads decisions into the totals)."""

    out: dict[str, Any] = copy.deepcopy(dict(trace))
    for choice in out.get("choices") or []:
        record = records.get(stream_of(CHOICE, str(choice["id"])))
        if record:
            _decide(choice, record)
    for input_id, item in (out.get("inputs") or {}).items():
        for side in SIDES:
            record = records.get(stream_of(INPUT, input_id, side))
            if record:
                _decide(_side(item, side), record)
        for row in item.get("rows") or []:
            for side in SIDES:
                record = records.get(stream_of(INPUT, f"{input_id}/{row['id']}", side))
                if record:
                    _decide(_side(row, side), record)
    return out


def _side(holder: dict[str, Any], side: str) -> dict[str, Any]:
    """The holder's side, made as an empty "not reported" side when the trace has none (a reviewer can enter a
    value where the company reported nothing)."""

    if not isinstance(holder.get(side), dict):
        holder[side] = {"value": None, "unit": None, "status": "not_reported"}
    node: dict[str, Any] = holder[side]
    return node


# --- finding the target in the live trace ----------------------------------------------------------

def find_choice(trace: Mapping[str, Any], choice_id: str) -> Mapping[str, Any] | None:
    return next((c for c in trace.get("choices") or [] if c.get("id") == choice_id), None)


def find_input(trace: Mapping[str, Any], input_id: str) -> tuple[Mapping[str, Any], Mapping[str, Any] | None] | None:
    """``(the input, the row or None)`` for ``input_id`` (``"<input>"`` or ``"<input>/<row id>"``); None when the
    trace has no such input or row. Input ids hold no ``/``; row ids may."""

    inputs = trace.get("inputs") or {}
    if input_id in inputs:
        return inputs[input_id], None
    base, _, row_id = input_id.partition("/")
    item = inputs.get(base)
    if item is None or not row_id:
        return None
    row = next((r for r in item.get("rows") or [] if r.get("id") == row_id), None)
    return (item, row) if row is not None else None


# --- the actions ---------------------------------------------------------------------------------------

def _seeded(record: Mapping[str, Any], offered: Mapping[str, Any] | None) -> dict[str, Any]:
    """The record, holding the trace's AI suggestion when it has none of its own, so Accept can take it."""

    out = dict(record)
    if not out.get("suggestion") and isinstance(offered, Mapping) and offered.get("value") is not None:
        out["suggestion"] = copy.deepcopy(dict(offered))
    return out


def default_option(choice: Mapping[str, Any]) -> str | None:
    """The option used with no decision: ``chosen`` while nobody has decided (``chosen_by`` default)."""

    return str(choice["chosen"]) if choice.get("chosen_by") == "default" else None


def decide_choice(record: Mapping[str, Any], choice: Mapping[str, Any], action: str, *, option_id: Any = None,
                  reason: Any = None, actor: Actor, now: datetime, basis: str | None = None) -> dict[str, Any]:
    """accept (the AI's suggestion) | choose (an option) | reject | revert, on a choice of the line."""

    label = str(choice.get("label") or choice["id"])
    options = {str(o["id"]): o for o in choice.get("options") or []}

    def validate(value: Any) -> str:
        if not isinstance(value, str) or value not in options:
            raise ReviewInvalid(f"'{label}': {_shown(value)} is not one of this line's options.")
        option = options[value]
        if not option.get("available", True):
            why = option.get("why_unavailable")
            raise ReviewConflict(f"'{option.get('label') or value}' can't be used for this line"
                                 + (f": {str(why).rstrip('.')}." if why else "."))
        return value

    record = _seeded(record, choice.get("suggestion"))
    if action == "accept":
        return _with_basis(review_field.accept(record, label, validate, actor, now, instead="Pick an option instead."),
                           basis)
    if action == "choose":
        if option_id is None:
            raise ReviewInvalid(f"Pick an option for '{label}'.")
        picked = validate(option_id)
        needs_reason = picked != default_option(choice)
        why = review_field.clean_reason(
            reason, missing=f"Say why '{label}' is not left as it is: a reason is required." if needs_reason else None)
        extra = {"reason": why} if why else {}
        if basis:
            extra["basis"] = basis
        return review_field.edit(record, validate, picked, actor, now, extra=extra or None)
    if action == "reject":
        return review_field.reject(record, label, reason, actor, now)
    if action == "revert":
        return review_field.revert(record, label, validate, lambda: None, actor, now, extras=EXTRAS)
    raise ReviewInvalid(f"'{action}' is not an action on a choice.")


def _with_basis(record: dict[str, Any], basis: str | None) -> dict[str, Any]:
    if basis and isinstance(record.get("decision"), dict):
        record["decision"]["basis"] = basis
    return record


def decide_input(record: Mapping[str, Any], item: Mapping[str, Any], row: Mapping[str, Any] | None, side: str,
                 action: str, *, value: Any = None, unit: Any = None, reason: Any = None, document_id: Any = None,
                 actor: Actor, now: datetime, basis: str | None = None) -> dict[str, Any]:
    """``basis`` (``basis_of``): what a recomputed decision replaces, stored with it to tell later when it is stale."""

    """accept (the AI's suggestion) | edit | reject | revert, on one side of an input (or of one of its rows)."""

    if side not in SIDES:
        raise ReviewInvalid("The side is company or recomputed.")
    holder: Mapping[str, Any] = row if row is not None else item
    label = f"{item.get('label') or item.get('id')}{' · ' + str(row.get('label') or row.get('id')) if row else ''}" \
            f" ({side})"
    sides = [s for s in (holder.get(side), holder.get("recomputed"), holder.get("company"), item.get("recomputed"),
                         item.get("company")) if isinstance(s, Mapping)]
    expected_unit = next((str(s["unit"]) for s in sides if s.get("unit")), None)
    numeric = _numeric(sides)
    own = holder.get(side)
    record = _seeded(record, own.get("suggestion") if isinstance(own, Mapping) else None)

    operand = side == "recomputed"  # this side's value is worked into the line's numbers

    def validate(given: Any) -> Any:
        value = _input_value(label, given, numeric)
        if operand and not isinstance(value, str) and value <= 0:
            raise ReviewInvalid(f"'{label}': enter a number above 0.")
        return value

    if operand and action in ("accept", "edit"):
        target = str(item.get("id") or "") + (f"/{row.get('id')}" if row is not None else "")
        why = not_decidable(target)
        if why is not None:
            raise Refused("not_decidable", f"'{label}' can't be changed for one line: {why}.")
    if not operand:
        basis = None
    if action == "accept":
        accepted = review_field.accept(record, label, validate, actor, now, carry=("unit",))
        decided = accepted["decision"]
        if operand and expected_unit and not isinstance(decided.get("value"), str) and not decided.get("unit"):
            raise ReviewInvalid(f"'{label}': the suggestion gives no unit. Edit the value and enter it in "
                                f"{expected_unit}.")
        if operand and decided.get("unit"):
            _unit(label, decided["unit"], expected_unit, True)
        return _with_basis(accepted, basis)
    if action == "edit":
        entered = validate(value)
        numeric_entry = numeric is not False and not isinstance(entered, str)
        own_unit = _unit(label, unit, expected_unit, numeric_entry)
        if side == "recomputed":
            why = review_field.clean_reason(
                reason, missing=f"Say why the recomputed value of '{label}' is changed: a reason is required.")
        else:
            why = review_field.clean_reason(reason)
        if operand and numeric_entry and expected_unit and (unit is None or (isinstance(unit, str)
                                                                             and not unit.strip())):
            raise ReviewInvalid(f"'{label}' is in {expected_unit}: enter the unit with the value.")
        extra: dict[str, Any] = {"kind": REVIEWER_ENTERED if side == "recomputed" else COMPANY_INPUT}
        if own_unit:
            extra["unit"] = own_unit
        if why:
            extra["reason"] = why
        if document_id is not None:
            extra["document_id"] = clean_id(document_id, "document id")
        if basis:
            extra["basis"] = basis
        return review_field.edit(record, validate, entered, actor, now, extra=extra)
    if action == "reject":
        return review_field.reject(record, label, reason, actor, now)
    if action == "revert":
        return review_field.revert(record, label, validate, lambda: None, actor, now, extras=EXTRAS)
    raise ReviewInvalid(f"'{action}' is not an action on an input.")


def _shown(value: Any) -> str:
    text_ = json.dumps(value, ensure_ascii=False, default=str)
    return text_ if len(text_) <= 60 else text_[:57] + "..."


def _numeric(sides: list[Mapping[str, Any]]) -> bool | None:
    """True when the input's values are numbers, False when text, None when no side holds a value to tell by."""

    values = [s.get("value") for s in sides if s.get("value") is not None]
    if not values:
        return None
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def _input_value(label: str, value: Any, numeric: bool | None) -> Any:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReviewInvalid(f"'{label}': enter a number or text.")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or len(stripped) > MAX_TEXT or _CONTROL.search(stripped):
            raise ReviewInvalid(f"'{label}': enter a value of at most {MAX_TEXT} characters, without control "
                                "characters.")
        if numeric is not True:
            return stripped
        try:
            number = float(stripped.replace(",", ""))
        except ValueError:
            raise ReviewInvalid(f"'{label}': enter a number.") from None
    else:
        if numeric is False:
            raise ReviewInvalid(f"'{label}': this input takes text, not a number.")
        number = value
    if not math.isfinite(number) or abs(number) > MAX_NUMBER:
        raise ReviewInvalid(f"'{label}': enter a number between -{MAX_NUMBER:.0e} and {MAX_NUMBER:.0e}.")
    return number


def _unit(label: str, given: Any, expected: str | None, numeric: bool) -> str | None:
    """The unit a value is stored in: the input's own. A different unit is refused, never converted."""

    if not numeric:
        return None
    if given is None or (isinstance(given, str) and not given.strip()):
        return expected
    if not isinstance(given, str) or len(given.strip()) > MAX_UNIT or _CONTROL.search(given):
        raise ReviewInvalid(f"'{label}': the unit is not valid.")
    given = given.strip()
    if expected and normalise_unit(given) != normalise_unit(expected):
        raise ReviewInvalid(f"'{label}' is in {expected}: enter the value in {expected} (it was {given}).")
    return given
