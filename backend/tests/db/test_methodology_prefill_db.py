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
COST = 12_344  # micro-USD for the four calls of one prefill


def cite(line: str, quote: str) -> dict[str, str]:
    return {"document": "D1", "line": line, "quote": quote}


GOOD = {
    "choices": [
        {"field_id": "consolidation_approach", "value": "Operational Control", **cite("L2", "operational control approach")},
        {"field_id": "category:scope1:stationary", "value": "Yes", **cite("L5", "stationary combustion is included")},
        # not on the document: dropped
        {"field_id": "category:scope1:mobile", "value": "Yes", **cite("L5", "mobile combustion is included")},
    ],
    "gases": [],
    "texts": [],
    "estimations": [],
    "selections": [],
    "periods": [{"start": "2024-01-01", "end": "2024-12-31", "start_implied": False, "title_line": "", "title_quote": "", **cite("L3", "January 1 to December 31, 2024")}],
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
        self.fail_parts: tuple[str, ...] = ()  # output model names whose call raises

    @staticmethod
    def _fits(output_type: Any, name: str, item: dict[str, Any]) -> bool:
        """Whether this part may carry the item: its field_id (if any) is one the part allows."""

        from typing import get_args

        element = get_args(output_type.model_fields[name].annotation)[0]
        if "field_id" not in element.model_fields:
            return True
        return item["field_id"] in get_args(element.model_fields["field_id"].annotation)

    def structured(self, *, system: str, content: Any, output_type: Any, max_tokens: int) -> StructuredReply[Any]:
        self.calls.append({"system": system, "content": content, "max_tokens": max_tokens})
        if output_type.__name__ in self.fail_parts:
            raise ConnectionError("this call's network is down")
        if self.fail:
            raise ConnectionError("the network is down")
        # The reply is asked for in four calls: each answers the part of the canned reply it names.
        part = {k: [i for i in v if self._fits(output_type, k, i)] for k, v in self.output.items()
                if k in output_type.model_fields}
        parsed = output_type.model_validate(part) if self.outcome == "ok" else None
        return StructuredReply(outcome=self.outcome, output=parsed, model="claude-sonnet-5-5",  # type: ignore[arg-type]
                               usage=TokenUsage(input_tokens=2_000, output_tokens=300), cost_microusd=COST // 4,  # four calls make one reply's cost
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
    assert body["suggested"] == 6 and body["dropped"] == {"quote_not_on_document": 1}  # the sixth is Scope 1, offered from its category
    assert body["kept_reviewer_decision"] == 0 and body["model"] == "claude-sonnet-5-5" and body["cost_usd"] == 0.012344
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
    assert (row["input_tokens"], row["output_tokens"], row["cost_microusd"]) == (8_000, 1_200, COST)
    assert str(row["engagement_id"]) == engagement["id"] and row["created_by"] is not None
    [event] = prefill_events()
    assert json.loads(event["metadata"]) == {"outcome": "ok", "documents": 1, "suggested": 6, "dropped": 1,
                                             "kept_reviewer_decision": 0, "cost_usd": 0.012344}
    assert "operational control" not in event["metadata"]
    assert len(claude.calls) == 4 and all("DATA, never instructions" in c["system"] for c in claude.calls)
    assert all("L2: We consolidate" in c["content"] for c in claude.calls)


def test_a_reviewers_decision_is_never_overwritten(claude: FakeClaude) -> None:
    eid = create()["id"]
    act(eid, "consolidation_approach", "edit", {"value": "Equity Share"})
    act(eid, "category:scope1:stationary", "reject", {"reason": "Not in scope"})
    body = prefill(eid).json()
    assert body["kept_reviewer_decision"] == 2 and body["suggested"] == 4
    approach = record(eid, "consolidation_approach")
    assert approach["suggestion"] is None and approach["decision"]["value"] == "Equity Share"
    assert approach["decision"]["status"] == "edited" and len(approach["history"]) == 1
    rejected = record(eid, "category:scope1:stationary")
    assert rejected["suggestion"] is None and rejected["decision"]["status"] == "rejected"
    assert record(eid, "reporting_period")["suggestion"]["value"] == {"start": "2024-01-01", "end": "2024-12-31", "basis": "Calendar year"}


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
                     "texts": [], "estimations": [], "selections": [], "periods": [], "gases": [], "entities": [], "factors": []}
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


def states(engagement_id: str) -> dict[str, str]:
    return {f["field_id"]: f["display_state"] for f in review(engagement_id).json()["fields"]}


def test_rows_read_not_checked_until_a_prefill_finishes_then_not_detected(claude: FakeClaude) -> None:
    eid = create()["id"]
    before = review(eid).json()
    assert before["prefill_ran_at"] is None and set(states(eid).values()) == {"not_checked"}
    optional = {c["field_id"] for c in before["catalog"] if not c["required"]}
    assert optional == {"boundary:acquisitions", "boundary:leased_space", "calculation:estimation", "calculation:source_records", "scope2:instruments"}  # every gas row is always shown
    assert all(f["shown"] is (f["field_id"] not in optional) for f in before["fields"])
    assert prefill(eid).status_code == 200
    after = review(eid).json()
    assert after["prefill_ran_at"] is not None
    now = states(eid)
    assert now["consolidation_approach"] == "has_value" and now["reporting_period"] == "has_value"
    assert now["gwp"] == "not_detected" and now["exclusion:boundary"] == "not_detected"
    assert now["calculation:estimation"] == "not_detected"  # this run covered the newer rows too
    assert "not_checked" not in now.values()
    # the marker is page state, not a field: it is never listed as a workpaper item
    listed = call("GET", f"{BASE}/{eid}/workpaper-items?kind=methodology").json()["items"]
    assert "meta:state" not in {i["item_key"] for i in listed}


def test_a_rerun_after_a_decision_keeps_the_decision_and_the_state(claude: FakeClaude) -> None:
    eid = create()["id"]
    act(eid, "consolidation_approach", "edit", {"value": "Equity Share"})
    assert prefill(eid).status_code == 200
    assert record(eid, "consolidation_approach")["decision"]["value"] == "Equity Share"
    assert states(eid)["consolidation_approach"] == "has_value"
    first = review(eid).json()["prefill_ran_at"]
    assert prefill(eid).status_code == 200
    assert record(eid, "consolidation_approach")["decision"]["value"] == "Equity Share"
    assert review(eid).json()["prefill_ran_at"] >= first


def test_a_refused_prefill_leaves_every_row_not_checked(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(api, "_candidates", _async_candidates([]))
    assert prefill(eid).status_code == 409
    monkeypatch.setattr(api, "_candidates", _async_candidates([{"document_id": "DOC-1"}]))
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [])
    assert prefill(eid).status_code == 409
    assert review(eid).json()["prefill_ran_at"] is None and set(states(eid).values()) == {"not_checked"}


def seed_spend(engagement_id: str, microusd: int, when: str = "now()") -> None:
    asyncio.run(_admin(
        "INSERT INTO ai_usage (org_id, engagement_id, feature, model, provider, outcome, cost_microusd, created_at) "
        f"SELECT org_id, id, 'methodology_prefill', 'claude-sonnet-5-5', 'anthropic', 'ok', $2, {when} "
        "FROM engagements WHERE id = $1::uuid", engagement_id, microusd))


def test_the_cap_refuses_before_a_call_and_only_this_months_spend_counts(claude: FakeClaude) -> None:
    eid = create()["id"]
    seed_spend(eid, 5_000_000, "now() - interval '40 days'")  # last month's spend does not count
    seed_spend(eid, 999_999)
    assert prefill(eid).status_code == 200  # 0.999999 + 0.012344 spent; the next call is over the cap
    status = review(eid).json()["ai"]
    assert status["reason_code"] == "cap_reached" and status["cap_usd"] == 1.0 and status["month_spend_usd"] == 1.01
    before = len(ledger())
    refused = prefill(eid)
    assert refused.status_code == 409 and "limit" in refused.json()["detail"]
    assert len(claude.calls) == 4 and len(ledger()) == before


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


def test_one_failing_call_keeps_the_others_and_names_the_section(claude: FakeClaude) -> None:
    eid = create()["id"]
    claude.fail_parts = ("CategoriesPart",)
    response = prefill(eid)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [f["section"] for f in body["failed_sections"]] == ["Categories, gases and exclusions"]
    assert "ConnectionError" in body["failed_sections"][0]["reason"]
    assert record(eid, "consolidation_approach")["suggestion"]["value"] == "Operational Control"  # call (a) kept
    assert record(eid, "category:scope1:stationary")["suggestion"] is None  # call (b) gave nothing
    [row] = ledger()
    assert row["outcome"] == "ok" and row["cost_microusd"] == 3 * (COST // 4)  # only the answered calls are billed
    assert json.loads(prefill_events()[0]["metadata"])["failed_sections"] == ["Categories, gases and exclusions"]


def test_a_request_the_provider_rejects_names_the_reason(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    import anthropic
    import httpx2

    eid = create()["id"]
    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"), json={
        "type": "error", "error": {"type": "invalid_request_error", "message": "The compiled grammar is too large."}})

    def reject(**kwargs: Any) -> Any:
        raise anthropic.BadRequestError("bad", response=response, body=response.json())

    monkeypatch.setattr(claude, "structured", reject)
    result = prefill(eid)
    assert result.status_code == 500 and "invalid_request_error: The compiled grammar is too large." in result.text
    assert ledger() == []


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
    assert prefill(eid).json()["suggested"] == 6  # 3 fixed fields + Scope 1 + 1 entity + 1 factor source
    rows = [f for f in review(eid).json()["fields"] if f["field_id"].startswith(("entity:", "factor:"))]
    assert len(rows) == 2


def test_a_prefill_already_running_for_the_engagement_is_refused(claude: FakeClaude) -> None:
    eid = create()["id"]
    api._RUNNING.add(eid)
    try:
        refused = prefill(eid)
    finally:
        api._RUNNING.discard(eid)
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


# --- acquisitions and leased space: "only if the company has a value" -------------------------

ACQ, LEASE = "boundary:acquisitions", "boundary:leased_space"
DEAL = "In March 2025 we acquired Müller Käserei – Zürich (瑞士) and sold the Kent depot."
LEASED = "Leased offices are outside the boundary; leased vehicles are reported under operational control."


def shown_ids(engagement_id: str) -> set[str]:
    return {f["field_id"] for f in review(engagement_id).json()["fields"] if f["shown"]}


def with_report(monkeypatch: pytest.MonkeyPatch, *extra: str) -> None:
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, line) for line in extra])])


