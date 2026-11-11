"""MVP-86 (DB-010): the rules for evidence requests ("asks"), as pure functions.

An ask is stored in ``workpaper_items`` (kind ``ask``) as the frontend's own object
(``frontend/features/s1/types/requests.ts``). The server writes the parts that record
what happened (state, request and line numbers, resolution, withdrawal reason, who
raised it, and the history), so a browser can neither skip a step nor put someone
else's name on an action.

    from \\ action   edit   send        resolve    withdraw
    not_yet_sent     ok     requested   409        withdrawn
    requested        409    409         resolved   withdrawn
    resolved         409    409         409        409
    withdrawn        409    409         409        409

An unknown (legacy) state refuses every action. A follow-up can only be raised on a
resolved request. Every transition returns a new ask with one event appended to its
history; earlier events are never rewritten, and the request and line numbers stay
after a resolve or withdraw.

Nothing here touches the database: ``backend/app/api/requests.py`` locks, saves and
audits. Refusals are plain sentences that say what is wrong and what to do, because the
frontend shows a string ``detail`` as it is.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.app.core.auth import CurrentUser

NOT_YET_SENT = "not_yet_sent"
REQUESTED = "requested"
RESOLVED = "resolved"
WITHDRAWN = "withdrawn"
STATES = (NOT_YET_SENT, REQUESTED, RESOLVED, WITHDRAWN)

# The states each action starts from.
_ALLOWED = {
    "edit": (NOT_YET_SENT,),
    "send": (NOT_YET_SENT,),
    "resolve": (REQUESTED,),
    "withdraw": (NOT_YET_SENT, REQUESTED),
}

# Why an action is refused, by (action, state). {name} is "Request 3", or "The request
# for '<item>'" before it is sent; {label} is the item; {sent_in} is " in request 3".
_REFUSALS = {
    ("edit", REQUESTED): "{name} was already sent, so its text can't change. "
                         "Withdraw it and add a new request instead.",
    ("edit", RESOLVED): "{name} is resolved, so its text can't change. Raise a follow-up if more is needed.",
    ("edit", WITHDRAWN): "{name} is withdrawn, so its text can't change. Add a new request instead.",
    ("send", REQUESTED): "'{label}' was already sent{sent_in}, so nothing was sent.",
    ("send", RESOLVED): "'{label}' was already sent{sent_in}, so nothing was sent.",
    ("send", WITHDRAWN): "'{label}' is withdrawn, so nothing was sent.",
    ("resolve", NOT_YET_SENT): "{name} hasn't been sent yet, so it can't be resolved. Send it first, or withdraw it.",
    ("resolve", RESOLVED): "{name} is already resolved. Raise a follow-up if the problem came back.",
    ("resolve", WITHDRAWN): "{name} is withdrawn and can't be resolved.",
    ("withdraw", RESOLVED): "{name} is resolved and can't be withdrawn. Raise a follow-up if the problem came back.",
    ("withdraw", WITHDRAWN): "{name} is already withdrawn.",
}
_UNKNOWN_STATE = "{name} is in a state this version doesn't recognise ('{state}'), so it can't be changed."


class RequestConflict(Exception):
    """The request's state does not allow the action (HTTP 409). The message is for the user."""


class RequestInvalid(ValueError):
    """The action's input does not fit the request (HTTP 422)."""


@dataclass(frozen=True)
class Actor:
    """Who acted, from the session: never from the request body."""

    user_id: str
    name: str
    login: str


def actor_of(user: CurrentUser) -> Actor:
    """The signed-in user as a request's history names them: the full name, else first
    and last name, else the email. The login is the email."""

    full = (user.full_name or "").strip()
    first_last = " ".join(part.strip() for part in (user.first_name, user.last_name) if part and part.strip())
    return Actor(user_id=str(user.id), name=full or first_last or user.email, login=user.email)


def stamp(at: datetime) -> str:
    """JavaScript's ``toISOString`` format (``2026-10-26T14:03:07.123Z``). The frontend
    orders asks by comparing these strings, so server times must sort with browser ones."""

    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    at = at.astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def request_number(ask: Mapping[str, Any]) -> int | None:
    """The number of the request the ask was sent in, or None if it was never sent."""

    number = ask.get("requestNumber")
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def _label(ask: Mapping[str, Any]) -> str:
    source = ask.get("source")
    label = source.get("itemLabel") if isinstance(source, Mapping) else None
    return str(label or ask.get("id") or "this request")


def _name(ask: Mapping[str, Any]) -> str:
    number = request_number(ask)
    return f"Request {number}" if number is not None else f"The request for '{_label(ask)}'"


