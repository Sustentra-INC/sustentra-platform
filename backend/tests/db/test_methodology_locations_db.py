"""GET methodology-review/documents/{id}/locations through the real app: each suggestion read from the
document is found on its cited page from the PDF's own text, and one that is not printed there is not located."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest

from backend.app.api import documents as documents_api
from backend.tests.db.test_engagements import ORG_A, create, pytestmark, seeded  # noqa: F401
from backend.tests.db.test_methodology_review import BASE, call, suggest

QUOTE = "Carbon dioxide (CO2) is reported."


class _Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def is_owned_by(self, uri: str, org: str) -> bool:
        return True

    def resolve_storage_uri(self, uri: str) -> Path:
        return self.path


class _Upload:
    def __init__(self, path: Path, org: Any) -> None:
        self.storage_service = _Storage(path)
        self.org = org

    def list_documents(self, engagement_id: str) -> list[dict[str, Any]]:
        return [{"document_id": "doc-1", "org_id": self.org, "storage_uri": "x", "file_name": "statement.pdf"}]


@pytest.fixture
def statement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pdf = fitz.open()
    for n in range(1, 6):
        page = pdf.new_page()
        page.insert_text((72, 100), QUOTE if n == 5 else f"Page {n} of the statement.", fontsize=11)
    path = tmp_path / "statement.pdf"
    pdf.save(path)
    pdf.close()
    monkeypatch.setattr(documents_api, "current_upload_service", lambda: _Upload(path, ORG_A))
    return path


def source(quote: str, page: int) -> dict[str, Any]:
    return {"value": "Yes", "quote": quote, "document_id": "doc-1", "file_name": "statement.pdf",
            "source_reference": {"page_number": page}, "origin": "ai", "model": "m", "request_id": "r",
            "suggested_at": "2026-11-11T09:00:00.000Z"}


def locations(engagement_id: str, document: str = "doc-1", token: str = "a_member") -> Any:
    return call("GET", f"{BASE}/{engagement_id}/methodology-review/documents/{document}/locations", token)


def test_a_quote_printed_on_the_cited_page_is_located_and_one_that_is_not_is_flagged(statement: Path) -> None:
    engagement = create()["id"]
    suggest(engagement, "gas:co2", source(QUOTE, 5))
    suggest(engagement, "gas:ch4", source("Methane (CH4) is reported.", 5))
    suggest(engagement, "gas:n2o", source(QUOTE, 2))  # printed, but not on the cited page
    response = locations(engagement)
    assert response.status_code == 200, response.text
    items = {i["field_id"]: i for i in response.json()["items"]}
    assert items["gas:co2"]["located"] is True and items["gas:co2"]["page"] == 5 and len(items["gas:co2"]["rects"]) >= 1
    assert all(0 <= r["x"] <= 1 and 0 <= r["y"] <= 1 for r in items["gas:co2"]["rects"])
    assert items["gas:ch4"]["located"] is False and items["gas:ch4"]["page"] == 5 and items["gas:ch4"]["rects"] == []
    assert items["gas:n2o"]["located"] is False and items["gas:n2o"]["page"] == 2


def test_only_suggestions_from_that_document_are_listed(statement: Path) -> None:
    engagement = create()["id"]
    other = {**source(QUOTE, 5), "document_id": "doc-2"}
    suggest(engagement, "gas:co2", other)
    assert locations(engagement).json()["items"] == []


def test_another_orgs_engagement_and_an_unknown_document_are_404(statement: Path) -> None:
    engagement = create()["id"]
    assert locations(engagement, token="b_member").status_code == 404
    assert locations(engagement, document="nope").status_code == 404
