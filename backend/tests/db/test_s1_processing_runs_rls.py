"""Migration 0015: the processing-run queue, isolated per organization by RLS, with the two
SECURITY DEFINER functions the reader process uses across organizations.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user), like
test_s1_stores_rls.py; skipped locally without them.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

ORG_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000015a1")
ORG_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000015b2")
FUNCTIONS = ("claim_s1_processing_run(text,integer)", "requeue_expired_s1_processing_runs()")


def run(fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
    return asyncio.run(fn(*args))


async def _insert(conn: Any, run_id: str, org: uuid.UUID, document_id: str, **columns: Any) -> None:
    names = ["run_id", "org_id", "engagement_id", "document_id", "requested_by", *columns]
    values = [run_id, org, "ENG-1", document_id, "reader@example.com", *columns.values()]
    placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
    await conn.execute(f"INSERT INTO s1_processing_runs ({', '.join(names)}) VALUES ({placeholders})", *values)


async def _admin(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _seed() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute("TRUNCATE users, organizations CASCADE")
        await conn.execute("TRUNCATE s1_processing_runs")
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 'runs-org-a'), ($2, 'Org B', 'runs-org-b')",
            ORG_A, ORG_B)
        await _insert(conn, "run-a", ORG_A, "DOC-A")
        await _insert(conn, "run-b", ORG_B, "DOC-B")
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def seeded() -> None:
    run(_seed)


async def _as_app(work: Callable[[Any], Awaitable[Any]], *, tenant: uuid.UUID | None = None,
                  provider: bool = False) -> Any:
    conn = await asyncpg.connect(APP_URL)
    try:
        async with conn.transaction():
            if tenant is not None:
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            if provider:
                await conn.execute("SELECT set_config('app.is_provider', 'true', true)")
            return await work(conn)
    finally:
        await conn.close()


def _as(work: Callable[[Any], Awaitable[Any]], **scope: Any) -> Any:
    return run(lambda: _as_app(work, **scope))


async def _run_ids(conn: Any) -> set[str]:
    return {row["run_id"] for row in await conn.fetch("SELECT run_id FROM s1_processing_runs")}


# --- RLS and grants -------------------------------------------------------------------------

def test_each_org_sees_only_its_own_runs_and_provider_sees_all() -> None:
    assert _as(_run_ids, tenant=ORG_A) == {"run-a"}
    assert _as(_run_ids, tenant=ORG_B) == {"run-b"}
    assert _as(_run_ids, provider=True) == {"run-a", "run-b"}
    assert _as(_run_ids) == set()  # no tenant context: nothing


def test_writes_are_held_to_the_callers_org_and_nothing_is_deleted() -> None:
    async def insert_for_b(conn: Any) -> None:
        await _insert(conn, "sneaky", ORG_B, "DOC-X")

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):  # RLS WITH CHECK
        _as(insert_for_b, tenant=ORG_A)

    async def insert_own(conn: Any) -> None:
        await _insert(conn, "mine", ORG_A, "DOC-X")

    _as(insert_own, tenant=ORG_A)
    assert "mine" in _as(_run_ids, tenant=ORG_A)

    async def update_other(conn: Any) -> str:
        return await conn.execute("UPDATE s1_processing_runs SET updated_at = now() WHERE org_id = $1", ORG_B)

    assert _as(update_other, tenant=ORG_A) == "UPDATE 0"

    async def move_to_other(conn: Any) -> None:
        await conn.execute("UPDATE s1_processing_runs SET org_id = $1 WHERE run_id = 'run-a'", ORG_B)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _as(move_to_other, tenant=ORG_A)

    async def delete_own(conn: Any) -> None:
        await conn.execute("DELETE FROM s1_processing_runs WHERE org_id = $1", ORG_A)

    with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
        _as(delete_own, tenant=ORG_A)


def test_rls_is_forced_and_the_functions_are_locked_down() -> None:
    flags = run(_admin, "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 's1_processing_runs'")
    assert flags[0]["relrowsecurity"] and flags[0]["relforcerowsecurity"]
    for signature in FUNCTIONS:
        rows = run(_admin,
                   "SELECT p.prosecdef, p.proconfig, p.proacl::text AS acl, "
                   "has_function_privilege('app_user', p.oid, 'EXECUTE') AS app_user_may "
                   "FROM pg_proc p WHERE p.oid = $1::regprocedure", signature)
        row = rows[0]
        assert row["prosecdef"], signature
        assert row["proconfig"] == ["search_path=public, pg_temp"], signature
        assert row["app_user_may"], signature
        assert "{=" not in row["acl"] and ",=" not in row["acl"], (signature, row["acl"])  # nothing for PUBLIC


# --- constraints ----------------------------------------------------------------------------

@pytest.mark.parametrize(("columns", "error"), [
    ({"status": "in_progress"}, "CheckViolationError"),  # a run being read has a reader and a lease
    ({"status": "failed"}, "CheckViolationError"),  # a failed run says why
    ({"status": "completed"}, "CheckViolationError"),  # a completed run names its pipeline run
    ({"status": "paused"}, "CheckViolationError"),
    ({"kind": "send_email"}, "CheckViolationError"),
    ({"attempts": -1}, "CheckViolationError"),
    ({"max_attempts": 0}, "CheckViolationError"),
])
def test_a_run_must_be_consistent(columns: dict[str, Any], error: str) -> None:
    async def insert(conn: Any) -> None:
        await _insert(conn, "bad", ORG_A, "DOC-NEW", **columns)

    with pytest.raises(getattr(asyncpg.exceptions, error)):
        _as(insert, tenant=ORG_A)


def test_params_must_be_an_object_and_org_is_required() -> None:
    async def array_params(conn: Any) -> None:
        await conn.execute("INSERT INTO s1_processing_runs (run_id, org_id, engagement_id, document_id, "
                           "requested_by, params) VALUES ('x', $1, 'E', 'D', 'r', '[]'::jsonb)", ORG_A)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        _as(array_params, tenant=ORG_A)

    async def no_org(conn: Any) -> None:
        await conn.execute("INSERT INTO s1_processing_runs (run_id, engagement_id, document_id, requested_by) "
                           "VALUES ('x', 'E', 'D', 'r')")

    with pytest.raises(asyncpg.exceptions.NotNullViolationError):
        _as(no_org, provider=True)


def test_one_active_run_per_document() -> None:
    async def second_active(conn: Any) -> None:
        await _insert(conn, "run-a2", ORG_A, "DOC-A")

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        _as(second_active, tenant=ORG_A)

    async def finish_then_requeue(conn: Any) -> set[str]:
        await conn.execute("UPDATE s1_processing_runs SET status = 'completed', pipeline_run_id = 'P-1' "
                           "WHERE run_id = 'run-a'")
        await _insert(conn, "run-a2", ORG_A, "DOC-A")  # the first one finished: room for the next
        return await _run_ids(conn)

    assert _as(finish_then_requeue, tenant=ORG_A) == {"run-a", "run-a2"}


# --- claim_s1_processing_run ----------------------------------------------------------------

async def _claim(conn: Any, worker: str = "worker:1", lease: int = 120) -> Any:
    return await conn.fetchrow("SELECT * FROM claim_s1_processing_run($1, $2)", worker, lease)


def test_claim_takes_the_oldest_due_run_across_orgs_without_a_tenant() -> None:
    run(_admin, "UPDATE s1_processing_runs SET created_at = now() - interval '1 minute' WHERE run_id = 'run-b'")
    run(_admin, "UPDATE s1_processing_runs SET run_after = now() + interval '1 hour' WHERE run_id = 'run-a'")

    async def work(conn: Any) -> tuple[Any, Any, set[str], str | None]:
        first = await _claim(conn)
        second = await _claim(conn)  # run-a is not due yet
        visible = await _run_ids(conn)
        setting = await conn.fetchval("SELECT current_setting('app.is_provider', true)")
        return first, second, visible, setting

    first, second, visible, setting = _as(work)
    assert first["run_id"] == "run-b" and first["org_id"] == ORG_B
    assert (first["status"], first["attempts"], first["worker_id"]) == ("in_progress", 1, "worker:1")
    assert first["lease_expires_at"] > first["started_at"]
    assert second is None
    assert visible == set()  # the caller itself still sees no organization's rows
    assert setting in ("", None)  # provider scope was the function's own


def test_claim_and_requeue_restore_the_callers_provider_setting() -> None:
    async def work(conn: Any) -> list[str]:
        seen = []
        for value in ("false", "true"):
            await conn.execute("SELECT set_config('app.is_provider', $1, true)", value)
            await conn.fetch("SELECT * FROM requeue_expired_s1_processing_runs()")
            seen.append(await conn.fetchval("SELECT current_setting('app.is_provider', true)"))
            await conn.execute("SELECT set_config('app.is_provider', $1, true)", value)
            await _claim(conn)
            seen.append(await conn.fetchval("SELECT current_setting('app.is_provider', true)"))
        return seen

    assert _as(work, tenant=ORG_A) == ["false", "false", "true", "true"]


def test_concurrent_claims_get_different_runs() -> None:
    async def work() -> tuple[str, str, Any]:
        one = await asyncpg.connect(APP_URL)
        two = await asyncpg.connect(APP_URL)
        try:
            first_tx = one.transaction()
            await first_tx.start()
            first = await _claim(one, "worker:one")  # its row stays locked until commit
            second_tx = two.transaction()
            await second_tx.start()
            second = await _claim(two, "worker:two")  # SKIP LOCKED: the next run, no waiting
            third = await _claim(two, "worker:two")
            await first_tx.commit()
            await second_tx.commit()
            return first["run_id"], second["run_id"], third
        finally:
            await one.close()
            await two.close()

    first, second, third = run(work)
    assert {first, second} == {"run-a", "run-b"}
    assert third is None


def test_claim_refuses_a_missing_worker_or_lease() -> None:
    for worker, lease in (("", 120), ("worker:1", 0)):
        async def work(conn: Any, worker: str = worker, lease: int = lease) -> None:
            await _claim(conn, worker, lease)

        with pytest.raises(asyncpg.exceptions.RaiseError):
            _as(work)


# --- requeue_expired_s1_processing_runs -----------------------------------------------------

def test_expired_leases_are_requeued_then_failed_as_timed_out() -> None:
    run(_admin, "UPDATE s1_processing_runs SET status = 'in_progress', worker_id = 'gone', attempts = 1, "
                "lease_expires_at = now() - interval '1 second' WHERE run_id = 'run-a'")
    run(_admin, "UPDATE s1_processing_runs SET status = 'in_progress', worker_id = 'gone', attempts = 3, "
                "lease_expires_at = now() - interval '1 second' WHERE run_id = 'run-b'")
    run(_admin, "INSERT INTO s1_processing_runs (run_id, org_id, engagement_id, document_id, requested_by, status, "
                "worker_id, attempts, lease_expires_at) VALUES ('run-live', $1, 'ENG-1', 'DOC-L', 'r', "
                "'in_progress', 'alive', 1, now() + interval '1 minute')", ORG_A)

    async def requeue(conn: Any) -> list[tuple[str, uuid.UUID, str, str]]:
        rows = await conn.fetch("SELECT * FROM requeue_expired_s1_processing_runs()")
        return sorted((r["run_id"], r["org_id"], r["document_id"], r["status"]) for r in rows)

    assert _as(requeue) == [("run-a", ORG_A, "DOC-A", "queued"), ("run-b", ORG_B, "DOC-B", "failed")]
    assert _as(requeue) == []

    rows = {r["run_id"]: r for r in run(_admin, "SELECT * FROM s1_processing_runs")}
    requeued, failed, live = rows["run-a"], rows["run-b"], rows["run-live"]
    assert (requeued["status"], requeued["worker_id"], requeued["lease_expires_at"]) == ("queued", None, None)
    assert requeued["attempts"] == 1 and requeued["completed_at"] is None
    assert (failed["status"], failed["error_code"], failed["worker_id"]) == ("failed", "timed_out", None)
    assert failed["error"] == "Reading stopped 3 times before it finished. Try again later, or upload a smaller file."
    assert failed["completed_at"] is not None
    assert (live["status"], live["worker_id"]) == ("in_progress", "alive")


def test_fenced_updates_from_a_reader_that_lost_the_run_change_nothing() -> None:
    async def claim(conn: Any) -> Any:
        return await _claim(conn, "worker:new")

    claimed = _as(claim)

    async def stale_finish(conn: Any) -> str:
        return await conn.execute(
            "UPDATE s1_processing_runs SET status = 'completed', pipeline_run_id = 'P-stale' "
            "WHERE run_id = $1 AND worker_id = 'worker:old' AND status = 'in_progress'", claimed["run_id"])

    assert _as(stale_finish, tenant=claimed["org_id"]) == "UPDATE 0"
