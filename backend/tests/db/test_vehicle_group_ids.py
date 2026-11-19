"""S1-BE-012: vehicle groups carry a stable group_id.

Through the real app and Postgres: ids on create and save, a hand-placed document staying on its group's
line through a rename, a removal and a reorder, and migration 0021 on stored engagements (with RLS).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.app.api import evidence_tree as tree_api
from backend.app.core.rate_limit import limiter
from backend.app.services.calculation_lines import GROUP_ID, legacy_group_anchors
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.db.test_engagements import ADMIN_URL, BASE, ORG_A, _admin, _seed, asyncpg, call
from backend.tests.services.test_calculation_lines import _group, _mobile
from backend.tests.services.test_engagement_recalculation_service import FakeStore

KENT = {"facilityId": "F1", "name": "Kent Cannery"}
UNASSIGNED = "supporting:unassigned"


@pytest.fixture(autouse=True)
def seeded() -> None:
    limiter.reset()
    asyncio.run(_seed())


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(tree_api, "_service", lambda: EvidenceTreeService(fake, fake, fake))
    return fake


def make(groups: list[dict], token: str = "a_member") -> dict:
    body = {"name": "FY2025", "settings": {"facilities": [KENT], "recalculation": {"vehicle_groups": groups}}}
    response = call("POST", BASE, token, body)
    assert response.status_code == 201, response.text
    return response.json()


def groups_of(engagement_id: str) -> list[dict]:
    return call("GET", f"{BASE}/{engagement_id}").json()["settings"]["recalculation"]["vehicle_groups"]


def save(engagement_id: str, groups: list[dict], token: str = "a_member", **more: Any) -> Any:
    return call("PATCH", f"{BASE}/{engagement_id}", token,
                {"settings": {"facilities": [KENT], "recalculation": {**more, "vehicle_groups": groups}}})


def ids(groups: list[dict]) -> list[str]:
    return [g["group_id"] for g in groups]


# --- ids on create and save ------------------------------------------------------------------------------
def test_a_new_engagement_gives_every_group_an_id() -> None:
    created = make([_group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "配送トラック"),
                    _group("Diesel Fuel", "Lieferwagen – Zürich")])
    given = ids(created["settings"]["recalculation"]["vehicle_groups"])
    assert len(set(given)) == 3 and all(GROUP_ID.match(i) for i in given)
    assert ids(groups_of(created["id"])) == given  # what is stored is what was answered


def test_a_save_keeps_ids_through_rename_reorder_and_removal_and_never_trusts_a_forged_one() -> None:
    created = make([_group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "Trucks"), _group("Motor Gasoline", "Pickups")])
    a, b, c = stored = groups_of(created["id"])
    assert save(created["id"], [{**a, "label": "Delivery 配送"}, b, c]).status_code == 200
    assert ids(groups_of(created["id"])) == [a["group_id"], b["group_id"], c["group_id"]]
    assert groups_of(created["id"])[0]["label"] == "Delivery 配送"
    save(created["id"], [c, a, b])
    assert ids(groups_of(created["id"])) == [c["group_id"], a["group_id"], b["group_id"]]
    save(created["id"], [c, b])  # a removed
    assert ids(groups_of(created["id"])) == [c["group_id"], b["group_id"]]
    # a group added again is a new group; an id the engagement never had is replaced; a malformed id is a 422
    forged = {**_group("Diesel Fuel", "Trucks"), "group_id": "vg-forgedforged"}
    save(created["id"], [c, b, forged])
    final = groups_of(created["id"])
    assert final[2]["group_id"] not in ("vg-forgedforged", a["group_id"]) and GROUP_ID.match(final[2]["group_id"])
    assert save(created["id"], [{**c, "group_id": "Not A Valid Id!"}]).status_code == 422
    assert save(created["id"], [c, c]).status_code == 422  # one id twice
    assert ids(groups_of(created["id"])) == ids(final)  # nothing changed by the refused saves
    assert stored[0]["group_id"] == a["group_id"]


def test_a_client_that_sends_no_ids_keeps_the_groups_it_did_not_change() -> None:
    created = make([_group("Diesel Fuel", "Trucks"), _group("Motor Gasoline", "Pickups")])
    before = groups_of(created["id"])
    bare = [{k: v for k, v in g.items() if k != "group_id"} for g in before]
    assert save(created["id"], bare[::-1]).status_code == 200
    assert ids(groups_of(created["id"])) == ids(before[::-1])


# --- a document placed by hand stays on its group's line ---------------------------------------------------
def test_a_hand_placed_document_stays_on_its_groups_line_and_the_audit_names_it(store: FakeStore) -> None:
    created = make([_group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "Trucks"), _group("Diesel Fuel", "配送トラック")])
    engagement_id = created["id"]
    a, b, c = groups_of(engagement_id)
    store.add_document("M1", "CT-S1-MOBFUEL", [_mobile()], engagement_id=engagement_id, org_id=str(ORG_A))
    line = f"s1:mobile:diesel-fuel:{c['group_id']}"

    def filed() -> dict[str, list[str]]:
        supporting = call("GET", f"{BASE}/{engagement_id}/evidence-tree").json()["blocks"]["supporting"]
        out = {UNASSIGNED: [d["document_id"] for d in supporting["unassigned"]]}
        for scope in supporting["scopes"]:
            for category in scope["categories"]:
                for level2 in category["level2s"]:
                    for entry in level2["lines"]:
                        out[entry["line"]["key"]] = [d["document_id"] for d in entry["documents"]]
        return out

    assert filed()[UNASSIGNED] == ["M1"]  # three groups use the fuel: no default line
    moved = call("POST", f"{BASE}/{engagement_id}/documents/M1/placements", "a_member", {"from": UNASSIGNED, "to": line})
    assert moved.status_code == 200, moved.text
    assert filed()[line] == ["M1"]

    for step, groups in [("renamed", [a, b, {**c, "label": "Renamed 運搬車"}]), ("first removed", [b, c]),
                         ("reordered", [c, b]), ("other edited", [{**b, "model_year": 2020}, c])]:
        assert save(engagement_id, groups).status_code == 200, step
        assert filed()[line] == ["M1"], step
        assert ids(groups_of(engagement_id))[ids(groups_of(engagement_id)).index(c["group_id"])] == c["group_id"]
    labels = {ln["key"]: ln["label"] for ln in call("GET", f"{BASE}/{engagement_id}/evidence-tree").json()["lines"]}
    assert labels[line].endswith("配送トラック")  # the last save sent the group's original name back: same line, its name

    rows = asyncio.run(_admin("SELECT metadata FROM audit_logs WHERE event_type = 'evidence_document_moved'"))
    meta = rows[0]["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else meta
    assert meta["to"] == line and meta["to_label"].endswith("配送トラック")  # the key carries the id, the label the name then


# --- migration 0021 on stored engagements -----------------------------------------------------------------------
BACKEND = Path(__file__).resolve().parents[2]
LEGACY = [_group("Diesel Fuel", "配送トラック"), _group("Diesel Fuel", "配送トラック"),
          _group("Diesel Fuel", "Lieferwagen – Zürich"), _group("Motor Gasoline", "Pickups")]


def alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": ADMIN_URL or ""}
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


async def _insert(settings: dict, placements: list[dict]) -> str:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        engagement = await conn.fetchval(
            "INSERT INTO engagements (org_id, name, settings) VALUES ($1, 'Legacy', $2::jsonb) RETURNING id",
            ORG_A, json.dumps(settings, ensure_ascii=False))
        await conn.execute(
            "INSERT INTO workpaper_items (org_id, engagement_id, kind, item_key, payload) "
            "VALUES ($1, $2, 'document', 'M1', $3::jsonb)",
            ORG_A, engagement, json.dumps({"documentId": "M1", "note": "mine", "placements": placements}))
        # an engagement with no groups, and one with an empty list: untouched
        await conn.execute("INSERT INTO engagements (org_id, name, settings) VALUES ($1, 'No groups', '{}'::jsonb), "
                           "($1, 'Empty', '{\"recalculation\": {\"vehicle_groups\": []}}'::jsonb)", ORG_A)
        return str(engagement)
    finally:
        await conn.close()


def test_migration_0021_gives_existing_groups_their_anchor_as_id_and_changes_nothing_else() -> None:
    placements = [{"from": UNASSIGNED, "to": "s1:mobile:diesel-fuel:vg-none-2"},
                  {"from": "s1:mobile:diesel-fuel:vg-none-2", "to": "s1:mobile:diesel-fuel:vg-gone"}]
    settings = {"facilities": [KENT], "recalculation": {"vehicle_groups": LEGACY, "reported_lines": {"s1:mobile:diesel-fuel:vg-none": 4.5}},
                "evidenceLines": [{"key": "s1:mobile:diesel-fuel:vg-none-2", "label": "Night trucks"}]}
    try:
        alembic("downgrade", "0020_audit_logs_target_index")
        engagement_id = asyncio.run(_insert(settings, placements))
        alembic("upgrade", "head")
        row = asyncio.run(_admin("SELECT settings FROM engagements WHERE id = $1::uuid", engagement_id))[0]["settings"]
        migrated = json.loads(row) if isinstance(row, str) else row
        groups = migrated["recalculation"]["vehicle_groups"]
        assert [g["group_id"] for g in groups] == legacy_group_anchors(LEGACY) == [
            "vg-none", "vg-none-2", "vg-lieferwagen-z-rich", "vg-pickups"]
        assert [{k: v for k, v in g.items() if k != "group_id"} for g in groups] == LEGACY
        assert migrated["recalculation"]["reported_lines"] == settings["recalculation"]["reported_lines"]
        assert migrated["evidenceLines"] == settings["evidenceLines"] and migrated["facilities"] == [KENT]
        payload = asyncio.run(_admin("SELECT payload FROM workpaper_items WHERE engagement_id = $1::uuid", engagement_id))[0]["payload"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        assert payload == {"documentId": "M1", "note": "mine", "placements": placements}  # chains and parked: as they were
        others = asyncio.run(_admin("SELECT name, settings FROM engagements WHERE name IN ('No groups', 'Empty') ORDER BY name"))
        assert [json.loads(r["settings"]) if isinstance(r["settings"], str) else r["settings"] for r in others] == [
            {"recalculation": {"vehicle_groups": []}}, {}]

        # down: the ids go (the older code rejects the key); up again: the same ids as before
        alembic("downgrade", "0020_audit_logs_target_index")
        down = asyncio.run(_admin("SELECT settings FROM engagements WHERE id = $1::uuid", engagement_id))[0]["settings"]
        down = json.loads(down) if isinstance(down, str) else down
        assert down["recalculation"]["vehicle_groups"] == LEGACY
        alembic("upgrade", "head")
        again = asyncio.run(_admin("SELECT settings FROM engagements WHERE id = $1::uuid", engagement_id))[0]["settings"]
        again = json.loads(again) if isinstance(again, str) else again
        assert [g["group_id"] for g in again["recalculation"]["vehicle_groups"]] == [g["group_id"] for g in groups]
    finally:
        alembic("upgrade", "head")
        asyncio.run(_admin("TRUNCATE workpaper_items, engagements CASCADE"))


def test_a_migrated_engagement_saves_and_keeps_its_ids(store: FakeStore) -> None:
    """Groups with the ids the migration gave them are the stored data: a save sending them back keeps them."""

    migrated = [{**g, "group_id": a} for g, a in zip(LEGACY, legacy_group_anchors(LEGACY), strict=True)]
    created = call("POST", BASE, "a_member", {"name": "Old", "settings": {"facilities": [KENT]}}).json()
    asyncio.run(_admin("UPDATE engagements SET settings = $2::jsonb WHERE id = $1::uuid", created["id"],
                       json.dumps({"facilities": [KENT], "recalculation": {"vehicle_groups": migrated}})))
    assert ids(groups_of(created["id"])) == ["vg-none", "vg-none-2", "vg-lieferwagen-z-rich", "vg-pickups"]
    assert save(created["id"], migrated[1:]).status_code == 200  # the first removed: the others are not renumbered
    assert ids(groups_of(created["id"])) == ["vg-none-2", "vg-lieferwagen-z-rich", "vg-pickups"]
