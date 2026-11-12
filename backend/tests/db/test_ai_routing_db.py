"""Claude routing on the real ledger (migration 0017, as ``app_user``): the call is recorded in
its own organization's scope with feature ``routing``, the cap reads the real month spend, and no
database connection is open while Claude answers. A fake Claude; the document is in memory.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest

from sqlalchemy import create_engine

from backend.app.core.config import Settings
from backend.app.core.db import to_sync_url
from backend.app.services.ai_routing import AiRouting, DbLedger
from backend.tests.services.test_ai_routing import ORG as ORG_TEXT
from backend.tests.services.test_ai_routing import FakeClaude, parsed, said

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ENGINE = create_engine(to_sync_url(APP_URL)) if APP_URL else None
ORG = uuid.UUID(ORG_TEXT)
OTHER = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000c3")
ENGAGEMENT = uuid.UUID("cccccccc-0000-0000-0000-0000000000c3")


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
    asyncio.run(_admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'route-acme'), "
                       "($2, 'Beta', 'route-beta')", ORG, OTHER))


def settings(cap: float = 1.0) -> Settings:
    return Settings(environment="test", git_sha="t", ALLOWED_ORIGINS="https://app.sustentra.test",  # type: ignore[call-arg]
                    ai_suggestions_enabled=True, ai_monthly_cap_usd=cap, database_url=APP_URL)


class WatchingClaude(FakeClaude):
    """Looks for a connection of the app in a transaction (or running a statement) while it
    'answers'. A pooled connection sitting idle is not held by anyone."""

    open_connections: list[int]

    def structured(self, **kwargs: Any) -> Any:
        rows = asyncio.run(_admin("SELECT count(*) AS n FROM pg_stat_activity WHERE usename = 'app_user' AND state <> 'idle'"))
        self.open_connections = [rows[0]["n"]]
        return super().structured(**kwargs)


def ask(claude: FakeClaude, cap: float = 1.0) -> Any:
    chosen = settings(cap)
    routing = AiRouting(settings=chosen, client_factory=lambda s: claude, ledger=DbLedger(ENGINE))
    return routing.suggest(parsed(), org_id=ORG_TEXT, engagement_id=str(ENGAGEMENT), has_targets=lambda t: True)


def ledger_rows() -> list[Any]:
    return asyncio.run(_admin("SELECT org_id, engagement_id, feature, provider, outcome, model, request_id, "
                              "input_tokens, output_tokens, cost_microusd, created_by FROM ai_usage"))


def test_a_call_is_recorded_for_its_organization_with_the_routing_feature() -> None:
    result = ask(WatchingClaude(said("CT-S1-REFRSVC", "Refrigerant charge log and top-up record")))
    assert result.status == "suggested" and result.canonical_type_id == "CT-S1-REFRSVC"
    (row,) = ledger_rows()
    assert (row["org_id"], row["engagement_id"], row["feature"], row["provider"], row["outcome"]) == (
        ORG, ENGAGEMENT, "routing", "anthropic", "ok")
    assert (row["input_tokens"], row["output_tokens"], row["cost_microusd"], row["request_id"]) == (900, 60, 4_000, "req-1")
    assert row["created_by"] is None


def test_a_refused_or_ignored_answer_is_recorded_too() -> None:
    assert ask(FakeClaude(outcome="refused")).status == "unavailable"
    assert ask(FakeClaude(said("CT-S1-REFRSVC", "A quote that is not on the document"))).status == "ignored"
    assert sorted(r["outcome"] for r in ledger_rows()) == ["ok", "refused"]


def test_no_connection_is_open_while_claude_answers() -> None:
    claude = WatchingClaude(said("none", "", ""))
    assert ask(claude).status == "none"
    assert claude.open_connections == [0]


def test_the_cap_reads_the_organizations_own_spend() -> None:
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'methodology_prefill', 'm', 'anthropic', 'ok', 1000000)", ORG))
    claude = FakeClaude(said("none", "", ""))
    assert ask(claude, cap=1.0).status == "off" and claude.calls == []  # $1.00 spent of $1.00
    asyncio.run(_admin("TRUNCATE ai_usage"))
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'methodology_prefill', 'm', 'anthropic', 'ok', 1000000)", OTHER))
    assert ask(claude, cap=1.0).status == "none" and len(claude.calls) == 1  # another organization's spend does not count