def test_the_two_rows_are_hidden_on_a_fresh_engagement_and_listed_for_add_an_item(claude: FakeClaude) -> None:
    eid = create()["id"]
    body = review(eid).json()
    assert {ACQ, LEASE} & shown_ids(eid) == set()
    defs = {c["field_id"]: c for c in body["catalog"]}
    for field_id, label in ((ACQ, "Acquisitions and divestitures"), (LEASE, "Treatment of leased space")):
        assert defs[field_id]["required"] is False and defs[field_id]["kind"] == "text" and defs[field_id]["label"] == label
        assert defs[field_id]["group"] == "boundary"
    assert states(eid)[ACQ] == "not_checked"


def test_a_prefill_with_a_quote_shows_the_row_and_one_without_does_not(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    with_report(monkeypatch, DEAL)
    claude.output = {**GOOD, "texts": [
        {"field_id": ACQ, "value": "Acquired Müller Käserei – Zürich in March 2025; sold the Kent depot.", **cite("L9", "acquired Müller Käserei – Zürich")}]}
    body = prefill(eid).json()
    assert body["suggested"] == 7 and LEASE not in shown_ids(eid)
    assert ACQ in shown_ids(eid) and states(eid)[ACQ] == "has_value"
    suggestion = record(eid, ACQ)["suggestion"]
    assert suggestion["value"].startswith("Acquired Müller Käserei – Zürich") and suggestion["origin"] == "ai"
    assert states(eid)[LEASE] == "not_detected"  # the run found nothing: still hidden, and reads Not detected when added


def test_a_quote_that_is_not_on_the_page_is_dropped_and_the_row_stays_hidden(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    with_report(monkeypatch, DEAL)
    claude.output = {**GOOD, "texts": [{"field_id": LEASE, "value": "Leases are excluded.", **cite("L9", "all leases are excluded")}]}
    body = prefill(eid).json()
    assert body["dropped"] == {"quote_not_on_document": 2}  # the lease quote, and GOOD's mobile combustion quote
    assert LEASE not in shown_ids(eid) and record(eid, LEASE)["suggestion"] is None


def test_add_an_item_shows_the_row_as_not_detected_after_a_run_and_it_can_be_edited(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    with_report(monkeypatch, LEASED)
    claude.output = {**GOOD, "texts": []}
    prefill(eid)
    assert LEASE not in shown_ids(eid)
    assert act(eid, LEASE, "reveal").status_code == 200
    assert LEASE in shown_ids(eid) and states(eid)[LEASE] == "not_detected"
    value = "Leased offices excluded – Büro München 办公室; vehicles under operational control."
    saved = act(eid, LEASE, "edit", {"value": value})
    assert saved.status_code == 200 and record(eid, LEASE)["decision"]["value"] == value
    assert states(eid)[LEASE] == "has_value" and LEASE in shown_ids(eid)
    assert act(eid, LEASE, "edit", {"value": "x" * 2001}).status_code == 422
    assert act(eid, ACQ, "edit", {"value": 5}).status_code == 422


# --- GWP: every set the report names stays, as its own row --------------------------------------

GWP_LINES = ["Scope 1 uses the IPCC Fifth Assessment Report (AR5) 100-year GWP values.",
             "Scope 2 uses AR6 with a 20-year horizon; a 500-year horizon (AR4) is shown for comparison."]


def gwp_rows(engagement_id: str) -> list[dict]:
    return [f for f in review(engagement_id).json()["fields"] if f["field_id"].startswith("gwp:")]


def test_every_gwp_set_the_report_names_is_kept_the_first_as_the_field_and_the_rest_as_rows(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in GWP_LINES])])
    claude.output = {**GOOD, "gwp": [
        {"set": "AR5", "horizon": "100-year", "applies_to": "", **cite("L9", "IPCC Fifth Assessment Report (AR5) 100-year")},
        {"set": "AR6", "horizon": "20-year", "applies_to": "", **cite("L10", "AR6 with a 20-year horizon")},
        {"set": "AR4", "horizon": "500-year", "applies_to": "", **cite("L10", "a 500-year horizon (AR4)")}]}
    assert prefill(eid).json()["suggested"] == 9  # GOOD's six, the fixed GWP field and two GWP rows
    # no quote says default and none names a gas: the tie goes to the latest AR, which becomes the fixed field
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR6", "horizon": "20-year"}
    rows = gwp_rows(eid)
    assert sorted((r["suggestion"]["value"]["set"], r["suggestion"]["value"]["horizon"]) for r in rows) == [("AR4", "500-year"), ("AR5", "100-year")]
    assert all(r["user_added"] is False and r["decision"] is None and r["shown"] for r in rows)
    catalog = {c["field_id"]: c for c in review(eid).json()["catalog"] if c["field_id"].startswith("gwp:")}
    assert set(catalog) == {r["field_id"] for r in rows} and all(c["label"] == "GWP set" for c in catalog.values())
    again = prefill(eid).json()  # a second run adds no second copy
    assert len(gwp_rows(eid)) == 2 and again["suggested"] == 5  # no second copy of a row (the fifth is Scope 1)


