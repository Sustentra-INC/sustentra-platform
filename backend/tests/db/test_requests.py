"""MVP-86: evidence requests through their action endpoints, the real app and Postgres RLS.
The server checks each move, numbers sent requests, names who acted and audits each
action. Reuses the engagement test harness, like test_workpaper_items.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.tests.db.test_engagements import (  # noqa: F401 - `seeded` is an autouse fixture
    A_ADMIN,
    A_MEMBER,
    BASE,
    _admin,
    _call,
    call,
    create,
    pytestmark,
    seeded,
)

SOURCE = {"origin": "expected_item", "itemLabel": "Kent electricity Jan", "facilityName": "Kent Cannery",
          "period": "Jan 2024"}


def raise_request(engagement_id: str, ask_id: str = "ASK-1", token: str = "a_member", **fields: Any) -> Any:
    body = {"id": ask_id, "type": "missing_document", "whatIsNeeded": "The January bill", "source": SOURCE,
            **fields}
    return call("POST", f"{BASE}/{engagement_id}/requests", token, body)


def send(engagement_id: str, ask_ids: list[str], token: str = "a_member", **fields: Any) -> Any:
    return call("POST", f"{BASE}/{engagement_id}/requests/send", token, {"askIds": ask_ids, **fields})


def act(engagement_id: str, ask_id: str, action: str, body: Any = None, token: str = "a_member") -> Any:
    if action == "edit":
        return call("PATCH", f"{BASE}/{engagement_id}/requests/{ask_id}", token, body)
    return call("POST", f"{BASE}/{engagement_id}/requests/{ask_id}/{action}", token, body)


def stored(ask_id: str) -> tuple[str, Any]:
    """The row exactly as saved: payload text and update time."""

    rows = asyncio.run(_admin(
        "SELECT payload::text AS payload, updated_at FROM workpaper_items WHERE kind = 'ask' AND item_key = $1",
        ask_id))
    return rows[0]["payload"], rows[0]["updated_at"]


def events() -> list[Any]:
    return asyncio.run(_admin(
        "SELECT event_type, actor_user_id, target_id, metadata::text AS metadata FROM audit_logs "
        "WHERE event_type LIKE 'request_%' ORDER BY created_at, id"))


def test_raising_a_request_records_the_signed_in_raiser_and_reads_back_unchanged() -> None:
    engagement = create()
    created = raise_request(engagement["id"])
    assert created.status_code == 201, created.text
    ask = created.json()
    assert ask["state"] == "not_yet_sent" and ask["requestNumber"] is None
    assert (ask["raisedByName"], ask["raisedByLogin"]) == ("member@acme.test", "member@acme.test")
    assert [(e["kind"], e["actorUserId"]) for e in ask["history"]] == [("raised", str(A_MEMBER))]
    listed = call("GET", f"{BASE}/{engagement['id']}/workpaper-items?kind=ask").json()["items"]
    assert [(i["item_key"], i["payload"]) for i in listed] == [("ASK-1", ask)]

    before = stored("ASK-1")
    duplicate = raise_request(engagement["id"], whatIsNeeded="Something else")
    assert duplicate.status_code == 409 and duplicate.json()["detail"] == "A request with this id already exists."
    assert stored("ASK-1") == before


def test_text_can_change_until_the_request_is_sent() -> None:
    engagement = create()
    raise_request(engagement["id"])
    edited = act(engagement["id"], "ASK-1", "edit", {"whatIsNeeded": "  The January and February bills "})
    assert edited.status_code == 200, edited.text
    assert edited.json()["whatIsNeeded"] == "The January and February bills"
    assert [e["kind"] for e in edited.json()["history"]] == ["raised", "edited"]
    same = act(engagement["id"], "ASK-1", "edit", {"whatIsNeeded": "The January and February bills"})
    assert same.status_code == 200 and len(same.json()["history"]) == 2  # nothing changed, nothing recorded

    assert send(engagement["id"], ["ASK-1"]).status_code == 200
    before = stored("ASK-1")
    refused = act(engagement["id"], "ASK-1", "edit", {"whatIsNeeded": "Anything"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == ("Request 1 was already sent, so its text can't change. "
                                        "Withdraw it and add a new request instead.")
    assert stored("ASK-1") == before


def test_sending_numbers_the_request_and_a_second_send_is_refused() -> None:
    engagement = create()
    for ask_id in ("ASK-1", "ASK-2", "ASK-3"):
        raise_request(engagement["id"], ask_id)
    sent = send(engagement["id"], ["ASK-2", "ASK-1"], lineNumbers={"ASK-1": 1})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert (body["requestNumber"], body["askIds"]) == (1, ["ASK-2", "ASK-1"])
    assert [(a["id"], a["state"], a["requestNumber"], a["lineNumber"]) for a in body["asks"]] == [
        ("ASK-2", "requested", 1, 1), ("ASK-1", "requested", 1, 1)]
    assert body["asks"][0]["history"][-1]["detail"] == "request 1"

    before = stored("ASK-3")
    again = send(engagement["id"], ["ASK-3", "ASK-1"])
    assert again.status_code == 409
    assert again.json()["detail"] == "'Kent electricity Jan' was already sent in request 1, so nothing was sent."
    assert stored("ASK-3") == before  # all or nothing
    assert send(engagement["id"], ["ASK-3", "ASK-9"]).status_code == 404
    assert send(engagement["id"], ["ASK-3"], lineNumbers={"ASK-3": 2}).status_code == 422
    assert send(engagement["id"], ["ASK-3"]).json()["requestNumber"] == 2


def test_two_sends_at_once_get_different_numbers() -> None:
    engagement = create()
    for n in range(1, 8):
        raise_request(engagement["id"], f"ASK-{n}")
    path = f"{BASE}/{engagement['id']}/requests/send"

    async def together(first: list[str], second: list[str]) -> list[Any]:
        return list(await asyncio.gather(_call("POST", path, "a_member", {"askIds": first}),
                                         _call("POST", path, "a_admin", {"askIds": second})))

    apart = asyncio.run(together(["ASK-1", "ASK-2"], ["ASK-3", "ASK-4"]))
    assert [r.status_code for r in apart] == [200, 200]
    assert sorted(r.json()["requestNumber"] for r in apart) == [1, 2]

    overlapping = asyncio.run(together(["ASK-5", "ASK-6"], ["ASK-6", "ASK-7"]))
    assert sorted(r.status_code for r in overlapping) == [200, 409]
    assert [r.json()["requestNumber"] for r in overlapping if r.status_code == 200] == [3]
    assert send(engagement["id"], ["ASK-7" if overlapping[0].status_code == 200 else "ASK-5"]).json()[
        "requestNumber"] == 4  # the refused send left no gap


def test_numbering_continues_after_requests_numbered_in_the_browser() -> None:
    engagement = create()
    legacy = {"id": "ASK-old", "type": "clarify", "whatIsNeeded": "Confirm the unit", "state": "requested",
              "requestNumber": 7, "lineNumber": 1, "source": SOURCE, "raisedByName": "Ann",
              "raisedByLogin": "ann", "raisedAt": "2026-10-12T22:00:00.000Z", "history": []}
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload, created_by, updated_by) "
        "VALUES ($1, $2, 'ask', 'ASK-old', $3::jsonb, $4, $4)",
        engagement["org_id"], engagement["id"], json.dumps(legacy), A_MEMBER))
    raise_request(engagement["id"])
    assert send(engagement["id"], ["ASK-1"]).json()["requestNumber"] == 8
    resolved = act(engagement["id"], "ASK-old", "resolve", {})
    assert resolved.status_code == 200 and resolved.json()["requestNumber"] == 7  # legacy rows still work


def test_refused_moves_change_nothing_and_say_why() -> None:
    engagement = create()
    for ask_id in ("ASK-1", "ASK-2"):
        raise_request(engagement["id"], ask_id)
    not_sent = act(engagement["id"], "ASK-1", "resolve", {})
    assert not_sent.status_code == 409
    assert not_sent.json()["detail"] == ("The request for 'Kent electricity Jan' hasn't been sent yet, so it can't "
                                         "be resolved. Send it first, or withdraw it.")

    send(engagement["id"], ["ASK-1", "ASK-2"])
    assert act(engagement["id"], "ASK-1", "withdraw", {"reason": "   "}).status_code == 422
    assert act(engagement["id"], "ASK-1", "withdraw", {"reason": "Sent twice"}).status_code == 200
    assert act(engagement["id"], "ASK-2", "resolve").status_code == 200  # no body at all is fine
    count = len(events())

    for ask_id, action, body, detail in [
        ("ASK-1", "resolve", {}, "Request 1 is withdrawn and can't be resolved."),
        ("ASK-1", "withdraw", {"reason": "Again"}, "Request 1 is already withdrawn."),
        ("ASK-2", "resolve", {}, "Request 1 is already resolved. Raise a follow-up if the problem came back."),
        ("ASK-2", "withdraw", {"reason": "No"}, "Request 1 is resolved and can't be withdrawn. "
                                                "Raise a follow-up if the problem came back."),
    ]:
        before = stored(ask_id)
        refused = act(engagement["id"], ask_id, action, body)
        assert (refused.status_code, refused.json()["detail"]) == (409, detail)
        assert stored(ask_id) == before
    assert len(events()) == count  # a refused move is not audited
    assert act(engagement["id"], "ASK-9", "resolve", {}).status_code == 404


def test_history_and_audit_name_whoever_acted() -> None:
    asyncio.run(_admin("UPDATE users SET full_name = 'Ada Admin' WHERE id = $1", A_ADMIN))
    engagement = create()
    raise_request(engagement["id"])
    send(engagement["id"], ["ASK-1"], token="a_member")
    resolved = act(engagement["id"], "ASK-1", "resolve", {"link": "https://share.test/jan.pdf", "note": "Got it"},
                   token="a_admin").json()
    assert [(e["kind"], e["actorName"], e["actorUserId"]) for e in resolved["history"]] == [
        ("raised", "member@acme.test", str(A_MEMBER)),
        ("sent", "member@acme.test", str(A_MEMBER)),
        ("resolved", "Ada Admin", str(A_ADMIN)),
    ]
    assert resolved["resolution"]["by"] == "Ada Admin" and resolved["raisedByName"] == "member@acme.test"
    assert [(r["event_type"], r["actor_user_id"]) for r in events()] == [
        ("request_created", A_MEMBER), ("request_sent", A_MEMBER), ("request_resolved", A_ADMIN)]


def test_each_action_is_audited_once_with_the_request_number_and_no_content() -> None:
    engagement = create()
    raise_request(engagement["id"], "ASK-1")
    raise_request(engagement["id"], "ASK-2")
    act(engagement["id"], "ASK-1", "edit", {"whatIsNeeded": "The January bill, both pages"})
    send(engagement["id"], ["ASK-1", "ASK-2"])
    act(engagement["id"], "ASK-1", "resolve", {"link": "https://share.test/secret-link", "note": "Private note"})
    act(engagement["id"], "ASK-2", "withdraw", {"reason": "Confidential reason"})
    raise_request(engagement["id"], "ASK-3")
    act(engagement["id"], "ASK-3", "withdraw", {"reason": "Not needed"})

    rows = events()
    assert all(r["target_id"] == engagement["id"] for r in rows)
    assert [(r["event_type"], json.loads(r["metadata"])) for r in rows] == [
        ("request_created", {"ask_id": "ASK-1", "type": "missing_document", "origin": "expected_item",
                             "follow_up_of": None}),
        ("request_created", {"ask_id": "ASK-2", "type": "missing_document", "origin": "expected_item",
                             "follow_up_of": None}),
        ("request_edited", {"ask_id": "ASK-1"}),
        ("request_sent", {"request_number": 1, "ask_ids": ["ASK-1", "ASK-2"], "count": 2}),
        ("request_resolved", {"ask_id": "ASK-1", "request_number": 1}),
        ("request_withdrawn", {"ask_id": "ASK-2", "request_number": 1}),
        ("request_created", {"ask_id": "ASK-3", "type": "missing_document", "origin": "expected_item",
                             "follow_up_of": None}),
        ("request_withdrawn", {"ask_id": "ASK-3", "request_number": None}),
    ]
    text = " ".join(r["metadata"] for r in rows)
    for secret in ("January", "secret-link", "Private note", "Confidential", "Not needed"):
        assert secret not in text


def test_a_follow_up_needs_a_resolved_request_in_the_same_engagement() -> None:
    engagement = create()
    other = create(name="Another engagement")
    raise_request(engagement["id"], "ASK-1")
    raise_request(other["id"], "ASK-elsewhere")
    assert raise_request(engagement["id"], "ASK-2", linkedFromAskId="ASK-missing").status_code == 422
    assert raise_request(engagement["id"], "ASK-2", linkedFromAskId="ASK-elsewhere").status_code == 422
    open_one = raise_request(engagement["id"], "ASK-2", linkedFromAskId="ASK-1")
    assert open_one.status_code == 409 and "isn't resolved" in open_one.json()["detail"]

    send(engagement["id"], ["ASK-1"])
    act(engagement["id"], "ASK-1", "resolve", {})
    follow_up = raise_request(engagement["id"], "ASK-2", linkedFromAskId="ASK-1")
    assert follow_up.status_code == 201 and follow_up.json()["linkedFromAskId"] == "ASK-1"
    assert json.loads(events()[-1]["metadata"])["follow_up_of"] == "ASK-1"


def test_other_orgs_provider_admins_and_archived_engagements_cannot_write() -> None:
    engagement = create()
    raise_request(engagement["id"])
    assert raise_request(engagement["id"], "ASK-2", token="b_member").status_code == 404
    assert send(engagement["id"], ["ASK-1"], token="b_member").status_code == 404
    assert act(engagement["id"], "ASK-1", "withdraw", {"reason": "x"}, token="b_member").status_code == 404
    assert raise_request(engagement["id"], "ASK-2", token="provider").status_code == 403
    assert act(engagement["id"], "ASK-1", "resolve", {}, token="provider").status_code == 403

    call("PATCH", f"{BASE}/{engagement['id']}", body={"status": "archived"})
    assert raise_request(engagement["id"], "ASK-2").status_code == 409
    assert send(engagement["id"], ["ASK-1"]).status_code == 409
    rows = asyncio.run(_admin("SELECT payload->>'state' AS state FROM workpaper_items"))
    assert [r["state"] for r in rows] == ["not_yet_sent"]


def test_a_client_cannot_set_the_state_numbers_history_or_raiser() -> None:
    engagement = create()
    for extra in ({"state": "resolved"}, {"requestNumber": 5}, {"history": []}, {"raisedByName": "Someone"}):
        assert raise_request(engagement["id"], **extra).status_code == 422, extra
    assert raise_request(engagement["id"], "has space").status_code == 422
    assert raise_request(engagement["id"], type="other").status_code == 422
    assert raise_request(engagement["id"], whatIsNeeded="  ").status_code == 422
    raise_request(engagement["id"])
    assert act(engagement["id"], "ASK-1", "edit", {"whatIsNeeded": "x", "state": "requested"}).status_code == 422
    assert send(engagement["id"], ["ASK-1"], requestNumber=9).status_code == 422
    assert send(engagement["id"], ["ASK-1", "ASK-1"]).status_code == 422
    assert act(engagement["id"], "ASK-1", "withdraw", {"reason": "x", "state": "resolved"}).status_code == 422
    saved = json.loads(stored("ASK-1")[0])
    assert (saved["state"], saved["requestNumber"], len(saved["history"])) == ("not_yet_sent", None, 1)
