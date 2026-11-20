"""Why Sustentra's AI suggested a Methodology value: the reason kept with it and the checks built from stored data."""

from __future__ import annotations

from typing import Any

from backend.app.services import methodology_explanation as ex
from backend.app.services import methodology_prefill as mp
from backend.app.services import methodology_review as rules
from backend.app.services.ai_reason import MAX_REASON, NO_REASON
from backend.tests.services.test_methodology_prefill import answer, check, cite, doc

REASON = "The report states it uses the operational control approach under 'Organizational boundary'."


def stored(output: mp.PrefillOutput, documents: list[mp.PrefillDocument] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The field and the suggestion as they are stored: through verify and the store's own bounding."""

    kept, dropped = check(output, documents)
    assert not dropped, dropped
    item = kept[0]
    field_id = item.field_id or f"{rules.ROW_GROUPS[item.row_group or ''][0]}:abcd"
    field = rules.catalog_field(field_id) or rules.row_field(field_id)
    assert field is not None
    return field, rules.bound_suggestion(field, item.suggestion)


def test_the_reason_is_stored_with_the_suggestion_and_shown_with_its_evidence_and_checks() -> None:
    field, suggestion = stored(answer(choices=[{"field_id": "consolidation_approach", "value": "Operational Control",
                                                **cite("L2", "operational control approach"), "reason": REASON}]))
    assert suggestion["reason"] == REASON
    shown = ex.explain(field, suggestion)
    assert shown is not None and shown["reason"] == REASON and shown["reason_note"] is None
    (item,) = shown["items"]
    assert item["quote"] == "operational control approach" and item["file_name"] == "report.pdf" and item["page"] == 1
    assert item["document_id"] == "DOC-1"
    assert any("found on the document (report.pdf, page 1)" in c for c in item["checks"])
    assert "The wording matched: 'operational control' → Operational Control." in item["checks"]
    assert shown["model"] == "claude-x" and shown["read_at"] == "2026-11-11T09:00:00.000Z"


def test_a_reason_is_cut_to_240_characters_and_one_line() -> None:
    field, suggestion = stored(answer(choices=[{"field_id": "consolidation_approach", "value": "Operational Control",
                                                **cite("L2", "operational control approach"),
                                                "reason": "The report\nstates it. " + "word " * 100}]))
    assert len(suggestion["reason"]) <= MAX_REASON and "\n" not in suggestion["reason"]


def test_a_suggestion_saved_without_a_reason_says_so_and_still_shows_evidence_and_checks() -> None:
    field, suggestion = stored(answer(choices=[{"field_id": "consolidation_approach", "value": "Operational Control",
                                                **cite("L2", "operational control approach")}]))
    assert "reason" not in suggestion
    shown = ex.explain(field, suggestion)
    assert shown is not None and shown["reason"] is None and shown["reason_note"] == NO_REASON
    assert shown["items"][0]["quote"] and shown["items"][0]["checks"]
    assert "Reason not recorded for this suggestion. Re-read the reports to get one." in ex.as_text(shown)


def test_no_suggestion_has_no_explanation() -> None:
    assert ex.explain(rules.catalog_field("consolidation_approach") or {}, None) is None


def test_an_option_says_which_wording_matched() -> None:
    documents = [doc([(1, "Energy attribute certificates: we buy RECs and sign a PPA for our power.")])]
    field, suggestion = stored(answer(selections=[
        {"field_id": "scope2:instruments", "option": "PPA or VPPA", "wording": "", **cite("L1", "we buy RECs and sign a PPA for our power", "D1"),
         "reason": "The report says it signs a PPA."}]), documents)
    shown = ex.explain(field, suggestion)
    assert shown is not None
    assert "The wording matched: 'ppa' → PPA or VPPA." in shown["items"][0]["checks"]
    assert shown["items"][0]["reason"] == "The report says it signs a PPA." and shown["items"][0]["label"] == "PPA or VPPA"


def test_an_implied_start_date_says_so_and_how() -> None:
    documents = [doc([(1, "GHG inventory"), (1, "Emissions for the year ended December 31, 2024.")])]
    field, suggestion = stored(answer(periods=[{
        "start": "2024-01-01", "end": "2024-12-31", "title_line": "", "title_quote": "",
        **cite("L2", "for the year ended December 31, 2024", "D1"), "reason": "The report names the year it ended."}]), documents)
    shown = ex.explain(field, suggestion)
    assert shown is not None
    item = shown["items"][0]
    assert "The end date, 2024-12-31, is printed in the quote." in item["checks"]
    assert len(item["implied"]) == 1 and "Start date implied" in item["implied"][0]
    assert "2024-01-01" in item["implied"][0] and "year ended 2024-12-31" in item["implied"][0]


def test_a_period_with_both_dates_printed_implies_nothing() -> None:
    field, suggestion = stored(answer(periods=[{
        "start": "2024-01-01", "end": "2024-12-31", "title_line": "", "title_quote": "",
        **cite("L3", "January 1 to December 31, 2024")}]))
    shown = ex.explain(field, suggestion)
    assert shown is not None and shown["items"][0]["implied"] == []
    assert "The start date, 2024-01-01, is printed in the quote." in shown["items"][0]["checks"]


def test_a_year_taken_from_the_title_says_so_and_applies_the_title_year_rule() -> None:
    documents = [doc([(1, "2023 Statement of GHG Emissions"), (1, "Emissions are reported for the calendar year.")])]
    field, suggestion = stored(answer(periods=[{
        "start": "2023-01-01", "end": "2023-12-31", "title_line": "L1", "title_quote": "2023 Statement of GHG Emissions",
        **cite("L2", "reported for the calendar year", "D1")}]), documents)
    shown = ex.explain(field, suggestion)
    assert shown is not None and len(shown["items"]) == 2
    first, title = shown["items"]
    assert "taken from the document's title" in first["implied"][0] and "2023-01-01 to 2023-12-31" in first["implied"][0]
    assert title["quote"] == "2023 Statement of GHG Emissions"
    assert any("title-year rule" in c for c in title["checks"])


def test_every_kind_of_stored_suggestion_explains_without_an_error() -> None:
    cases = [
        answer(gwp=[{"set": "AR5", "horizon": "100-year", "applies_to": "", **cite("L8", "IPCC Fifth Assessment Report (AR5) 100-year GWP values")}]),
        answer(entities=[{"name": "Acme Foods Kent LLC", "facilities": [], "equity_share_pct": 51, "financial_control": 51,
                          **cite("L4", "Acme Foods Kent LLC: equity share 51%, financial control 51%, operational control: yes")}]),
        answer(factors=[{"scope": "scope1", "database": "U.S. EPA GHG Emission Factors Hub", "edition": "2024",
                         **cite("L6", "U.S. EPA GHG Emission Factors Hub, 2024 edition")}]),
        answer(texts=[{"field_id": "boundary:entities", "value": "We consolidate our emissions using the operational control approach.",
                       **cite("L2", "We consolidate our emissions using the operational control approach.")}]),
    ]
    for output in filter(None, cases):
        field, suggestion = stored(output)
        shown = ex.explain(field, suggestion)
        assert shown is not None and shown["items"][0]["checks"], field["field_id"]


def test_the_assistants_answer_never_carries_the_model_and_matches_by_field_or_value() -> None:
    from backend.app.services import methodology_assistant as assistant

    field, suggestion = stored(answer(choices=[{"field_id": "consolidation_approach", "value": "Operational Control",
                                                **cite("L2", "operational control approach"), "reason": REASON}]))
    records = {"consolidation_approach": {"field_id": "consolidation_approach", "suggestion": suggestion, "decision": None}}
    for query in ("why was operational control suggested for the consolidation approach", "operational control"):
        (match,) = assistant.explain_matches(records, query)["matches"]
        assert match["explanation"]["reason"] == REASON and "model" not in match["explanation"]
    assert assistant.explain_matches(records, "why was the reporting period suggested")["matches"] == []
    assert assistant.explain_matches(records, field_id="reporting_period")["matches"] == []
