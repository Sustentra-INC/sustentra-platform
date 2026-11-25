"""A retried upload (same client upload id) never stores a second document."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.api.engagements import require_open_engagement
from backend.app.core.auth import get_current_user
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.api.conftest import ORG_A, make_user, owned_upload_service

ORIGIN = {"Origin": "http://localhost:3000"}
CLIENT_ID = "5b0f8c2e-3d0a-4c35-9a53-0c4f7d1f9e11"


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, dict]]:
    app = create_app(Settings())
    who = {"user": make_user(), "engagement": "ENG-1"}
    app.dependency_overrides[get_current_user] = lambda: who["user"]
    app.dependency_overrides[require_open_engagement] = lambda: {"status": "active"}
    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    documents_api.configure_services(upload_service=owned_upload_service(tmp_path))
    try:
        yield TestClient(app), who
    finally:
        documents_api.configure_services(upload_service=original[0], pipeline_service=original[1],
                                         storage_service=original[2])


def post(client: TestClient, who: dict, client_id: str | None = CLIENT_ID, name: str = "bill.pdf"):
    data = {"client_upload_id": client_id} if client_id is not None else {}
    return client.post(f"/api/v1/engagements/{who['engagement']}/documents/upload", data=data,
                       files={"file": (name, b"%PDF bill", "application/pdf")}, headers=ORIGIN)


def stored(client: TestClient, who: dict) -> list[dict]:
    return documents_api._upload_service._document_repository.list_by_engagement(who["engagement"])


def test_the_same_id_twice_gives_the_same_document(api) -> None:
    client, who = api
    first, second = post(client, who), post(client, who)
    assert first.status_code == second.status_code == 200
    assert first.json()["document_id"] == second.json()["document_id"]
    assert first.json()["client_upload_id"] == CLIENT_ID
    assert len(stored(client, who)) == 1


def test_a_retry_keeps_the_first_documents_file_and_name(api) -> None:
    client, who = api
    first = post(client, who, name="bill.pdf").json()
    second = post(client, who, name="renamed.pdf").json()
    assert second["file_name"] == first["file_name"] == "bill.pdf"


def test_without_an_id_every_upload_is_new(api) -> None:
    client, who = api
    post(client, who, None), post(client, who, None)
    assert len(stored(client, who)) == 2


def test_different_ids_are_different_documents(api) -> None:
    client, who = api
    post(client, who), post(client, who, str(uuid.uuid4()))
    assert len(stored(client, who)) == 2


@pytest.mark.parametrize("bad", ["not-a-uuid", "123", "5b0f8c2e-3d0a-4c35-9a53", "../../etc"])
def test_an_id_that_is_not_a_uuid_is_a_422(api, bad: str) -> None:
    client, who = api
    response = post(client, who, bad)
    assert response.status_code == 422
    assert "UUID" in response.json()["detail"]
    assert stored(client, who) == []


def test_an_id_is_matched_in_any_letter_case(api) -> None:
    client, who = api
    post(client, who, CLIENT_ID.upper())
    assert post(client, who, CLIENT_ID).status_code == 200
    assert len(stored(client, who)) == 1


def test_another_engagement_or_org_never_gets_the_document(api) -> None:
    client, who = api
    first = post(client, who).json()
    who["engagement"] = "ENG-2"
    other_engagement = post(client, who).json()
    assert other_engagement["document_id"] != first["document_id"]
    who["engagement"] = "ENG-1"
    who["user"] = make_user(org_id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001"))
    other_org = post(client, who).json()
    assert other_org["document_id"] != first["document_id"]
    assert other_org["org_id"] != str(ORG_A)
    assert len(documents_api._upload_service._document_repository.list_all()) == 3


def test_a_withdrawn_document_is_still_the_same_upload(api) -> None:
    client, who = api
    first = post(client, who).json()
    repo = documents_api._upload_service._document_repository
    repo.save({**repo.get_by_id(first["document_id"]), "processing_status": "failed"})
    assert post(client, who).json()["document_id"] == first["document_id"]
    assert len(stored(client, who)) == 1
