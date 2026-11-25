"""A retried upload never stores a second document, even when it arrives while the first is still
being stored (Postgres stores, as app_user so RLS applies). Needs TEST_DATABASE_URL and
TEST_APP_DATABASE_URL, like test_identical_upload_isolation.py, whose setup it reuses."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from backend.app.api import documents as documents_api
from backend.tests.db.test_identical_upload_isolation import (  # noqa: F401 - stores is a fixture
    BILL,
    ORG_B,
    call,
    engagement,
    pytestmark as _needs_db,
    stores,
)

pytestmark = [_needs_db, pytest.mark.usefixtures("stores")]

CLIENT_ID = "8c1e2f4a-6b7d-4e90-a1b2-3c4d5e6f7a80"


def post(eng: str, token: str = "a_member", client_id: str | None = CLIENT_ID) -> Any:
    data = {"client_upload_id": client_id} if client_id else None
    return call("POST", f"/api/v1/engagements/{eng}/documents/upload", token, data=data,
                files={"file": ("bill.txt", BILL, "text/plain")})


def count(eng: str, token: str = "a_member") -> int:
    return len(call("GET", f"/api/v1/engagements/{eng}/documents", token).json()["items"])


def test_the_same_id_twice_is_one_document() -> None:
    eng = engagement("a_member", "Retry once")
    first, second = post(eng), post(eng)
    assert first.status_code == second.status_code == 200
    assert first.json()["document_id"] == second.json()["document_id"]
    assert count(eng) == 1


def test_a_retry_that_arrives_while_the_first_is_still_being_stored_gets_that_document() -> None:
    eng = engagement("a_member", "Retry racing")
    service = documents_api._upload_service
    real = service.upload_document

    def slow(**kwargs: Any) -> dict:
        time.sleep(0.6)  # the first attempt is still writing when the retries land
        return real(**kwargs)

    service.upload_document = slow  # type: ignore[method-assign]
    results: list[Any] = []

    def attempt(delay: float) -> None:
        time.sleep(delay)
        results.append(post(eng))

    try:
        threads = [threading.Thread(target=attempt, args=(d,)) for d in (0.0, 0.2, 0.3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        service.upload_document = real  # type: ignore[method-assign]
    assert [r.status_code for r in results] == [200, 200, 200]
    assert len({r.json()["document_id"] for r in results}) == 1
    assert count(eng) == 1


def test_another_org_or_engagement_gets_its_own_document() -> None:
    eng_a, eng_a2, eng_b = engagement("a_member", "A one"), engagement("a_member", "A two"), engagement("b_member", "B one")
    mine = post(eng_a).json()
    assert post(eng_a2).json()["document_id"] != mine["document_id"]
    theirs = post(eng_b, "b_member").json()
    assert theirs["document_id"] != mine["document_id"] and theirs["org_id"] == str(ORG_B)
    assert (count(eng_a), count(eng_a2), count(eng_b, "b_member")) == (1, 1, 1)
    # Org B sending org A's id for org A's engagement is refused as any foreign engagement is.
    assert post(eng_a, "b_member").status_code == 404


def test_a_bad_id_is_422_and_no_id_is_as_before() -> None:
    eng = engagement("a_member", "Bad id")
    assert post(eng, client_id="nope").status_code == 422
    post(eng, client_id=None), post(eng, client_id=None)
    assert count(eng) == 2
