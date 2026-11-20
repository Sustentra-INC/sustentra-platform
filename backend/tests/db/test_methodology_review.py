"""Methodology review through the real app and Postgres RLS: the GET, each action, the audit
trail, access by org and engagement state, and migration 0016 up and down.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.app.services import methodology_review as rules
from backend.tests.db.test_engagements import (  # noqa: F401 - `seeded` is an autouse fixture
    A_ADMIN,
    A_MEMBER,
    BASE,
    _admin,
    call,
    create,
    pytestmark,
    seeded,
)

SUGGESTION = {"value": "Yes", "quote": "We report stationary combustion.", "document_id": "doc-1",
              "file_name": "report.pdf", "source_reference": "p. 4", "origin": "ai", "model": "claude-x",
              "request_id": "req-1", "suggested_at": "2026-11-11T09:00:00.000Z"}


def review(engagement_id: str, token: str = "a_member") -> Any:
    return call("GET", f"{BASE}/{engagement_id}/methodology-review", token)


def act(engagement_id: str, field_id: str, action: str, body: Any = None, token: str = "a_member") -> Any:
    return call("POST", f"{BASE}/{engagement_id}/methodology-review/{field_id}/{action}", token, body)


def add_row(engagement_id: str, group: str = "entities", token: str = "a_member") -> Any:
    return call("POST", f"{BASE}/{engagement_id}/methodology-review/rows", token, {"group": group})


def record(engagement_id: str, field_id: str) -> dict[str, Any]:
    fields = review(engagement_id).json()["fields"]
    return next(f for f in fields if f["field_id"] == field_id)


def events() -> list[Any]:
    return asyncio.run(_admin(
        "SELECT event_type, actor_user_id, target_id, metadata::text AS metadata FROM audit_logs "
        "WHERE event_type = 'methodology_decision' ORDER BY created_at, id"))


def suggest(engagement_id: str, field_id: str, suggestion: dict[str, Any] = SUGGESTION) -> None:
    """What the AI task does later: put a proposal on the field's stored record."""

    payload = {"field_id": field_id, "suggestion": suggestion, "decision": None, "history": []}
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', $2, $3::jsonb FROM engagements WHERE id = $1::uuid "
        "ON CONFLICT (engagement_id, kind, item_key) DO UPDATE SET payload = EXCLUDED.payload",
        engagement_id, field_id, json.dumps(payload)))


def test_get_lists_every_field_pending_with_the_catalog_and_ai_off() -> None:
    engagement = create()
    body = review(engagement["id"]).json()
    assert len(body["fields"]) == len(body["catalog"]) == 35  # 34 + scopes:covered
    assert [f["field_id"] for f in body["fields"]] == [c["field_id"] for c in body["catalog"]]
    assert all(f["suggestion"] is None and f["decision"] is None and f["history"] == [] for f in body["fields"])
    assert body["ai"]["enabled"] is False and body["ai"]["reason_code"] == "off" and body["ai"]["reason"]
    assert all(f["user_added"] is False for f in body["fields"])
    gwp = next(c for c in body["catalog"] if c["field_id"] == "gwp")
    assert gwp["group"] == "gwp" and gwp["group_label"] == "GWP factors source"
    assert [p["key"] for p in gwp["parts"]] == ["set", "horizon", "applies_to"] and gwp["parts"][0]["allowed"] == ["AR4", "AR5", "AR6"]
    assert "parts" not in next(c for c in body["catalog"] if c["field_id"] == "exclusion:boundary")
    assert body["row_groups"] == ["entities", "factor:scope1", "factor:scope2", "gwp"]
    assert {"group": "boundary", "label": "Organizational boundary"} in body["groups"]
    assert next(c for c in body["catalog"] if c["field_id"] == "gwp")["allowed"]["set"] == ["AR4", "AR5", "AR6"]
    assert asyncio.run(_admin("SELECT count(*) AS n FROM workpaper_items"))[0]["n"] == 0  # reading writes nothing