def _check(ask: Mapping[str, Any], action: str) -> None:
    state = ask.get("state")
    if state in _ALLOWED[action]:
        return
    number = request_number(ask)
    template = _REFUSALS[(action, state)] if state in STATES else _UNKNOWN_STATE
    raise RequestConflict(
        template.format(
            name=_name(ask),
            label=_label(ask),
            sent_in=f" in request {number}" if number is not None else "",
            state=state,
        )
    )


def _event(kind: str, actor: Actor, at: datetime, detail: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "kind": kind,
        "actorName": actor.name,
        "actorLogin": actor.login,
        "actorUserId": actor.user_id,
        "at": stamp(at),
    }
    if detail is not None:
        event["detail"] = detail
    return event


def _appended(ask: Mapping[str, Any], event: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A copy of the ask with ``changes`` applied and ``event`` added to its history."""

    updated = copy.deepcopy(dict(ask))
    history = updated.get("history")
    updated.update(changes)
    updated["history"] = [*(history if isinstance(history, list) else []), event]
    return updated


def new_ask(ask_id: str, body: Mapping[str, Any], actor: Actor, at: datetime) -> dict[str, Any]:
    """A not-yet-sent ask raised by ``actor``. Only the fields a person writes are taken
    from ``body``: who raised it, when, its state, numbers and history are the server's."""

    source = body.get("source") or {}
    return {
        "id": ask_id,
        "type": body["type"],
        "whatIsNeeded": body["whatIsNeeded"],
        "source": {
            "origin": source.get("origin") or "workspace_document",
            "documentId": source.get("documentId"),
            "fieldKey": source.get("fieldKey"),
            "itemLabel": source["itemLabel"],
            "facilityName": source.get("facilityName"),
            "period": source.get("period"),
            "sourcePage": source.get("sourcePage"),
            "arrival": source.get("arrival"),
        },
        "raisedByName": actor.name,
        "raisedByLogin": actor.login,
        "raisedAt": stamp(at),
        "state": NOT_YET_SENT,
        "requestNumber": None,
        "lineNumber": None,
        "linkedFromAskId": body.get("linkedFromAskId"),
        "resolution": None,
        "withdrawReason": None,
        "history": [_event("raised", actor, at)],
    }


def check_follow_up(original: Mapping[str, Any] | None) -> None:
    """A follow-up must point at a request in the same engagement that is resolved."""

    if original is None:
        raise RequestInvalid("linkedFromAskId: there is no request with this id in this engagement.")
    if original.get("state") != RESOLVED:
        raise RequestConflict(
            f"{_name(original)} isn't resolved, so it can't have a follow-up. "
            "A follow-up is for a resolved request whose problem came back."
        )


def edit(ask: Mapping[str, Any], what_is_needed: str, actor: Actor, at: datetime) -> dict[str, Any] | None:
    """The ask with new text, or None when the text is unchanged (nothing is recorded)."""

    _check(ask, "edit")
    if ask.get("whatIsNeeded") == what_is_needed:
        return None
    return _appended(ask, _event("edited", actor, at), whatIsNeeded=what_is_needed)


def send(
    asks: Mapping[str, Mapping[str, Any]],
    number: int,
    line_numbers: Mapping[str, int] | None,
    actor: Actor,
    at: datetime,
) -> dict[str, dict[str, Any]]:
    """Send ``asks`` (keyed by id, in the order chosen) as request ``number``. All or
    nothing: one ask that can't be sent refuses the whole batch.

    ``line_numbers`` lets asks that one document answers share a line; each ask that has
    none takes its position (1, 2, ...)."""

    lines = dict(line_numbers or {})
    unknown = sorted(set(lines) - set(asks))
    if unknown:
        raise RequestInvalid(f"lineNumbers: '{unknown[0]}' is not one of the requests being sent.")
    for key, line in lines.items():
        if isinstance(line, bool) or not isinstance(line, int) or not 1 <= line <= len(asks):
            raise RequestInvalid(f"lineNumbers: '{key}' must be a whole number from 1 to {len(asks)}.")
    for ask in asks.values():
        _check(ask, "send")
    return {
        key: _appended(
            ask,
            _event("sent", actor, at, f"request {number}"),
            state=REQUESTED,
            requestNumber=number,
            lineNumber=lines.get(key, position),
        )
        for position, (key, ask) in enumerate(asks.items(), start=1)
    }


def resolve(
    ask: Mapping[str, Any], link: str | None, note: str | None, actor: Actor, at: datetime
) -> dict[str, Any]:
    _check(ask, "resolve")
    return _appended(
        ask,
        _event("resolved", actor, at),
        state=RESOLVED,
        resolution={"at": stamp(at), "by": actor.name, "link": link, "note": note},
    )


def withdraw(ask: Mapping[str, Any], reason: str, actor: Actor, at: datetime) -> dict[str, Any]:
    _check(ask, "withdraw")
    return _appended(ask, _event("withdrawn", actor, at, reason), state=WITHDRAWN, withdrawReason=reason)
