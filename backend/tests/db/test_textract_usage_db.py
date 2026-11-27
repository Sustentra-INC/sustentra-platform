"""The Textract ledger on the real database (migration 0029, as ``app_user``): a row per call in its own
organization's scope, add-only, never visible to another organization, and counted with the AI's spend.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from backend.app.core.db import to_sync_url
from backend.app.services.textract_usage import DbScanLedger

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ENGINE = create_engine(to_sync_url(APP_URL)) if APP_URL else None
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000d4")
OTHER = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000d4")


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def orgs() -> None:
    asyncio.run(_admin("TRUNCATE textract_usage"))
    asyncio.run(_admin("TRUNCATE ai_usage"))
    asyncio.run(_admin("TRUNCATE users, organizations CASCADE"))
    asyncio.run(_admin("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'scan-acme'), "
                       "($2, 'Beta', 'scan-beta')", ORG, OTHER))


def _record(ledger: DbScanLedger, org: uuid.UUID, cost: int = 65_000, pages: int = 1) -> None:
    ledger.record(org_id=org, document_id="DOC-1", sha256="a" * 64, pages=pages, mode="forms_tables", ok=True,
                  cost_microusd=cost)


def test_the_month_spend_adds_the_ais_and_the_scans_of_that_org_only() -> None:
    ledger = DbScanLedger(ENGINE)
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'routing', 'm', 'anthropic', 'ok', 1000000)", ORG))
    _record(ledger, ORG)
    _record(ledger, OTHER, cost=9_000_000)
    assert ledger.month_spend_microusd(ORG) == 1_065_000
    assert ledger.month_spend_microusd(OTHER) == 9_000_000


def test_the_app_can_insert_but_never_update_or_delete_and_never_a_bad_row() -> None:
    ledger = DbScanLedger(ENGINE)
    _record(ledger, ORG)
    assert ENGINE is not None
    for statement in ("UPDATE textract_usage SET cost_microusd = 0", "DELETE FROM textract_usage"):
        with pytest.raises(DBAPIError), ENGINE.begin() as conn:
            conn.execute(text("SELECT set_config('app.is_provider', 'true', true)"))
            conn.execute(text(statement))
    for pages, cost in ((0, 0), (-1, 0), (1, -5)):
        with pytest.raises(DBAPIError):
            _record(ledger, ORG, cost=cost, pages=pages)


def test_the_month_spend_counts_the_pages_of_a_multi_page_row() -> None:
    ledger = DbScanLedger(ENGINE)
    asyncio.run(_admin("INSERT INTO ai_usage (org_id, feature, model, provider, outcome, cost_microusd) "
                       "VALUES ($1, 'routing', 'm', 'anthropic', 'ok', 2000000)", ORG))
    _record(ledger, ORG, pages=2, cost=130_000)
    assert ledger.month_spend_microusd(ORG) == 2_130_000