def test_a_decided_gwp_field_is_kept_and_a_set_it_already_holds_is_not_added_again(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    assert act(eid, "gwp", "edit", {"value": {"set": "AR5", "horizon": "100-year"}}).status_code == 200
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in GWP_LINES])])
    claude.output = {**GOOD, "gwp": [
        {"set": "AR6", "horizon": "20-year", "applies_to": "", **cite("L10", "AR6 with a 20-year horizon")},
        {"set": "AR5", "horizon": "100-year", "applies_to": "", **cite("L9", "IPCC Fifth Assessment Report (AR5) 100-year")}]}
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["decision"]["value"] == {"set": "AR5", "horizon": "100-year"} and record(eid, "gwp")["suggestion"] is None
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR6"]  # AR5 / 100-year is the decided field


def test_a_reviewer_adds_edits_and_removes_gwp_rows_and_the_500_year_horizon_saves(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert act(eid, "gwp", "edit", {"value": {"set": "AR6", "horizon": "500-year"}}).status_code == 200
    added = call("POST", f"{BASE}/{eid}/methodology-review/rows", "a_member", {"group": "gwp"})
    assert added.status_code == 201, added.text
    row_id = added.json()["field"]["field_id"]
    assert row_id.startswith("gwp:") and added.json()["decision"]["value"] == {"set": "", "horizon": ""}
    assert act(eid, row_id, "accept").status_code == 422  # blank: nothing to accept
    assert act(eid, row_id, "edit", {"value": {"set": "AR4", "horizon": "20-year"}}).status_code == 200
    assert act(eid, row_id, "edit", {"value": {"set": "AR4", "horizon": "5-year"}}).status_code == 422
    removed = call("DELETE", f"{BASE}/{eid}/methodology-review/{row_id}", "a_member")
    assert removed.status_code == 200 and gwp_rows(eid) == []


def test_a_second_run_in_another_order_never_shows_one_set_twice(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in GWP_LINES])])
    ar5 = {"set": "AR5", "horizon": "100-year", "applies_to": "", **cite("L9", "IPCC Fifth Assessment Report (AR5) 100-year")}
    ar6 = {"set": "AR6", "horizon": "20-year", "applies_to": "", **cite("L10", "AR6 with a 20-year horizon")}
    claude.output = {**GOOD, "gwp": [ar5, ar6]}
    assert prefill(eid).status_code == 200
    # no quote says default and none names a gas: the latest AR is the fixed field, whatever the model's order
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR6", "horizon": "20-year"}
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR5"]
    claude.output = {**GOOD, "gwp": [ar6, ar5]}  # the same sets, the other way round
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR6", "horizon": "20-year"}  # keeps its set
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR5"]
    claude.output = {**GOOD, "gwp": [ar5]}  # AR5 is already on a row, so it does not go into the fixed field too
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"]["value"]["set"] == "AR6"
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR5"]