def test_edit_accept_reject_and_revert_record_the_session_user_and_audit_each() -> None:
    engagement = create()
    eid = engagement["id"]
    edited = act(eid, "consolidation_approach", "edit", {"value": "Financial Control"})
    assert edited.status_code == 200, edited.text
    decision = edited.json()["decision"]
    assert (decision["status"], decision["value"]) == ("edited", "Financial Control")
    assert decision["by"] == {"name": "member@acme.test", "login": "member@acme.test"}
    assert decision["at"].endswith("Z")
    assert record(eid, "consolidation_approach")["decision"] == decision

    suggest(eid, "category:scope1:stationary")
    accepted = act(eid, "category:scope1:stationary", "accept", token="a_admin")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["decision"]["value"] == "Yes" and accepted.json()["decision"]["status"] == "accepted"
    assert accepted.json()["suggestion"] == SUGGESTION
    assert accepted.json()["history"][0]["by"]["login"] == "admin@acme.test"

    suggest(eid, "category:scope1:mobile", {**SUGGESTION, "value": "No"})
    rejected = act(eid, "category:scope1:mobile", "reject", {"reason": "  The report says otherwise  "})
    assert rejected.status_code == 200
    assert rejected.json()["decision"]["reason"] == "The report says otherwise"
    assert rejected.json()["decision"]["value"] is None
    reverted = act(eid, "category:scope1:mobile", "revert")
    assert reverted.json()["decision"]["status"] == "pending"
    assert [h["action"] for h in reverted.json()["history"]] == ["reject", "revert"]
    assert record(eid, "category:scope1:mobile")["suggestion"]["value"] == "No"  # still there to decide again

    rows = events()
    assert [(r["event_type"], r["actor_user_id"]) for r in rows] == [("methodology_decision", A_MEMBER),
                                                                       ("methodology_decision", A_ADMIN),
                                                                       ("methodology_decision", A_MEMBER),
                                                                       ("methodology_decision", A_MEMBER)]
    metadata = [json.loads(r["metadata"]) for r in rows]
    assert metadata[0] == {"field_id": "consolidation_approach", "action": "edit", "status": "edited"}
    assert metadata[2] == {"field_id": "category:scope1:mobile", "action": "reject", "status": "rejected"}
    assert metadata[3]["status"] == "pending"
    blob = " ".join(r["metadata"] for r in rows)
    assert "Financial Control" not in blob and "otherwise" not in blob and "stationary combustion" not in blob


def test_refused_moves_answer_with_a_sentence_and_write_nothing() -> None:
    engagement = create()
    eid = engagement["id"]
    assert act(eid, "exclusion:inventory", "edit", {"value": "2025"}).status_code == 200
    before = events()

    again = act(eid, "exclusion:inventory", "accept")
    assert again.status_code == 409 and "already edited" in again.json()["detail"]
    assert act(eid, "exclusion:inventory", "reject", {"reason": "x"}).status_code == 409
    assert act(eid, "gwp", "revert").status_code == 409
    nothing = act(eid, "exclusion:boundary", "accept")
    assert nothing.status_code == 409 and "nothing to accept" in nothing.json()["detail"]
    assert act(eid, "gwp", "edit", {"value": {"set": "AR9", "horizon": "20-year"}}).status_code == 422
    assert act(eid, "category:scope1:fugitive", "edit", {"value": "Maybe"}).status_code == 422
    assert act(eid, "category:scope1:fugitive", "reject", {"reason": "   "}).status_code == 422
    assert act(eid, "category:scope1:fugitive", "reject", {"reason": "x" * 501}).status_code == 422
    assert act(eid, "category:scope1:fugitive", "reject", {}).status_code == 422
    assert act(eid, "no_such_field", "accept").status_code == 404
    assert act(eid, "entity:abcd1234", "edit", {"value": {}}).status_code == 404
    assert len(events()) == len(before)
    assert record(eid, "exclusion:inventory")["decision"]["value"] == "2025"
    assert record(eid, "category:scope1:fugitive")["decision"] is None
    stored = asyncio.run(_admin("SELECT item_key FROM workpaper_items WHERE kind = 'methodology'"))
    assert [r["item_key"] for r in stored] == ["exclusion:inventory"]  # refused moves leave no rows behind


def test_a_client_cannot_name_the_actor_or_set_the_status() -> None:
    engagement = create()
    eid = engagement["id"]
    assert act(eid, "exclusion:boundary", "edit", {"value": "2025", "by": "Someone"}).status_code == 422
    assert act(eid, "exclusion:boundary", "edit", {"value": "2025", "status": "accepted"}).status_code == 422
    assert act(eid, "exclusion:boundary", "reject", {"reason": "r", "by": {"name": "x"}}).status_code == 422
    assert act(eid, "exclusion:boundary", "edit", {}).status_code == 422
    put = call("PUT", f"{BASE}/{eid}/workpaper-items/methodology/reporting_period", body={"payload": {"a": 1}})
    assert put.status_code == 422  # decisions are not saved around the actions
    assert call("GET", f"{BASE}/{eid}/workpaper-items?kind=methodology").json() == {"items": []}


