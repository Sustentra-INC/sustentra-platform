"""The review-field state machine: a reviewer's accept / edit / reject / revert on one value, as pure functions.

Extracted from ``methodology_review`` (which keeps its behaviour and its names) so that other pages can keep
the same record shape and the same rules. A record is

    {suggestion: null | {value, ...}, decision: null | {status: pending|accepted|edited|rejected, value, reason?,
                                                          by, at, ...},
     history: [{at, by, action, to?}] (newest 50),
     value_history: [decision, ...] (the decisions before the current one, oldest first, at most 10)}

plus whatever else the owner keeps on it (``field_id``, ``user_added``...), which every function here carries
over untouched.

    from \\ action        accept     edit     reject     revert
    none / pending        accepted   edited   rejected   409
    accepted / edited     409        edited   409        the decision before this one
    rejected              409        edited   409        the decision before this one

What differs between owners is passed in, so nothing here knows about a particular page: ``label`` (how a
refusal names the field), ``validate`` (checks a value and returns it in its stored form; raises
``ReviewInvalid``) and, for a revert, ``blank`` (the value a field goes back to when nothing was decided and
nothing was detected). ``extras`` names decision keys beyond status / value / reason that a revert restores
(checked as short text), ``carry`` the keys an accept copies from the suggestion onto the decision. Both are
empty for Methodology, whose decisions hold status, value and reason only.

Refusals are plain sentences, because the frontend shows them as is: ``ReviewConflict`` is a 409 (the state
does not allow the move), ``ReviewInvalid`` a 422 (the input does not fit).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from backend.app.services.request_service import Actor, stamp
from backend.app.services.workpaper_item_service import MAX_PAYLOAD_BYTES, payload_size

PENDING, ACCEPTED, EDITED, REJECTED = "pending", "accepted", "edited", "rejected"
STATUSES = (PENDING, ACCEPTED, EDITED, REJECTED)

MAX_REASON = 500
MAX_HISTORY = 50
MAX_VALUE_HISTORY = 10  # earlier decisions kept per field, for Revert
HISTORY_ROOM = 10 * 1024  # bytes of event history a record keeps room for before it keeps earlier decisions


class ReviewConflict(Exception):
    """The field's state does not allow the action (HTTP 409). The message is for the user."""


class ReviewInvalid(ValueError):
    """The action's input does not fit the field (HTTP 422). The message is for the user."""


Validate = Callable[[Any], Any]


def by(actor: Actor) -> dict[str, str]:
    return {"name": actor.name, "login": actor.login}


def status_of(record: Mapping[str, Any]) -> str:
    decision = record.get("decision")
    return str(decision["status"]) if decision else PENDING


def transition(record: Mapping[str, Any], action: str, decision: dict[str, Any], actor: Actor, now: datetime,
               to: Any = None) -> dict[str, Any]:
    out = copy.deepcopy(dict(record))
    event: dict[str, Any] = {"at": stamp(now), "by": by(actor), "action": action}
    if to is not None:
        event["to"] = to
    previous = record.get("decision")
    if previous and previous.get("status") != PENDING and action != "revert":  # the decision this one replaces, for Revert
        out["value_history"] = [*record.get("value_history", []), copy.deepcopy(previous)]
    out["decision"] = {**decision, "by": by(actor), "at": stamp(now)}
    pushed = out.get("value_history", [])[-1:] if previous and previous.get("status") != PENDING and action != "revert" else []
    trim_value_history(out)
    if pushed:  # the decision just replaced could not be kept (too large): Revert must say so, not go elsewhere
        if out.get("value_history", [])[-1:] == pushed:
            out.pop("previous_lost", None)
        else:
            out["previous_lost"] = True
    out["history"] = fit([*record.get("history", []), event], out)
    return out


def trim_value_history(record: dict[str, Any]) -> None:
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


