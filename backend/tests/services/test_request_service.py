"""MVP-86: the request rules on their own (no database). Every state against every action,
who the history names, and the timestamp format the frontend sorts by."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from backend.app.core.auth import CurrentUser
from backend.app.services import request_service as rs
from backend.app.services.request_service import Actor, RequestConflict, RequestInvalid

RAISER = Actor(user_id="u-raiser", name="M. Osei", login="mosei@acme.test")
SENDER = Actor(user_id="u-sender", name="Ann Lee", login="ann@acme.test")
AT = datetime(2026, 10, 26, 14, 3, 7, 123456, tzinfo=UTC)
LATER = AT + timedelta(minutes=5)
BODY = {
    "type": "missing_document",
    "whatIsNeeded": "The January bill",
    "source": {"origin": "expected_item", "itemLabel": "Kent electricity Jan", "facilityName": "Kent Cannery",
               "period": "Jan 2024"},
}
ISO_MS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def _ask(state: str = "not_yet_sent", number: int | None = None, ask_id: str = "ASK-1") -> dict[str, Any]:
    ask = rs.new_ask(ask_id, BODY, RAISER, AT)
    if state == "not_yet_sent":
        return ask
    if state == "withdrawn" and number is None:
        return rs.withdraw(ask, "Not needed", RAISER, AT)
    ask = rs.send({ask_id: ask}, number or 3, None, RAISER, AT)[ask_id]
    if state == "resolved":
        return rs.resolve(ask, None, None, RAISER, AT)
    if state == "withdrawn":
        return rs.withdraw(ask, "Not needed", RAISER, AT)
    return ask


def _act(action: str, ask: dict[str, Any]) -> Any:
    if action == "edit":
        return rs.edit(ask, "Something else", SENDER, LATER)
    if action == "send":
        return rs.send({ask["id"]: ask}, 4, None, SENDER, LATER)[ask["id"]]
    if action == "resolve":
        return rs.resolve(ask, "https://share.example/bill.pdf", "Uploaded", SENDER, LATER)
    return rs.withdraw(ask, "Raised by mistake", SENDER, LATER)


# --- the state table -------------------------------------------------------------------

ALLOWED = {
    ("not_yet_sent", "edit"): "not_yet_sent",
    ("not_yet_sent", "send"): "requested",
    ("not_yet_sent", "withdraw"): "withdrawn",
    ("requested", "resolve"): "resolved",
    ("requested", "withdraw"): "withdrawn",
}
REFUSED = {
    ("not_yet_sent", "resolve"): "The request for 'Kent electricity Jan' hasn't been sent yet, so it can't be "
                                 "resolved. Send it first, or withdraw it.",
    ("requested", "edit"): "Request 3 was already sent, so its text can't change. "
                           "Withdraw it and add a new request instead.",
    ("requested", "send"): "'Kent electricity Jan' was already sent in request 3, so nothing was sent.",
    ("resolved", "edit"): "Request 3 is resolved, so its text can't change. Raise a follow-up if more is needed.",
    ("resolved", "send"): "'Kent electricity Jan' was already sent in request 3, so nothing was sent.",
    ("resolved", "resolve"): "Request 3 is already resolved. Raise a follow-up if the problem came back.",
    ("resolved", "withdraw"): "Request 3 is resolved and can't be withdrawn. "
                              "Raise a follow-up if the problem came back.",
    ("withdrawn", "edit"): "Request 3 is withdrawn, so its text can't change. Add a new request instead.",
    ("withdrawn", "send"): "'Kent electricity Jan' is withdrawn, so nothing was sent.",
    ("withdrawn", "resolve"): "Request 3 is withdrawn and can't be resolved.",
    ("withdrawn", "withdraw"): "Request 3 is already withdrawn.",
}


def test_the_table_covers_every_state_and_action() -> None:
    cells = {(state, action) for state in rs.STATES for action in ("edit", "send", "resolve", "withdraw")}
    assert set(ALLOWED) | set(REFUSED) == cells
    assert not set(ALLOWED) & set(REFUSED)


@pytest.mark.parametrize(("state", "action"), sorted(ALLOWED))
def test_allowed_moves(state: str, action: str) -> None:
    before = _ask(state, number=3 if state != "not_yet_sent" else None)
    snapshot = copy.deepcopy(before)
    after = _act(action, before)
    assert after["state"] == ALLOWED[(state, action)]
    assert before == snapshot  # the stored ask is never changed in place
    assert after["history"][:-1] == before["history"]  # earlier events untouched
    assert len(after["history"]) == len(before["history"]) + 1
    assert after["history"][-1]["kind"] == {"edit": "edited", "send": "sent", "resolve": "resolved",
                                            "withdraw": "withdrawn"}[action]


@pytest.mark.parametrize(("state", "action"), sorted(REFUSED))
def test_refused_moves_say_why(state: str, action: str) -> None:
    ask = _ask(state, number=3)
    snapshot = copy.deepcopy(ask)
    with pytest.raises(RequestConflict) as refused:
        _act(action, ask)
    assert str(refused.value) == REFUSED[(state, action)]
    assert ask == snapshot


def test_a_withdrawn_request_that_was_never_sent_is_named_by_its_item() -> None:
    ask = _ask("withdrawn")
    with pytest.raises(RequestConflict, match=r"^The request for 'Kent electricity Jan' is withdrawn and can't"):
        _act("resolve", ask)


@pytest.mark.parametrize("action", ["edit", "send", "resolve", "withdraw"])
@pytest.mark.parametrize("state", ["sent", "", None])
def test_an_unknown_legacy_state_refuses_everything(action: str, state: str | None) -> None:
    ask = {**_ask(), "state": state}
    with pytest.raises(RequestConflict, match="doesn't recognise"):
        _act(action, ask)


# --- who acted, and what is recorded -----------------------------------------------------

def test_new_asks_take_the_raiser_from_the_session_not_the_body() -> None:
    body = {**BODY, "raisedByName": "Someone else", "raisedByLogin": "else", "state": "resolved",
            "requestNumber": 9, "history": [{"kind": "resolved"}], "linkedFromAskId": "ASK-0"}
    ask = rs.new_ask("ASK-1", body, RAISER, AT)
    assert ask["raisedByName"] == "M. Osei" and ask["raisedByLogin"] == "mosei@acme.test"
    assert ask["state"] == "not_yet_sent" and ask["requestNumber"] is None and ask["lineNumber"] is None
    assert ask["history"] == [{"kind": "raised", "actorName": "M. Osei", "actorLogin": "mosei@acme.test",
                               "actorUserId": "u-raiser", "at": "2026-10-26T14:03:07.123Z"}]
    assert ask["linkedFromAskId"] == "ASK-0"
    assert ask["source"] == {"origin": "expected_item", "documentId": None, "fieldKey": None,
                             "itemLabel": "Kent electricity Jan", "facilityName": "Kent Cannery",
                             "period": "Jan 2024", "sourcePage": None, "arrival": None}


def test_each_action_names_who_did_it_not_who_raised_it() -> None:
    sent = rs.send({"ASK-1": _ask()}, 1, None, SENDER, LATER)["ASK-1"]
    assert sent["history"][-1] == {"kind": "sent", "actorName": "Ann Lee", "actorLogin": "ann@acme.test",
                                   "actorUserId": "u-sender", "at": "2026-10-26T14:08:07.123Z",
                                   "detail": "request 1"}
    resolved = rs.resolve(sent, "https://x.test/a.pdf", None, SENDER, LATER)
    assert resolved["resolution"] == {"at": "2026-10-26T14:08:07.123Z", "by": "Ann Lee",
                                      "link": "https://x.test/a.pdf", "note": None}
    assert resolved["history"][-1]["actorName"] == "Ann Lee"
    withdrawn = rs.withdraw(_ask(), "Raised twice", SENDER, LATER)
    assert withdrawn["withdrawReason"] == "Raised twice"
    assert withdrawn["history"][-1]["detail"] == "Raised twice"
    assert withdrawn["history"][-1]["actorUserId"] == "u-sender"


def test_the_numbers_stay_after_a_resolve_or_withdraw() -> None:
    for state in ("resolved", "withdrawn"):
        ask = _ask(state, number=5)
        assert (ask["requestNumber"], ask["lineNumber"]) == (5, 1)
        assert rs.request_number(ask) == 5


def test_an_edit_with_the_same_text_records_nothing() -> None:
    ask = _ask()
    assert rs.edit(ask, "The January bill", SENDER, LATER) is None
    edited = rs.edit(ask, "The January and February bills", SENDER, LATER)
    assert edited is not None and edited["whatIsNeeded"] == "The January and February bills"
    assert edited["history"][-1]["kind"] == "edited" and "detail" not in edited["history"][-1]


def test_a_legacy_ask_without_history_gets_one() -> None:
    ask = {key: value for key, value in _ask().items() if key != "history"}
    assert [event["kind"] for event in rs.edit(ask, "New", SENDER, LATER)["history"]] == ["edited"]


# --- sending ------------------------------------------------------------------------------

def test_a_send_numbers_lines_in_the_order_chosen_unless_told_otherwise() -> None:
    asks = {key: _ask(ask_id=key) for key in ("ASK-b", "ASK-a", "ASK-c")}
    sent = rs.send(asks, 2, None, SENDER, LATER)
    assert [(k, a["requestNumber"], a["lineNumber"]) for k, a in sent.items()] == [
        ("ASK-b", 2, 1), ("ASK-a", 2, 2), ("ASK-c", 2, 3)]
    shared = rs.send(asks, 2, {"ASK-a": 1, "ASK-b": 1}, SENDER, LATER)
    assert [a["lineNumber"] for a in shared.values()] == [1, 1, 3]


@pytest.mark.parametrize("lines", [
    {"ASK-x": 1},  # not in the batch
    {"ASK-1": 0},
    {"ASK-1": 3},  # more than the number of asks
    {"ASK-1": True},
    {"ASK-1": "1"},
])
def test_line_numbers_must_fit_the_batch(lines: dict[str, Any]) -> None:
    asks = {key: _ask(ask_id=key) for key in ("ASK-1", "ASK-2")}
    with pytest.raises(RequestInvalid, match="^lineNumbers: "):
        rs.send(asks, 1, lines, SENDER, LATER)


def test_a_send_is_all_or_nothing() -> None:
    asks = {"ASK-1": _ask(ask_id="ASK-1"), "ASK-2": _ask("requested", number=1, ask_id="ASK-2")}
    with pytest.raises(RequestConflict, match="was already sent in request 1, so nothing was sent"):
        rs.send(asks, 2, None, SENDER, LATER)
    assert asks["ASK-1"]["state"] == "not_yet_sent"


# --- follow-ups -------------------------------------------------------------------------

def test_a_follow_up_needs_a_resolved_request() -> None:
    rs.check_follow_up(_ask("resolved", number=1))
    with pytest.raises(RequestInvalid):
        rs.check_follow_up(None)
    with pytest.raises(RequestConflict, match="^Request 1 isn't resolved, so it can't have a follow-up"):
        rs.check_follow_up(_ask("requested", number=1))


# --- actor and time ----------------------------------------------------------------------

def _user(**names: str | None) -> CurrentUser:
    return CurrentUser(id=uuid.UUID(int=7), email="ann@acme.test", role="org_member", org_id=uuid.UUID(int=1),
                       org_slug="acme", session_id=uuid.UUID(int=2),
                       **{"first_name": None, "last_name": None, "full_name": None, **names})


def test_the_actor_is_the_full_name_else_first_and_last_else_the_email() -> None:
    assert rs.actor_of(_user(full_name="Ann Lee", first_name="A")).name == "Ann Lee"
    assert rs.actor_of(_user(first_name="Ann", last_name="Lee")).name == "Ann Lee"
    assert rs.actor_of(_user(first_name="Ann")).name == "Ann"
    assert rs.actor_of(_user(full_name="  ")) == Actor(
        user_id=str(uuid.UUID(int=7)), name="ann@acme.test", login="ann@acme.test")


def test_timestamps_use_the_browsers_format_so_they_sort_with_browser_ones() -> None:
    assert rs.stamp(AT) == "2026-10-26T14:03:07.123Z"
    assert rs.stamp(datetime(2026, 10, 26, 16, 3, 7, tzinfo=timezone(timedelta(hours=2)))) == \
        "2026-10-26T14:03:07.000Z"
    assert rs.stamp(datetime(2026, 1, 2, 3, 4, 5, 999999)) == "2026-01-02T03:04:05.999Z"  # naive means UTC
    assert ISO_MS.match(rs.stamp(datetime.now(UTC)))
    for event in _ask("resolved", number=1)["history"]:
        assert ISO_MS.match(event["at"])