def test_rows_can_be_added_edited_and_removed_when_the_reviewer_added_them() -> None:
    engagement = create()
    eid = engagement["id"]
    added = add_row(eid, "entities")
    assert added.status_code == 201, added.text
    field_id = added.json()["field"]["field_id"]
    assert field_id.startswith("entity:") and added.json()["field"]["user_added"] is True
    assert added.json()["user_added"] is True
    assert [p["key"] for p in added.json()["field"]["parts"]] == [
        "name", "facilities", "equity_share_pct", "financial_control", "operational_control"]
    assert added.json()["decision"]["status"] == "pending"
    assert added.json()["decision"]["by"]["login"] == "member@acme.test"

    listed = review(eid).json()
    assert listed["fields"][-1]["field_id"] == field_id and listed["catalog"][-1]["kind"] == "entity"
    assert len(listed["fields"]) == 36  # 34 fixed + scopes:covered + 1 row

    blank = act(eid, field_id, "accept")
    assert blank.status_code == 422 and "name" in blank.json()["detail"]
    entity = {"name": "Stockton JV", "facilities": ["Cold storage"], "equity_share_pct": 50,
              "financial_control": 50, "operational_control": "No"}
    assert act(eid, field_id, "edit", {"value": entity}).json()["decision"]["value"] == entity
    assert act(eid, field_id, "edit", {"value": {**entity, "equity_share_pct": 150}}).status_code == 422

    factor = add_row(eid, "factor:scope2").json()["field"]["field_id"]
    assert factor.startswith("factor:scope2:")
    assert act(eid, factor, "edit", {"value": {"database": "EPA eGRID", "edition": "eGRID2023"}}).status_code == 200
    assert add_row(eid, "categories").status_code == 422

    removed = call("DELETE", f"{BASE}/{eid}/methodology-review/{field_id}")
    assert removed.status_code == 200 and removed.json()["removed"] is True and removed.json()["field_id"] == field_id
    assert field_id not in [f["field_id"] for f in review(eid).json()["fields"]]
    assert act(eid, field_id, "edit", {"value": entity}).status_code == 404
    assert call("DELETE", f"{BASE}/{eid}/methodology-review/{field_id}").status_code == 404
    kept = asyncio.run(_admin("SELECT payload->>'removed' AS removed FROM workpaper_items WHERE item_key = $1",
                              field_id))
    assert kept[0]["removed"] == "true"  # marked, not deleted

    actions = [json.loads(r["metadata"])["action"] for r in events()]
    assert actions == ["add_row", "edit", "add_row", "edit", "remove_row"]
    assert json.loads(events()[-1]["metadata"])["status"] is None


def test_rows_from_the_report_cannot_be_removed_only_rejected() -> None:
    engagement = create()
    eid = engagement["id"]
    refused = call("DELETE", f"{BASE}/{eid}/methodology-review/reporting_period")
    assert refused.status_code == 409 and "Reject it instead" in refused.json()["detail"]
    assert call("DELETE", f"{BASE}/{eid}/methodology-review/not_a_field").status_code == 404
    assert [r for r in events()] == []


def test_other_orgs_provider_admins_and_archived_engagements() -> None:
    engagement = create()
    eid = engagement["id"]
    field_id = add_row(eid).json()["field"]["field_id"]
    assert act(eid, "exclusion:boundary", "edit", {"value": "2025"}).status_code == 200

    assert review(eid, "b_member").status_code == 404
    assert act(eid, "exclusion:boundary", "edit", {"value": "x"}, token="b_member").status_code == 404
    assert act(eid, "exclusion:boundary", "revert", token="b_member").status_code == 404
    assert add_row(eid, token="b_member").status_code == 404
    assert call("DELETE", f"{BASE}/{eid}/methodology-review/{field_id}", "b_member").status_code == 404
    assert review(eid, "provider").status_code == 200  # read-only
    assert act(eid, "exclusion:boundary", "revert", token="provider").status_code == 403
    assert add_row(eid, token="provider").status_code == 403
    assert call("GET", f"{BASE}/{eid}/methodology-review", None).status_code == 401

    call("PATCH", f"{BASE}/{eid}", body={"status": "archived"})
    assert act(eid, "exclusion:boundary", "revert").status_code == 409
    assert act(eid, "gwp", "edit", {"value": {"set": "AR5", "horizon": "100-year"}}).status_code == 409
    assert add_row(eid).status_code == 409
    assert call("DELETE", f"{BASE}/{eid}/methodology-review/{field_id}").status_code == 409
    assert review(eid).status_code == 200  # still readable
    assert record(eid, "exclusion:boundary")["decision"]["status"] == "edited"


