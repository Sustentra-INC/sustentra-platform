"""The assistant's read-only Methodology tools through the real app and Postgres RLS: an answer is built from the
stored suggestion, an honest one when no reason was stored, and another organization's engagement is refused.

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

from typing import Any

from backend.tests.db.test_engagements import BASE, call, create, pytestmark, seeded  # noqa: F401 - `seeded` is autouse
from backend.tests.db.test_methodology_review import suggest

REASON = "The report states it uses the operational control approach under 'Organizational boundary'."
APPROACH = {"value": "Operational Control", "quote": "we use the operational control approach.", "document_id": "doc-1",
            "file_name": "GHG statement.pdf", "source_reference": {"page_number": 4}, "origin": "ai",
            "model": "claude-secret-model-id", "request_id": "req-1", "suggested_at": "2026-11-11T09:00:00.000Z"}


def explain(engagement_id: str, q: str, token: str = "a_member") -> Any:
    return call("GET", f"{BASE}/{engagement_id}/methodology-assistant/explain?q={q}", token)


def summary(engagement_id: str, query: str = "", token: str = "a_member") -> Any:
    return call("GET", f"{BASE}/{engagement_id}/methodology-assistant/summary{query}", token)


def test_why_was_the_consolidation_approach_suggested_cites_the_stored_reason_quote_and_page() -> None:
    eid = create()["id"]
    suggest(eid, "consolidation_approach", {**APPROACH, "reason": REASON})
    response = explain(eid, "why was operational control suggested for the consolidation approach")
    assert response.status_code == 200
    (match,) = response.json()["matches"]
    item = match["explanation"]["items"][0]
    assert match["field_key"] == "consolidation_approach" and match["suggested_value"] == "Operational Control"
    assert item["reason"] == REASON
    assert item["quote"] == "we use the operational control approach." and item["page"] == 4
    assert item["file_name"] == "GHG statement.pdf" and match["ref"] == "doc:doc-1"
    assert "The wording matched: 'operational control' → Operational Control." in item["checks"]
    assert "claude-secret-model-id" not in response.text and '"model"' not in response.text


def test_a_suggestion_saved_without_a_reason_is_answered_honestly() -> None:
    eid = create()["id"]
    suggest(eid, "consolidation_approach", APPROACH)
    (match,) = explain(eid, "consolidation approach").json()["matches"]
    assert match["explanation"]["reason"] is None
    assert match["explanation"]["reason_note"] == "Reason not recorded for this suggestion. Re-read the reports to get one."
    assert match["explanation"]["items"][0]["quote"]  # the evidence is still there


def test_a_question_about_something_with_no_suggestion_says_so() -> None:
    eid = create()["id"]
    suggest(eid, "consolidation_approach", APPROACH)
    body = explain(eid, "why was the reporting period suggested").json()
    assert body["matches"] == [] and "No suggestion" in body["note"]
    assert explain(create()["id"], "consolidation approach").json()["matches"] == []  # an engagement with none


def test_the_summary_lists_what_sustentras_ai_found_and_can_be_limited_to_a_document() -> None:
    eid = create()["id"]
    suggest(eid, "consolidation_approach", {**APPROACH, "reason": REASON})
    rows = summary(eid).json()["suggestions"]
    assert [r["field_key"] for r in rows] == ["consolidation_approach"]
    assert rows[0]["file"] == "GHG statement.pdf" and rows[0]["location"] == "page 4" and rows[0]["reason_recorded"] is True
    assert summary(eid, "?document=statement").json()["count"] == 1
    other = summary(eid, "?document=invoice").json()
    assert other["suggestions"] == [] and "no stored suggestions" in other["note"]


def test_another_organizations_engagement_is_refused() -> None:
    eid = create()["id"]
    suggest(eid, "consolidation_approach", {**APPROACH, "reason": REASON})
    assert explain(eid, "consolidation", token="b_member").status_code == 404
    assert summary(eid, token="b_member").status_code == 404
