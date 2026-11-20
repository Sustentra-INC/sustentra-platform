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
    assert event["actor_user_id"] is None and event["suggested"] == 6 and len(claude.calls) == 4  # 6: Scope 1 is offered from its category
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
    assert event["kept_reviewer_decision"] == 2 and event["suggested"] == 4  # 4: Scope 1 is offered from its category


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


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "BUSY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 0.3)


def test_a_read_in_flight_causes_a_skip_when_it_does_not_end(claude: FakeClaude, quick: None) -> None:
    eid = create()["id"]
    api._RUNNING.add(eid)
    try:
        result = auto(eid)
    finally:
        api._RUNNING.discard(eid)
    assert result.state == "skipped" and result.reason_code == "busy"
    assert claude.calls == [] and ledger() == []
    assert [e["reason_code"] for e in events()] == ["busy"]


def test_busy_waits_for_the_current_read_to_end_and_then_reads_once(claude: FakeClaude,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    monkeypatch.setattr(api, "BUSY_POLL_SECONDS", 0.05)
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 5.0)
    eid = create()["id"]
    api._RUNNING.add(eid)
    threading.Timer(0.4, lambda: api._RUNNING.discard(eid)).start()
    result = auto(eid)
    assert result.state == "done" and len(ledger()) == 1 and len(claude.calls) == 4
    assert [e["outcome"] for e in events()] == ["ok"]  # nothing was lost, nothing skipped


def test_the_busy_guard_is_per_engagement_not_per_organization(claude: FakeClaude, quick: None) -> None:
    one, two = create()["id"], create()["id"]
    api._RUNNING.add(one)
    try:
        assert auto(two).state == "done"  # another engagement of the same organization is not blocked
    finally:
        api._RUNNING.discard(one)


class _Blind:
    """A guard that never knows anyone: only the database claim stands between two callers."""

    def __contains__(self, item: object) -> bool:
        return False

    def add(self, item: str) -> None: ...

    def discard(self, item: str) -> None: ...


def test_two_concurrent_callers_make_exactly_one_ai_call(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    eid = create()["id"]
    monkeypatch.setattr(api, "_RUNNING", _Blind())  # as if the other caller were another process
    monkeypatch.setattr(api, "BUSY_WAIT_SECONDS", 0.0)
    original = claude.structured

    def slow(**kw: Any) -> Any:
        time.sleep(0.4)
        return original(**kw)

    monkeypatch.setattr(claude, "structured", slow)

    async def both() -> list[api.AutoReadResult]:
        engine = db.create_engine(APP_URL or "", pool_size=4, max_overflow=0)
        try:
            sessions = db.build_sessionmaker(engine)
            return list(await asyncio.gather(
                api.run_automatic_prefill(str(ORG_A), eid, ["a.pdf"], sessions),
                api.run_automatic_prefill(str(ORG_A), eid, ["b.pdf"], sessions)))
        finally:
            await engine.dispose()

    results = asyncio.run(both())
    assert sorted(r.state for r in results) == ["done", "skipped"]
    assert [r.reason_code for r in results if r.state == "skipped"] == ["busy"]
    assert len(ledger()) == 1 and len(claude.calls) == 4  # one read: its four parts, once
    assert claim_of(eid) is None  # released


def claim_of(eid: str) -> Any:
    rows = asyncio.run(_admin("SELECT payload->'claim' AS c FROM workpaper_items WHERE engagement_id = $1::uuid "
                              "AND item_key = 'meta:state'", eid))
    return json.loads(rows[0]["c"]) if rows and rows[0]["c"] else None


def hold_claim(eid: str, seconds_ago: int = 0) -> None:
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) VALUES ($1, $2::uuid, "
        "'methodology', 'meta:state', '{}'::jsonb) ON CONFLICT DO NOTHING", ORG_A, eid))
    asyncio.run(_admin(
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{claim}', jsonb_build_object('by', 'other', 'at', "
        "to_jsonb(now() - make_interval(secs => $2)))) WHERE engagement_id = $1::uuid AND item_key = 'meta:state'",
        eid, float(seconds_ago)))


