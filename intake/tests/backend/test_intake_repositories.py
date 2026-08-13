"""Append-only repository semantics and JSONL round-tripping."""

from __future__ import annotations

import json

from intake.backend.repositories.base import AppendOnlyRepository, InMemoryStore, JsonlStore
from intake.backend.repositories.org_repository import JsonlOrgRepository
from intake.backend.repositories.user_repository import InMemoryUserRepository, normalise_email


class _ThingRepository(AppendOnlyRepository):
    id_field = "thing_id"


def _repo() -> _ThingRepository:
    return _ThingRepository(InMemoryStore())


def test_save_returns_the_stored_record() -> None:
    repo = _repo()
    saved = repo.save({"thing_id": "t1", "name": "first"})
    assert saved["name"] == "first"


def test_updates_append_and_latest_wins() -> None:
    repo = _repo()
    repo.save({"thing_id": "t1", "name": "first"})
    repo.save({"thing_id": "t1", "name": "second"})

    assert repo.get("t1")["name"] == "second"
    assert len(repo.list_records()) == 2, "history must be preserved, not overwritten"
    assert len(repo.list_latest()) == 1


def test_missing_id_field_is_rejected() -> None:
    repo = _repo()
    try:
        repo.save({"name": "no id"})
    except ValueError as exc:
        assert "thing_id" in str(exc)
    else:  # pragma: no cover - guard
        raise AssertionError("expected ValueError")


def test_filter_and_find_latest() -> None:
    repo = _repo()
    repo.save({"thing_id": "t1", "org_id": "o1"})
    repo.save({"thing_id": "t2", "org_id": "o1"})
    repo.save({"thing_id": "t3", "org_id": "o2"})

    assert {r["thing_id"] for r in repo.filter_latest(org_id="o1")} == {"t1", "t2"}
    assert repo.find_latest(org_id="o2")["thing_id"] == "t3"
    assert repo.find_latest(org_id="nope") is None


def test_stored_records_are_copies() -> None:
    """Mutating a returned record must not corrupt the store."""
    repo = _repo()
    repo.save({"thing_id": "t1", "name": "first"})
    fetched = repo.get("t1")
    fetched["name"] = "mutated"
    assert repo.get("t1")["name"] == "first"


def test_jsonl_round_trip(tmp_path) -> None:
    path = tmp_path / "things.jsonl"
    repo = _ThingRepository(JsonlStore(path))
    repo.save({"thing_id": "t1", "name": "first"})
    repo.save({"thing_id": "t1", "name": "second"})

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["name"] == "second"
    assert _ThingRepository(JsonlStore(path)).get("t1")["name"] == "second"


def test_jsonl_repository_is_empty_before_first_write(tmp_path) -> None:
    repo = _ThingRepository(JsonlStore(tmp_path / "missing.jsonl"))
    assert repo.list_records() == []
    assert repo.get("anything") is None


def test_user_email_lookup_is_case_insensitive() -> None:
    repo = InMemoryUserRepository()
    repo.save(
        {
            "user_id": "u1",
            "org_id": "o1",
            "email": "Ada@Example.com",
            "name": "Ada",
            "role": "client_owner",
            "status": "active",
            "created_at": "2026-08-13T09:00:00+00:00",
        }
    )
    assert repo.get_by_email("ADA@example.COM")["user_id"] == "u1"
    assert normalise_email("  Ada@Example.com ") == "ada@example.com"


def test_jsonl_org_repository_defaults_under_local_data(monkeypatch, tmp_path) -> None:
    """Intake data must land in the gitignored local-data tree."""
    from intake.backend.config import DATA_DIR_ENV, reset_caches

    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    reset_caches()
    try:
        assert JsonlOrgRepository().store.path == tmp_path / "orgs.jsonl"
    finally:
        reset_caches()
