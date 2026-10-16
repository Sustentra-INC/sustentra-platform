"""With the Postgres stores, RLS hides another organization's records from the evidence
checks, so they also ask the evidence owners table. With the JSONL stores they do not."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.app.api import s1_access
from backend.app.core.auth import CurrentUser
from backend.app.repositories import s1_postgres

ORG = uuid.UUID("cccccccc-0000-0000-0000-0000000000c3")


def _user(role: str = "org_member") -> CurrentUser:
    return CurrentUser(id=uuid.uuid4(), email="m@c.test", first_name=None, last_name=None, full_name=None,
                       role=role, org_id=None if role == "provider_admin" else ORG, org_slug=None,
                       session_id=uuid.uuid4())


@pytest.fixture
def held_elsewhere(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[str] = []

    def status(evidence_id: str) -> str:
        asked.append(evidence_id)
        return "taken"

    monkeypatch.setattr(s1_postgres, "evidence_owner_status", status)
    return asked


def _store(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(s1_access, "get_settings", lambda: SimpleNamespace(s1_store=name))


@pytest.mark.parametrize("store", ["postgres", "postgres+jsonl"])
def test_evidence_held_by_another_organization_is_never_free_or_visible(
    monkeypatch: pytest.MonkeyPatch, held_elsewhere: list[str], store: str
) -> None:
    _store(monkeypatch, store)
    own = [{"org_id": str(ORG), "evidence_id": "EV-1"}]
    monkeypatch.setattr(s1_access, "evidence_records", lambda _e: [])  # RLS: nothing visible
    assert not s1_access.evidence_free_or_own("EV-1", _user())
    monkeypatch.setattr(s1_access, "evidence_records", lambda _e: own)  # own records beside a foreign claim
    assert not s1_access.evidence_owned_by_caller("EV-1", _user())
    assert not s1_access.evidence_visible("EV-1", _user())
    assert held_elsewhere


def test_the_jsonl_stores_decide_from_the_records_alone(
    monkeypatch: pytest.MonkeyPatch, held_elsewhere: list[str]
) -> None:
    _store(monkeypatch, "jsonl")
    monkeypatch.setattr(s1_access, "evidence_records", lambda _e: [])
    assert s1_access.evidence_free_or_own("EV-1", _user())
    assert held_elsewhere == []


def test_provider_scope_sees_every_record_so_needs_no_owner_check(
    monkeypatch: pytest.MonkeyPatch, held_elsewhere: list[str]
) -> None:
    _store(monkeypatch, "postgres")
    monkeypatch.setattr(s1_access, "evidence_records", lambda _e: [{"org_id": str(ORG), "evidence_id": "EV-1"}])
    assert s1_access.evidence_visible("EV-1", _user("provider_admin"))
    assert held_elsewhere == []
