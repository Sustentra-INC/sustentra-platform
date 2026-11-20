"""MVP-139: line and placement changes as server actions, with a real audit trail.

Through the real app and Postgres (locks, one transaction, the audit table). Documents come from
the recalculation tests' FakeStore, plugged in where the app builds its tree service.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.app.api import evidence_tree as tree_api
from backend.app.core.rate_limit import limiter
from backend.app.services import workpaper_item_service
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.db.test_engagements import (
    A_ADMIN,
    A_MEMBER,
    BASE,
    ORG_A,
    _admin,
    _call,
    _seed,
    call,
)
from backend.tests.services.test_calculation_lines import _gas
from backend.tests.services.test_engagement_recalculation_service import FakeStore

KENT = {"facilityId": "F1", "name": "Kent Cannery"}
TACOMA = {"facilityId": "F2", "name": "Tacoma Works"}
GAS_KENT = "s1:stationary:natural-gas:f1"
GAS_TACOMA = "s1:stationary:natural-gas:f2"
PROPANE = {"category": "stationary", "level2_label": "Propane", "anchor_kind": "facility", "anchor_id": "F1",
           "label": "Propane at Kent"}
PROPANE_KEY = "s1:stationary:propane:f1"
UNASSIGNED = "supporting:unassigned"
SECRET = "SECRET-CLIENT-TEXT"


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    asyncio.run(_seed())


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(tree_api, "_service", lambda: EvidenceTreeService(fake, fake, fake))
    return fake


def make_engagement(store: FakeStore, facilities: list[dict] | None = None, docs: int = 0) -> str:
    body = {"name": "FY2024", "settings": {"facilities": facilities if facilities is not None else [KENT]}}
    response = call("POST", BASE, "a_member", body)
    assert response.status_code == 201, response.text
    engagement_id = response.json()["id"]
    for i in range(docs):
        add_gas(store, f"D{i}", engagement_id)
    return engagement_id


def add_gas(store: FakeStore, document_id: str, engagement_id: str, plant: str = "Kent Cannery") -> None:
    store.add_document(document_id, "CT-S1-FUELQTY", [_gas(plant=plant)], engagement_id=engagement_id,
                       org_id=str(ORG_A))
    store.documents[-1]["file_name"] = f"{SECRET}-{document_id}.pdf"


def path(engagement_id: str, tail: str) -> str:
    return f"{BASE}/{engagement_id}/{tail}"


def tree_lines(engagement_id: str, token: str = "a_member") -> dict[str, list[str]]:
    """line key (or 'supporting:unassigned') -> the documents filed there."""

    response = call("GET", path(engagement_id, "evidence-tree"), token)
    assert response.status_code == 200, response.text
    supporting = response.json()["blocks"]["supporting"]
    out: dict[str, list[str]] = {UNASSIGNED: [d["document_id"] for d in supporting["unassigned"]]}
    for scope in supporting["scopes"]:
        for category in scope["categories"]:
            for level2 in category["level2s"]:
                for entry in level2["lines"]:
                    out[entry["line"]["key"]] = [d["document_id"] for d in entry["documents"]]
    return out


def events(engagement_id: str) -> list[dict]:
    rows = asyncio.run(_admin(
        "SELECT event_type, actor_user_id, target_id, metadata, created_at FROM audit_logs "
        "WHERE target_type = 'engagement' AND target_id = $1 AND event_type LIKE 'evidence_%' "
        "ORDER BY created_at, id", engagement_id))
    return [{**dict(r), "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"]}
            for r in rows]


def create_line(engagement_id: str, token: str = "a_member", **changes: Any) -> Any:
    return call("POST", path(engagement_id, "evidence-lines"), token, {**PROPANE, **changes})


def move(engagement_id: str, document_id: str, source: str, target: str, token: str = "a_member") -> Any:
    return call("POST", path(engagement_id, f"documents/{document_id}/placements"), token,
                {"from": source, "to": target})


# --- lines -----------------------------------------------------------------------------------
def test_create_a_line_stamps_it_audits_it_and_shows_in_the_tree(store: FakeStore) -> None:
    engagement_id = make_engagement(store)
    created = create_line(engagement_id)
    assert created.status_code == 201, created.text
    line = created.json()["line"]
    assert line["key"] == PROPANE_KEY and line["created_by"] == str(A_MEMBER) and line["created_at"]
    assert created.json()["evidenceLines"] == [line]
    assert PROPANE_KEY in tree_lines(engagement_id)
    [event] = events(engagement_id)
    assert event["event_type"] == "evidence_line_created" and event["actor_user_id"] == A_MEMBER
    assert event["metadata"] == {"line_key": PROPANE_KEY, "label": "Propane at Kent", "level2_label": "Propane",
                                 "category": "stationary"}


def test_create_refuses_what_the_settings_check_refuses_and_a_duplicate(store: FakeStore) -> None:
    engagement_id = make_engagement(store)
    assert create_line(engagement_id, anchor_id="F9").status_code == 422
    assert create_line(engagement_id, level2_label="燃料").status_code == 422
    assert create_line(engagement_id, created_by=str(A_ADMIN)).status_code == 422  # not a field a client may send
    assert create_line(engagement_id).status_code == 201
    again = create_line(engagement_id)
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    assert create_line(make_engagement(store, facilities=[])).status_code == 422
    assert len(events(engagement_id)) == 1  # only the one that was saved


def test_a_system_line_cannot_be_created_renamed_or_deleted(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    clash = create_line(engagement_id, level2_label="Natural Gas", label="Gas at Kent")
    assert clash.status_code == 422 and "already creates" in clash.json()["detail"]
    assert call("PATCH", path(engagement_id, f"evidence-lines/{GAS_KENT}"), body={"label": "x"}).status_code == 422
    assert call("DELETE", path(engagement_id, f"evidence-lines/{GAS_KENT}")).status_code == 422
    assert events(engagement_id) == []


def test_rename_keeps_the_creator_and_logs_old_and_new_labels(store: FakeStore) -> None:
    engagement_id = make_engagement(store)
    created = create_line(engagement_id, label="Müller Käserei – Zürich").json()["line"]
    renamed = call("PATCH", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", {"label": "  燃料 tank  "})
    assert renamed.status_code == 200, renamed.text
    line = renamed.json()["line"]
    assert line["label"] == "燃料 tank" and line["created_by"] == created["created_by"]
    assert call("PATCH", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", {"label": "燃料 tank"}).status_code == 200
    assert call("PATCH", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", {"label": "  "}).status_code == 422
    assert call("PATCH", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", {"label": "x" * 121}).status_code == 422
    assert call("PATCH", path(engagement_id, "evidence-lines/s1:stationary:nope:f1"), "a_admin", {"label": "x"}).status_code == 404
    created_event, renamed_event = events(engagement_id)  # the unchanged re-save logged nothing
    assert renamed_event["event_type"] == "evidence_line_renamed" and renamed_event["actor_user_id"] == A_ADMIN
    assert renamed_event["metadata"] == {"line_key": PROPANE_KEY, "old_label": "Müller Käserei – Zürich",
                                         "new_label": "燃料 tank"}


def test_delete_moves_three_documents_to_unassigned_and_they_stay_when_the_line_comes_back(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=3)
    create_line(engagement_id)
    for i in range(3):
        assert move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY).status_code == 200
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0", "D1", "D2"]

    deleted = call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["documents_moved"] == 3 and deleted.json()["evidenceLines"] == []
    after = tree_lines(engagement_id)
    assert sorted(after[UNASSIGNED]) == ["D0", "D1", "D2"] and PROPANE_KEY not in after

    assert create_line(engagement_id).status_code == 201  # same key again
    again = tree_lines(engagement_id)
    assert sorted(again[UNASSIGNED]) == ["D0", "D1", "D2"] and again[PROPANE_KEY] == []
    last = events(engagement_id)[-2]
    assert last["event_type"] == "evidence_line_deleted"
    assert last["metadata"] == {"line_key": PROPANE_KEY, "label": "Propane at Kent", "documents_moved": 3}


def test_a_document_on_two_lines_loses_only_the_deleted_placement(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    store.add_document("TWO", "CT-S1-FUELQTY", [_gas(plant="Kent Cannery"), _gas(plant="Tacoma Works")],
                       engagement_id=engagement_id, org_id=str(ORG_A))
    create_line(engagement_id)
    assert tree_lines(engagement_id)[GAS_KENT] == ["TWO"] and tree_lines(engagement_id)[GAS_TACOMA] == ["TWO"]
    assert move(engagement_id, "TWO", GAS_KENT, PROPANE_KEY).status_code == 200
    assert call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).json()["documents_moved"] == 1
    lines = tree_lines(engagement_id)
    assert lines[GAS_TACOMA] == ["TWO"] and lines[UNASSIGNED] == ["TWO"] and lines[GAS_KENT] == []


def test_deleting_a_line_with_500_documents_is_all_or_nothing(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    engagement_id = make_engagement(store, docs=500)
    create_line(engagement_id)
    rows = [(engagement_id, f"D{i}", json.dumps({"documentId": f"D{i}", "note": "kept",
                                                 "placements": [{"from": GAS_KENT, "to": PROPANE_KEY}]}))
            for i in range(500)]
    asyncio.run(_admin("SELECT 1"))  # warm
    asyncio.run(_insert_documents(rows))
    assert len(tree_lines(engagement_id)[PROPANE_KEY]) == 500

    real = workpaper_item_service.save_item
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 300:
            raise RuntimeError("the database went away")
        return await real(*args, **kwargs)

    monkeypatch.setattr(workpaper_item_service, "save_item", flaky)
    with pytest.raises(RuntimeError):
        call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"))
    monkeypatch.setattr(workpaper_item_service, "save_item", real)
    after = tree_lines(engagement_id)
    assert len(after[PROPANE_KEY]) == 500 and after[UNASSIGNED] == []  # nothing moved, the line is still there
    assert [e["event_type"] for e in events(engagement_id)] == ["evidence_line_created"]

    deleted = call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"))
    assert deleted.status_code == 200 and deleted.json()["documents_moved"] == 500
    done = tree_lines(engagement_id)
    assert len(done[UNASSIGNED]) == 500
    kept = asyncio.run(_admin("SELECT payload FROM workpaper_items WHERE item_key = 'D7' AND kind = 'document'"))
    payload = kept[0]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert payload["note"] == "kept" and len(payload["placements"]) <= 2  # other keys kept, chain compacted


async def _insert_documents(rows: list[tuple[str, str, str]]) -> None:
    from backend.tests.db.test_engagements import asyncpg, ADMIN_URL

    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.executemany(
            "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload, created_by, updated_by) "
            "VALUES ($1, $2::uuid, 'document', $3, $4::jsonb, $5, $5)",
            [(ORG_A, e, k, p, A_MEMBER) for e, k, p in rows])
    finally:
        await conn.close()


# --- placements ------------------------------------------------------------------------------
def test_a_move_is_saved_audited_and_answers_the_payload(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    moved = move(engagement_id, "D0", GAS_KENT, PROPANE_KEY)
    assert moved.status_code == 200, moved.text
    assert moved.json()["payload"] == {"documentId": "D0", "placements": [{"from": GAS_KENT, "to": PROPANE_KEY}]}
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0"]
    event = events(engagement_id)[-1]
    assert event["event_type"] == "evidence_document_moved" and event["actor_user_id"] == A_MEMBER
    assert event["metadata"]["document_id"] == "D0" and event["metadata"]["from"] == GAS_KENT
    assert event["metadata"]["to_label"] == "Propane at Kent"


def test_a_stale_from_is_409_and_nothing_is_saved_or_logged(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    assert move(engagement_id, "D0", GAS_KENT, PROPANE_KEY).status_code == 200
    stale = move(engagement_id, "D0", GAS_KENT, UNASSIGNED)
    assert stale.status_code == 409 and "already moved" in stale.json()["detail"]
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0"]
    assert len([e for e in events(engagement_id) if e["event_type"] == "evidence_document_moved"]) == 1


def test_a_move_to_a_line_that_is_gone_or_to_where_it_is_or_for_an_unknown_document_is_refused(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    assert move(engagement_id, "D0", GAS_KENT, "s1:stationary:gone:f1").status_code == 422
    assert move(engagement_id, "D0", GAS_KENT, GAS_KENT).status_code == 422
    assert move(engagement_id, "NOPE", GAS_KENT, UNASSIGNED).status_code == 404
    assert move(engagement_id, "bad key!", GAS_KENT, UNASSIGNED).status_code == 404
    assert move(engagement_id, "D0", GAS_KENT, "block:unassigned").status_code == 200
    assert events(engagement_id)[0]["metadata"]["to_label"] == "Unassigned documents"


def test_moves_apply_in_order_and_the_chain_stays_short(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    create_line(engagement_id, level2_label="Diesel", label="Diesel at Kent")
    diesel = "s1:stationary:diesel:f1"
    for source, target in [(GAS_KENT, PROPANE_KEY), (PROPANE_KEY, diesel), (diesel, GAS_KENT), (GAS_KENT, PROPANE_KEY)]:
        assert move(engagement_id, "D0", source, target).status_code == 200
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0"]
    saved = asyncio.run(_admin("SELECT payload FROM workpaper_items WHERE item_key = 'D0'"))[0]["payload"]
    saved = json.loads(saved) if isinstance(saved, str) else saved
    assert len(saved["placements"]) == 1  # four moves, one effective placement


def test_two_simultaneous_moves_of_one_document_apply_one_after_the_other(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    create_line(engagement_id, level2_label="Diesel", label="Diesel at Kent")
    diesel = "s1:stationary:diesel:f1"

    async def both() -> list[Any]:
        return await asyncio.gather(
            _call("POST", path(engagement_id, "documents/D0/placements"), "a_member", {"from": GAS_KENT, "to": PROPANE_KEY}),
            _call("POST", path(engagement_id, "documents/D0/placements"), "a_admin", {"from": GAS_KENT, "to": diesel}))

    statuses = sorted(r.status_code for r in asyncio.run(both()))
    assert statuses == [200, 409]  # the second one finds the document already moved
    lines = tree_lines(engagement_id)
    assert sum(1 for key in (PROPANE_KEY, diesel) if lines[key] == ["D0"]) == 1
    assert len([e for e in events(engagement_id) if e["event_type"] == "evidence_document_moved"]) == 1


def test_simultaneous_creates_and_moves_of_different_things_all_survive(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)

    async def together() -> list[Any]:
        return await asyncio.gather(
            _call("POST", path(engagement_id, "evidence-lines"), "a_member", PROPANE),
            _call("POST", path(engagement_id, "evidence-lines"), "a_admin", {**PROPANE, "level2_label": "Diesel", "label": "Diesel"}),
            _call("POST", path(engagement_id, "evidence-lines"), "a_member", {**PROPANE, "level2_label": "Kerosene", "label": "Kerosene"}),
            _call("POST", path(engagement_id, "documents/D0/placements"), "a_admin", {"from": GAS_KENT, "to": UNASSIGNED}),
            _call("POST", path(engagement_id, "documents/D1/placements"), "a_member", {"from": GAS_KENT, "to": "block:unassigned"}))

    assert [r.status_code for r in asyncio.run(together())] == [201, 201, 201, 200, 200]
    keys = [line["key"] for line in call("GET", f"{BASE}/{engagement_id}").json()["settings"]["evidenceLines"]]
    assert sorted(keys) == sorted([PROPANE_KEY, "s1:stationary:diesel:f1", "s1:stationary:kerosene:f1"])
    assert len(events(engagement_id)) == 5


# --- who can, who cannot ----------------------------------------------------------------------
def test_another_org_gets_404_a_provider_cannot_write_and_an_archived_engagement_is_409(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    for method, tail, body in [("POST", "evidence-lines", PROPANE),
                               ("PATCH", f"evidence-lines/{PROPANE_KEY}", {"label": "x"}),
                               ("DELETE", f"evidence-lines/{PROPANE_KEY}", None),
                               ("POST", "documents/D0/placements", {"from": GAS_KENT, "to": UNASSIGNED}),
                               ("GET", "evidence-activity", None)]:
        assert call(method, path(engagement_id, tail), "b_member", body).status_code == 404, (method, tail)
    assert call("POST", path(engagement_id, "evidence-lines"), "provider", PROPANE).status_code == 403
    assert call("POST", path(engagement_id, "evidence-lines"), None, PROPANE).status_code == 401
    assert call("GET", path(engagement_id, "evidence-activity"), None).status_code == 401
    assert tree_lines(engagement_id)[GAS_KENT] == ["D0"] and len(events(engagement_id)) == 1
    assert call("PATCH", f"{BASE}/{engagement_id}", "a_member", {"status": "archived"}).status_code == 200
    for method, tail, body in [("POST", "evidence-lines", PROPANE),
                               ("PATCH", f"evidence-lines/{PROPANE_KEY}", {"label": "x"}),
                               ("DELETE", f"evidence-lines/{PROPANE_KEY}", None),
                               ("POST", "documents/D0/placements", {"from": GAS_KENT, "to": UNASSIGNED})]:
        assert call(method, path(engagement_id, tail), "a_member", body).status_code == 409, (method, tail)


# --- the log ------------------------------------------------------------------------------------
def test_the_log_is_newest_first_paged_named_and_readable_by_any_reader(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    asyncio.run(_admin("UPDATE users SET full_name = 'Müller Käserei' WHERE id = $1", A_MEMBER))
    create_line(engagement_id)
    call("PATCH", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", {"label": "Renamed"})
    move(engagement_id, "D0", GAS_KENT, PROPANE_KEY)
    call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin")

    first = call("GET", path(engagement_id, "evidence-activity?limit=3"), "a_member").json()
    assert [i["event_type"] for i in first["items"]] == ["evidence_line_deleted", "evidence_document_moved",
                                                         "evidence_line_renamed"]
    assert first["items"][0]["actor_name"] == "admin@acme.test" and first["items"][0]["documents_moved"] == 1
    assert first["items"][1]["from_label"] and first["items"][1]["document_id"] == "D0"
    assert first["items"][2]["old_label"] == "Propane at Kent" and first["items"][2]["new_label"] == "Renamed"
    assert first["next_cursor"]
    rest = call("GET", path(engagement_id, f"evidence-activity?limit=3&cursor={first['next_cursor']}"), "provider").json()
    assert [i["event_type"] for i in rest["items"]] == ["evidence_line_created"] and rest["next_cursor"] is None
    assert rest["items"][0]["actor_name"] == "Müller Käserei"
    assert call("GET", path(engagement_id, "evidence-activity?cursor=junk"), "a_member").status_code == 400
    assert call("GET", path(engagement_id, "evidence-activity?limit=0"), "a_member").status_code == 422


def test_no_document_text_reaches_any_audit_row(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    create_line(engagement_id)
    move(engagement_id, "D0", GAS_KENT, PROPANE_KEY)
    call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"))
    rows = asyncio.run(_admin("SELECT event_type, target_id, metadata::text AS m FROM audit_logs "
                              "WHERE event_type LIKE 'evidence_%'"))
    assert len(rows) == 3
    dump = json.dumps([dict(r) for r in rows])
    assert SECRET not in dump and "file_name" not in dump and ".pdf" not in dump
    allowed = {"line_key", "label", "level2_label", "category", "old_label", "new_label", "documents_moved",
               "document_id", "from", "to", "from_label", "to_label"}
    assert all(set(json.loads(r["m"])) <= allowed for r in rows)
    log = json.dumps(call("GET", path(engagement_id, "evidence-activity"), "a_member").json())
    assert SECRET not in log


def stored_payload(document_id: str) -> dict:
    row = asyncio.run(_admin("SELECT payload FROM workpaper_items WHERE kind = 'document' AND item_key = $1",
                             document_id))[0]["payload"]
    return json.loads(row) if isinstance(row, str) else row


def stored_lines(engagement_id: str) -> list[dict]:
    return call("GET", f"{BASE}/{engagement_id}").json()["settings"].get("evidenceLines") or []


# --- the old paths no longer change lines or placements (C1, C2) ---------------------------------
def test_a_settings_save_from_a_stale_tab_cannot_delete_rename_or_bring_back_a_line(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    stale_tab = stored_lines(engagement_id)  # what reviewer B loaded at 9:00: no lines
    create_line(engagement_id)
    assert move(engagement_id, "D0", GAS_KENT, PROPANE_KEY).status_code == 200
    before = stored_lines(engagement_id)
    assert len(before) == 1

    for sent in (stale_tab, [], [{**before[0], "label": "Stale rename"}], before + [{**before[0], "key": "x"}]):
        saved = call("PATCH", f"{BASE}/{engagement_id}", "a_admin",
                     {"settings": {"facilities": [KENT], "assuranceLevel": "Limited", "evidenceLines": sent}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["settings"]["assuranceLevel"] == "Limited"  # the other settings did save
        assert saved.json()["settings"]["evidenceLines"] == before  # and the lines are the server's
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0"]  # the document did not fall to Unassigned
    assert [e["event_type"] for e in events(engagement_id)] == ["evidence_line_created", "evidence_document_moved"]

    # a save without the key keeps the lines too, and one that never had lines gets none
    assert call("PATCH", f"{BASE}/{engagement_id}", "a_admin", {"settings": {"facilities": [KENT]}}).json()[
        "settings"]["evidenceLines"] == before
    plain = make_engagement(store)
    assert "evidenceLines" not in call("PATCH", f"{BASE}/{plain}", "a_admin", {"settings": {"facilities": [KENT]}}
                                       ).json()["settings"]
    # a broken copy is dropped, never a reason for the autosave to fail
    assert call("PATCH", f"{BASE}/{plain}", "a_admin", {"settings": {"evidenceLines": "junk"}}).status_code == 200
    # and creating an engagement with lines in its settings stores none
    made = call("POST", BASE, "a_member", {"name": "X", "settings": {"facilities": [KENT], "evidenceLines": before}})
    assert made.status_code == 201 and "evidenceLines" not in made.json()["settings"]


def test_a_document_save_from_a_stale_tab_cannot_undo_a_move_or_a_deletes_moves(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    stale = {"documentId": "D0", "facilityId": "F1", "placements": []}  # B's tab: loaded before the move
    assert move(engagement_id, "D0", GAS_KENT, PROPANE_KEY).status_code == 200
    put = call("PUT", path(engagement_id, "workpaper-items/document/D0"), "a_admin", {"payload": stale})
    assert put.status_code == 200, put.text
    assert put.json()["payload"]["facilityId"] == "F1"  # the other keys saved
    assert put.json()["payload"]["placements"] == [{"from": GAS_KENT, "to": PROPANE_KEY}]  # the move did not
    assert tree_lines(engagement_id)[PROPANE_KEY] == ["D0"]

    # a delete's moves to Unassigned survive a stale save too
    assert call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).status_code == 200
    call("PUT", path(engagement_id, "workpaper-items/document/D0"), "a_admin",
         {"payload": {**stale, "placements": [{"from": GAS_KENT, "to": PROPANE_KEY}]}})
    assert tree_lines(engagement_id)[UNASSIGNED] == ["D0"]
    # a first save of a document that has no stored item gets no placements from the client either
    first = call("PUT", path(engagement_id, "workpaper-items/document/NEW"), "a_member",
                 {"payload": {"documentId": "NEW", "placements": [{"from": "a", "to": "b"}], "note": "n"}})
    assert first.status_code == 200 and first.json()["payload"] == {"documentId": "NEW", "note": "n"}
    # the other kinds are untouched
    assert call("PUT", path(engagement_id, "workpaper-items/finding/F-1"), "a_member",
                {"payload": {"placements": [1]}}).json()["payload"] == {"placements": [1]}


def test_a_first_document_save_racing_a_first_move_does_not_fail_or_deadlock(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)

    async def both() -> list[Any]:
        return await asyncio.gather(
            _call("PUT", path(engagement_id, "workpaper-items/document/D0"), "a_admin",
                  {"payload": {"documentId": "D0", "facilityId": "F1"}}),
            _call("POST", path(engagement_id, "documents/D0/placements"), "a_member", {"from": GAS_KENT, "to": PROPANE_KEY}))

    results = asyncio.run(both())
    assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
    payload = stored_payload("D0")
    assert payload["facilityId"] == "F1" and payload["placements"] == [{"from": GAS_KENT, "to": PROPANE_KEY}]


# --- the delete answers with what it changed, and names what stops it ---------------------------
def test_delete_answers_with_the_changed_payloads_and_keeps_other_keys(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    create_line(engagement_id)
    call("PUT", path(engagement_id, "workpaper-items/document/D0"), "a_member", {"payload": {"documentId": "D0", "note": "mine"}})
    for i in range(2):
        move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY)
    answer = call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).json()
    assert sorted(answer["documents"]) == ["D0", "D1"] and answer["documents_moved"] == 2
    assert answer["documents"]["D0"] == stored_payload("D0")
    assert answer["documents"]["D0"]["note"] == "mine"
    assert answer["documents"]["D0"]["placements"] == [{"from": GAS_KENT, "to": UNASSIGNED}]


def test_a_withdrawn_document_moved_to_the_line_gets_its_move_out_and_is_not_counted(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    create_line(engagement_id)
    for i in range(2):
        assert move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY).status_code == 200
    assert call("PUT", path(engagement_id, "workpaper-items/document/D1"), "a_member",
                {"payload": {"documentId": "D1", "disposition": "withdrawn"}}).status_code == 200
    answer = call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).json()
    assert answer["documents_moved"] == 1 and sorted(answer["documents"]) == ["D0", "D1"]
    assert stored_payload("D1")["placements"] == [{"from": GAS_KENT, "to": UNASSIGNED}]
    assert stored_payload("D1")["disposition"] == "withdrawn"


def test_a_document_that_cannot_take_the_move_fails_the_whole_delete_by_name(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api import evidence_actions
    from backend.app.services import calculation_lines as cl

    engagement_id = make_engagement(store, docs=2)
    create_line(engagement_id)
    for i in range(2):
        move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY)
    monkeypatch.setattr(cl, "MAX_PLACEMENT_MOVES", 0)  # nothing can be saved: the first document fails
    response = call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}"))
    assert response.status_code == 409 and "D0.pdf" in response.json()["detail"] and SECRET in response.json()["detail"]
    monkeypatch.setattr(cl, "MAX_PLACEMENT_MOVES", 200)
    assert evidence_actions.cl.MAX_PLACEMENT_MOVES == 200
    assert len(tree_lines(engagement_id)[PROPANE_KEY]) == 2 and len(stored_lines(engagement_id)) == 1  # nothing changed
    assert call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).status_code == 200


# --- sentences for a line that another tab changed (M4) and labels (M5) -----------------------
def test_renaming_or_deleting_a_line_another_tab_already_deleted_says_so(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    create_line(engagement_id)
    assert call("DELETE", path(engagement_id, f"evidence-lines/{PROPANE_KEY}")).status_code == 200
    for method, body in (("PATCH", {"label": "x"}), ("DELETE", None)):
        gone = call(method, path(engagement_id, f"evidence-lines/{PROPANE_KEY}"), "a_admin", body)
        assert gone.status_code == 404 and gone.json()["detail"] == "This line was already deleted. Reload to see the current lines."
        system = call(method, path(engagement_id, f"evidence-lines/{GAS_KENT}"), "a_admin", body)
        assert system.status_code == 422 and "system creates this line" in system.json()["detail"]


def test_a_reviewer_line_that_the_system_now_creates_cannot_be_renamed_or_deleted(store: FakeStore) -> None:
    engagement_id = make_engagement(store)
    assert create_line(engagement_id, level2_label="Natural Gas", label="Gas at Kent").status_code == 201
    add_gas(store, "LATE", engagement_id)  # a document arrives: the system now creates this very line
    for method, body in (("PATCH", {"label": "x"}), ("DELETE", None)):
        clash = call(method, path(engagement_id, f"evidence-lines/{GAS_KENT}"), "a_member", body)
        assert clash.status_code == 409 and "now holds documents the system filed" in clash.json()["detail"]
    assert len(stored_lines(engagement_id)) == 1


def test_the_audit_labels_follow_the_pages_line_title_rule(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=1)
    assert move(engagement_id, "D0", GAS_KENT, UNASSIGNED).status_code == 200
    create_line(engagement_id)
    assert move(engagement_id, "D0", UNASSIGNED, GAS_KENT).status_code == 200
    first, second = [e["metadata"] for e in events(engagement_id) if e["event_type"] == "evidence_document_moved"]
    # a system line's label already names its fuel ("Natural Gas, Kent Cannery"): not "Natural Gas · Natural Gas, ..."
    assert first["from_label"] == "Natural Gas, Kent Cannery" and second["to_label"] == "Natural Gas, Kent Cannery"


# --- the activity log pages (M7) ----------------------------------------------------------------
def test_the_audit_log_has_an_index_for_one_engagements_events() -> None:
    rows = asyncio.run(_admin("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_audit_logs_target'"))
    assert rows and "target_id" in rows[0]["indexdef"] and "created_at DESC" in rows[0]["indexdef"]


# --- Claude's facility suggestion, confirmed by the reviewer (EXT-026) -------------------------------------------------
def add_unplaced(store: FakeStore, document_id: str, engagement_id: str, suggestion: dict | None) -> None:
    """A bill that names no facility (so it is unplaced), with Claude's suggestion stored with its result."""

    bill = {k: v for k, v in _gas().items() if k != "facility_name"}
    store.add_document(document_id, "CT-S1-FUELQTY", [bill], engagement_id=engagement_id, org_id=str(ORG_A))
    store.documents[-1]["file_name"] = f"{SECRET}-{document_id}.pdf"
    if suggestion:
        store.results[document_id][0]["facility_suggestion"] = suggestion


