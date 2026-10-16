"""Uploaded files in Postgres behave like LocalStorageService's files on disk.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user, so RLS
applies); skipped without them, except the URI checks that need no database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import MissingS1Scope, S1Scope, scoped
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.postgres_file_store import PostgresFileStore

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
ORG = uuid.UUID("cccccccc-0000-0000-0000-0000000000c3")
OTHER_ORG = uuid.UUID("dddddddd-0000-0000-0000-0000000000d4")
BILL = b"%PDF-1.4 gas bill, March 2025"


@pytest.fixture(scope="module")
def engines() -> Iterator[tuple[Any, Any]]:
    if not (ADMIN_URL and APP_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")
    admin = create_engine(to_sync_url(ADMIN_URL), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL), pool_size=2, max_overflow=0)
    try:
        yield admin, app
    finally:
        admin.dispose()
        app.dispose()


@pytest.fixture
def store(engines: tuple[Any, Any], tmp_path: Path) -> Iterator[PostgresFileStore]:
    admin, app = engines
    with admin.begin() as connection:
        connection.execute(text("TRUNCATE s1_document_files"))
        connection.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'Files A', 's1-files-a'), "
                 "(:b, 'Files B', 's1-files-b') ON CONFLICT DO NOTHING"),
            {"a": ORG, "b": OTHER_ORG},
        )
    with scoped(S1Scope.tenant(ORG)):
        yield PostgresFileStore(cache_dir=tmp_path / "cache", engine=app)


def _save(store: PostgresFileStore, owner: uuid.UUID = ORG, name: str = "March bill.pdf",
          content: bytes = BILL) -> dict:
    return store.save_upload(file_name=name, content=content, engagement_id="ENG 1", evidence_id="EV-1",
                             document_id="DOC-1", owner=str(owner))


def test_an_upload_gets_the_same_storage_uri_as_on_disk(store: PostgresFileStore, tmp_path: Path) -> None:
    on_disk = LocalStorageService(tmp_path / "local-data" / "uploads")
    disk_kwargs = dict(file_name="March bill.pdf", content=BILL, engagement_id="ENG 1", evidence_id="EV-1",
                       document_id="DOC-1", owner=str(ORG))
    expected = on_disk.save_upload(**disk_kwargs)  # type: ignore[arg-type]
    again = on_disk.save_upload(**disk_kwargs)  # type: ignore[arg-type]

    first, second = _save(store), _save(store)
    assert first["storage_uri"] == "local-data/uploads/" + expected["storage_uri"].split("/", 1)[1]
    assert (first["stored_file_name"], second["stored_file_name"]) == (
        expected["stored_file_name"], again["stored_file_name"]) == ("March_bill.pdf", "March_bill_1.pdf")
    assert first["size_bytes"] == len(BILL)


def test_a_stored_file_is_read_back_through_a_local_copy(store: PostgresFileStore, tmp_path: Path) -> None:
    uri = _save(store)["storage_uri"]

    path = store.resolve_storage_uri(uri)
    assert path.read_bytes() == BILL
    assert path.name == "March_bill.pdf"  # parsers tell the file type from its name
    assert store.exists(uri)
    assert store.is_owned_by(uri, str(ORG))
    assert not store.is_owned_by(uri, str(OTHER_ORG))

    path.write_bytes(b"truncated")  # a damaged copy is replaced
    assert store.resolve_storage_uri(uri).read_bytes() == BILL
    path.unlink()  # so is a deleted one
    assert store.resolve_storage_uri(uri).read_bytes() == BILL


def test_another_organization_cannot_read_or_find_the_file(store: PostgresFileStore) -> None:
    uri = _save(store)["storage_uri"]
    with scoped(S1Scope.tenant(OTHER_ORG)):
        assert not store.exists(uri)
        with pytest.raises(ValueError):
            store.resolve_storage_uri(uri)
    with scoped(S1Scope.platform()):
        assert store.resolve_storage_uri(uri).read_bytes() == BILL


def test_a_file_cannot_be_stored_for_another_organization(store: PostgresFileStore) -> None:
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        _save(store, owner=OTHER_ORG)


def test_empty_or_unnamed_uploads_are_refused(store: PostgresFileStore) -> None:
    with pytest.raises(ValueError):
        _save(store, content=b"")
    with pytest.raises(ValueError):
        _save(store, name="../")


def test_with_no_organization_bound_the_store_refuses(engines: tuple[Any, Any], tmp_path: Path) -> None:
    store = PostgresFileStore(cache_dir=tmp_path, engine=engines[1])
    with pytest.raises(MissingS1Scope):
        store.exists("local-data/uploads/x/y.pdf")
    with pytest.raises(MissingS1Scope):
        _save(store)


@pytest.mark.parametrize("uri", ["", "/etc/passwd", "local-data/uploads/../secrets.pdf", "a\\b.pdf"])
def test_unsafe_storage_uris_are_never_looked_up(uri: str, tmp_path: Path) -> None:
    store = PostgresFileStore(cache_dir=tmp_path)  # no scope, no engine: a lookup would raise otherwise
    assert not store.exists(uri)
    assert not store.is_owned_by(uri, str(ORG))
    with pytest.raises(ValueError):
        store.resolve_storage_uri(uri)
