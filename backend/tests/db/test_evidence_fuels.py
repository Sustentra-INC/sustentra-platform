# ruff: noqa: F811
"""MVP-145: rename and delete a fuel (Level 2) on the Evidence page.

Through the real app and Postgres, like ``test_evidence_actions``. A fuel's id is its slug (in every line key), so a
rename keeps the documents, the lines and the reviewers' decisions where they are; a delete moves the documents to
Unassigned supporting evidence and keeps the audit trail. The system's own fuels can't be deleted.
"""

from __future__ import annotations

import asyncio
import copy
import unicodedata
from typing import Any

import pytest

from backend.app.api import recalculation as recalculation_api
from backend.app.services import calculation_lines as cl
from backend.tests.db.test_calc_line_review_db import TRACE
from backend.tests.db.test_engagements import A_ADMIN, A_MEMBER, BASE, ORG_A, call
from backend.tests.db.test_evidence_actions import (  # noqa: F401 - `seeded` is an autouse fixture
    GAS_KENT,
    KENT,
    PROPANE,
    PROPANE_KEY,
    SECRET,
    TACOMA,
    UNASSIGNED,
    add_gas,
    create_line,
    events,
    make_engagement,
    move,
    path,
    seeded,
    store,
    tree_lines,
)
from backend.tests.services.test_calculation_lines import _gas
from backend.tests.services.test_engagement_recalculation_service import FakeStore

PROPANE_TACOMA = {**PROPANE, "anchor_id": "F2", "label": "Propane at Tacoma"}
PROPANE_TACOMA_KEY = "s1:stationary:propane:f2"


def fuel_path(engagement_id: str, level2: str = "propane", category: str = "stationary") -> str:
    return path(engagement_id, f"evidence-fuels/{category}/{level2}")


def rename(engagement_id: str, name: Any, level2: str = "propane", token: str = "a_member") -> Any:
    return call("PATCH", fuel_path(engagement_id, level2), token, {"name": name})


def fuels(engagement_id: str, token: str = "a_member") -> dict[str, dict[str, Any]]:
    """category:level2 -> the Level 2 node of the tree, as the page gets it."""

    tree = call("GET", path(engagement_id, "evidence-tree"), token).json()
    return {f"{c['category']}:{n['level2']}": n for s in tree["blocks"]["supporting"]["scopes"]
            for c in s["categories"] for n in c["level2s"]}


def with_propane(store: FakeStore, docs: int = 3, facilities: list[dict] | None = None) -> str:
    engagement_id = make_engagement(store, facilities=facilities, docs=docs)
    assert create_line(engagement_id).status_code == 201
    return engagement_id


# --- rename ------------------------------------------------------------------------------------
def test_rename_keeps_the_id_the_line_keys_and_where_documents_sit(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    for i in range(3):
        assert move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY).status_code == 200
    before = tree_lines(engagement_id)
    renamed = rename(engagement_id, "  LPG   (bulk)  ", token="a_admin")
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["level2"] == {"category": "stationary", "level2": "propane", "label": "LPG (bulk)"}
    assert tree_lines(engagement_id) == before  # same keys, same documents
    node = fuels(engagement_id)["stationary:propane"]
    assert node["label"] == "LPG (bulk)" and [n["line"]["key"] for n in node["lines"]] == [PROPANE_KEY]
    assert node["lines"][0]["line"]["level2_label"] == "LPG (bulk)"
    [renamed_event] = [e for e in events(engagement_id) if e["event_type"] == "evidence_level2_renamed"]
    assert renamed_event["event_type"] == "evidence_level2_renamed" and renamed_event["actor_user_id"] == A_ADMIN
    assert renamed_event["metadata"] == {"category": "stationary", "level2": "propane", "old_label": "Propane",
                                         "new_label": "LPG (bulk)"}
    assert renamed_event["created_at"] and renamed_event["target_id"] == engagement_id