def doc_rows(engagement_id: str) -> dict[str, dict]:
    tree = call("GET", path(engagement_id, "evidence-tree"), "a_member").json()
    rows: dict[str, dict] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "document_id" in node and "facility_id" in node:
                rows[node["document_id"]] = node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    return rows


SUGGESTION = {"facility_id": "F2", "quote": "Tacoma Käserei 工場", "source": "line", "page_number": 2}


def test_a_suggestion_awaits_the_reviewer_then_one_click_places_it_and_the_audit_trail_shows_it(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    add_unplaced(store, "D0", engagement_id, SUGGESTION)
    row = doc_rows(engagement_id)["D0"]
    assert row["facility_id"] is None  # a suggestion is not a placement
    assert row["facility_suggestion"] == {"facility_id": "F2", "facility_name": "Tacoma Works",
                                           "quote": "Tacoma Käserei 工場", "where": "page 2", "label": "Suggested by Claude"}
    assert tree_lines(engagement_id)[GAS_TACOMA] == [] and tree_lines(engagement_id)[UNASSIGNED] == ["D0"]  # still unplaced

    placed = call("POST", path(engagement_id, "documents/D0/facility"), "a_member", {"facility_id": "F2"})
    assert placed.status_code == 200, placed.text
    assert placed.json()["payload"]["facilityId"] == "F2"
    assert tree_lines(engagement_id)[GAS_TACOMA] == ["D0"]  # the reviewer's own decision places it
    assert doc_rows(engagement_id)["D0"]["facility_suggestion"] is None  # nothing is left to decide

    [event] = [e for e in events(engagement_id) if e["event_type"] == "evidence_document_facility_set"]
    assert event["actor_user_id"] == A_MEMBER  # the actor is the session's
    assert event["metadata"] == {"document_id": "D0", "facility_id": "F2", "facility_name": "Tacoma Works", "suggested": True}
    assert SECRET not in json.dumps(event["metadata"]) and "Käserei" not in json.dumps(event["metadata"], ensure_ascii=False)
    log = call("GET", path(engagement_id, "evidence-activity"), "a_member").json()["items"]
    assert log[0]["event_type"] == "evidence_document_facility_set" and log[0]["facility_name"] == "Tacoma Works"
    assert log[0]["suggested"] is True and log[0]["actor_name"]


def test_choosing_another_facility_is_audited_as_not_the_suggestion(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    add_unplaced(store, "D0", engagement_id, SUGGESTION)
    assert call("POST", path(engagement_id, "documents/D0/facility"), "a_member", {"facility_id": "F1"}).status_code == 200
    assert tree_lines(engagement_id)[GAS_KENT] == ["D0"]
    [event] = [e for e in events(engagement_id) if e["event_type"] == "evidence_document_facility_set"]
    assert event["metadata"]["suggested"] is False


def test_a_facility_not_in_setup_a_missing_document_and_a_reader_are_refused(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    add_unplaced(store, "D0", engagement_id, SUGGESTION)
    url = path(engagement_id, "documents/D0/facility")
    assert call("POST", url, "a_member", {"facility_id": "F9"}).status_code == 422
    assert call("POST", url, "a_member", {"facility_id": "F2", "actor": "x"}).status_code == 422  # no extra keys
    assert call("POST", path(engagement_id, "documents/NOPE/facility"), "a_member", {"facility_id": "F2"}).status_code == 404
    assert call("POST", url, None, {"facility_id": "F2"}).status_code == 401
    assert [e for e in events(engagement_id) if e["event_type"] == "evidence_document_facility_set"] == []
    assert doc_rows(engagement_id)["D0"]["facility_suggestion"] is not None  # nothing changed


def test_a_suggestion_for_a_facility_that_left_setup_is_not_shown(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT])
    add_unplaced(store, "D0", engagement_id, SUGGESTION)  # F2 is not in this Setup
    assert doc_rows(engagement_id)["D0"]["facility_suggestion"] is None
