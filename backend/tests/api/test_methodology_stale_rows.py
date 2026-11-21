"""Which rows a re-read replaces (``_replace_stale_rows``), against an in-memory item store. The same behaviour
through the real app and Postgres is in tests/db/test_methodology_prefill_db.py."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.api import methodology_review as api
from backend.app.services import methodology_review as rules

ENG = {"id": "E1"}
USER = SimpleNamespace(id=None)


def fac(database: str, edition: str, doc: str = "D1") -> dict[str, Any]:
    return {"value": {"database": database, "edition": edition}, "document_id": doc}


def row(key: str, **payload: Any) -> dict[str, Any]:
    return {"item_key": key, "payload": {"field_id": key, "suggestion": None, "decision": None, "history": [], **payload}}


class Store:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = {r["item_key"]: r for r in rows}

    async def list_items(self, db: Any, eid: Any, kind: Any = None) -> list[dict[str, Any]]:
        return list(self.rows.values())

    async def get_items(self, db: Any, eid: Any, kind: Any, keys: list[str], for_update: bool = False) -> list[dict[str, Any]]:
        return [self.rows[k] for k in keys if k in self.rows]

    async def update_payload(self, db: Any, eid: Any, kind: Any, key: str, payload: dict[str, Any], user_id: Any) -> dict[str, Any]:
        self.rows[key] = {"item_key": key, "payload": payload}
        return self.rows[key]


def run(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], wanted: list[tuple[str, Any]],
        groups: frozenset[str] = frozenset(rules.ROW_GROUPS),
        docs: frozenset[str] | None = frozenset({"D1"})) -> tuple[Store, set[str]]:
    store = Store(rows)
    for name in ("list_items", "get_items", "update_payload"):
        monkeypatch.setattr(api.workpaper_item_service, name, getattr(store, name))
    return store, asyncio.run(api._replace_stale_rows(None, ENG, USER, wanted, groups, docs))  # type: ignore[arg-type]


def removed(store: Store) -> set[str]:
    return {k for k, r in store.rows.items() if r["payload"].get("removed")}


def test_a_source_the_read_did_not_mention_stays_and_the_same_source_with_other_wording_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row("factor:scope1:aaaa", suggestion=fac("U.S. EPA GHG Emission Factors Hub", "2024")),
            row("factor:scope1:bbbb", suggestion=fac("eGRID", "2022")),
            row("factor:scope1:cccc", suggestion=fac("UK DESNZ", "2021")),
            row("entity:eeee", suggestion={"value": {"name": "Acme"}}), row("gwp", suggestion=fac("x", "y"))]
    wanted = [("factor:scope1", fac("EPA GHG Emission Factors Hub", "2023")["value"]), ("factor:scope1", fac("UK DESNZ", "2021")["value"]),
              ("entities", {"name": "Acme"})]
    store, gone = run(monkeypatch, rows, wanted)
    assert gone == {"factor:scope1:aaaa"} and removed(store) == gone  # eGRID not mentioned: kept; DESNZ again: kept as is


def test_a_group_the_read_returned_nothing_for_keeps_its_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row("factor:scope1:aaaa", suggestion=fac("EPA", "2024")), row("factor:scope2:bbbb", suggestion=fac("eGRID", "2022")),
            row("entity:cccc", suggestion={"value": {"name": "Acme"}})]
    store, gone = run(monkeypatch, rows, [("factor:scope2", fac("eGRID", "2023")["value"])])
    assert gone == {"factor:scope2:bbbb"}  # scope 1 and the entities returned nothing: untouched


def test_a_row_whose_document_is_no_longer_read_is_removed_even_if_not_mentioned(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row("factor:scope1:aaaa", suggestion=fac("EPA", "2024", "D9")), row("factor:scope1:bbbb", suggestion=fac("eGRID", "2022", "D1")),
            row("factor:scope1:nodoc", suggestion=fac("DESNZ", "2021", ""))]
    store, gone = run(monkeypatch, rows, [], docs=frozenset({"D1"}))
    assert gone == {"factor:scope1:aaaa"}  # even with nothing returned; no recorded document: not judged on it
    store, gone = run(monkeypatch, rows, [], docs=None)
    assert gone == set()


def test_how_the_same_source_is_told() -> None:
    from backend.app.services import methodology_prefill as p

    same = lambda a, b: p.same_source("factor:scope1", {"database": a}, {"database": b})  # noqa: E731
    assert same("EPA GHG Emission Factors Hub", "U.S. EPA GHG Emission Factors Hub")
    assert same("The U.S. EPA  GHG Emission Factors Hub", "us epa ghg emission factors hub")
    assert same("Defra & BEIS conversion factors", "DEFRA and BEIS Conversion Factors")
    assert not same("EPA", "EPA eGRID") and not same("EPA eGRID", "UK DESNZ conversion factors") and not same("", "")
    assert p.same_source("gwp", {"set": "AR5", "applies_to": "All gases", "horizon": "100"}, {"set": "ar5", "applies_to": "all  gases"})
    assert not p.same_source("gwp", {"set": "AR5", "applies_to": "A"}, {"set": "AR5", "applies_to": "B"})
    assert p.same_source("entities", {"name": "Acme  LLC"}, {"name": "acme llc"})
    assert not p.same_source("entities", {"name": ""}, {"name": ""}) and not p.same_source("other", {"name": "A"}, {"name": "A"})


def test_a_row_a_reviewer_touched_in_any_way_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    touched = {"decision": {"status": "accepted", "value": {}}}, {"decision": {"status": "pending", "value": {}}}, \
        {"history": [{"action": "accept"}]}, {"value_history": [{}]}, {"user_added": True}, {"previous_lost": True}
    rows = [row(f"factor:scope1:t{i}", suggestion=fac("d", str(i)), **extra) for i, extra in enumerate(touched)]
    rows.append(row("factor:scope1:ask", suggestion=fac("d", "ask")))
    rows.append({"item_key": "ASK-METH-factor:scope1:ask", "payload": {"state": "resolved"}})
    store, gone = run(monkeypatch, rows, [])
    assert gone == set() and removed(store) == set()


def test_only_the_groups_whose_section_ran_are_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row("factor:scope1:aaaa", suggestion=fac("EPA", "2024")), row("entity:cccc", suggestion={"value": {"name": "Acme"}})]
    wanted = [("factor:scope1", fac("EPA", "2023")["value"]), ("entities", {"name": "Acme"})]
    store, gone = run(monkeypatch, rows, wanted, frozenset(g for g, p in rules.ROW_GROUP_PART.items() if p != "factors"))
    assert gone == set()  # the factors section did not run: its row is not judged (the entity came again as it was)
    store, gone = run(monkeypatch, rows, wanted, frozenset(g for g, p in rules.ROW_GROUP_PART.items() if p == "factors"))
    assert gone == {"factor:scope1:aaaa"}
    store, gone = run(monkeypatch, rows, wanted, frozenset())
    assert gone == set()


def test_every_row_group_belongs_to_a_prefill_section() -> None:
    from backend.app.services import methodology_prefill as prefill

    assert set(rules.ROW_GROUP_PART) == set(rules.ROW_GROUPS) and set(rules.ROW_GROUP_PART.values()) <= set(prefill.PART_LABELS)
