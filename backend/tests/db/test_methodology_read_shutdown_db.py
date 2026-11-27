"""The reviewer's methodology read on the background reader (MVP-237), through the real app and Postgres RLS: a
shutdown during a part records every call that came back and releases the claim; a read that lost its claim stops
without spending; the audit event names the person who started it and where from.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import pytest

from backend.app.api import methodology_review as api
from backend.app.core import db as core_db
from backend.app.services import auto_read
from backend.app.services import methodology_prefill as mp
from backend.tests.db.test_auto_read_db import claim_of, hold_claim
from backend.tests.db.test_engagements import (  # noqa: F401
    A_MEMBER, APP_URL, _admin, call, create, pytestmark, seeded)
from backend.tests.db.test_methodology_prefill_db import (  # noqa: F401
    ON, FakeClaude, _async_candidates, background_now, ledger, marker, prefill, start)
from backend.tests.services.test_ai_locator import _pdf_like
from backend.app.services.ai_locator import document_lines

# Two parts: 12 pages of about 20,000 characters (150,000 a part).
LONG = [(page, f"Narrative page {page} " + "text " * 4_000) for page in range(1, 13)]


def long_doc() -> mp.PrefillDocument:
    return mp.PrefillDocument("D1", "DOC-1", "report.pdf", document_lines(_pdf_like(LONG, "DOC-1")), False)


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    fake = FakeClaude()
    monkeypatch.setattr(api, "get_settings", lambda: ON)
    monkeypatch.setattr(api, "new_client", lambda settings: fake)
    monkeypatch.setattr(api, "_candidates", _async_candidates([{"document_id": "DOC-1", "file_name": "report.pdf"}]))
    monkeypatch.setattr(mp, "read_documents", lambda candidates, **kw: [long_doc()])
    monkeypatch.setattr(mp, "estimate_microusd", lambda *a, **k: 0)
    return fake


def test_a_shutdown_during_a_part_records_every_call_and_releases_the_claim(claude: FakeClaude,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    reader = auto_read.AutoReader()
    reader._engine = core_db.create_engine(APP_URL or "", pool_size=4, max_overflow=2)
    reader._sessions = core_db.build_sessionmaker(reader._engine)
    monkeypatch.setattr(auto_read, "_reader", reader)
    monkeypatch.setattr(api, "_start_background", reader.submit)
    in_flight = threading.Event()
    original = claude.structured

    def slow(**kw: Any) -> Any:
        in_flight.set()
        time.sleep(0.5)  # the first part's four calls are under way when the shutdown comes
        return original(**kw)

    monkeypatch.setattr(claude, "structured", slow)
    assert start(eid).json()["state"] == "started"
    assert in_flight.wait(10)
    reader.shutdown(drain_seconds=20)  # what the API's lifespan does on a deploy
    assert len(claude.calls) == 4  # the second part never started
    rows = ledger()
    assert len(rows) == 4 and all(r["outcome"] == "ok" for r in rows)  # every call that came back is recorded
    assert claim_of(eid) is None and eid not in api._RUNNING  # released
    found = marker(eid)
    assert found["state"] == "done" and [d["not_read"] for d in found["not_read"]] == ["pages 8–12"]
    assert found["not_read"][0]["note"].endswith(f"because {api.SHUTTING_DOWN}.")


def test_a_read_that_lost_its_claim_stops_without_spending(claude: FakeClaude, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = create()["id"]
    original = claude.structured
    taken = threading.Event()

    def take_over(**kw: Any) -> Any:
        if not taken.is_set():  # another process takes the claim (this read's heartbeat had stalled)
            taken.set()
            hold_claim(eid)
        return original(**kw)

    monkeypatch.setattr(claude, "structured", take_over)
    body = prefill(eid).json()
    assert len(claude.calls) == 4  # the first part only
    assert body["documents_read"][0]["note"].endswith(f"because {api.CLAIM_LOST}.")
    assert len(ledger()) == 4
    assert claim_of(eid)["by"] == "other"  # the other read's claim is left alone


def test_the_background_read_audits_the_person_who_started_it_and_where_from(claude: FakeClaude) -> None:
    eid = create()["id"]
    assert prefill(eid).status_code == 200
    rows = asyncio.run(_admin("SELECT actor_user_id, actor_role, ip_address::text AS ip, user_agent, request_id, "
                              "metadata::text AS metadata FROM audit_logs WHERE event_type = 'methodology_prefill'"))
    [event] = rows
    assert event["actor_user_id"] == A_MEMBER and event["actor_role"] == "org_member"
    assert event["ip"] and event["user_agent"]  # kept from the request, though the read ran after it answered
    meta = json.loads(event["metadata"])
    assert meta["outcome"] == "ok" and "automatic" not in meta and "actor" not in meta
