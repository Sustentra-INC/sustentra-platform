"""Reviewer decisions on calculation lines through the real app and Postgres (migration 0028): add-only rows, the
audit trail, RLS by org, two clicks at once, and the migration up and down.

The recalculation engine is replaced by one line with a trace (the engine has its own tests); everything else is
real: the session, the engagement checks, the RLS context, the inserts and the audit events.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user); skipped locally without them.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.app.api import recalculation as recalculation_api
from backend.tests.db.test_engagements import (  # noqa: F401 - `seeded` is an autouse fixture
    A_MEMBER,
    BASE,
    ORG_A,
    ORG_B,
    _admin,
    _as_app,
    _call,
    asyncpg,
    call,
    create,
    pytestmark,
    seeded,
)

LINE = "s1:stationary:natural-gas:fac-kc01"
TRACE = {
    "trace_version": 1, "line_key": LINE, "panel": "stationary", "state": "complete", "blocking": [],
    "choices": [{"id": "method", "label": "Calculation method", "chosen": "per_unit", "chosen_by": "default",
                 "options": [{"id": "per_unit", "label": "Per unit", "available": True},
                             {"id": "heat", "label": "Heat content", "available": False,
                              "why_unavailable": "No heat content in evidence"}]}],
    "inputs": {"activity.total": {"id": "activity.total", "label": "Activity data", "kind": "evidence_sum",
                                  "company": None,
                                  "recomputed": {"value": 650000.0, "unit": "therm", "status": "accepted"}}},
    "steps": [], "result": {"unit": "t CO2e", "company": None, "recomputed": 3452.44, "difference": None},
    "method_mismatch": False, "flags": [],
}
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(db: Any, engagement: dict, user: Any, **_: Any) -> dict:
        return {"calculation_lines": [{"key": LINE, "trace": copy.deepcopy(TRACE)}]}

    monkeypatch.setattr(recalculation_api, "traced_recalculation", fake)


def path(engagement_id: str, tail: str) -> str:
    return f"{BASE}/{engagement_id}/calculation-lines/{tail}"


def rows(kind: str = "calc_line") -> list[Any]:
    return asyncio.run(_admin("SELECT item_key, payload, created_by FROM workpaper_items WHERE kind = $1 "
                              "ORDER BY created_at, item_key", kind))


def test_each_decision_is_a_new_row_and_the_trace_shows_the_current_one() -> None:
    engagement = create()
    eid = engagement["id"]
    one = call("POST", path(eid, f"{LINE}/choices/method"), "a_member",
               {"action": "choose", "option_id": "per_unit"})
    assert one.status_code == 200, one.text
    edit = {"action": "edit", "value": 640000, "unit": "therm", "reason": "Invoice shows less"}
    two = call("POST", path(eid, f"{LINE}/inputs/activity.total/recomputed"), "a_member", edit)
    three = call("POST", path(eid, f"{LINE}/inputs/activity.total/recomputed"), "a_admin",
                 {**edit, "value": 641000})
    assert (two.status_code, three.status_code) == (200, 200), (two.text, three.text)
    assert two.json()["seq"] == 1 and three.json()["seq"] == 2
    assert three.json()["decision"]["by"] == "admin@acme.test" and three.json()["decision"]["value"] == 641000.0
    reverted = call("POST", path(eid, f"{LINE}/inputs/activity.total/recomputed"), "a_member", {"action": "revert"})
    assert reverted.status_code == 200 and reverted.json()["decision"]["value"] == 640000.0 and reverted.json()["seq"] == 3

    stored = rows()
    assert len(stored) == 4  # nothing was rewritten: one row per decision
    first_edit = [json.loads(r["payload"]) for r in stored if json.loads(r["payload"])["seq"] == 1]
    assert {e["stream"] for e in first_edit} == {"choice|method|", "input|activity.total|recomputed"}
    assert all(len(r["item_key"]) <= 200 for r in stored)

    shown = call("GET", f"{BASE}/{eid}/recalculation/lines/{LINE}/trace", "a_member").json()
    assert shown["trace"]["choices"][0]["decision"]["value"] == "per_unit"
    recomputed = shown["trace"]["inputs"]["activity.total"]["recomputed"]
    # the engine is faked here, so the working is not redone (the engine tests cover that)
    assert recomputed["decision"]["value"] == 640000.0 and recomputed["value"] == 650000.0
    listed = call("GET", path(eid, "decisions"), "a_member").json()
    assert len(listed["decisions"]) == 2 and listed["orphaned_decisions"] == []


def test_every_action_writes_an_audit_event_without_the_value_or_the_reason() -> None:
    eid = create()["id"]
    call("POST", path(eid, f"{LINE}/inputs/activity.total/recomputed"), "a_member",
         {"action": "edit", "value": 123456, "unit": "therm", "reason": "secret-looking reason"})
    call("POST", path(eid, f"{LINE}/inputs/activity.total/recomputed"), "a_member", {"action": "revert"})
    refused = call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "heat",
                                                                              "reason": "x"})
    assert refused.status_code == 409 and "No heat content in evidence" in refused.json()["detail"]
    events = asyncio.run(_admin("SELECT actor_user_id, target_id, metadata::text AS metadata FROM audit_logs "
                                "WHERE event_type = 'calc_line_decision' ORDER BY created_at, id"))
    assert [json.loads(e["metadata"])["action"] for e in events] == ["edit", "revert"]  # the refusal wrote none
    assert all(e["actor_user_id"] == A_MEMBER and e["target_id"] == eid for e in events)
    assert json.loads(events[1]["metadata"])["restored"] == "empty"
    blob = " ".join(e["metadata"] for e in events)
    assert "123456" not in blob and "secret-looking" not in blob
    assert len(rows()) == 2  # a refused move stores nothing


def test_the_rows_are_add_only_for_every_role() -> None:
    eid = create()["id"]
    call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "per_unit"})
    [row] = rows()
    denied = asyncpg.exceptions.InsufficientPrivilegeError
    with pytest.raises(denied, match="add-only"):
        asyncio.run(_as_app(ORG_A, "UPDATE workpaper_items SET payload = '{}' WHERE kind = 'calc_line'"))
    with pytest.raises(denied, match="permission denied"):  # the app never had DELETE on this table (0012)
        asyncio.run(_as_app(ORG_A, "DELETE FROM workpaper_items WHERE kind = 'calc_line'"))
    with pytest.raises(denied, match="add-only"):  # the owner too
        asyncio.run(_admin("UPDATE workpaper_items SET payload = '{}' WHERE kind = 'calc_line'"))
    with pytest.raises(denied, match="add-only"):
        asyncio.run(_admin("DELETE FROM workpaper_items WHERE kind = 'calc_line'"))
    assert [r["item_key"] for r in rows()] == [row["item_key"]]
    assert json.loads(rows()[0]["payload"]) == json.loads(row["payload"])


def test_other_kinds_are_still_editable_and_cannot_be_turned_into_calc_lines() -> None:
    eid = create()["id"]
    saved = call("PUT", f"{BASE}/{eid}/workpaper-items/ask/ask-1", "a_member", {"payload": {"state": "draft"}})
    again = call("PUT", f"{BASE}/{eid}/workpaper-items/ask/ask-1", "a_member", {"payload": {"state": "sent"}})
    assert (saved.status_code, again.status_code) == (200, 200)
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="add-only"):
        asyncio.run(_admin("UPDATE workpaper_items SET kind = 'calc_line' WHERE item_key = 'ask-1'"))
    # the generic endpoint never writes or lists them
    assert call("PUT", f"{BASE}/{eid}/workpaper-items/calc_line/x", "a_member", {"payload": {}}).status_code == 422
    call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "per_unit"})
    listed = call("GET", f"{BASE}/{eid}/workpaper-items", "a_member").json()["items"]
    assert [i["kind"] for i in listed] == ["ask"]
    assert call("GET", f"{BASE}/{eid}/workpaper-items?kind=calc_line", "a_member").status_code == 422
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        asyncio.run(_admin("INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
                           "SELECT org_id, id, 'calc_lines', 'k', '{}' FROM engagements"))


def test_another_orgs_engagement_is_404_and_rls_hides_the_rows() -> None:
    eid = create()["id"]
    call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "per_unit"})
    for token in ("b_member",):
        assert call("POST", path(eid, f"{LINE}/choices/method"), token, {"action": "revert"}).status_code == 404
        assert call("POST", path(eid, "has space/choices/method"), token, {"action": "revert"}).status_code == 404
        assert call("GET", path(eid, "decisions"), token).status_code == 404
    assert call("POST", path(eid, f"{LINE}/choices/method"), "provider", {"action": "revert"}).status_code == 403
    assert call("GET", path(eid, "decisions"), "provider").status_code == 200
    assert call("POST", path(eid, f"{LINE}/choices/method"), None, {"action": "revert"}).status_code == 401
    assert len(asyncio.run(_as_app(ORG_A, "SELECT 1 FROM workpaper_items WHERE kind = 'calc_line'"))) == 1
    assert asyncio.run(_as_app(ORG_B, "SELECT 1 FROM workpaper_items WHERE kind = 'calc_line'")) == []
    assert asyncio.run(_as_app(None, "SELECT 1 FROM workpaper_items WHERE kind = 'calc_line'")) == []
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):  # B cannot write a row for A
        asyncio.run(_as_app(ORG_B, "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
                                   "VALUES ($1, $2::uuid, 'calc_line', 'k', '{}')", ORG_A, eid))


def test_an_archived_engagement_takes_no_decision() -> None:
    eid = create()["id"]
    assert call("PATCH", f"{BASE}/{eid}", "a_member", {"status": "archived"}).status_code == 200
    refused = call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose",
                                                                              "option_id": "per_unit"})
    assert refused.status_code == 409 and rows() == []


def test_two_clicks_at_once_both_land_one_after_the_other() -> None:
    eid = create()["id"]
    url = path(eid, f"{LINE}/inputs/activity.total/company")

    async def both() -> list[Any]:
        return list(await asyncio.gather(
            *(_call("POST", url, "a_member", {"action": "edit", "value": 10 + n}) for n in range(3))))

    answers = asyncio.run(both())
    assert [a.status_code for a in answers] == [200, 200, 200], [a.text for a in answers]
    assert sorted(a.json()["seq"] for a in answers) == [1, 2, 3]
    assert len(rows()) == 3
    # a duplicate accept (two clicks on Accept) is one decision and one refusal
    async def accepts() -> list[Any]:
        return list(await asyncio.gather(*(_call("POST", path(eid, f"{LINE}/choices/method"), "a_member",
                                                 {"action": "reject", "reason": "no"}) for _ in range(2))))

    codes = sorted(a.status_code for a in asyncio.run(accepts()))
    assert codes == [200, 409]


def test_a_decision_whose_line_is_gone_is_kept_and_listed_as_orphaned(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "per_unit"})

    async def renamed(db: Any, engagement: dict, user: Any) -> dict:
        return {"calculation_lines": [{"key": "s1:stationary:natural-gas:fac-new", "trace": {**TRACE, "line_key": "x"}}]}

    monkeypatch.setattr(recalculation_api, "traced_recalculation", renamed)
    listed = call("GET", path(eid, "decisions"), "a_member").json()
    assert listed["decisions"] == [] and [o["line_key"] for o in listed["orphaned_decisions"]] == [LINE]
    assert listed["orphaned_decisions"][0]["decision"]["value"] == "per_unit"
    assert len(rows()) == 1


def test_a_line_key_of_200_characters_works_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    longest = "s1:" + "k" * 197

    async def long_line(db: Any, engagement: dict, user: Any) -> dict:
        return {"calculation_lines": [{"key": longest, "trace": {**copy.deepcopy(TRACE), "line_key": longest}}]}

    monkeypatch.setattr(recalculation_api, "traced_recalculation", long_line)
    eid = create()["id"]
    response = call("POST", path(eid, f"{longest}/choices/method"), "a_member",
                    {"action": "choose", "option_id": "per_unit"})
    assert response.status_code == 200, response.text
    assert json.loads(rows()[0]["payload"])["line_key"] == longest
    assert call("POST", path(eid, f"{longest}x/choices/method"), "a_member", {"action": "revert"}).status_code == 422


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "")}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stderr


def test_downgrade_removes_the_rows_and_the_trigger_and_upgrade_brings_them_back() -> None:
    eid = create()["id"]
    call("POST", path(eid, f"{LINE}/choices/method"), "a_member", {"action": "choose", "option_id": "per_unit"})
    call("PUT", f"{BASE}/{eid}/workpaper-items/ask/ask-1", "a_member", {"payload": {"state": "draft"}})
    try:
        _alembic("downgrade", "0027_s1_parsed_texts")
        assert rows() == [] and len(rows("ask")) == 1  # only the calc_line rows went
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            asyncio.run(_admin("INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
                               "SELECT org_id, id, 'calc_line', 'k', '{}' FROM engagements"))
    finally:
        _alembic("upgrade", "head")
    asyncio.run(_admin("INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
                       "SELECT org_id, id, 'calc_line', 'k', '{}' FROM engagements"))  # the kind is back
    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError, match="add-only"):  # and the trigger
        asyncio.run(_admin("UPDATE workpaper_items SET payload = '{}' WHERE kind = 'calc_line'"))