def test_the_button_answers_409_while_another_process_holds_the_claim(claude: FakeClaude) -> None:
    eid = create()["id"]
    hold_claim(eid)
    refused = call("POST", f"{BASE}/{eid}/methodology-review/prefill")
    assert refused.status_code == 409 and "already being prepared" in refused.json()["detail"]
    assert claude.calls == [] and ledger() == []
    hold_claim(eid, seconds_ago=120)  # an expired claim (its process stopped) is free
    assert call("POST", f"{BASE}/{eid}/methodology-review/prefill").status_code == 200
    assert len(claude.calls) == 4 and claim_of(eid) is None


def test_the_claim_is_renewed_while_the_read_lasts(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "HEARTBEAT_SECONDS", 0.1)
    eid = create()["id"]

    async def at() -> Any:
        rows = await _admin("SELECT payload->'claim'->>'at' AS at FROM workpaper_items WHERE engagement_id = $1::uuid "
                            "AND item_key = 'meta:state'", eid)
        return rows[0]["at"]

    async def go() -> list[Any]:
        engine = db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
        try:
            sessions = db.build_sessionmaker(engine)
            async with api._short_transaction(sessions, ORG_A) as session:
                engagement = await api.engagement_service.get_engagement(session, eid)
            seen = []
            async with api._claimed(sessions, engagement):
                for _ in range(3):
                    await asyncio.sleep(0.25)
                    seen.append(await at())
            return seen
        finally:
            await engine.dispose()

    seen = asyncio.run(go())
    assert len(set(seen)) == 3  # the claim's time moved on at each look
    assert claim_of(eid) is None


def test_a_reading_marker_without_a_heartbeat_reads_as_interrupted(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert prepare(eid)  # a marker exists
    asyncio.run(_admin(
        "UPDATE workpaper_items SET payload = jsonb_set(payload, '{auto_read,state}', '\"reading\"') "
        "WHERE engagement_id = $1::uuid AND item_key = 'meta:state'", eid))
    hold_claim(eid, seconds_ago=5)
    assert review(eid).json()["auto_read"]["state"] == "reading"  # alive: the claim is recent
    hold_claim(eid, seconds_ago=90)
    for shown in (review(eid).json()["auto_read"],
                  call("GET", f"{BASE}/{eid}/methodology-review/auto-read").json()["auto_read"]):
        assert shown["state"] == "failed" and shown["reason"] == "Reading was interrupted. Try again."
    asyncio.run(_admin("UPDATE workpaper_items SET payload = payload - 'claim' WHERE engagement_id = $1::uuid "
                       "AND item_key = 'meta:state'", eid))
    assert review(eid).json()["auto_read"]["state"] == "failed"  # no claim at all: interrupted too
    assert call("POST", f"{BASE}/{eid}/methodology-review/prefill").status_code == 200  # the button works again
    assert (review(eid).json()["auto_read"] or {}).get("state") != "failed"  # and the old failure is gone


def test_a_provider_failure_shows_as_a_failure(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.fail = True
    result = auto(eid)
    assert result.state == "failed" and "could not be reached" in (result.reason or "")
    shown = review(eid).json()["auto_read"]
    assert shown["state"] == "failed" and "could not be reached" in shown["reason"]
    assert [e["outcome"] for e in events()] == ["failed"]


def test_suggestions_that_could_not_be_saved_show_as_a_failure(claude: FakeClaude,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]

    async def broken(*args: Any, **kw: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(api, "_store", broken)
    result = auto(eid)
    assert result.state == "failed" and result.reason_code == "not_saved" and "could not be saved" in (result.reason or "")
    shown = review(eid).json()["auto_read"]
    assert shown["state"] == "failed" and "could not be saved" in shown["reason"]


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
