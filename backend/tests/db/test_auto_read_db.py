"""The automatic read of a summary document through the real app and Postgres RLS, with a fake Claude:
it is the button's own code path run by Sustentra's AI, so the busy lock, the switch and the monthly cap
still say no, a reviewer's decision is never overwritten, and the audit event names its actor. Also the
organization's switch (PATCH /orgs/{id}/settings). Migration 0024.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.app.api import methodology_review as api
from backend.app.core import db
from backend.app.services import methodology_prefill as mp
from backend.tests.db.test_engagements import (  # noqa: F401
    A_MEMBER, APP_URL, ORG_A, ORIGIN, _admin, call, create, pytestmark, seeded)
from backend.tests.db.test_methodology_review import BASE
from backend.tests.db.test_methodology_prefill_db import (  # noqa: F401
    ON, FakeClaude, _async_candidates, act, ledger, prefill_events, record, review)
from backend.tests.services.test_methodology_prefill import REPORT, doc

ACTOR = "Sustentra's AI (automatic)"


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    fake = FakeClaude()
    monkeypatch.setattr(api, "get_settings", lambda: ON)
    monkeypatch.setattr(api, "new_client", lambda settings: fake)
    monkeypatch.setattr(api, "_candidates", _async_candidates([{"document_id": "DOC-1"}]))
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT)])
    return fake


def auto(engagement_id: str, names: list[str] | None = None) -> api.AutoReadResult:
    async def go() -> api.AutoReadResult:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            return await api.run_automatic_prefill(str(ORG_A), engagement_id, names or ["report.pdf"],
                                                   db.build_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def prepare(engagement_id: str) -> bool:
    async def go() -> bool:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            return await api.prepare_automatic_prefill(str(ORG_A), engagement_id, ["report.pdf"],
                                                       db.build_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def events() -> list[dict[str, Any]]:
    rows = asyncio.run(_admin("SELECT actor_user_id, actor_role, metadata::text AS metadata FROM audit_logs "
                              "WHERE event_type = 'methodology_prefill' ORDER BY created_at"))
    return [{"actor_user_id": r["actor_user_id"], "actor_role": r["actor_role"], **json.loads(r["metadata"])}
            for r in rows]


def set_switch(value: bool) -> None:
    asyncio.run(_admin("UPDATE organizations SET auto_read_summaries = $1 WHERE id = $2", value, ORG_A))


def test_the_automatic_read_stores_suggestions_records_the_call_and_names_its_actor(claude: FakeClaude) -> None:
    eid = create()["id"]
    result = auto(eid)
    assert result == api.AutoReadResult("done")
    assert record(eid, "consolidation_approach")["suggestion"]["value"] == "Operational Control"
    assert review(eid).json()["prefill_ran_at"] is not None
    [row] = ledger()
    assert (row["outcome"], row["feature"], row["created_by"]) == ("ok", "methodology_prefill", None)
    [event] = events()
    assert event["actor"] == ACTOR and event["automatic"] is True and event["outcome"] == "ok"
    assert event["actor_user_id"] is None and event["suggested"] == 5 and len(claude.calls) == 3
    assert review(eid).json()["auto_read"] is None  # finished: nothing is shown any more


def test_a_reviewers_decision_is_kept_by_the_automatic_read(claude: FakeClaude) -> None:
    eid = create()["id"]
    act(eid, "consolidation_approach", "edit", {"value": "Equity Share"})
    act(eid, "category:scope1:stationary", "reject", {"reason": "Not in scope"})
    assert auto(eid).state == "done"
    approach = record(eid, "consolidation_approach")
    assert approach["suggestion"] is None and approach["decision"]["value"] == "Equity Share"
    assert record(eid, "category:scope1:stationary")["decision"]["status"] == "rejected"
    [event] = events()
    assert event["kept_reviewer_decision"] == 2 and event["suggested"] == 3


def test_the_monthly_spend_gate_causes_a_skip_that_says_why(claude: FakeClaude) -> None:
    eid = create()["id"]
    asyncio.run(_admin(
        "INSERT INTO ai_usage (org_id, engagement_id, feature, model, provider, outcome, input_tokens, "
        "output_tokens, cost_microusd) VALUES ($1, $2::uuid, 'methodology_prefill', 'm', 'anthropic', 'ok', 1, 1, 2000000)",
        ORG_A, eid))
    result = auto(eid)
    assert result.state == "skipped" and result.reason_code == "cap_reached" and "limit" in (result.reason or "")
    assert claude.calls == [] and len(ledger()) == 1  # no new call was made or billed
    [event] = events()
    assert (event["outcome"], event["reason_code"], event["actor"]) == ("skipped", "cap_reached", ACTOR)
    shown = review(eid).json()["auto_read"]
    assert shown["state"] == "skipped" and "limit" in shown["reason"]


def test_a_prefill_already_running_for_the_organization_causes_a_skip(claude: FakeClaude) -> None:
    eid = create()["id"]
    api._RUNNING.add(str(ORG_A))
    try:
        result = auto(eid)
    finally:
        api._RUNNING.discard(str(ORG_A))
    assert result.state == "skipped" and result.reason_code == "busy"
    assert claude.calls == [] and ledger() == []
    assert [e["reason_code"] for e in events()] == ["busy"]
    assert str(ORG_A) not in api._RUNNING


def test_the_organizations_switch_turns_the_automatic_read_off(claude: FakeClaude) -> None:
    eid = create()["id"]
    set_switch(False)
    assert prepare(eid) is False and review(eid).json()["auto_read"] is None
    result = auto(eid)
    assert result.state == "skipped" and result.reason_code == "setting_off"
    assert claude.calls == [] and ledger() == [] and events() == []
    set_switch(True)
    assert prepare(eid) is True
    assert review(eid).json()["auto_read"]["state"] == "waiting"
    assert review(eid).json()["auto_read"]["file_names"] == ["report.pdf"]
    small = call("GET", f"{BASE}/{eid}/methodology-review/auto-read").json()
    assert small["auto_read"]["state"] == "waiting" and small["auto_read"]["file_names"] == ["report.pdf"]
    assert call("GET", f"{BASE}/{eid}/methodology-review/auto-read", "b_member").status_code == 404


def test_the_page_says_reading_while_the_call_is_made(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    seen: list[Any] = []
    original = claude.structured

    def watching(**kw: Any) -> Any:
        if not seen:
            seen.append(review(eid).json()["auto_read"])
        return original(**kw)

    monkeypatch.setattr(claude, "structured", watching)
    assert auto(eid).state == "done"
    assert seen[0]["state"] == "reading" and seen[0]["file_names"] == ["report.pdf"]


def test_a_closed_engagement_is_not_read(claude: FakeClaude) -> None:
    eid = create()["id"]
    asyncio.run(_admin("UPDATE engagements SET status = 'archived' WHERE id = $1::uuid", eid))
    assert auto(eid).reason_code == "engagement_unavailable" and claude.calls == []


# --- the organization's setting ---------------------------------------------------------------------

def test_org_admins_read_and_change_the_setting_members_cannot() -> None:
    path = f"/api/v1/orgs/{ORG_A}/settings"
    assert call("GET", path, "a_admin").json() == {"read_summary_documents_automatically": True}  # the default
    changed = call("PATCH", path, "a_admin", {"read_summary_documents_automatically": False})
    assert changed.status_code == 200 and changed.json() == {"read_summary_documents_automatically": False}
    assert call("GET", path, "a_admin").json() == {"read_summary_documents_automatically": False}
    assert call("GET", path, "a_member").status_code == 403
    assert call("PATCH", path, "a_member", {"read_summary_documents_automatically": True}).status_code == 403
    assert call("GET", f"/api/v1/orgs/{ORG_A}/settings", "b_member").status_code in (403, 404)
    assert call("PATCH", path, "a_admin", {"read_summary_documents_automatically": "maybe"}).status_code == 422
    audit = asyncio.run(_admin("SELECT metadata::text AS m FROM audit_logs WHERE event_type = 'org_settings_updated'"))
    assert json.loads(audit[0]["m"]) == {"read_summary_documents_automatically": False}
