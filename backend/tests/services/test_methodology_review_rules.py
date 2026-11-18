"""The methodology review's field catalog, value validation and action rules (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.services import methodology_review as m
from backend.app.services.request_service import Actor
from backend.app.services.workpaper_item_service import ITEM_KEY

ACTOR = Actor(user_id="u1", name="Ada Admin", login="ada@acme.test")
NOW = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
SUGGESTION = {"value": "Yes", "quote": "q", "document_id": "d", "file_name": "r.pdf", "source_reference": "p. 4",
              "origin": "ai", "model": "m", "request_id": "r", "suggested_at": "2026-11-11T09:00:00.000Z"}


def field(field_id: str) -> dict:
    found = m.catalog_field(field_id)
    assert found is not None
    return found


def test_catalog_has_every_field_with_a_valid_unique_key() -> None:
    ids = [f["field_id"] for f in m.CATALOG]
    assert len(ids) == len(set(ids)) == 22
    assert all(ITEM_KEY.match(i) for i in ids)
    for expected in ("reporting_period", "consolidation_approach", "category:scope1:fugitive",
                     "category:location:cooling", "category:market:steam", "category:biogenic:indirect",
                     "exclusion:materiality", "gwp", "calculation:process"):
        assert expected in ids
    groups = {g for g, _ in m.GROUPS}
    assert {f["group"] for f in m.CATALOG} <= groups
    assert field("consolidation_approach")["allowed"] == ["Equity Share", "Financial Control", "Operational Control"]
    assert field("category:scope1:process")["allowed"] == ["Yes", "No", "Not detected"]
    assert field("gwp")["allowed"] == {"set": ["AR4", "AR5", "AR6"], "horizon": ["100-year", "20-year"]}
    assert m.catalog_field("entity:abcd1234") is None


def test_row_ids_are_made_by_the_server_and_recognised() -> None:
    for group in m.ROW_GROUPS:
        row_id = m.new_row_id(group)
        assert ITEM_KEY.match(row_id)
        definition = m.row_field(row_id)
        assert definition is not None and definition["user_added"] is True
    assert m.row_field("entity:abcd1234")["kind"] == "entity"  # type: ignore[index]
    assert m.row_field("factor:scope2:abcd1234")["kind"] == "factor"  # type: ignore[index]
    for bad in ("entity:", "entity:UPPER1234", "factor:scope3:abcd1234", "reporting_period", "entity:ab"):
        assert m.row_field(bad) is None
    with pytest.raises(m.MethodologyInvalid):
        m.new_row_id("categories")


@pytest.mark.parametrize(("field_id", "good", "cleaned"), [
    ("reporting_period", "  2025-01-01 to 2025-12-31 ", "2025-01-01 to 2025-12-31"),
    ("exclusion:boundary", "", ""),
    ("consolidation_approach", "Equity Share", "Equity Share"),
    ("category:market:heating", "Not detected", "Not detected"),
    ("gwp", {"set": "AR6", "horizon": "20-year"}, {"set": "AR6", "horizon": "20-year"}),
])
def test_valid_values(field_id: str, good: object, cleaned: object) -> None:
    assert m.validate_value(field(field_id), good) == cleaned


@pytest.mark.parametrize(("field_id", "bad"), [
    ("reporting_period", 5),
    ("reporting_period", "x" * 4001),
    ("consolidation_approach", "Control"),
    ("consolidation_approach", None),
    ("category:scope1:mobile", ["Yes"]),
    ("gwp", {"set": "AR7", "horizon": "20-year"}),
    ("gwp", {"set": "AR5"}),
    ("gwp", "AR5"),
])
def test_invalid_values_are_refused_with_a_sentence(field_id: str, bad: object) -> None:
    with pytest.raises(m.MethodologyInvalid) as err:
        m.validate_value(field(field_id), bad)
    assert str(err.value).startswith(f"'{field(field_id)['label']}'")


def test_entity_and_factor_rows_validate() -> None:
    entity = m.row_field("entity:abcd1234")
    good = {"name": " Cascade Co. ", "facilities": ["Kent Cannery"], "equity_share_pct": 50.5,
            "financial_control": 100, "operational_control": "Yes"}
    assert m.validate_value(entity, good)["name"] == "Cascade Co."  # type: ignore[arg-type]
    for change in ({"name": " "}, {"facilities": "Kent"}, {"facilities": [""]}, {"equity_share_pct": 101},
                   {"equity_share_pct": True}, {"financial_control": -1}, {"financial_control": "5"},
                   {"operational_control": "Maybe"}, {"facilities": ["x"] * 51}):
        with pytest.raises(m.MethodologyInvalid):
            m.validate_value(entity, {**good, **change})  # type: ignore[arg-type]
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(entity, {**good, "extra": 1})  # type: ignore[arg-type]
    factor = m.row_field("factor:scope1:abcd1234")
    assert m.validate_value(factor, {"database": " EPA Hub ", "edition": ""}) == {"database": "EPA Hub", "edition": ""}  # type: ignore[arg-type]
    for bad in ({"database": "", "edition": "2025"}, {"database": "EPA", "edition": 5}, {"database": "EPA"}):
        with pytest.raises(m.MethodologyInvalid):
            m.validate_value(factor, bad)  # type: ignore[arg-type]


def test_accept_takes_the_suggestion_then_refuses_a_second_decision() -> None:
    f = field("category:scope1:stationary")
    record = {**m.new_record(f["field_id"]), "suggestion": SUGGESTION}
    accepted = m.accept(record, f, ACTOR, NOW)
    assert accepted["decision"] == {"status": "accepted", "value": "Yes",
                                    "by": {"name": "Ada Admin", "login": "ada@acme.test"},
                                    "at": "2026-11-11T09:30:00.000Z"}
    assert accepted["history"] == [{"at": "2026-11-11T09:30:00.000Z", "by": accepted["decision"]["by"],
                                    "action": "accept", "to": "Yes"}]
    assert record["decision"] is None  # the input is not changed
    for action in (lambda: m.accept(accepted, f, ACTOR, NOW), lambda: m.reject(accepted, f, "no", ACTOR, NOW)):
        with pytest.raises(m.MethodologyConflict, match="already accepted"):
            action()


def test_accept_with_nothing_to_take_is_refused_and_a_current_value_is_taken() -> None:
    f = field("reporting_period")
    with pytest.raises(m.MethodologyConflict, match="nothing to accept"):
        m.accept(m.new_record("reporting_period"), f, ACTOR, NOW)
    row = m.new_row("entity:abcd1234", ACTOR, NOW)
    entity = m.row_field("entity:abcd1234")
    with pytest.raises(m.MethodologyInvalid):  # the blank row has no name
        m.accept(row, entity, ACTOR, NOW)  # type: ignore[arg-type]
    filled = m.edit(row, entity, {**m.blank_value("entity:abcd1234"), "name": "Co"}, ACTOR, NOW)  # type: ignore[arg-type]
    reverted = m.revert(filled, entity, ACTOR, NOW)  # type: ignore[arg-type]
    assert reverted["decision"]["status"] == "pending"
    assert reverted["decision"]["value"] == m.blank_value("entity:abcd1234")  # an added row goes back to blank


def test_edit_works_from_any_state_and_history_keeps_from_and_to() -> None:
    f = field("consolidation_approach")
    record = m.new_record("consolidation_approach")
    first = m.edit(record, f, "Equity Share", ACTOR, NOW)
    second = m.edit(first, f, "Financial Control", ACTOR, NOW)
    assert second["decision"]["status"] == "edited" and second["decision"]["value"] == "Financial Control"
    assert [(h["action"], h.get("to")) for h in second["history"]] == [
        ("edit", "Equity Share"), ("edit", "Financial Control")]
    assert all("from" not in h for h in second["history"])
    rejected = m.reject(m.new_record("exclusion:inventory"), field("exclusion:inventory"), " not in report ", ACTOR, NOW)
    after = m.edit(rejected, field("exclusion:inventory"), "Backup generators", ACTOR, NOW)
    assert after["decision"]["status"] == "edited" and "reason" not in after["decision"]
    with pytest.raises(m.MethodologyInvalid):
        m.edit(record, f, "nope", ACTOR, NOW)


def test_reject_needs_a_reason_of_at_most_500_characters_and_keeps_no_value() -> None:
    f = field("category:biogenic:direct")
    record = {**m.new_record(f["field_id"]), "suggestion": {**SUGGESTION, "value": "No"}}
    for reason in (None, "", "   ", 5):
        with pytest.raises(m.MethodologyInvalid, match="reason is required"):
            m.reject(record, f, reason, ACTOR, NOW)
    with pytest.raises(m.MethodologyInvalid, match="at most 500"):
        m.reject(record, f, "x" * 501, ACTOR, NOW)
    rejected = m.reject(record, f, "x" * 500, ACTOR, NOW)
    assert rejected["decision"]["status"] == "rejected" and rejected["decision"]["value"] is None
    assert rejected["suggestion"] == record["suggestion"]  # the proposal stays on the record
    with pytest.raises(m.MethodologyConflict, match="already rejected"):
        m.accept(rejected, f, ACTOR, NOW)


def test_revert_returns_to_pending_and_is_refused_when_already_pending() -> None:
    f = field("calculation:approach")
    with pytest.raises(m.MethodologyConflict, match="already pending"):
        m.revert(m.new_record("calculation:approach"), f, ACTOR, NOW)
    edited = m.edit(m.new_record("calculation:approach"), f, "Activity x factor", ACTOR, NOW)
    reverted = m.revert(edited, f, ACTOR, NOW)
    assert m.status_of(reverted) == "pending" and reverted["decision"]["value"] is None
    assert [h["action"] for h in reverted["history"]] == ["edit", "revert"]
    assert m.status_of(m.new_record("gwp")) == "pending"


def test_only_reviewer_added_rows_can_be_removed() -> None:
    entity = m.row_field("entity:abcd1234")
    row = m.new_row("entity:abcd1234", ACTOR, NOW)
    assert row["user_added"] is True and row["decision"]["status"] == "pending"
    removed = m.remove(row, entity, ACTOR, NOW)  # type: ignore[arg-type]
    assert removed["removed"] is True and removed["history"][-1]["action"] == "remove_row"
    with pytest.raises(m.MethodologyConflict, match="Reject it instead"):
        m.remove({**m.new_record("entity:abcd1234"), "suggestion": SUGGESTION}, entity, ACTOR, NOW)  # type: ignore[arg-type]


def test_public_shape() -> None:
    row = m.new_row("factor:scope1:abcd1234", ACTOR, NOW)
    assert set(m.public(row)) == {"field_id", "suggestion", "decision", "history", "user_added"}
    assert m.public(m.new_record("gwp"))["user_added"] is False
