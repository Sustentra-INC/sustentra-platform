"""Methodology review: history and size limits, the row cap, record-owned user_added, the
generic list and saving a suggestion under a row lock. Real app and Postgres RLS."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

from backend.app.core import db as core_db
from backend.app.services import methodology_review as rules
from backend.tests.db.test_engagements import (  # noqa: F401 - `seeded` is an autouse fixture
    A_MEMBER,
    APP_URL,
    BASE,
    ORG_A,
    _admin,
    call,
    create,
    pytestmark,
    seeded,
)
from backend.tests.db.test_methodology_review import SUGGESTION, act, add_row, events, record, review, suggest


def insert_row(engagement_id: str, key: str, payload: dict[str, Any]) -> None:
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', $2, $3::jsonb FROM engagements WHERE id = $1::uuid",
        engagement_id, key, json.dumps(payload)))


def test_a_field_edited_many_times_with_long_non_ascii_text_can_still_be_changed() -> None:
    eid = create()["id"]
    suggest(eid, "calculation:approach", {**SUGGESTION, "value": "é" * 2000, "quote": "语" * 1000})
    for n in range(20):
        edited = act(eid, "calculation:approach", "edit", {"value": chr(0x4E00 + n) * 2000})  # 3 bytes each
        assert edited.status_code == 200, (n, edited.text)
    after = record(eid, "calculation:approach")
    assert len(after["history"]) <= 50 and all("from" not in h for h in after["history"])
    assert act(eid, "calculation:approach", "revert").status_code == 200
    assert act(eid, "calculation:approach", "edit", {"value": "short"}).status_code == 200
    assert act(eid, "calculation:approach", "edit", {"value": "a\x00b"}).status_code == 422


def test_history_keeps_the_newest_50_events_and_the_audit_log_keeps_all() -> None:
    eid = create()["id"]
    for n in range(30):
        assert act(eid, "reporting_period", "edit", {"value": f"p{n}"}).status_code == 200
        assert act(eid, "reporting_period", "revert").status_code == 200
    history = record(eid, "reporting_period")["history"]
    assert len(history) == 50 and history[-1]["action"] == "revert"
    assert len(events()) == 60


def test_the_catalog_def_takes_user_added_from_the_record() -> None:
    eid = create()["id"]
    key = "entity:abcd12345678"
    insert_row(eid, key, {"field_id": key, "suggestion": None, "decision": None, "history": [],
                          "user_added": False})
    body = review(eid).json()
    assert next(c for c in body["catalog"] if c["field_id"] == key)["user_added"] is False
    assert next(f for f in body["fields"] if f["field_id"] == key)["user_added"] is False
    assert call("DELETE", f"{BASE}/{eid}/methodology-review/{key}").status_code == 409


def test_the_generic_list_filters_removed_rows_and_uses_the_review_shape() -> None:
    eid = create()["id"]
    act(eid, "reporting_period", "edit", {"value": "2025"})
    gone = add_row(eid).json()["field_id"]
    kept = add_row(eid, "factor:scope1").json()["field_id"]
    call("DELETE", f"{BASE}/{eid}/methodology-review/{gone}")
    items = call("GET", f"{BASE}/{eid}/workpaper-items?kind=methodology").json()["items"]
    assert sorted(i["item_key"] for i in items) == sorted(["reporting_period", kept])
    assert all(set(i["payload"]) == {"field_id", "suggestion", "decision", "history", "user_added"} for i in items)


def test_reverting_a_reviewer_added_row_restores_its_blank_value() -> None:
    eid = create()["id"]
    key = add_row(eid, "factor:scope1").json()["field_id"]
    act(eid, key, "edit", {"value": {"database": "EPA", "edition": "2025"}})
    reverted = act(eid, key, "revert").json()
    assert reverted["decision"]["status"] == "pending"
    assert reverted["decision"]["value"] == {"database": "", "edition": ""}


def test_at_most_200_rows_can_be_added() -> None:
    eid = create()["id"]
    asyncio.run(_admin(
        "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
        "SELECT org_id, id, 'methodology', 'entity:seed' || n, "
        "jsonb_build_object('field_id', 'entity:seed' || n, 'user_added', true, 'history', '[]'::jsonb) "
        "FROM engagements, generate_series(1, 200) AS n WHERE id = $1::uuid", eid))
    refused = add_row(eid)
    assert refused.status_code == 409 and "200" in refused.json()["detail"]


async def _save(engagement_id: str, field_id: str, value: Any) -> Any:
    engine = core_db.create_engine(APP_URL or "", pool_size=2, max_overflow=0)
    try:
        async with core_db.build_sessionmaker(engine)() as session, session.begin():
            await core_db.set_tenant(session, ORG_A)
            return await rules.save_suggestion(
                session, org_id=ORG_A, engagement_id=uuid.UUID(engagement_id), field_id=field_id,
                suggestion={**SUGGESTION, "value": value}, user_id=A_MEMBER)
    finally:
        await engine.dispose()


def test_save_suggestion_changes_only_the_suggestion_under_a_row_lock() -> None:
    eid = create()["id"]
    act(eid, "consolidation_approach", "edit", {"value": "Equity Share"})
    saved = asyncio.run(_save(eid, "consolidation_approach", "Operational Control"))
    assert saved["suggestion"]["value"] == "Operational Control"
    assert saved["decision"]["value"] == "Equity Share" and len(saved["history"]) == 1
    assert record(eid, "consolidation_approach")["suggestion"]["value"] == "Operational Control"
    fresh = asyncio.run(_save(eid, "category:scope1:mobile", "Yes"))  # a fixed field with no row yet
    assert fresh["decision"] is None and fresh["suggestion"]["value"] == "Yes"
    assert asyncio.run(_save(eid, "no_such_field", "x")) is None
    assert asyncio.run(_save(eid, "entity:abcd1234", "x")) is None  # a row that was never added
    with pytest.raises(rules.MethodologyInvalid):
        asyncio.run(_save(eid, "category:scope1:process", "Maybe"))
