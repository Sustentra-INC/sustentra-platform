"""Migration 0017 (s1_document_chunks, the waiting_on_chunks run status) up and down.

Runs alembic against TEST_DATABASE_URL and always leaves the database at head.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

BACKEND = Path(__file__).resolve().parents[2]
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000001717")
NEW = "0017_s1_document_chunks"


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


async def _fetch(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


def fetch(sql: str, *args: Any) -> list[Any]:
    return asyncio.run(_fetch(sql, *args))


def _state() -> tuple[bool, int]:
    table = bool(fetch("SELECT 1 FROM pg_class WHERE relname = 's1_document_chunks'"))
    functions = fetch("SELECT count(*) AS n FROM pg_proc WHERE proname IN "
                      "('claim_s1_document_chunk', 'requeue_expired_s1_document_chunks', 's1_wake_parent_run')")
    return table, int(functions[0]["n"])


def _active_index() -> str:
    return fetch("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_s1_processing_runs_active'")[0]["indexdef"]


def test_0017_down_and_up_returns_a_parked_run_to_the_queue() -> None:
    try:
        assert _state() == (True, 3)
        # At or past 0017: later migrations (0018 batches) sit on top of it.
        assert fetch("SELECT version_num FROM alembic_version")[0]["version_num"] in (NEW, "0018_s1_document_batches")
        fetch("TRUNCATE s1_processing_runs")
        fetch("TRUNCATE users, organizations CASCADE")
        fetch("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org', 'mig-0017')", ORG)
        fetch("INSERT INTO s1_processing_runs (run_id, org_id, engagement_id, document_id, requested_by, status) "
              "VALUES ('parked', $1, 'E', 'D', 'r', 'waiting_on_chunks')", ORG)

        alembic("downgrade", "0016")

        assert _state() == (False, 0)
        assert fetch("SELECT status FROM s1_processing_runs WHERE run_id = 'parked'")[0]["status"] == "queued"
        with pytest.raises(asyncpg.exceptions.CheckViolationError):  # the old status list is back
            fetch("UPDATE s1_processing_runs SET status = 'waiting_on_chunks'")
        assert "waiting_on_chunks" not in _active_index()

        alembic("upgrade", "head")

        assert _state() == (True, 3)
        fetch("UPDATE s1_processing_runs SET status = 'waiting_on_chunks'")  # the new status is allowed again
        assert "waiting_on_chunks" in _active_index()
    finally:
        alembic("upgrade", "head")
        fetch("TRUNCATE s1_processing_runs")
