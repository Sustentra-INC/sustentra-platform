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


def fac(database: str, edition: str) -> dict[str, Any]:
    return {"value": {"database": database, "edition": edition}}


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
        groups: frozenset[str] = frozenset(rules.ROW_GROUPS)) -> tuple[Store, set[str]]:
    store = Store(rows)
    for name in ("list_items", "get_items", "update_payload"):
        monkeypatch.setattr(api.workpaper_item_service, name, getattr(store, name))
    return store, asyncio.run(api._replace_stale_rows(None, ENG, USER, wanted, groups))  # type: ignore[arg-type]


def removed(store: Store) -> set[str]:
    return {k for k, r in store.rows.items() if r["payload"].get("removed")}


def test_undecided_rows_the_read_no_longer_suggests_are_marked_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row("factor:scope1:aaaa", suggestion=fac("EPA", "2024")), row("factor:scope1:bbbb", suggestion=fac("eGRID", "2022")),
            row("entity:cccc", suggestion={"value": {"name": "Acme"}}), row("gwp", suggestion=fac("x", "y"))]
    store, gone = run(monkeypatch, rows, [("factor:scope1", fac("eGRID", "2022")["value"]), ("entities", {"name": "Acme"})])
    assert gone == {"factor:scope1:aaaa"} and removed(store) == gone  # same id kept; the fixed field is not a row


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
    store, gone = run(monkeypatch, rows, [], frozenset(g for g, p in rules.ROW_GROUP_PART.items() if p != "factors"))
    assert gone == {"entity:cccc"}
    store, gone = run(monkeypatch, rows, [], frozenset())
    assert gone == set()


def test_every_row_group_belongs_to_a_prefill_section() -> None:
    from backend.app.services import methodology_prefill as prefill

    assert set(rules.ROW_GROUP_PART) == set(rules.ROW_GROUPS) and set(rules.ROW_GROUP_PART.values()) <= set(prefill.PART_LABELS)
