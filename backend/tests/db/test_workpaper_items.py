"""Workpaper items (migration 0012): requests, findings and examination states saved per
engagement, through the real app and Postgres RLS. Reuses the engagement test harness.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio

from backend.app.api.workpaper_items import ASKS_HAVE_ACTIONS
from backend.tests.db.test_engagements import (  # noqa: F401 - `seeded` is an autouse fixture
    BASE,
    _admin,
    call,
    create,
    pytestmark,
    seeded,
)

ASK = {"id": "ask-1", "type": "clarify", "whatIsNeeded": "Confirm the unit · bill p.2 (m³)", "state": "not_yet_sent",
       "raisedByName": "Ann", "raisedByLogin": "member@acme.test", "raisedAt": "2026-10-12T22:00:00Z"}
FINDING = {"id": "finding-1", "sentence": "Factor too low"}


def items(engagement_id: str, token: str = "a_member", kind: str | None = None):  # noqa: ANN201
    suffix = f"?kind={kind}" if kind else ""
    return call("GET", f"{BASE}/{engagement_id}/workpaper-items{suffix}", token)


def save(engagement_id: str, kind: str, key: str, payload: dict, token: str = "a_member"):  # noqa: ANN201
    return call("PUT", f"{BASE}/{engagement_id}/workpaper-items/{kind}/{key}", token, {"payload": payload})


def test_saved_items_come_back_after_a_reload() -> None:
    engagement = create()
    first = save(engagement["id"], "finding", "finding-1", FINDING)
    assert first.status_code == 200, first.text
    save(engagement["id"], "finding", "finding-2", {"id": "finding-2", "sentence": "Unit missing"})
    save(engagement["id"], "examination", "RECALC-scope1_total", {"examinationState": "finding_raised"})

    listed = items(engagement["id"]).json()["items"]
    assert [(i["kind"], i["item_key"]) for i in listed] == [
        ("finding", "finding-1"), ("finding", "finding-2"), ("examination", "RECALC-scope1_total")]
    assert listed[0]["payload"] == FINDING
    assert [i["item_key"] for i in items(engagement["id"], kind="finding").json()["items"]] == [
        "finding-1", "finding-2"]


def test_saving_again_replaces_the_payload_and_keeps_who_created_it() -> None:
    engagement = create()
    save(engagement["id"], "finding", "finding-1", FINDING, token="a_member")
    updated = save(engagement["id"], "finding", "finding-1", {**FINDING, "sentence": "Factor corrected"},
                   token="a_admin").json()
    assert updated["payload"]["sentence"] == "Factor corrected"
    assert updated["created_by"] != updated["updated_by"]
    assert len(items(engagement["id"]).json()["items"]) == 1


def test_other_orgs_and_provider_admins_cannot_write() -> None:
    engagement = create()
    save(engagement["id"], "finding", "finding-1", FINDING)
    assert items(engagement["id"], token="b_member").status_code == 404
    assert save(engagement["id"], "finding", "finding-2", FINDING, token="b_member").status_code == 404
    assert items(engagement["id"], token="provider").status_code == 200  # support can read
    assert save(engagement["id"], "finding", "finding-2", FINDING, token="provider").status_code == 403
    rows = asyncio.run(_admin("SELECT count(*) AS n FROM workpaper_items"))
    assert rows[0]["n"] == 1


def test_bad_kind_key_or_payload_is_refused() -> None:
    engagement = create()
    assert save(engagement["id"], "note", "x", ASK).status_code == 422
    assert save(engagement["id"], "document", "DOC-1", {"documentId": "DOC-1", "disposition": "withdrawn"}).status_code == 200
    assert save(engagement["id"], "finding", "has space", FINDING).status_code == 422
    assert save(engagement["id"], "finding", "big", {"text": "x" * 40_000}).status_code == 422


def test_archived_engagements_take_no_new_work_and_saves_are_audited_without_values() -> None:
    engagement = create()
    save(engagement["id"], "finding", "finding-1", FINDING)
    events = asyncio.run(_admin(
        "SELECT event_type, metadata::text AS metadata FROM audit_logs WHERE event_type = 'workpaper_item_saved'"))
    assert len(events) == 1 and "Factor too low" not in events[0]["metadata"]
    call("PATCH", f"{BASE}/{engagement['id']}", body={"status": "archived"})
    assert save(engagement["id"], "finding", "finding-2", FINDING).status_code == 409


def test_asks_are_refused_and_point_at_the_request_actions() -> None:
    engagement = create()
    refused = save(engagement["id"], "ask", "ask-1", ASK)
    assert refused.status_code == 409
    assert refused.json()["detail"] == ASKS_HAVE_ACTIONS
    rows = asyncio.run(_admin("SELECT count(*) AS n FROM workpaper_items"))
    assert rows[0]["n"] == 0
    events = asyncio.run(_admin("SELECT event_type FROM audit_logs WHERE event_type = 'workpaper_item_saved'"))
    assert events == []
