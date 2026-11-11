"""Methodology review: sizes, null characters, suggestions and reverting added rows (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.services import methodology_review as m
from backend.app.services.request_service import Actor
from backend.app.services.workpaper_item_service import MAX_PAYLOAD_BYTES, payload_size

ACTOR = Actor(user_id="u1", name="Ada Admin", login="ada@acme.test")
NOW = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
SUGGESTION = {"value": "Yes", "quote": "q", "document_id": "d", "file_name": "r.pdf", "source_reference": "p. 4",
              "origin": "ai", "model": "m", "request_id": "r", "suggested_at": "2026-11-11T09:00:00.000Z"}


def field(field_id: str) -> dict:
    found = m.catalog_field(field_id)
    assert found is not None
    return found


def test_text_with_a_null_character_is_refused() -> None:
    with pytest.raises(m.MethodologyInvalid, match="null character"):
        m.validate_value(field("reporting_period"), "a\x00b")
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(m.row_field("entity:abcd1234"), {  # type: ignore[arg-type]
            "name": "a\x00", "facilities": [], "equity_share_pct": 1, "financial_control": 1,
            "operational_control": "Yes"})


def test_payload_size_counts_utf8_bytes() -> None:
    assert payload_size({"a": "é"}) == len('{"a": "é"}'.encode())
    assert payload_size({"a": "😀"}) == len('{"a": "😀"}'.encode())


def test_with_suggestion_sets_only_the_suggestion_and_validates_it() -> None:
    f = field("category:scope1:stationary")
    decided = m.edit(m.new_record(f["field_id"]), f, "No", ACTOR, NOW)
    proposed = m.with_suggestion(decided, f, {**SUGGESTION, "value": "Yes"})
    assert proposed["suggestion"]["value"] == "Yes"
    assert proposed["decision"] == decided["decision"] and proposed["history"] == decided["history"]
    assert decided["suggestion"] is None
    with pytest.raises(m.MethodologyInvalid):
        m.with_suggestion(decided, f, {**SUGGESTION, "value": "Maybe"})


def test_a_worst_case_record_fits_and_history_is_trimmed_to_make_room() -> None:
    f = field("calculation:approach")
    big = "😀" * m.MAX_TEXT  # 4 bytes per character
    record = {**m.new_record(f["field_id"]), "suggestion": {**SUGGESTION, "value": big, "quote": "😀" * 1000}}
    for _ in range(80):
        record = m.edit(record, f, big, ACTOR, NOW)
        assert payload_size(record) <= MAX_PAYLOAD_BYTES
    assert 0 < len(record["history"]) <= m.MAX_HISTORY
    assert m.revert(record, f, ACTOR, NOW)["decision"]["status"] == "pending"


def test_history_keeps_only_the_newest_50_events() -> None:
    f = field("reporting_period")
    record = m.new_record("reporting_period")
    for n in range(70):
        record = m.edit(record, f, f"p{n}", ACTOR, NOW)
    assert len(record["history"]) == 50 and record["history"][-1]["to"] == "p69"


def test_the_largest_entity_value_fits_twice_with_a_quote() -> None:
    entity = m.row_field("entity:abcd1234")
    value = {"name": "😀" * 200, "facilities": ["😀" * m.MAX_FACILITY] * m.MAX_FACILITIES,
             "equity_share_pct": 100, "financial_control": 100, "operational_control": "Yes"}
    record = {**m.new_row("entity:abcd1234", ACTOR, NOW),
              "suggestion": {**SUGGESTION, "value": value, "quote": "😀" * 1000}}
    edited = m.edit(record, entity, value, ACTOR, NOW)  # type: ignore[arg-type]
    assert payload_size(edited) <= MAX_PAYLOAD_BYTES


def test_reverting_an_added_row_restores_the_blank_value() -> None:
    row = m.new_row("factor:scope2:abcd1234", ACTOR, NOW)
    definition = m.row_field("factor:scope2:abcd1234")
    edited = m.edit(row, definition, {"database": "EPA", "edition": "1"}, ACTOR, NOW)  # type: ignore[arg-type]
    reverted = m.revert(edited, definition, ACTOR, NOW)  # type: ignore[arg-type]
    assert reverted["decision"]["value"] == {"database": "", "edition": ""}