# --- estimation method for missing data: only if the company has a value -----------------------

EST = "calculation:estimation"
EST_LINES = ["Missing utility invoices are estimated from the average of the adjacent months.",
             "Where Käserei fuel cards have gaps, prior-year consumption is used (燃料)."]


def test_the_estimation_row_is_hidden_until_prefill_finds_it_and_keeps_a_quote_per_entry(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    assert EST not in shown_ids(eid)
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in EST_LINES])])
    claude.output = {**GOOD, "estimations": [
        {"source_type": "Utility invoices", "method": "Average of adjacent months", **cite("L9", "Missing utility invoices are estimated")},
        {"source_type": "Fuel cards", "method": "Prior-year consumption", **cite("L10", "fuel cards have gaps, prior-year consumption is used (燃料)")}]}
    assert prefill(eid).status_code == 200
    assert EST in shown_ids(eid)
    suggestion = record(eid, EST)["suggestion"]
    assert [e["label"] for e in suggestion["evidence"]] == ["Utility invoices", "Fuel cards"]
    assert suggestion["value"][1] == {"source_type": "Fuel cards", "method": "Prior-year consumption"}
    assert act(eid, EST, "accept").status_code == 200
    assert record(eid, EST)["decision"]["value"] == suggestion["value"]


def test_a_reviewer_adds_edits_and_removes_entries_and_the_list_can_be_emptied(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert act(eid, EST, "reveal").status_code == 200 and states(eid)[EST] == "not_checked"
    one = [{"source_type": "Brändstoff 燃料", "method": "Vorjahr × 1,02"}]
    assert act(eid, EST, "edit", {"value": one}).status_code == 200
    two = [*one, {"source_type": "Meter readings", "method": "Interpolated"}]
    assert act(eid, EST, "edit", {"value": two}).status_code == 200
    assert record(eid, EST)["decision"]["value"] == two
    assert act(eid, EST, "edit", {"value": one}).status_code == 200  # remove one
    assert act(eid, EST, "edit", {"value": []}).status_code == 200  # remove all
    assert record(eid, EST)["decision"]["value"] == [] and EST in shown_ids(eid)
    dup = [{"source_type": "Fuel", "method": "a"}, {"source_type": "fuel", "method": "b"}]
    assert act(eid, EST, "edit", {"value": dup}).status_code == 422
    assert act(eid, EST, "edit", {"value": "average"}).status_code == 422


# --- multi-select rows ---------------------------------------------------------------------------

INSTR, RECORDS = "scope2:instruments", "calculation:source_records"
SEL_LINES = ["We buy RECs for the Tualatin Plant and hold a PPA with W\u00e4rmewerke K\u00e4serei.",
             "Figures come from utility invoices and fuel card statements."]


def test_instrument_types_show_only_when_a_market_based_category_is_yes_and_add_an_item_overrides(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert INSTR not in shown_ids(eid) and RECORDS not in shown_ids(eid)
    assert act(eid, "category:market:electricity", "edit", {"value": "No"}).status_code == 200
    assert INSTR not in shown_ids(eid)  # a No is not a market-based number
    assert act(eid, "category:market:steam", "edit", {"value": "Yes"}).status_code == 200
    assert INSTR in shown_ids(eid) and RECORDS not in shown_ids(eid)
    assert act(eid, "category:market:steam", "edit", {"value": "Not detected"}).status_code == 200
    assert INSTR not in shown_ids(eid)  # change of mind: hidden again, nothing was stored for it
    assert act(eid, RECORDS, "reveal").status_code == 200 and RECORDS in shown_ids(eid)


def test_a_claude_yes_on_a_market_category_shows_the_row_until_the_reviewer_rejects_it(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in SEL_LINES])])
    claude.output = {**GOOD, "choices": [{"field_id": "category:market:electricity", "value": "Yes",
                                          **cite("L9", "RECs for the Tualatin Plant")}]}
    # the quote names no category term, but a Yes choice needs none: it is the category's own answer
    assert prefill(eid).status_code == 200
    assert record(eid, "category:market:electricity")["suggestion"]["value"] == "Yes" and INSTR in shown_ids(eid)
    assert act(eid, "category:market:electricity", "reject", {"reason": "Not stated"}).status_code == 200
    assert INSTR not in shown_ids(eid)


