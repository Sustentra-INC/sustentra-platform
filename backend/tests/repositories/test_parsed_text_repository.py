"""The kept parser outputs behave the same in memory and in Postgres (migration 0027).

The Postgres runs need TEST_DATABASE_URL (owner) and TEST_APP_DATABASE_URL (app_user, so RLS applies);
without them only those runs are skipped.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import to_sync_url
from backend.app.repositories.parsed_text_repository import (
    InMemoryParsedTextRepository,
    PostgresParsedTextRepository,
)

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
ORG = str(uuid.UUID("eeeeeeee-0000-0000-0000-0000000000e5"))
OTHER_ORG = str(uuid.UUID("ffffffff-0000-0000-0000-0000000000f6"))
SHA = "a" * 64


def _output(pages: int = 2, text_: str = "Café ☕ 1,200 kWh") -> dict[str, Any]:
    return {"status": "parsed", "parser_name": "pdf_parser", "document_id": "DOC-1",
            "pages": [{"page_number": n, "text": text_} for n in range(1, pages + 1)],
            "text_blocks": [], "warnings": []}


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> Iterator[Any]:
    if request.param == "memory":
        yield InMemoryParsedTextRepository()
        return
    if not (ADMIN_URL and APP_URL):
        pytest.skip("TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")
    admin = create_engine(to_sync_url(ADMIN_URL), pool_size=1, max_overflow=0)
    app = create_engine(to_sync_url(APP_URL), pool_size=2, max_overflow=0)
    try:
        with admin.begin() as connection:
            connection.execute(text("TRUNCATE s1_parsed_texts"))
            connection.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:a, 'Kept A', 's1-kept-a'), "
                     "(:b, 'Kept B', 's1-kept-b') ON CONFLICT DO NOTHING"), {"a": ORG, "b": OTHER_ORG})
        yield PostgresParsedTextRepository(app)
    finally:
        admin.dispose()
        app.dispose()


def test_a_kept_output_comes_back_whole(store: Any) -> None:
    store.put(ORG, SHA, "v0|ocr=on", 0, 0, _output(300))
    kept = store.get(ORG, SHA, "v0|ocr=on")
    assert kept is not None and len(kept["pages"]) == 300 and kept["pages"][0]["text"] == "Café ☕ 1,200 kWh"


def test_the_key_is_organization_hash_version_and_pages(store: Any) -> None:
    store.put(ORG, SHA, "v0", 0, 0, _output())
    assert store.get(OTHER_ORG, SHA, "v0") is None
    assert store.get(ORG, "b" * 64, "v0") is None
    assert store.get(ORG, SHA, "v1") is None
    assert store.get(ORG, SHA, "v0", 1, 5) is None


def test_a_second_put_replaces_the_row(store: Any) -> None:
    store.put(ORG, SHA, "v0", 0, 0, _output(1, "old"))
    store.put(ORG, SHA, "v0", 0, 0, _output(1, "new"))
    kept = store.get(ORG, SHA, "v0")
    assert kept is not None and kept["pages"][0]["text"] == "new"
