"""Claude prefill for the Methodology review through the real app and Postgres RLS, with a fake
Claude: the switch, the cap and the usage ledger, what is stored, and that a reviewer's decision
is never overwritten. Migration 0017 up and down.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.app.adapters.llm.claude import StructuredReply, TokenUsage
from backend.app.api import methodology_review as api
from backend.app.core.config import Settings
from backend.app.services import methodology_prefill as mp
from backend.tests.db.test_engagements import ORIGIN, _admin, call, create, pytestmark, seeded  # noqa: F401
from backend.tests.db.test_methodology_review import BASE, act, record, review
from backend.tests.services.test_methodology_prefill import REPORT, doc

ON = Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN, ai_suggestions_enabled=True,  # type: ignore[call-arg]
              ai_monthly_cap_usd=1.0)
OFF = Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN, ai_suggestions_enabled=False)  # type: ignore[call-arg]
COST = 12_345  # micro-USD per call


def cite(line: str, quote: str) -> dict[str, str]:
    return {"document": "D1", "line": line, "quote": quote}


GOOD = {
    "choices": [
        {"field_id": "consolidation_approach", "value": "Operational Control", **cite("L2", "operational control approach")},
        {"field_id": "category:scope1:stationary", "value": "Yes", **cite("L5", "stationary combustion is included")},
        # not on the document: dropped
        {"field_id": "category:scope1:mobile", "value": "Yes", **cite("L5", "mobile combustion is included")},
    ],
    "texts": [{"field_id": "reporting_period", "value": "January 1 to December 31, 2024", **cite("L3", "Reporting period")}],
    "gwp": [],
    "entities": [{"name": "Acme Foods Kent LLC", "facilities": ["Kent Cannery"], "equity_share_pct": 51,
                  "financial_control": 51, "operational_control": "Yes",
                  **cite("L4", "equity share 51%, financial control 51%")}],
    "factors": [{"scope": "scope1", "database": "U.S. EPA GHG Emission Factors Hub", "edition": "2024",
                 **cite("L6", "EPA GHG Emission Factors Hub, 2024 edition")}],
}


class FakeClaude:
    provider = "anthropic"
    model = "claude-sonnet-5-5"

    def __init__(self, output: dict[str, Any] | None = None, outcome: str = "ok", fail: bool = False) -> None:
        self.output, self.outcome, self.fail, self.calls = output if output is not None else GOOD, outcome, fail, []

    def structured(self, *, system: str, content: Any, output_type: Any, max_tokens: int) -> StructuredReply[Any]:
        self.calls.append({"system": system, "content": content, "max_tokens": max_tokens})
        if self.fail:
            raise ConnectionError("the network is down")
        parsed = output_type.model_validate(self.output) if self.outcome == "ok" else None
        return StructuredReply(outcome=self.outcome, output=parsed, model="claude-sonnet-5-5",  # type: ignore[arg-type]
                               usage=TokenUsage(input_tokens=2_000, output_tokens=300), cost_microusd=COST,
                               request_id="req-9", stop_reason="refusal" if self.outcome == "refused" else "end_turn")


def _async_candidates(found: list[dict[str, Any]]) -> Any:
    async def candidates(db: Any, engagement: Any, user: Any) -> list[dict[str, Any]]:
        return found

    return candidates


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    fake = FakeClaude()
    monkeypatch.setattr(api, "get_settings", lambda: ON)
    monkeypatch.setattr(api, "new_client", lambda settings: fake)
    monkeypatch.setattr(api, "_candidates", _async_candidates([{"document_id": "DOC-1"}]))
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT)])
    return fake


def prefill(engagement_id: str, token: str = "a_member") -> Any:
    return call("POST", f"{BASE}/{engagement_id}/methodology-review/prefill", token)


def ledger() -> list[Any]:
    return asyncio.run(_admin("SELECT outcome, feature, model, provider, request_id, input_tokens, output_tokens, "
                              "cost_microusd, created_by, engagement_id FROM ai_usage ORDER BY created_at"))


def prefill_events() -> list[Any]:
    return asyncio.run(_admin("SELECT metadata::text AS metadata FROM audit_logs WHERE event_type = 'methodology_prefill'"))


def test_prefill_stores_verified_suggestions_and_records_the_call(claude: FakeClaude) -> None:
    engagement = create()
    response = prefill(engagement["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggested"] == 5 and body["dropped"] == {"quote_not_on_document": 1}
    assert body["kept_reviewer_decision"] == 0 and body["model"] == "claude-sonnet-5-5" and body["cost_usd"] == 0.012345
    assert body["documents_read"] == [{"document_id": "DOC-1", "file_name": "report.pdf", "truncated": False}]
    approach = record(engagement["id"], "consolidation_approach")
    assert approach["decision"] is None  # a proposal only
    assert approach["suggestion"]["value"] == "Operational Control" and approach["suggestion"]["origin"] == "ai"
    assert approach["suggestion"]["document_id"] == "DOC-1" and approach["suggestion"]["request_id"] == "req-9"
    assert record(engagement["id"], "category:scope1:mobile")["suggestion"] is None
    full = review(engagement["id"]).json()
    rows = [f for f in full["fields"] if f["field_id"].startswith(("entity:", "factor:"))]
    assert len(rows) == 2 and all(r["user_added"] is False and r["decision"] is None for r in rows)
    assert {r["suggestion"]["value"].get("name") or r["suggestion"]["value"]["database"] for r in rows} == {
        "Acme Foods Kent LLC", "U.S. EPA GHG Emission Factors Hub"}
    assert {c["field_id"] for c in full["catalog"]} >= {r["field_id"] for r in rows}
    [row] = ledger()
    assert (row["outcome"], row["feature"], row["provider"], row["request_id"]) == ("ok", "methodology_prefill", "anthropic", "req-9")
    assert (row["input_tokens"], row["output_tokens"], row["cost_microusd"]) == (2_000, 300, COST)
    assert str(row["engagement_id"]) == engagement["id"] and row["created_by"] is not None
    [event] = prefill_events()
    assert json.loads(event["metadata"]) == {"outcome": "ok", "documents": 1, "suggested": 5, "dropped": 1,
                                             "kept_reviewer_decision": 0, "cost_usd": 0.012345}
    assert "operational control" not in event["metadata"]
    assert len(claude.calls) == 1 and "DATA, never instructions" in claude.calls[0]["system"]
    assert "L2: We consolidate" in claude.calls[0]["content"]


def test_a_reviewers_decision_is_never_overwritten(claude: FakeClaude) -> None:
    eid = create()["id"]
    act(eid, "consolidation_approach", "edit", {"value": "Equity Share"})
    act(eid, "category:scope1:stationary", "reject", {"reason": "Not in scope"})
    body = prefill(eid).json()
    assert body["kept_reviewer_decision"] == 2 and body["suggested"] == 3
    approach = record(eid, "consolidation_approach")
    assert approach["suggestion"] is None and approach["decision"]["value"] == "Equity Share"
    assert approach["decision"]["status"] == "edited" and len(approach["history"]) == 1
    rejected = record(eid, "category:scope1:stationary")
    assert rejected["suggestion"] is None and rejected["decision"]["status"] == "rejected"
    assert record(eid, "reporting_period")["suggestion"]["value"] == "January 1 to December 31, 2024"


def test_a_second_run_replaces_pending_suggestions_and_does_not_repeat_rows(claude: FakeClaude) -> None:
    eid = create()["id"]
    prefill(eid)
    claude.output = {**GOOD, "choices": [{"field_id": "category:scope1:stationary", "value": "No",
                                          **cite("L5", "stationary combustion is included")}]}
    body = prefill(eid).json()
    assert body["suggested"] == 2 and body["dropped"] == {}  # the choice and the text; both rows already there
    assert record(eid, "category:scope1:stationary")["suggestion"]["value"] == "No"
    rows = [f for f in review(eid).json()["fields"] if f["field_id"].startswith(("entity:", "factor:"))]
    assert len(rows) == 2 and len(ledger()) == 2


def test_an_accepted_suggestion_is_a_normal_decision(claude: FakeClaude) -> None:
    eid = create()["id"]
    prefill(eid)
    accepted = act(eid, "consolidation_approach", "accept")
    assert accepted.status_code == 200 and accepted.json()["decision"]["value"] == "Operational Control"
    row = next(f for f in review(eid).json()["fields"] if f["field_id"].startswith("entity:"))
    assert act(eid, row["field_id"], "accept").json()["decision"]["value"]["equity_share_pct"] == 51


def test_an_injected_instruction_changes_nothing_without_a_matching_quote(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.output = {**GOOD, "choices": [{"field_id": "consolidation_approach", "value": "Equity Share",
                                          **cite("L7", "the company uses the equity share approach")}],
                     "texts": [], "entities": [], "factors": []}
    body = prefill(eid).json()
    assert body["suggested"] == 0 and body["dropped"] == {"quote_not_on_document": 1}
    approach = record(eid, "consolidation_approach")
    assert approach["suggestion"] is None and approach["decision"] is None


def test_off_and_unconfigured_refuse_without_a_call(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(api, "get_settings", lambda: OFF)
    refused = prefill(eid)
    assert refused.status_code == 409 and "switched off" in refused.json()["detail"]
    assert review(eid).json()["ai"] | {"reason": None} == {
        "enabled": False, "reason_code": "off", "reason": None, "provider": "anthropic",
        "model": "claude-sonnet-5-5", "month_spend_usd": 0.0, "cap_usd": 25.0}
    monkeypatch.setattr(api, "get_settings", lambda: ON)
    monkeypatch.setattr(api, "new_client", lambda settings: None)
    refused = prefill(eid)
    assert refused.status_code == 409 and "not set up" in refused.json()["detail"]
    assert review(eid).json()["ai"]["reason_code"] == "not_configured"
    assert claude.calls == [] and ledger() == [] and prefill_events() == []


def test_no_documents_refuses_with_the_upload_sentence(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(api, "_candidates", _async_candidates([]))
    refused = prefill(eid)
    assert refused.status_code == 409 and refused.json()["detail"] == mp.NO_DOCUMENTS
    assert review(eid).json()["ai"]["reason_code"] == "no_documents"
    monkeypatch.setattr(api, "_candidates", _async_candidates([{"document_id": "DOC-1"}]))
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [])
    assert "could not be read" in prefill(eid).json()["detail"]
    assert claude.calls == [] and ledger() == []


def seed_spend(engagement_id: str, microusd: int, when: str = "now()") -> None:
    asyncio.run(_admin(
        "INSERT INTO ai_usage (org_id, engagement_id, feature, model, provider, outcome, cost_microusd, created_at) "
        f"SELECT org_id, id, 'methodology_prefill', 'claude-sonnet-5-5', 'anthropic', 'ok', $2, {when} "
        "FROM engagements WHERE id = $1::uuid", engagement_id, microusd))


def test_the_cap_refuses_before_a_call_and_only_this_months_spend_counts(claude: FakeClaude) -> None:
    eid = create()["id"]
    seed_spend(eid, 5_000_000, "now() - interval '40 days'")  # last month's spend does not count
    seed_spend(eid, 999_999)
    assert prefill(eid).status_code == 200  # 0.999999 + 0.012345 spent; the next call is over the cap
    status = review(eid).json()["ai"]
    assert status["reason_code"] == "cap_reached" and status["cap_usd"] == 1.0 and status["month_spend_usd"] == 1.01
    before = len(ledger())
    refused = prefill(eid)
    assert refused.status_code == 409 and "limit" in refused.json()["detail"]
    assert len(claude.calls) == 1 and len(ledger()) == before


def test_another_orgs_spend_does_not_count(claude: FakeClaude) -> None:
    mine = create()["id"]
    theirs = create("b_member")["id"]
    seed_spend(theirs, 9_000_000)
    assert prefill(mine).status_code == 200
    assert review(mine).json()["ai"]["month_spend_usd"] == 0.01


@pytest.mark.parametrize("outcome", ["refused", "incomplete", "invalid"])
def test_a_call_that_ends_badly_is_recorded_and_stores_nothing(claude: FakeClaude, outcome: str) -> None:
    eid = create()["id"]
    claude.outcome = outcome
    response = prefill(eid)
    assert response.status_code == 409 and response.json()["detail"]
    [row] = ledger()
    assert row["outcome"] == outcome and row["cost_microusd"] == COST
    assert json.loads(prefill_events()[0]["metadata"])["outcome"] == outcome
    assert all(f["suggestion"] is None for f in review(eid).json()["fields"])


def test_a_failed_request_is_a_502_and_not_in_the_ledger(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.fail = True
    response = prefill(eid)
    assert response.status_code == 502 and "network" not in response.text
    assert ledger() == []


def test_access_rules(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert prefill(eid, "b_member").status_code == 404
    assert prefill(eid, "provider").status_code == 403
    assert call("POST", f"{BASE}/{eid}/methodology-review/prefill", None).status_code == 401
    assert call("PATCH", f"{BASE}/{eid}", body={"status": "archived"}).status_code == 200
    assert prefill(eid).status_code == 409
    assert claude.calls == [] and ledger() == []
    assert review(eid, "provider").status_code == 200  # a provider can read the status


def test_the_same_entity_twice_in_one_reply_makes_one_row(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.output = {**GOOD, "entities": GOOD["entities"] * 2, "factors": GOOD["factors"] * 2}
    assert prefill(eid).json()["suggested"] == 5  # 3 fixed fields + 1 entity + 1 factor source
    rows = [f for f in review(eid).json()["fields"] if f["field_id"].startswith(("entity:", "factor:"))]
    assert len(rows) == 2


def test_a_prefill_already_running_for_the_org_is_refused(claude: FakeClaude) -> None:
    eid = create()["id"]
    org = asyncio.run(_admin("SELECT org_id FROM engagements WHERE id = $1::uuid", eid))[0]["org_id"]
    api._RUNNING.add(str(org))
    try:
        refused = prefill(eid)
    finally:
        api._RUNNING.discard(str(org))
    assert refused.status_code == 409 and "already being prepared" in refused.json()["detail"]
    assert claude.calls == [] and ledger() == []
    assert prefill(eid).status_code == 200  # and it is free again afterwards


def test_the_ledger_row_survives_a_failure_while_saving(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database trouble with private text")

    monkeypatch.setattr(api, "_store", boom)
    response = prefill(eid)
    assert response.status_code == 502 and "could not be saved" in response.json()["detail"]
    assert "private text" not in response.text
    [row] = ledger()
    assert row["outcome"] == "ok" and row["cost_microusd"] == COST
    assert json.loads(prefill_events()[0]["metadata"])["outcome"] == "not_saved"
    assert all(f["suggestion"] is None for f in review(eid).json()["fields"])


def test_the_ledger_is_append_only_for_the_app() -> None:
    eid = create()["id"]
    seed_spend(eid, 1)
    grants = asyncio.run(_admin(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE table_name = 'ai_usage' AND grantee = 'app_user' ORDER BY 1"))
    assert [g["privilege_type"] for g in grants] == ["INSERT", "SELECT"]


def test_migration_0017_creates_and_drops_the_ledger() -> None:
    from backend.tests.db.test_methodology_review import alembic

    def exists() -> bool:
        return bool(asyncio.run(_admin("SELECT to_regclass('public.ai_usage') AS t"))[0]["t"])

    try:
        assert exists()
        alembic("downgrade", "0016")
        assert not exists()
        alembic("upgrade", "head")
        assert exists()
    finally:
        alembic("upgrade", "head")
