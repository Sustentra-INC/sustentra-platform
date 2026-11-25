"""Migration 0025: review decisions are add-only for the application role.

app_user keeps SELECT and INSERT on s1_review_decisions and loses UPDATE, DELETE and TRUNCATE; a decision
and its audit event commit together. Needs TEST_DATABASE_URL (owner) and TEST_APP_DATABASE_URL (app_user);
skipped locally without them (CI sets both). The downgrade test runs alembic and always leaves head.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.repositories.review_repository import PostgresReviewDecisionRepository
from backend.app.repositories.s1_stores import MirroredRepository
from backend.app.services.review_decision_service import AuditContext, ReviewDecisionService

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

BACKEND = Path(__file__).resolve().parents[2]
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000002501")
OTHER = uuid.UUID("bbbbbbbb-0000-0000-0000-000000002502")
ACTOR = uuid.UUID("cccccccc-0000-0000-0000-000000002503")
PREVIOUS = "0024_org_auto_read_summaries"
TABLE = "s1_review_decisions"
DENIED = (ProgrammingError, DBAPIError)


@pytest.fixture(scope="module")
def engines() -> Iterator[tuple[Any, Any]]:
    admin = create_engine(to_sync_url(ADMIN_URL or ""), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL or ""), pool_size=2, max_overflow=0)
    try:
        yield admin, app
    finally:
        admin.dispose()
        app.dispose()


@pytest.fixture
def seeded(engines: tuple[Any, Any]) -> tuple[Any, Any]:
    admin, app = engines
    with admin.begin() as c:
        c.execute(text("TRUNCATE users, organizations CASCADE"))
        c.execute(text(f"TRUNCATE {TABLE}, audit_logs"))
        c.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'A', 'rd-a'), (:b, 'B', 'rd-b')"),
                  {"a": ORG, "b": OTHER})
    return admin, app


def _record(key: str, org: uuid.UUID = ORG, decision: str = "accepted") -> dict[str, Any]:
    return {
        "review_decision_id": key, "candidate_id": "candidate::EV-1::DOC-1::f", "evidence_id": "EV-1",
        "document_id": "DOC-1", "field_name": "f", "decision": decision, "reviewed_value": 5, "reviewed_unit": "kWh",
        "reviewer_id": "r@example.com", "reviewed_at": "2026-01-01T00:00:00+00:00", "reviewer_note": None,
        "candidate_snapshot": {}, "source_reference": {}, "org_id": str(org),
    }


def _as_app(app: Any, sql: str, **params: Any) -> Any:
    with app.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true), set_config('app.is_provider', 'false', true)"),
                  {"t": str(ORG)})
        return c.execute(text(sql), params)


def _insert_sql() -> str:
    return (f"INSERT INTO {TABLE} (org_id, review_decision_id, candidate_id, evidence_id, document_id, field_name, record) "
            "VALUES (:org, :id, 'c', 'EV-1', 'DOC-1', 'f', CAST(:rec AS jsonb))")


def _insert(app: Any, key: str) -> None:
    rec = {**_record(key), "candidate_id": "c"}
    _as_app(app, _insert_sql(), org=ORG, id=key, rec=json.dumps(rec))


def test_the_app_role_can_insert_and_select_but_not_update_delete_or_truncate(seeded: tuple[Any, Any]) -> None:
    admin, app = seeded
    _insert(app, "d1")
    assert [r.review_decision_id for r in _as_app(app, f"SELECT review_decision_id FROM {TABLE}")] == ["d1"]

    with admin.connect() as c:
        privileges = {p: c.execute(text("SELECT has_table_privilege('app_user', :t, :p)"), {"t": TABLE, "p": p}).scalar()
                      for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")}
    assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False}

    for sql in (f"UPDATE {TABLE} SET updated_at = now()",
                f"UPDATE {TABLE} SET record = '{{}}'::jsonb WHERE review_decision_id = 'd1'",
                f"DELETE FROM {TABLE}",
                f"TRUNCATE {TABLE}",
                # ON CONFLICT DO UPDATE needs UPDATE even when nothing conflicts
                _insert_sql() + " ON CONFLICT (legacy_key) DO UPDATE SET updated_at = now()",
                f"SELECT 1 FROM {TABLE} FOR UPDATE"):
        with pytest.raises(DENIED, match="permission denied"):
            _as_app(app, sql, org=ORG, id="x", rec=json.dumps(_record("x")))
    assert [r.review_decision_id for r in _as_app(app, f"SELECT review_decision_id FROM {TABLE}")] == ["d1"]


def test_no_policy_allows_update_or_delete_and_nothing_cascades_into_the_table(seeded: tuple[Any, Any]) -> None:
    admin, _app = seeded
    with admin.connect() as c:
        policies = {r.policyname: r.cmd for r in c.execute(
            text("SELECT policyname, cmd FROM pg_policies WHERE tablename = :t"), {"t": TABLE})}
        assert sorted(policies.values()) == ["INSERT", "SELECT"]
        # the only foreign key is org_id -> organizations ON DELETE RESTRICT; no table references this one
        out = c.execute(text("SELECT confrelid::regclass::text AS ref, confdeltype FROM pg_constraint "
                             "WHERE contype = 'f' AND conrelid = CAST(:t AS regclass)"), {"t": TABLE}).all()
        assert [(r.ref, r.confdeltype) for r in out] == [("organizations", "r")]
        referencing = c.execute(text("SELECT count(*) FROM pg_constraint WHERE contype = 'f' "
                                     "AND confrelid = CAST(:t AS regclass)"), {"t": TABLE}).scalar()
        assert referencing == 0


def test_a_decision_and_its_audit_event_commit_together(seeded: tuple[Any, Any]) -> None:
    admin, app = seeded
    repository = PostgresReviewDecisionRepository(app)
    context = AuditContext(org_id=str(ORG), actor_user_id=None, actor_role="org_member", engagement_id="ENG-1",
                           pipeline_run_id="RUN-1")
    service = ReviewDecisionService(repository=repository)
    candidate = {"candidate_id": "candidate::EV-1::DOC-1::f", "evidence_id": "EV-1", "document_id": "DOC-1",
                 "field_name": "f", "display_label": "F", "raw_value": "5", "normalized_value": 5, "unit": "kWh",
                 "confidence": 1, "source_reference": {}, "validation_flags": []}
    with scoped(S1Scope.tenant(ORG)):
        saved = service.submit_decision(candidate, "accepted", "r@example.com", org_id=str(ORG), audit=context)
    with admin.connect() as c:
        events = c.execute(text("SELECT event_type, target_type, target_id, metadata FROM audit_logs "
                                "WHERE event_type LIKE 'review_value_%'")).all()
        assert [(e.event_type, e.target_type, e.target_id) for e in events] == [
            ("review_value_accepted", "engagement", "ENG-1")]
        assert events[0].metadata["review_decision_id"] == saved["review_decision_id"]
        assert "5" not in {str(v) for v in events[0].metadata.values()} and "kWh" not in str(events[0].metadata)
        assert c.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() == 1


def test_a_failing_audit_insert_rolls_the_decision_back(seeded: tuple[Any, Any]) -> None:
    admin, app = seeded
    repository = PostgresReviewDecisionRepository(app)
    bad = {"event_type": "NOT A VALID TYPE", "org_id": str(ORG), "actor_user_id": None, "actor_role": None}
    with scoped(S1Scope.tenant(ORG)), pytest.raises(DBAPIError):
        repository.save(_record("lost"), audit=bad)
    with admin.connect() as c:
        assert c.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM audit_logs WHERE event_type = 'NOT A VALID TYPE'")).scalar() == 0


def test_the_mirrored_store_writes_the_event_in_postgres_then_the_file(seeded: tuple[Any, Any], tmp_path: Path) -> None:
    from backend.app.repositories.review_repository import JsonlReviewDecisionRepository

    admin, app = seeded
    mirror = JsonlReviewDecisionRepository(tmp_path / "d.jsonl")
    repository = MirroredRepository(PostgresReviewDecisionRepository(app), mirror)
    event = {"event_type": "review_value_accepted", "org_id": str(ORG), "actor_user_id": None, "actor_role": None}
    with scoped(S1Scope.tenant(ORG)):
        repository.save(_record("m1"), audit=event)
    assert [r["review_decision_id"] for r in mirror.list_all()] == ["m1"]
    with admin.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_logs WHERE event_type = 'review_value_accepted'")).scalar() == 1


def test_the_previous_app_version_still_works_against_the_new_schema(seeded: tuple[Any, Any]) -> None:
    """The old release only inserts (plain INSERT) and selects on this table, one short transaction each."""
    _admin, app = seeded
    repository = PostgresReviewDecisionRepository(app)
    with scoped(S1Scope.tenant(ORG)):
        repository.save(_record("old1"))  # no audit argument, as the old code calls it
        repository.save(_record("old2", decision="edited"))
        assert repository.get_latest_by_candidate("candidate::EV-1::DOC-1::f")["review_decision_id"] == "old2"
        assert len(repository.list_by_document("DOC-1")) == 2


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_downgrade_restores_the_old_grants_and_upgrade_removes_them_again(seeded: tuple[Any, Any]) -> None:
    admin, app = seeded
    _insert(app, "d1")
    try:
        _alembic("downgrade", PREVIOUS)
        _as_app(app, f"UPDATE {TABLE} SET updated_at = now()")  # allowed again, as after 0013
        with pytest.raises(DENIED, match="permission denied"):
            _as_app(app, f"DELETE FROM {TABLE}")  # never granted
        with admin.connect() as c:
            assert [r.cmd for r in c.execute(text("SELECT cmd FROM pg_policies WHERE tablename = :t"), {"t": TABLE})] \
                == ["ALL"]
    finally:
        _alembic("upgrade", "head")
    with pytest.raises(DENIED, match="permission denied"):
        _as_app(app, f"UPDATE {TABLE} SET updated_at = now()")
    assert [r.review_decision_id for r in _as_app(app, f"SELECT review_decision_id FROM {TABLE}")] == ["d1"]
