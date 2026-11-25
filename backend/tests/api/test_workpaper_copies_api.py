"""Kept copies of the Excel workpaper (MVP-242): what is kept on each download, the order of saving and
sending, the list and the download of a kept copy, and the hostile cases. No database here; the
Postgres side is in backend/tests/db/test_workpaper_copies.py."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app.api import recalculation as recalculation_api
from backend.app.main import app
from backend.app.services import workpaper_export_service
from backend.app.services.workpaper_copy_store import InMemoryWorkpaperCopyStore, sha256_of
from backend.tests.api.conftest import ORG_A, ORG_B
from backend.tests.api.test_recalculation import ENGAGEMENT, wired  # noqa: F401 - the shared fixture
from backend.tests.services.test_engagement_recalculation_service import FakeStore, _elec

URL = "/v1/engagements/ENG-1/export"
COPIES = "/v1/engagements/ENG-1/workpaper-copies"


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch, wired: FakeStore) -> list[dict[str, Any]]:  # noqa: F811
    events: list[dict[str, Any]] = []

    async def record(db, **kwargs):  # noqa: ANN001, ANN003, ANN202
        events.append(kwargs)

    monkeypatch.setattr(recalculation_api, "write_audit_event", record)
    return events


def _memory(wired: FakeStore) -> InMemoryWorkpaperCopyStore:  # noqa: F811
    return wired.copies  # type: ignore[attr-defined,no-any-return]


def test_a_download_keeps_the_exact_bytes_and_records_who_and_when(act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    user = act_as("org_member", ORG_A)
    with TestClient(app) as client:
        response = client.get(URL)
    assert response.status_code == 200
    (copy, kept_bytes), = _memory(wired).copies
    assert kept_bytes == response.content  # byte for byte what was served
    assert copy.sha256 == sha256_of(response.content) and copy.size_bytes == len(response.content)
    assert response.headers["etag"] == f'"{copy.sha256}"'
    assert (copy.org_id, copy.engagement_id) == (str(ORG_A), "ENG-1")
    assert copy.prepared_by_email == user.email and copy.prepared_by_user_id == user.id
    assert copy.app_version == "dev" and copy.created_at is not None
    assert copy.file_name in response.headers["content-disposition"]
    assert [d["kind"] for d in _memory(wired).downloads] == ["prepared"]
    (event,) = audit
    assert event["event_type"] == "workpaper_exported"
    assert event["metadata"] == {"format": "xlsx", "copy_id": str(copy.id), "sha256": copy.sha256,
                                 "size_bytes": copy.size_bytes, "copy_reused": False}


def test_the_same_figures_again_keep_one_copy_and_add_a_download(act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        first = client.get(URL)
        second = client.get(URL)
    assert second.content == first.content  # the kept file itself is served again
    assert len(_memory(wired).copies) == 1
    assert [d["kind"] for d in _memory(wired).downloads] == ["prepared", "prepared"]
    assert [e["metadata"]["copy_reused"] for e in audit] == [False, True]
    assert audit[0]["metadata"]["copy_id"] == audit[1]["metadata"]["copy_id"]


def test_changed_figures_or_another_preparer_keep_a_new_copy(act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        client.get(URL)
        wired.add_document("BILL-B", "CT-S2-ELEC", [_elec(300, "Facility A", "Albany, NY")], org_id=str(ORG_A))
        client.get(URL)
        assert len(_memory(wired).copies) == 2
        act_as("org_admin", ORG_A)  # the workbook names who prepared it, so another person gets their own
        client.get(URL)
    assert len(_memory(wired).copies) == 3


def test_the_fingerprint_ignores_the_time_but_the_file_still_shows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    real = datetime

    class At(datetime):
        now_value = real(2026, 1, 1, 9, 5, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return cls.now_value

    monkeypatch.setattr(workpaper_export_service, "datetime", At)
    store = FakeStore()
    store.add_document("BILL-A", "CT-S2-ELEC", [_elec(1200, "Facility A", "Albany, NY")], org_id=str(ORG_A))
    from backend.tests.services.test_engagement_recalculation_service import _service

    service = _service(store)
    engagement = {**ENGAGEMENT}
    recalculation = service.recalculate(engagement, lambda r: True, {})
    register = service.evidence_register("ENG-1", lambda r: True)

    def build(by: str) -> tuple[bytes, str]:
        return workpaper_export_service.build_workbook_with_fingerprint(
            engagement=engagement, recalculation=recalculation, register=register, items=[], exported_by=by)

    first_bytes, first = build("a@example.com")
    At.now_value = real(2026, 3, 9, 17, 45, tzinfo=UTC)
    later_bytes, later = build("a@example.com")
    assert first == later and first_bytes != later_bytes
    assert build("b@example.com")[1] != first  # who prepared it is part of the content
    # where the time shows today: the Summary's Exported row
    summary = dict(load_workbook(io.BytesIO(first_bytes))["Summary"].iter_rows(min_row=2, values_only=True))
    assert summary["Exported"] == "2026-01-01 09:05 UTC by a@example.com"
    assert dict(load_workbook(io.BytesIO(later_bytes))["Summary"].iter_rows(min_row=2, values_only=True))[
        "Exported"] == "2026-03-09 17:45 UTC by a@example.com"


def test_when_the_copy_cannot_be_saved_nothing_is_sent_and_nothing_is_recorded(
        act_as, wired: FakeStore, audit, caplog) -> None:  # noqa: F811
    _memory(wired).fail_on_add = True
    act_as("org_member", ORG_A)
    with caplog.at_level(logging.ERROR), TestClient(app) as client:
        response = client.get(URL)
    assert response.status_code == 503 and response.headers["retry-after"] == "5"
    assert response.headers["content-type"].startswith("application/json")
    assert "not downloaded" in response.json()["detail"] and "try again" in response.json()["detail"]
    assert _memory(wired).copies == [] and _memory(wired).downloads == [] and audit == []
    assert "workpaper download refused" in caplog.text  # a missing record is never silent
    _memory(wired).fail_on_add = False
    with TestClient(app) as client:
        assert client.get(URL).status_code == 200  # a retry works


def test_when_the_audit_event_cannot_be_saved_nothing_is_sent_either(
        act_as, wired: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    async def broken(db, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise RuntimeError("audit log is down")

    monkeypatch.setattr(recalculation_api, "write_audit_event", broken)
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        response = client.get(URL)
    assert response.status_code == 503 and "attachment" not in response.headers.get("content-disposition", "")


def test_a_workpaper_over_the_size_limit_is_refused_with_a_clear_message(
        act_as, wired: FakeStore, audit, monkeypatch: pytest.MonkeyPatch, caplog) -> None:  # noqa: F811
    monkeypatch.setattr(recalculation_api, "get_settings", lambda: SimpleNamespace(
        git_sha="x", workpaper_copy_max_mb=50, workpaper_copy_max_bytes=1000))
    act_as("org_member", ORG_A)
    with caplog.at_level(logging.ERROR), TestClient(app) as client:
        response = client.get(URL)
    assert response.status_code == 413
    assert "larger than the 50 MB" in response.json()["detail"] and "contact support" in response.json()["detail"]
    assert _memory(wired).copies == [] and audit == []
    assert "too large to keep" in caplog.text


def test_a_hostile_engagement_name_gives_a_safe_short_file_name(
        act_as, wired: FakeStore, audit, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    for name in ("=HYPERLINK(\"http://x\")" * 20, "A" * 5000, "..\\..\\evil\"\r\nX-Injected: 1", "@SUM(1+1)", "///", ""):
        monkeypatch.setitem(ENGAGEMENT, "name", name or None)
        act_as("org_member", ORG_A)
        with TestClient(app) as client:
            response = client.get(URL)
        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        file_name = disposition.split('filename="')[1].rstrip('"')
        assert len(file_name) <= 80 + len(" workpaper 2026-11-25.xlsx") and file_name.endswith(".xlsx")
        assert all(c.isalnum() or c in " ._-" for c in file_name) and not file_name.startswith((" ", ".", "-", "_"))
        assert "X-Injected" not in response.headers and "\n" not in disposition
        summary = dict(load_workbook(io.BytesIO(response.content))["Summary"].iter_rows(min_row=2, values_only=True))
        assert summary["Engagement"] == name or name == ""  # written as text, never a formula
    first_cell = load_workbook(io.BytesIO(response.content))["Summary"]["B2"]
    assert first_cell.data_type != "f"


def test_the_list_is_newest_first_paged_and_counts_downloads(act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        assert client.get(COPIES).json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
        for n in range(3):  # three different workpapers
            wired.add_document(f"B{n}", "CT-S2-ELEC", [_elec(100 + n, "Facility A", "Albany, NY")], org_id=str(ORG_A))
            client.get(URL)
        client.get(URL)  # the same as the last: a download, not a copy
        body = client.get(COPIES).json()
        assert body["total"] == 3 and [i["downloads"] for i in body["items"]] == [2, 1, 1]
        newest = body["items"][0]
        assert set(newest) == {"id", "created_at", "prepared_by", "file_name", "size_bytes", "sha256", "app_version",
                               "downloads"}
        assert newest["sha256"] == _memory(wired).copies[-1][0].sha256 and "content" not in newest
        page = client.get(COPIES, params={"limit": 1, "offset": 1}).json()
        assert page["total"] == 3 and [i["id"] for i in page["items"]] == [body["items"][1]["id"]]
        assert client.get(COPIES, params={"offset": 50}).json()["items"] == []
        for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}):
            assert client.get(COPIES, params=bad).status_code == 422


def test_a_kept_copy_downloads_byte_for_byte_and_the_download_is_recorded(
        act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    user = act_as("org_member", ORG_A)
    with TestClient(app) as client:
        live = client.get(URL)
        copy_id = client.get(COPIES).json()["items"][0]["id"]
        kept = client.get(f"{COPIES}/{copy_id}/download")
    assert kept.status_code == 200 and kept.content == live.content
    assert kept.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert kept.headers["content-disposition"] == live.headers["content-disposition"]
    assert [d["kind"] for d in _memory(wired).downloads] == ["prepared", "saved"]
    assert _memory(wired).downloads[1]["email"] == user.email
    event = audit[-1]
    assert event["event_type"] == "workpaper_copy_downloaded" and event["target_id"] == "ENG-1"
    assert event["metadata"] == {"copy_id": copy_id, "sha256": sha256_of(live.content), "size_bytes": len(live.content)}


def test_another_org_an_unknown_copy_and_a_bad_id_are_404(act_as, wired: FakeStore, audit) -> None:  # noqa: F811
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        client.get(URL)
        copy_id = client.get(COPIES).json()["items"][0]["id"]
        for path in (f"{COPIES}/{uuid.uuid4()}/download", f"{COPIES}/not-a-uuid/download",
                     "/v1/engagements/OTHER/workpaper-copies", f"/v1/engagements/OTHER/workpaper-copies/{copy_id}/download"):
            assert client.get(path).status_code == 404, path
    act_as("org_member", ORG_B)
    with TestClient(app) as client:
        assert client.get(COPIES).status_code == 404
        assert client.get(f"{COPIES}/{copy_id}/download").status_code == 404
    assert len(_memory(wired).downloads) == 1  # nothing was recorded for the refused requests


def test_signed_out_requests_are_refused(act_as, wired: FakeStore) -> None:  # noqa: F811
    act_as(None)
    with TestClient(app) as client:
        copy = str(uuid.uuid4())
        for path in (URL, COPIES, f"{COPIES}/{copy}/download"):
            assert client.get(path).status_code == 401, path
    assert _memory(wired).copies == []


def test_a_copy_that_no_longer_matches_its_checksum_is_not_sent(
        act_as, wired: FakeStore, audit, caplog) -> None:  # noqa: F811
    act_as("org_member", ORG_A)
    with TestClient(app) as client:
        client.get(URL)
        record, content = _memory(wired).copies[0]
        _memory(wired).copies[0] = (record, content[:-1] + bytes([content[-1] ^ 1]))  # one bit flipped
        with caplog.at_level(logging.ERROR):
            response = client.get(f"{COPIES}/{record.id}/download")
        # the same figures again would be served from that copy: the damaged file is not handed out; a new copy is kept
        again = client.get(URL)
    assert response.status_code == 500 and "no longer matches its checksum" in response.json()["detail"]
    assert "does not match its SHA-256" in caplog.text
    assert again.status_code == 200 and len(_memory(wired).copies) == 2
    assert sha256_of(again.content) == _memory(wired).copies[1][0].sha256
    assert all(d["kind"] != "saved" for d in _memory(wired).downloads)