def test_rename_works_on_a_system_fuel_and_the_line_label_follows(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    assert fuels(engagement_id)["stationary:natural-gas"]["label"] == "Natural Gas"
    assert rename(engagement_id, "Pipeline gas", "natural-gas").status_code == 200
    node = fuels(engagement_id)["stationary:natural-gas"]
    assert node["label"] == "Pipeline gas" and node["created_by_user"] is False
    [line] = node["lines"]
    assert line["line"]["key"] == GAS_KENT and line["line"]["label"].startswith("Pipeline gas")
    assert tree_lines(engagement_id)[GAS_KENT] == ["D0", "D1"]


def test_rename_validates_the_name_and_a_duplicate_is_refused(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    assert rename(engagement_id, "").status_code == 422
    assert rename(engagement_id, "   \t ").status_code == 422
    assert rename(engagement_id, "x" * 1000).status_code == 422
    assert rename(engagement_id, "x" * 81).status_code == 422
    assert rename(engagement_id, "bad\x00name").status_code == 422
    assert rename(engagement_id, None).status_code == 422
    assert rename(engagement_id, "x" * 80).status_code == 200  # exactly the limit
    taken = rename(engagement_id, "NATURAL GAS")  # another fuel of the category, ignoring case
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "level2_name_taken"
    assert fuels(engagement_id)["stationary:propane"]["label"] == "x" * 80
    assert rename(engagement_id, "Propane", "natural-gas").status_code == 200  # another category's name is fine
    assert len(events(engagement_id)) == 3  # the line, and two renames: nothing refused was logged


def test_rename_with_unicode_and_html_is_stored_as_text(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    for name in ("燃料 Brennstoff Écume", "<script>alert(1)</script>", "Müller & Söhne \"LPG\"", "é"):
        done = rename(engagement_id, name)
        assert done.status_code == 200, (name, done.text)
        assert fuels(engagement_id)["stationary:propane"]["label"] == " ".join(unicodedata.normalize("NFC", name).split())
    assert rename(engagement_id, "é").status_code == 200  # the same name as the last one in another Unicode form: no change
    assert events(engagement_id)[-1]["metadata"]["new_label"] == "é" and len(events(engagement_id)) == 5


def test_a_duplicate_submit_of_a_rename_logs_once(store: FakeStore) -> None:
    engagement_id = with_propane(store)

    async def twice() -> list[Any]:
        return list(await asyncio.gather(*(asyncio.to_thread(rename, engagement_id, "LPG") for _ in range(2))))

    codes = sorted(r.status_code for r in asyncio.run(twice()))
    assert codes == [200, 200]
    assert [e["event_type"] for e in events(engagement_id)] == ["evidence_line_created", "evidence_level2_renamed"]


def test_a_line_added_under_the_new_name_joins_the_renamed_fuel(store: FakeStore) -> None:
    engagement_id = with_propane(store, facilities=[KENT, TACOMA])
    assert rename(engagement_id, "LPG").status_code == 200
    by_name = create_line(engagement_id, level2_label="lpg", anchor_id="F2", label="LPG at Tacoma")  # no id sent
    assert by_name.status_code == 201 and by_name.json()["line"]["key"] == PROPANE_TACOMA_KEY
    assert sorted(k for k in fuels(engagement_id) if k.startswith("stationary:")) == ["stationary:natural-gas", "stationary:propane"]
    assert sorted(n["line"]["key"] for n in fuels(engagement_id)["stationary:propane"]["lines"]) == [PROPANE_KEY, PROPANE_TACOMA_KEY]


def test_rename_of_what_is_not_there_is_404_and_another_org_cannot_see_it(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    assert rename(engagement_id, "X", "no-such-fuel").status_code == 404
    assert call("PATCH", fuel_path(engagement_id, "propane", "nope"), "a_member", {"name": "X"}).status_code == 404
    assert rename(engagement_id, "Mine now", token="b_member").status_code == 404
    assert call("DELETE", fuel_path(engagement_id), "b_member").status_code == 404
    assert call("PATCH", fuel_path(engagement_id), "a_member", {"name": "X", "extra": 1}).status_code == 422
    assert call("PATCH", fuel_path(engagement_id), "provider", {"name": "X"}).status_code == 403
    assert call("PATCH", fuel_path(engagement_id), None, {"name": "X"}).status_code == 401
    assert fuels(engagement_id)["stationary:propane"]["label"] == "Propane" and len(events(engagement_id)) == 1


def test_a_setup_save_cannot_write_or_wipe_the_renames(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    assert rename(engagement_id, "LPG").status_code == 200
    sent = {"facilities": [KENT], "evidenceLevel2Names": {"stationary:propane": {"label": "Hacked"}}}
    assert call("PATCH", f"{BASE}/{engagement_id}", "a_member", {"settings": sent}).status_code == 200
    assert call("PATCH", f"{BASE}/{engagement_id}", "a_member", {"settings": {"facilities": [KENT]}}).status_code == 200
    assert fuels(engagement_id)["stationary:propane"]["label"] == "LPG"


def test_a_decision_on_a_line_under_a_renamed_fuel_still_applies(store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    engagement_id = with_propane(store)

    async def fake(db: Any, engagement: dict, user: Any, **kw: Any) -> dict:
        settings = engagement["settings"]  # the engine's lines are the engagement's lines as they are now
        keys = [ln.key for ln in cl.merge_lines([], cl.user_lines(settings), cl.stored_level2_names(settings))]
        if kw.get("proposal") is not None:
            kw["proposal"].offer(PROPANE_KEY, {**copy.deepcopy(TRACE), "line_key": PROPANE_KEY})
        return {"calculation_lines": [{"key": k, "trace": {**copy.deepcopy(TRACE), "line_key": k}} for k in keys]}

    monkeypatch.setattr(recalculation_api, "traced_recalculation", fake)
    monkeypatch.setattr(recalculation_api, "run_recalculation", fake)
    decide = f"{BASE}/{engagement_id}/calculation-lines/{PROPANE_KEY}/choices/method"
    assert call("POST", decide, "a_member", {"action": "choose", "option_id": "per_unit"}).status_code == 200
    listing = f"{BASE}/{engagement_id}/calculation-lines/decisions"
    assert rename(engagement_id, "LPG").status_code == 200
    after = call("GET", listing, "a_member").json()
    assert [d["line_key"] for d in after["decisions"]] == [PROPANE_KEY] and after["orphaned_decisions"] == []
    # and deleting the fuel orphans it, as a deleted line does: kept, listed, never applied to another line
    assert call("DELETE", fuel_path(engagement_id), "a_member").status_code == 200
    gone = call("GET", listing, "a_member").json()
    assert gone["decisions"] == [] and [d["line_key"] for d in gone["orphaned_decisions"]] == [PROPANE_KEY]


# --- delete ------------------------------------------------------------------------------------
def test_delete_moves_the_documents_removes_the_fuel_and_its_lines_and_keeps_the_audit_trail(store: FakeStore) -> None:
    engagement_id = with_propane(store, docs=3, facilities=[KENT, TACOMA])
    assert create_line(engagement_id, **{k: v for k, v in PROPANE_TACOMA.items() if k != "level2_label"}).status_code == 201
    assert rename(engagement_id, "LPG").status_code == 200
    for i in range(3):
        assert move(engagement_id, f"D{i}", GAS_KENT, PROPANE_KEY).status_code == 200
    node = fuels(engagement_id)["stationary:propane"]
    assert node["created_by_user"] is True and node["created_by"] == str(A_MEMBER) and node["created_at"]
    assert node["created_by_name"]
    deleted = call("DELETE", fuel_path(engagement_id), "a_admin")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["documents_moved"] == 3 and deleted.json()["evidenceLines"] == []
    assert deleted.json()["evidenceLevel2Names"] == {}
    after = tree_lines(engagement_id)
    assert sorted(after[UNASSIGNED]) == ["D0", "D1", "D2"]
    assert PROPANE_KEY not in after and PROPANE_TACOMA_KEY not in after and "stationary:propane" not in fuels(engagement_id)
    *_, last = events(engagement_id)
    assert last["event_type"] == "evidence_level2_deleted" and last["actor_user_id"] == A_ADMIN
    assert last["metadata"] == {"category": "stationary", "level2": "propane", "label": "LPG", "lines_deleted": 2,
                                "documents_moved": 3}
    assert not any(SECRET in str(e) for e in events(engagement_id))  # ids and labels, never document text
    # making the fuel again does not pull the documents back
    assert create_line(engagement_id).status_code == 201
    again = tree_lines(engagement_id)
    assert sorted(again[UNASSIGNED]) == ["D0", "D1", "D2"] and again[PROPANE_KEY] == []
    assert fuels(engagement_id)["stationary:propane"]["label"] == "Propane"  # the old rename went with the fuel
    assert call("DELETE", fuel_path(engagement_id, "nope"), "a_member").status_code == 404


def test_a_document_on_two_lines_of_one_fuel_loses_both_placements_in_one_delete(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    store.add_document("TWO", "CT-S1-FUELQTY", [_gas(plant="Kent Cannery"), _gas(plant="Tacoma Works")],
                       engagement_id=engagement_id, org_id=str(ORG_A))
    assert create_line(engagement_id).status_code == 201
    assert create_line(engagement_id, **{k: v for k, v in PROPANE_TACOMA.items() if k != "level2_label"}).status_code == 201
    assert move(engagement_id, "TWO", GAS_KENT, PROPANE_KEY).status_code == 200
    deleted = call("DELETE", fuel_path(engagement_id), "a_member")
    assert deleted.status_code == 200 and deleted.json()["documents_moved"] == 1
    lines = tree_lines(engagement_id)
    assert lines[UNASSIGNED] == ["TWO"] and lines[GAS_KENT] == []


def test_a_system_fuel_cannot_be_deleted_and_nothing_changes(store: FakeStore) -> None:
    engagement_id = make_engagement(store, docs=2)
    refused = call("DELETE", fuel_path(engagement_id, "natural-gas"), "a_member")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "level2_system_created"
    assert "can't be deleted" in refused.json()["detail"]["message"]
    assert tree_lines(engagement_id)[GAS_KENT] == ["D0", "D1"] and events(engagement_id) == []


def test_a_fuel_that_now_holds_a_line_the_system_makes_is_no_longer_deletable(store: FakeStore) -> None:
    engagement_id = make_engagement(store, facilities=[KENT, TACOMA])
    assert create_line(engagement_id, level2_label="Natural gas", anchor_id="F2", label="Gas at Tacoma").status_code == 201
    assert fuels(engagement_id)["stationary:natural-gas"]["created_by_user"] is True  # only the reviewer's line is in it
    # a document arrives that the system files on that fuel at that facility: the line is the system's now
    add_gas(store, "NEW", engagement_id, plant="Tacoma Works")
    node = fuels(engagement_id)["stationary:natural-gas"]
    assert node["created_by_user"] is False
    assert call("DELETE", fuel_path(engagement_id, "natural-gas"), "a_member").status_code == 409


def test_a_delete_is_refused_for_a_provider_and_an_archived_engagement(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    assert call("DELETE", fuel_path(engagement_id), "provider").status_code == 403
    assert call("DELETE", fuel_path(engagement_id), None).status_code == 401
    assert call("PATCH", f"{BASE}/{engagement_id}", "a_member", {"status": "archived"}).status_code == 200
    assert call("DELETE", fuel_path(engagement_id), "a_member").status_code == 409
    assert rename(engagement_id, "LPG").status_code == 409
    assert "stationary:propane" in fuels(engagement_id)


def test_rename_and_delete_show_in_the_evidence_activity_with_who(store: FakeStore) -> None:
    engagement_id = with_propane(store)
    assert rename(engagement_id, "LPG").status_code == 200
    assert call("DELETE", fuel_path(engagement_id), "a_admin").status_code == 200
    items = call("GET", path(engagement_id, "evidence-activity"), "a_member").json()["items"]
    kinds = [i["event_type"] for i in items]
    assert kinds[:2] == ["evidence_level2_deleted", "evidence_level2_renamed"]
    assert items[0]["actor_name"] and items[0]["label"] == "LPG" and items[0]["lines_deleted"] == 1
    assert items[1]["old_label"] == "Propane" and items[1]["new_label"] == "LPG" and items[1]["at"]