def test_one_engagements_decisions_are_not_another_s() -> None:
    first, second = create(), create(name="Second")
    act(first["id"], "exclusion:boundary", "edit", {"value": "2025"})
    assert record(second["id"], "exclusion:boundary")["decision"] is None


# --- optional rows: hidden until there is a value or the reviewer adds them ----------------------

OPTIONAL_FIELDS = ("boundary:acquisitions", "boundary:leased_space", "calculation:estimation", "calculation:source_records", "scope2:instruments", *rules.GAS_IDS)  # the real optional rows
OPTIONAL = "optional:test-row"  # the catalog has no optional field yet; the rules are tested with one


@pytest.fixture
def optional_field(monkeypatch: pytest.MonkeyPatch) -> str:
    field = rules._field(OPTIONAL, "boundary", "Acquisitions und Veräußerungen – 买卖", "text", required=False)
    monkeypatch.setattr(rules, "CATALOG", (*rules.CATALOG, field))
    monkeypatch.setattr(rules, "_BY_ID", {**rules._BY_ID, OPTIONAL: field})
    return OPTIONAL


def shown(engagement_id: str, field_id: str) -> bool:
    return bool(record(engagement_id, field_id)["shown"])


def test_an_optional_row_is_hidden_until_a_suggestion_a_decision_or_add_an_item(optional_field: str) -> None:
    eid = create()["id"]
    catalog = {c["field_id"]: c for c in review(eid).json()["catalog"]}
    assert not shown(eid, optional_field) and catalog[optional_field]["required"] is False
    assert record(eid, optional_field)["display_state"] == "not_checked"
    assert all(shown(eid, f["field_id"]) for f in review(eid).json()["fields"]
               if f["field_id"] not in (optional_field, *OPTIONAL_FIELDS))

    suggest(eid, optional_field)  # a suggestion arrives
    assert shown(eid, optional_field) and record(eid, optional_field)["display_state"] == "has_value"

    other = create(name="Second")["id"]  # a reviewer adds it: it shows as not checked, and stays after a reload
    assert not shown(other, optional_field)
    added = act(other, optional_field, "reveal")
    assert added.status_code == 200 and added.json() == {"field_id": optional_field, "shown": True}
    assert act(other, optional_field, "reveal").status_code == 200  # twice is the same as once
    assert shown(other, optional_field) and record(other, optional_field)["display_state"] == "not_checked"
    assert asyncio.run(_admin(
        "SELECT payload FROM workpaper_items WHERE kind = 'methodology' AND item_key = 'meta:state' "
        "AND engagement_id = $1::uuid", other))[0]["payload"] is not None

    third = create(name="Third")["id"]  # an edit also brings a hidden row onto the page
    assert not shown(third, optional_field)
    assert act(third, optional_field, "edit", {"value": "Sold the Kent plant in March – Müller Käserei"}).status_code == 200
    assert shown(third, optional_field)
    assert events()[-1]["metadata"] and "Müller" not in events()[-1]["metadata"]


def test_reveal_refuses_a_required_row_an_unknown_row_and_other_orgs(optional_field: str) -> None:
    eid = create()["id"]
    refused = act(eid, "exclusion:boundary", "reveal")
    assert refused.status_code == 422 and "always shown" in refused.json()["detail"]
    assert act(eid, "nope", "reveal").status_code == 404
    assert act(eid, "entity:abc123", "reveal").status_code == 404
    assert act(eid, optional_field, "reveal", token="b_member").status_code == 404
    assert act(eid, optional_field, "reveal", token="provider").status_code == 403
    assert not shown(eid, optional_field)
    call("PATCH", f"{BASE}/{eid}", body={"status": "archived"})
    assert act(eid, optional_field, "reveal").status_code == 409