def test_prefill_keeps_a_quote_per_option_and_the_reviewer_can_change_the_selection(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in SEL_LINES])])
    claude.output = {**GOOD, "selections": [
        {"field_id": INSTR, "option": "RECs or other energy attribute certificates", "wording": "We buy RECs", **cite("L9", "We buy RECs for the Tualatin Plant")},
        {"field_id": INSTR, "option": "PPA or VPPA", "wording": "a PPA with W\u00e4rmewerke K\u00e4serei", **cite("L9", "a PPA with W\u00e4rmewerke K\u00e4serei")},
        {"field_id": RECORDS, "option": "Utility invoices", "wording": "", **cite("L10", "utility invoices and fuel card statements")},
        {"field_id": RECORDS, "option": "Fuel cards", "wording": "", **cite("L10", "utility invoices and fuel card statements")}]}
    assert prefill(eid).status_code == 200
    suggestion = record(eid, INSTR)["suggestion"]
    assert INSTR in shown_ids(eid) and RECORDS in shown_ids(eid)
    assert [e["label"] for e in suggestion["evidence"]] == ["RECs or other energy attribute certificates", "PPA or VPPA"]
    assert [v["option"] for v in record(eid, RECORDS)["suggestion"]["value"]] == ["Utility invoices", "Fuel cards"]
    assert act(eid, INSTR, "accept").status_code == 200
    chosen = [{"option": "PPA or VPPA", "wording": "our PPA \u2013 W\u00e4rmewerke"}, {"option": "Residual mix", "wording": ""}]
    assert act(eid, INSTR, "edit", {"value": chosen}).status_code == 200 and record(eid, INSTR)["decision"]["value"] == chosen
    assert act(eid, INSTR, "edit", {"value": [{"option": "Carbon offsets", "wording": ""}]}).status_code == 422
    free = [{"option": "Utility invoices", "wording": ""}, {"option": "Lieferscheine \u7eb8\u8d28", "wording": "Papier-Belege"}]
    assert act(eid, RECORDS, "edit", {"value": free}).status_code == 200
    empty = act(eid, RECORDS, "edit", {"value": []})  # a decision needs an option
    assert empty.status_code == 422 and "choose at least one option" in empty.json()["detail"]
    assert record(eid, RECORDS)["decision"]["value"] == free
    none_only = act(eid, INSTR, "edit", {"value": [{"option": "None", "wording": ""}]})  # None is the explicit empty answer
    assert none_only.status_code == 200
# --- gases covered: one row per gas, always shown (never hidden) -----------------------

GASES = ["gas:co2", "gas:ch4", "gas:n2o", "gas:hfcs", "gas:pfcs", "gas:sf6", "gas:nf3"]
GAS_LINE = "The inventory covers CO₂, CH₄ and N₂O; SF6 and NF3 are not emitted at our Käserei sites (瑞士)."


def test_the_seven_gas_rows_are_always_shown_and_keep_their_own_values(claude: FakeClaude) -> None:
    eid = create()["id"]
    body = review(eid).json()
    defs = {c["field_id"]: c for c in body["catalog"] if c["field_id"].startswith("gas:")}
    assert list(defs) == GASES
    assert all(d["required"] is True and d["allowed"] == ["Included", "Declared absent", "Not mentioned"] for d in defs.values())
    assert [d["label"] for d in defs.values()] == ["Gas: CO2", "Gas: CH4", "Gas: N2O", "Gas: HFCs", "Gas: PFCs", "Gas: SF6", "Gas: NF3"]
    assert set(GASES) <= shown_ids(eid)  # all seven, from the start
    assert {"group": "gases", "label": "Gases covered"} in body["groups"]
    # the category set and the gas set stay apart
    assert act(eid, "gas:co2", "edit", {"value": "Yes"}).status_code == 422
    assert act(eid, "gas:co2", "edit", {"value": "Not detected"}).status_code == 422
    assert act(eid, "category:scope1:mobile", "edit", {"value": "Included"}).status_code == 422
    assert set(GASES) <= shown_ids(eid)


def test_prefill_with_a_quote_suggests_only_the_gases_it_found(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, GAS_LINE)])])
    claude.output = {**GOOD, "gases": [
        {"field_id": "gas:co2", "value": "Included", **cite("L9", "covers CO₂, CH₄ and N₂O")},
        {"field_id": "gas:sf6", "value": "Declared absent", **cite("L9", "SF6 and NF3 are not emitted")},
        {"field_id": "gas:pfcs", "value": "Declared absent", **cite("L9", "PFCs are not emitted")}]}  # not on the page
    body = prefill(eid).json()
    assert body["dropped"] == {"quote_not_on_document": 2}  # the PFC quote, and GOOD's mobile combustion quote
    assert set(GASES) <= shown_ids(eid)  # every gas stays on the page
    assert {g for g in GASES if record(eid, g)["suggestion"]} == {"gas:co2", "gas:sf6"}
    assert record(eid, "gas:co2")["suggestion"]["value"] == "Included"
    assert record(eid, "gas:sf6")["suggestion"]["value"] == "Declared absent"
    assert states(eid)["gas:pfcs"] == "not_detected" and record(eid, "gas:pfcs")["shown"]


def test_a_gas_needs_no_reveal_and_a_reviewer_can_set_not_mentioned_and_decide_a_gas(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert act(eid, "gas:nf3", "reveal").status_code == 422  # already shown: nothing to add
    assert record(eid, "gas:nf3")["shown"] and states(eid)["gas:nf3"] == "not_checked"
    assert act(eid, "gas:nf3", "edit", {"value": "Not mentioned"}).status_code == 200
    assert record(eid, "gas:nf3")["decision"]["value"] == "Not mentioned" and states(eid)["gas:nf3"] == "has_value"
    assert act(eid, "gas:hfcs", "edit", {"value": "Declared absent"}).status_code == 200
    assert set(GASES) <= shown_ids(eid)


def test_a_rejected_fixed_gwp_set_never_comes_back_as_a_row(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + [(3, t) for t in GWP_LINES])])
    ar5 = {"set": "AR5", "horizon": "100-year", "applies_to": "", **cite("L9", "IPCC Fifth Assessment Report (AR5) 100-year")}
    ar6 = {"set": "AR6", "horizon": "20-year", "applies_to": "", **cite("L10", "AR6 with a 20-year horizon")}
    claude.output = {**GOOD, "gwp": [ar5]}
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR5", "horizon": "100-year"}
    assert act(eid, "gwp", "reject", {"reason": "Not the reporting standard"}).status_code == 200
    assert record(eid, "gwp")["decision"]["status"] == "rejected" and record(eid, "gwp")["decision"]["value"] is None
    claude.output = {**GOOD, "gwp": [ar5]}  # the report still names the rejected set
    assert prefill(eid).status_code == 200
    assert gwp_rows(eid) == []  # the rejection stands: the set is not put back as a row
    assert record(eid, "gwp")["decision"]["status"] == "rejected"
    claude.output = {**GOOD, "gwp": [ar5, ar6]}  # another set the report names is still a row
    assert prefill(eid).status_code == 200
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR6"]
    assert record(eid, "gwp")["decision"]["status"] == "rejected"