def fit(history: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """The newest MAX_HISTORY events, fewer if the record would not fit MAX_PAYLOAD_BYTES. The
    audit log keeps the full trail."""

    kept = history[-MAX_HISTORY:]
    while kept and payload_size({**record, "history": kept}) > MAX_PAYLOAD_BYTES:
        kept = kept[1:]
    return kept


def already(label: str, status: str) -> ReviewConflict:
    return ReviewConflict(f"'{label}' is already {status}. Revert it to pending first if you want to decide again.")


def clean_reason(reason: Any, *, missing: str | None = None) -> str | None:
    """A reason as stored: stripped. Absent gives None, or ``missing`` as a 422 sentence when it is required."""

    if reason is None or (isinstance(reason, str) and not reason.strip()):
        if missing is not None:
            raise ReviewInvalid(missing)
        return None
    if not isinstance(reason, str) or "\x00" in reason:
        raise ReviewInvalid("The reason must be text.")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise ReviewInvalid(f"The reason is too long: at most {MAX_REASON} characters.")
    return reason


def accept(record: Mapping[str, Any], label: str, validate: Validate, actor: Actor, now: datetime, *,
           carry: Sequence[str] = (), instead: str = "Edit it to enter the value.") -> dict[str, Any]:
    """Take the suggestion's value, or the value already set on the field."""

    status = status_of(record)
    if status != PENDING:
        raise already(label, status)
    suggestion = record.get("suggestion")
    value = suggestion["value"] if suggestion else (record.get("decision") or {}).get("value")
    if value is None:
        raise ReviewConflict(
            f"There is nothing to accept for '{label}': nothing was suggested and no value is set. "
            f"{instead}")
    value = validate(value)
    decision: dict[str, Any] = {"status": ACCEPTED, "value": value}
    if suggestion:
        decision.update({key: suggestion[key] for key in carry if suggestion.get(key) is not None})
    return transition(record, "accept", decision, actor, now, to=value)


def edit(record: Mapping[str, Any], validate: Validate, value: Any, actor: Actor, now: datetime, *,
         extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Decide on ``value`` whatever the state was. ``extra`` keys (a reason, a unit) go on the decision."""

    value = validate(value)
    return transition(record, "edit", {"status": EDITED, "value": value, **(extra or {})}, actor, now, to=value)


def reject(record: Mapping[str, Any], label: str, reason: Any, actor: Actor, now: datetime) -> dict[str, Any]:
    status = status_of(record)
    if status != PENDING:
        raise already(label, status)
    if not isinstance(reason, str) or not reason.strip():
        raise ReviewInvalid(f"Say why '{label}' is rejected: a reason is required.")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise ReviewInvalid(f"The reason is too long: at most {MAX_REASON} characters.")
    return transition(record, "reject", {"status": REJECTED, "value": None, "reason": reason}, actor, now)


def cannot_restore(reason: str) -> ReviewConflict:
    return ReviewConflict(f"The previous value can no longer be restored ({reason}). Edit the value instead.")


def restorable(validate: Validate, entry: Any, extras: Sequence[str] = ()) -> dict[str, Any]:
    """An earlier decision as Revert restores it: only its status, value and reason (and the ``extras``: more short
    text keys, such as a unit or a reason on an edit), with the value checked against the field again. A stored
    entry that is not a decision the field accepts is refused (409), never skipped."""

    if not isinstance(entry, Mapping) or entry.get("status") not in (ACCEPTED, EDITED, REJECTED):
        raise cannot_restore("the saved entry is not a decision")
    if entry["status"] == REJECTED:
        reason = entry.get("reason")
        return {"status": REJECTED, "value": None,
                "reason": reason[:MAX_REASON] if isinstance(reason, str) and "\x00" not in reason else ""}
    try:
        restored: dict[str, Any] = {"status": entry["status"], "value": validate(entry.get("value"))}
    except ReviewInvalid as exc:
        detail = str(exc).split(": ", 1)[-1].rstrip(".")
        raise cannot_restore(f"it no longer fits the field: {detail}") from None
    for key in extras:
        item = entry.get(key)
        if isinstance(item, str) and item and len(item) <= MAX_REASON and "\x00" not in item:
            restored[key] = item
    return restored


def revert(record: Mapping[str, Any], label: str, validate: Validate, blank: Callable[[], Any], actor: Actor,
           now: datetime, *, extras: Sequence[str] = ()) -> dict[str, Any]:
    """Go back to the PREVIOUS value: every accept, edit or reject pushes the decision it replaces onto
    ``value_history`` and a revert pops the last one. With no previous decision it restores the detected value (the
    suggestion stays on the field, pending), and with no suggestion either the field is empty (``blank()``, called
    only for a reviewer-added row). When the previous decision was saved but cannot be restored (it no longer
    validates, is not a decision, or was too large to keep) the revert is refused with 409: it never quietly falls
    back to the detected value or to empty. The event says what was restored: previous, detected or empty."""

    if status_of(record) == PENDING:
        raise ReviewConflict(f"'{label}' is already pending, so there is nothing to revert.")
    out = copy.deepcopy(dict(record))
    prior: list[dict[str, Any]] = out.get("value_history") or []
    if prior:
        decision = restorable(validate, prior[-1], extras)
        prior.pop()
        source = "previous"
    elif record.get("previous_lost"):
        raise cannot_restore("it was too large to keep")
    else:
        # No earlier decision was ever saved: the detected value (the suggestion stays, pending) or nothing. A row
        # the reviewer added goes back to its blank value.
        blank_value = blank() if record.get("user_added") else None
        decision = {"status": PENDING, "value": blank_value}
        source = "detected" if record.get("suggestion") else "empty"
    if prior:
        out["value_history"] = prior
    else:
        out.pop("value_history", None)
    event: dict[str, Any] = {"at": stamp(now), "by": by(actor), "action": "revert", "restored": source}
    if decision.get("value") is not None:
        event["to"] = decision["value"]
    out["decision"] = {**decision, "by": by(actor), "at": stamp(now)}
    out["history"] = fit([*record.get("history", []), event], out)
    return out