def test_a_hidden_row_after_a_prefill_that_found_nothing_stays_hidden(optional_field: str) -> None:
    eid = create()["id"]
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', 'meta:state', $2::jsonb FROM engagements WHERE id = $1::uuid",
        eid, json.dumps({"prefill_ran_at": "2026-11-18T10:00:00.000Z", "prefill_covered": [optional_field, "gwp"], "revealed": []})))
    row = record(eid, optional_field)
    assert row["display_state"] == "not_detected" and row["shown"] is False
    assert record(eid, "gwp")["display_state"] == "not_detected" and record(eid, "gwp")["shown"] is True
    # a field the run did not cover says nothing: it was not looked at
    assert record(eid, "reporting_period")["display_state"] == "not_checked"


def test_an_engagement_prefilled_before_the_newer_rows_existed_shows_them_as_not_checked_yet() -> None:
    eid = create()["id"]
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', 'meta:state', $2::jsonb FROM engagements WHERE id = $1::uuid",
        eid, json.dumps({"prefill_ran_at": "2026-11-18T10:00:00.000Z", "revealed": []})))  # no covered list: an older run
    states = {f["field_id"]: f["display_state"] for f in review(eid).json()["fields"]}
    assert states["gwp"] == states["reporting_period"] == states["category:market:steam"] == "not_detected"
    newer = [f for f in states if f not in rules.LEGACY_PREFILL_COVERED]
    assert newer and all(states[f] == "not_checked" for f in newer)
    assert "calculation:estimation" in newer and "boundary:acquisitions" in newer


# --- migration 0016 ----------------------------------------------------------------------

BACKEND = Path(__file__).resolve().parents[2]


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "")}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def allowed_kinds() -> set[str]:
    rows = asyncio.run(_admin(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname = 'ck_workpaper_items_kind'"))
    return {k for k in ("ask", "finding", "examination", "document", "methodology") if f"'{k}'" in rows[0]["def"]}


def test_migration_0016_widens_the_kind_check_and_downgrade_restores_it() -> None:
    engagement = create()
    try:
        assert "methodology" in allowed_kinds()
        act(engagement["id"], "exclusion:boundary", "edit", {"value": "2025"})
        alembic("downgrade", "0015")
        assert allowed_kinds() == {"ask", "finding", "examination", "document"}
        assert asyncio.run(_admin("SELECT count(*) AS n FROM workpaper_items WHERE kind = 'methodology'"))[0]["n"] == 0
        alembic("upgrade", "head")
        assert "methodology" in allowed_kinds()
    finally:
        alembic("upgrade", "head")


# --- reporting period: two dates ----------------------------------------------------------

def test_the_reporting_period_takes_two_real_dates_and_refuses_the_rest_with_a_sentence() -> None:
    eid = create()["id"]
    good = act(eid, "reporting_period", "edit", {"value": {"start": "2025-01-01", "end": "2025-12-31"}})
    assert good.status_code == 200 and good.json()["decision"]["value"] == {"start": "2025-01-01", "end": "2025-12-31", "basis": "Calendar year"}
    for bad, words in (({"start": "2025-12-31", "end": "2025-01-01"}, "can't be before"),
                       ({"start": "2025-13-45", "end": "2025-12-31"}, "not a real date"),
                       ({"start": "2025-01-01"}, "both a start date and an end date"),
                       ("January 1 to December 31, 2025", "both a start date and an end date")):
        refused = act(eid, "reporting_period", "edit", {"value": bad})
        assert refused.status_code == 422 and words in refused.json()["detail"]
    assert record(eid, "reporting_period")["decision"]["value"] == {
        "start": "2025-01-01", "end": "2025-12-31", "basis": "Calendar year"}


def test_an_old_text_period_is_kept_shown_as_a_value_and_replaced_only_by_two_dates() -> None:
    eid = create()["id"]
    old = {"field_id": "reporting_period", "suggestion": None, "history": [],
           "decision": {"status": "edited", "value": "Fiscal 2024 – Zürich 排放", "by": {"name": "A", "login": "a"},
                        "at": "2026-11-01T10:00:00.000Z"}}
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', 'reporting_period', $2::jsonb FROM engagements WHERE id = $1::uuid",
        eid, json.dumps(old)))
    row = record(eid, "reporting_period")
    assert row["decision"]["value"] == "Fiscal 2024 – Zürich 排放" and row["display_state"] == "has_value"
    assert act(eid, "reporting_period", "edit", {"value": "2025"}).status_code == 422
    assert record(eid, "reporting_period")["decision"]["value"] == "Fiscal 2024 – Zürich 排放"
    assert act(eid, "reporting_period", "edit", {"value": {"start": "2024-01-01", "end": "2024-12-31"}}).status_code == 200