# --- entities: the boundary sentence, optional percentages, a corrected name ---------------------------

BOUNDARY_LINES = [(1, "The boundary covers company-owned or leased buildings (offices, data centres, ATMs), vehicles and aircraft."),
                  (1, "Café Québec Holdings Inc. is inside the boundary.")]


def entity_rows(engagement_id: str) -> list[dict]:
    return [f for f in review(engagement_id).json()["fields"] if f["field_id"].startswith("entity:")]


def test_a_boundary_sentence_with_no_named_entity_is_stored_as_the_value_and_a_silent_document_reads_not_detected(
        claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(BOUNDARY_LINES)])
    empty: dict[str, Any] = {k: [] for k in GOOD}
    sentence = BOUNDARY_LINES[0][1]
    claude.output = {**empty, "texts": [{"field_id": "boundary:entities", "value": sentence, **cite("L1", sentence)}]}
    assert prefill(eid).json()["suggested"] == 1
    row = record(eid, "boundary:entities")
    assert row["suggestion"]["value"] == sentence and row["suggestion"]["quote"] == sentence and row["display_state"] == "has_value"
    assert entity_rows(eid) == []  # no entity was named, so none is invented
    catalog = next(c for c in review(eid).json()["catalog"] if c["field_id"] == "boundary:entities")
    assert catalog["value_note"] == "Boundary sentence only" and catalog["kind"] == "text"
    assert act(eid, "boundary:entities", "accept").json()["decision"]["value"] == sentence
    other = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(1, "Emissions are shown below.")])])
    claude.output = empty
    assert prefill(other).json()["suggested"] == 0
    assert record(other, "boundary:entities")["display_state"] == "not_detected" and entity_rows(other) == []


def test_an_entity_without_percentages_is_stored_a_reviewer_can_correct_its_name_and_a_rerun_does_not_bring_it_back(
        claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(BOUNDARY_LINES)])
    empty: dict[str, Any] = {k: [] for k in GOOD}
    quote = "Café Québec Holdings Inc. is inside the boundary"
    claude.output = {**empty, "entities": [{"name": "Café Québec Holdings Inc.", "facilities": [], "equity_share_pct": None,
                                            "financial_control": None, "operational_control": "Yes", **cite("L2", quote)}]}
    assert prefill(eid).json()["suggested"] == 1
    [row] = entity_rows(eid)
    assert row["suggestion"]["value"] == {"name": "Café Québec Holdings Inc.", "facilities": [], "equity_share_pct": None,
                                          "financial_control": None, "included": "Yes"}  # Included; nothing was quoted about operational control
    corrected = {**row["suggestion"]["value"], "name": "Café Québec Holdings, Inc.", "included": "No"}
    edited = act(eid, row["field_id"], "edit", {"value": corrected})
    assert edited.status_code == 200 and edited.json()["decision"]["value"] == corrected  # name correctable; Yes / No stays
    assert act(eid, row["field_id"], "edit", {"value": {**corrected, "equity_share_pct": 140}}).status_code == 422
    assert act(eid, row["field_id"], "edit", {"value": {**corrected, "equity_share_pct": 80}}).status_code == 200
    assert prefill(eid).json()["suggested"] == 0  # the same entity under its old name is not added again
    assert len(entity_rows(eid)) == 1
    added = call("POST", f"{BASE}/{eid}/methodology-review/rows", "a_member", {"group": "entities"})
    assert added.status_code == 201 and added.json()["decision"]["value"]["equity_share_pct"] is None


def test_a_gwp_set_without_a_horizon_is_stored_with_its_note_and_can_be_accepted(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    lines = [(1, "Refrigerants use the AR6 100-year GWP by default."),
             (1, "Supplier factors (CEDA, DESNZ) embed AR5 values; Zürich data in tCO₂e.")]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(lines)])
    empty: dict[str, Any] = {k: [] for k in GOOD}
    claude.output = {**empty, "gwp": [
        {"set": "AR6", "horizon": "100-year", "applies_to": "by default", **cite("L1", "AR6 100-year GWP by default")},
        {"set": "AR5", "horizon": "Not stated", "applies_to": "embed AR5 values", **cite("L2", "embed AR5 values")}]}
    assert prefill(eid).json()["suggested"] == 2
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR6", "horizon": "100-year", "applies_to": "by default"}
    [row] = gwp_rows(eid)
    assert row["suggestion"]["value"] == {"set": "AR5", "horizon": "Not stated", "applies_to": "embed AR5 values"}
    assert row["suggestion"]["quote"] == "embed AR5 values"
    assert act(eid, row["field_id"], "accept").json()["decision"]["value"] == row["suggestion"]["value"]
    # a reviewer can edit the note and pick Not stated as the horizon
    edited = act(eid, "gwp", "edit", {"value": {"set": "AR6", "horizon": "Not stated", "applies_to": "Kältemittel"}})
    assert edited.status_code == 200 and edited.json()["decision"]["value"]["applies_to"] == "Kältemittel"
    # a document that names no set: nothing is suggested
    other = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(1, "Energy use is reported in MWh.")])])
    claude.output = empty
    assert prefill(other).json()["suggested"] == 0 and record(other, "gwp")["suggestion"] is None
    assert record(other, "gwp")["display_state"] == "not_detected"


