"""Claude reading on the real ledger (migration 0017, as ``app_user``): each window's call is recorded
in its own organization's scope with feature ``extraction``, and the cap reads the real month spend
(Claude routing's and prefill's calls count too). A fake Claude; the document is in memory.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from backend.app.services.ai_extraction import AiExtraction
from backend.app.services.ai_routing import DbLedger
from backend.tests.services.test_ai_extraction import (
    BILL,
    ORG as ORG_TEXT,
    TARGETS,
    TYPE,
    FakeClaude,
    candidate,
    parsed,
    read,
    result,
    settings,
)

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG = uuid.UUID(ORG_TEXT)
OTHER = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000c4")
ENGAGEMENT = uuid.UUID("cccccccc-0000-0000-0000-0000000000c4")


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def orgs() -> None:
    asyncio.run(_admin("TRUNCATE ai_usage"))
    asyncio.run(_admin("TRUNCATE users, organizations CASCADE"))
    asyncio.run(_admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'read-acme'), "
                       "($2, 'Beta', 'read-beta')", ORG, OTHER))


def run(claude: FakeClaude, cap: float = 1.0, **over: Any) -> Any:
    chosen = settings(database_url=APP_URL, ai_monthly_cap_usd=cap, **over)
    service = AiExtraction(settings=chosen, client_factory=lambda s: claude, ledger=DbLedger(chosen, feature="extraction"))
    return service.assist(parser_output=parsed(BILL), extraction_result=result(candidate("account_number")),
                          extraction_targets=TARGETS, canonical_type_id=TYPE, file_name="f.pdf", org_id=ORG_TEXT,
                          engagement_id=str(ENGAGEMENT))


def ledger_rows() -> list[Any]:
    return asyncio.run(_admin("SELECT org_id, engagement_id, feature, provider, outcome, cost_microusd, created_by "
                              "FROM ai_usage"))


def test_each_window_is_recorded_for_its_organization_with_the_extraction_feature() -> None:
    claude = FakeClaude([read("account_number", "5521-8890", "Account Number 5521-8890", "L2")])
    outcome = run(claude, ai_window_pages=2)  # pages 1-2 and 2-3
    assert outcome.suggested == 1
    rows = ledger_rows()
    assert len(rows) == 2
    assert {(r["org_id"], r["engagement_id"], r["feature"], r["outcome"], r["created_by"]) for r in rows} == {
        (ORG, ENGAGEMENT, "extraction", "ok", None)}


def test_a_refused_window_is_recorded_too() -> None:
    assert run(FakeClaude(outcome="refused")).warnings[0].startswith("ai_unavailable")
    assert [r["outcome"] for r in ledger_rows()] == ["refused"]


def test_the_cap_reads_the_organizations_own_spend_across_features() -> None:
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'routing', 'm', 'anthropic', 'ok', 1000000)", ORG))
    claude = FakeClaude([])
    run(claude)
    assert claude.calls == []  # $1.00 spent of $1.00
    asyncio.run(_admin("TRUNCATE ai_usage"))
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'routing', 'm', 'anthropic', 'ok', 1000000)", OTHER))
    run(claude)
    assert len(claude.calls) == 1  # another organization's spend does not count