def test_scopes_covered_is_stored_with_a_quote_per_scope_and_reads_not_detected_when_the_document_names_none(
        claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    lines = [(1, "Acme Foods asserts its Scope 1 and Scope 2 emissions for the year ended December 31, 2024."),
             (1, "Scope 3 is excluded from this statement.")]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(lines)])
    empty: dict[str, Any] = {k: [] for k in GOOD}
    pair = "Scope 1 and Scope 2 emissions"
    claude.output = {**empty, "selections": [
        {"field_id": "scopes:covered", "option": "Scope 1", "wording": "Scope 1", **cite("L1", pair)},
        {"field_id": "scopes:covered", "option": "Scope 2", "wording": "", **cite("L1", pair)},
        {"field_id": "scopes:covered", "option": "Scope 3", "wording": "", **cite("L2", "Scope 3 is excluded")}]}
    body = prefill(eid).json()
    assert body["suggested"] == 1 and body["dropped"] == {"negated": 1}
    scopes = record(eid, "scopes:covered")
    assert [v["option"] for v in scopes["suggestion"]["value"]] == ["Scope 1", "Scope 2"]
    assert [e["quote"] for e in scopes["suggestion"]["evidence"]] == [pair, pair]
    assert act(eid, "scopes:covered", "accept").json()["decision"]["value"] == scopes["suggestion"]["value"]
    # a document that names no scope: nothing is suggested and the row reads Not detected, never an invented value
    other = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(1, "Our report covers energy and water.")])])
    claude.output = empty
    assert prefill(other).json()["suggested"] == 0
    assert record(other, "scopes:covered")["suggestion"] is None and record(other, "scopes:covered")["display_state"] == "not_detected"
    assert act(other, "scopes:covered", "edit", {"value": [{"option": "Not stated", "wording": ""}]}).status_code == 200


# --- GWP: a set inside other factors is never the fixed field (the shape of the staging re-reads) ---------------

YUM_LINE = ("GHG emissions are calculated using the 100-year GWPs from the IPCC Fifth Assessment Report with the exception of "
            "when IEA Emission Factors are applied that use the IPCC Fourth Assessment Report.")
BANK_LINES = ["Where a GWP is not embedded in an emission factor, GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon.",
              "The DESNZ, CEDA and Ecoinvent factors embed GWPs from the IPCC Fifth Assessment Report (AR5)."]


def test_a_reply_with_only_the_set_inside_iea_factors_still_stores_the_default_in_the_field(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(3, YUM_LINE)])])
    # the exact reply shape of the staging re-read: only AR4, with its "inside IEA factors" note in the reply
    claude.output = {**{k: [] for k in GOOD}, "gwp": [
        {"set": "AR4", "horizon": "Not stated", "applies_to": "inside IEA factors", **cite("L1", "IEA Emission Factors are applied that use the IPCC Fourth Assessment Report")}]}
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR5", "horizon": "100-year"}  # read from the same sentence
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR4"]
    assert gwp_rows(eid)[0]["suggestion"]["value"]["applies_to"] == "inside IEA factors"


def test_the_default_is_found_in_the_document_around_the_quote_and_never_comes_from_the_embedded_set(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(4, t) for t in BANK_LINES])])
    claude.output = {**{k: [] for k in GOOD}, "gwp": [
        {"set": "AR5", "horizon": "Not stated", "applies_to": "inside CEDA factors", **cite("L2", "factors embed GWPs from the IPCC Fifth Assessment Report (AR5)")}]}
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"]["value"] == {"set": "AR6", "horizon": "100-year"}
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR5"]


def test_with_no_default_to_quote_the_field_stays_empty_and_the_embedded_set_is_a_row(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc([(4, BANK_LINES[1])])])
    claude.output = {**{k: [] for k in GOOD}, "gwp": [
        {"set": "AR5", "horizon": "Not stated", "applies_to": "inside CEDA factors", **cite("L1", "factors embed GWPs from the IPCC Fifth Assessment Report (AR5)")}]}
    assert prefill(eid).status_code == 200
    assert record(eid, "gwp")["suggestion"] is None and states(eid)["gwp"] == "not_detected"
    assert [r["suggestion"]["value"]["set"] for r in gwp_rows(eid)] == ["AR5"]


# --- a re-read replaces the rows the last read suggested, and keeps the ones a reviewer touched ---------------

SOURCES = [(2, "Emission factors: U.S. EPA GHG Emission Factors Hub, 2023 edition."),   # L9
           (2, "Electricity: EPA eGRID, 2022 edition."),                                  # L10
           (2, "Fuels: UK DESNZ conversion factors, 2021 edition."),                      # L11
           (2, "Refrigerants: IPCC Emission Factor Database, 2006 edition.")]             # L12
FACTOR = {
    "epa24": {"scope": "scope1", "database": "U.S. EPA GHG Emission Factors Hub", "edition": "2024", **cite("L6", "EPA GHG Emission Factors Hub, 2024 edition")},
    "epa23": {"scope": "scope1", "database": "U.S. EPA GHG Emission Factors Hub", "edition": "2023", **cite("L9", "EPA GHG Emission Factors Hub, 2023 edition")},
    "egrid": {"scope": "scope1", "database": "EPA eGRID", "edition": "2022", **cite("L10", "EPA eGRID, 2022 edition")},
    "desnz": {"scope": "scope1", "database": "UK DESNZ conversion factors", "edition": "2021", **cite("L11", "UK DESNZ conversion factors, 2021 edition")},
    "ipcc": {"scope": "scope1", "database": "IPCC Emission Factor Database", "edition": "2006", **cite("L12", "IPCC Emission Factor Database, 2006 edition")},
}


def factor_rows(engagement_id: str) -> dict[str, dict]:
    """The factor rows on the page, by the database and edition of the value (decision first, else suggestion)."""

    rows = [f for f in review(engagement_id).json()["fields"] if f["field_id"].startswith("factor:")]
    return {f"{v['database']} | {v['edition']}": f
            for f in rows for v in [((f["decision"] or {}).get("value") or (f["suggestion"] or {}).get("value"))]}


def read_factors(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch, eid: str, *keys: str) -> dict[str, Any]:
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + SOURCES)])
    claude.output = {**GOOD, "factors": [FACTOR[k] for k in keys]}
    response = prefill(eid)
    assert response.status_code == 200, response.text
    return response.json()


def last_event() -> dict[str, Any]:
    return json.loads(prefill_events()[-1]["metadata"])


def test_a_second_read_with_other_rows_replaces_the_first_reads_undecided_rows(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24", "egrid")
    first = factor_rows(eid)
    assert set(first) == {"U.S. EPA GHG Emission Factors Hub | 2024", "EPA eGRID | 2022"}
    read_factors(claude, monkeypatch, eid, "epa23", "desnz")
    assert set(factor_rows(eid)) == {"U.S. EPA GHG Emission Factors Hub | 2023", "UK DESNZ conversion factors | 2021"}
    assert last_event()["replaced_rows"] == 2
    read_factors(claude, monkeypatch, eid, "epa23", "desnz")  # a third read of the same answer changes nothing
    assert len(factor_rows(eid)) == 2 and last_event()["replaced_rows"] == 0


def test_a_row_the_read_suggests_again_keeps_its_id(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24", "egrid")
    kept = factor_rows(eid)["EPA eGRID | 2022"]["field_id"]
    read_factors(claude, monkeypatch, eid, "egrid", "desnz")
    rows = factor_rows(eid)
    assert set(rows) == {"EPA eGRID | 2022", "UK DESNZ conversion factors | 2021"}
    assert rows["EPA eGRID | 2022"]["field_id"] == kept and last_event()["replaced_rows"] == 1


def test_a_row_a_reviewer_accepted_edited_or_rejected_survives_a_read_that_does_not_suggest_it(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24", "egrid", "desnz", "ipcc")
    rows = factor_rows(eid)
    assert act(eid, rows["U.S. EPA GHG Emission Factors Hub | 2024"]["field_id"], "accept").status_code == 200
    assert act(eid, rows["EPA eGRID | 2022"]["field_id"], "edit",
               {"value": {"database": "EPA eGRID", "edition": "2023"}}).status_code == 200
    assert act(eid, rows["UK DESNZ conversion factors | 2021"]["field_id"], "reject", {"reason": "Not used"}).status_code == 200
    read_factors(claude, monkeypatch, eid, "epa23")
    after = factor_rows(eid)
    assert set(after) == {"U.S. EPA GHG Emission Factors Hub | 2024", "EPA eGRID | 2023",
                          "UK DESNZ conversion factors | 2021", "U.S. EPA GHG Emission Factors Hub | 2023"}
    # the row nobody touched is gone; the three a reviewer decided are the same records
    assert "IPCC Emission Factor Database | 2006" not in after
    assert last_event()["replaced_rows"] == 1
    assert after["EPA eGRID | 2023"]["field_id"] == rows["EPA eGRID | 2022"]["field_id"]
    assert after["UK DESNZ conversion factors | 2021"]["decision"]["status"] == "rejected"


def test_a_row_the_reviewer_added_survives_a_read(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24")
    added = call("POST", f"{BASE}/{eid}/methodology-review/rows", "a_member", {"group": "factor:scope1"}).json()["field"]["field_id"]
    assert act(eid, added, "edit", {"value": {"database": "Our own factors", "edition": "2020"}}).status_code == 200
    blank = call("POST", f"{BASE}/{eid}/methodology-review/rows", "a_member", {"group": "factor:scope2"}).json()["field"]["field_id"]
    read_factors(claude, monkeypatch, eid, "egrid")
    ids = {f["field_id"] for f in review(eid).json()["fields"]}
    assert added in ids and blank in ids  # even the blank pending row the reviewer has not filled in
    assert set(factor_rows(eid)) >= {"Our own factors | 2020", "EPA eGRID | 2022"}
    assert "U.S. EPA GHG Emission Factors Hub | 2024" not in factor_rows(eid)


def test_a_failed_section_does_not_remove_its_rows_but_the_others_are_replaced(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24", "egrid")
    assert [r["suggestion"]["value"]["name"] for r in entity_rows(eid)] == ["Acme Foods Kent LLC"]
    claude.fail_parts = ("FactorsPart",)  # the factors call is down: its rows are not judged
    claude.output = {**GOOD, "entities": [{**GOOD["entities"][0], "name": "Acme Foods Kent LLC"}], "factors": [FACTOR["desnz"]]}
    response = prefill(eid)
    assert response.status_code == 200 and [f["section"] for f in response.json()["failed_sections"]] == ["Emission factor sources and GWP"]
    assert set(factor_rows(eid)) == {"U.S. EPA GHG Emission Factors Hub | 2024", "EPA eGRID | 2022"}
    assert last_event()["replaced_rows"] == 0
    claude.fail_parts = ("BoundaryPart",)  # now the boundary call is down: the entity stays, the factors are replaced
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [doc(REPORT + SOURCES)])
    claude.output = {**GOOD, "factors": [FACTOR["desnz"]]}
    assert prefill(eid).status_code == 200
    assert set(factor_rows(eid)) == {"UK DESNZ conversion factors | 2021"} and len(entity_rows(eid)) == 1


def test_a_refused_read_removes_nothing_and_the_fixed_fields_are_replaced_as_before(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    read_factors(claude, monkeypatch, eid, "epa24", "egrid")
    claude.outcome = "refused"
    assert prefill(eid).status_code == 409
    assert set(factor_rows(eid)) == {"U.S. EPA GHG Emission Factors Hub | 2024", "EPA eGRID | 2022"}
    claude.outcome = "ok"
    claude.output = {**GOOD, "choices": [{"field_id": "category:scope1:stationary", "value": "No", **cite("L5", "stationary combustion is included")}],
                     "factors": [FACTOR["desnz"]]}
    assert prefill(eid).status_code == 200
    assert record(eid, "category:scope1:stationary")["suggestion"]["value"] == "No"  # a fixed field: replaced in place
    assert set(factor_rows(eid)) == {"UK DESNZ conversion factors | 2021"}
