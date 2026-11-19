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
    assert len(ids) == len(set(ids)) == 27
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
    ("exclusion:boundary", "  2025-01-01 to 2025-12-31 ", "2025-01-01 to 2025-12-31"),
    ("exclusion:boundary", "", ""),
    ("consolidation_approach", "Equity Share", "Equity Share"),
    ("category:market:heating", "Not detected", "Not detected"),
    ("gwp", {"set": "AR6", "horizon": "20-year"}, {"set": "AR6", "horizon": "20-year"}),
])
def test_valid_values(field_id: str, good: object, cleaned: object) -> None:
    assert m.validate_value(field(field_id), good) == cleaned


@pytest.mark.parametrize(("field_id", "bad"), [
    ("exclusion:boundary", 5),
    ("exclusion:boundary", "x" * 4001),
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
    f = field("exclusion:boundary")
    with pytest.raises(m.MethodologyConflict, match="nothing to accept"):
        m.accept(m.new_record("exclusion:boundary"), f, ACTOR, NOW)
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


# --- reporting period: two dates -------------------------------------------------------------

def test_the_reporting_period_is_two_dates() -> None:
    f = field("reporting_period")
    assert f["kind"] == "date_range"
    assert m.validate_value(f, {"start": "2025-01-01", "end": "2025-12-31"}) == {"start": "2025-01-01", "end": "2025-12-31"}
    assert m.validate_value(f, {"start": "2024-02-29", "end": "2024-02-29"})["end"] == "2024-02-29"  # one day, leap day


@pytest.mark.parametrize("bad", [
    {"start": "2025-12-31", "end": "2025-01-01"},  # end before start
    {"start": "2025-13-45", "end": "2025-12-31"},  # not a date
    {"start": "2025-01-01", "end": "2025-02-30"},  # not a date
    {"start": "2023-02-29", "end": "2023-12-31"},  # not a leap year
    {"start": "2025-1-1", "end": "2025-12-31"},  # not YYYY-MM-DD
    {"start": "٢٠٢٥-01-01", "end": "2025-12-31"},  # Arabic-Indic digits
    {"start": "2025-01-01"},  # one date
    {"start": "2025-01-01", "end": None},
    {"start": "2025-01-01", "end": "2025-12-31", "note": "x"},
    "January 1 to December 31, 2025",  # an old text value cannot be saved again as is
    5,
    None,
])
def test_a_bad_reporting_period_is_refused_with_a_sentence(bad: object) -> None:
    with pytest.raises(m.MethodologyInvalid) as error:
        m.validate_value(field("reporting_period"), bad)
    assert error.value.args[0].startswith("'Reporting period': ")


def test_an_old_text_value_has_a_value_and_survives_other_actions() -> None:
    old = {**m.new_record("reporting_period"),
           "decision": {"status": "edited", "value": "FY2024 (1 janvier – 31 décembre)", "by": {}, "at": "x"}}
    assert m.has_value(old) and m.display_state(old, m.new_meta()) == "has_value"
    assert m.public(old)["decision"]["value"] == "FY2024 (1 janvier – 31 décembre)"
    edited = m.edit(old, field("reporting_period"), {"start": "2024-01-01", "end": "2024-12-31"}, ACTOR, NOW)
    assert edited["decision"]["value"] == {"start": "2024-01-01", "end": "2024-12-31"}


# --- estimation method: one entry per source type ---------------------------------------------

def entry(source: str, method: str) -> dict[str, str]:
    return {"source_type": source, "method": method}


def test_the_estimation_method_is_an_optional_list_of_entries() -> None:
    f = field("calculation:estimation")
    assert f["kind"] == "entry_list" and f["required"] is False and f["group"] == "calculation"
    assert [p["key"] for p in f["parts"]] == ["source_type", "method"]
    good = [entry("  Utility invoices ", "Average of the other months"), entry("Fuel cards", "Prior-year use × 1,02")]
    assert m.validate_value(f, good) == [entry("Utility invoices", "Average of the other months"),
                                         entry("Fuel cards", "Prior-year use × 1,02")]
    assert m.validate_value(f, []) == []  # removing every entry is allowed


@pytest.mark.parametrize("bad", [
    "text", None, {"a": 1},
    [entry("Utility invoices", "a"), entry("  utility   INVOICES ", "b")],  # one entry per source type
    [entry("", "a")], [entry("Fuel", "  ")],  # blank
    [entry("x" * 61, "a")], [entry("Fuel", "x" * 301)],  # too long
    [entry(f"Source {i}", "a") for i in range(11)],  # too many
    [{"source_type": "Fuel"}], [{"source_type": "Fuel", "method": "a", "extra": "b"}], ["Fuel: average"],
    [entry("Fuel", "a\x00b")], [entry("Fuel", 5)],
])
def test_a_bad_entry_list_is_refused_with_a_sentence(bad: object) -> None:
    with pytest.raises(m.MethodologyInvalid) as error:
        m.validate_value(field("calculation:estimation"), bad)
    assert error.value.args[0].startswith("'Estimation method for missing data': ")


def test_a_suggestion_keeps_the_quote_of_each_entry_bounded() -> None:
    f = field("calculation:estimation")
    ref = {"page_number": 3, "sheet_name": "S" * 300, "cell_or_range": "B12", "text_snippet": "s" * 500,
           "bounding_box": {"x": 1}}
    evidence = [{"label": f"Source {i}", "quote": "q" * 1500, "document_id": "d1", "file_name": "r.pdf",
                 "source_reference": ref} for i in range(10)]
    value = [entry(f"Source {i}", "Average") for i in range(10)]
    bounded = m.bound_suggestion(f, {**SUGGESTION, "value": value, "evidence": evidence})
    assert len(bounded["value"]) == len(bounded["evidence"]) and bounded["value"] == value[:len(bounded["value"])]
    assert all(len(e["quote"]) == m.MAX_EVIDENCE_QUOTE and e["quote_truncated"] is True for e in bounded["evidence"])
    assert all(set(e["source_reference"]) == {"page_number", "sheet_name", "cell_or_range"}
               and len(e["source_reference"]["sheet_name"]) == 100 for e in bounded["evidence"])  # no snippet or box
    assert m.payload_size({"e": bounded["evidence"]}) <= m.MAX_EVIDENCE_BYTES
    assert bounded.get("entries_omitted", 0) == 10 - len(bounded["value"])
    # a value entry whose quote did not come with it is never kept
    short = m.bound_suggestion(f, {**SUGGESTION, "value": value[:3], "evidence": evidence[:1]})
    assert short["value"] == value[:1] and short["entries_omitted"] == 2
    with pytest.raises(m.MethodologyInvalid):
        m.bound_suggestion(f, {**SUGGESTION, "value": value[:2], "evidence": ["junk", 5, None]})


def test_ten_cjk_entries_with_long_quotes_never_leave_an_entry_without_its_quote() -> None:
    f = field("calculation:estimation")
    cjk = "\u71c3\u6599\u8bb0\u5f55" * 250  # 1,000 characters, three bytes each
    value = [entry(f"\u71c3\u6599 {i}", "\u5e73\u5747" * 75) for i in range(10)]
    evidence = [{"label": v["source_type"], "quote": cjk, "document_id": "d1", "file_name": "r.pdf",
                 "source_reference": {"page_number": 1}} for v in value]
    bounded = m.bound_suggestion(f, {**SUGGESTION, "value": value, "evidence": evidence})
    kept = len(bounded["value"])
    assert 1 <= kept < 10 and kept == len(bounded["evidence"]) and bounded["entries_omitted"] == 10 - kept
    assert [v["source_type"] for v in bounded["value"]] == [e["label"] for e in bounded["evidence"]]
    assert all(e["quote"] for e in bounded["evidence"])
    # the record still fits with a decision of the same size on the same field
    record = {**m.new_record(f["field_id"]), "suggestion": bounded,
              "decision": {"status": "edited", "value": value, "by": {"name": "A", "login": "a"}, "at": "x"}}
    assert m.payload_size(record) < 32 * 1024
    ascii_value = [entry(f"Source {i}", "m" * 300) for i in range(10)]
    ascii_ev = [{"label": v["source_type"], "quote": "q" * 1000, "document_id": "d1", "file_name": "r.pdf"} for v in ascii_value]
    assert len(m.bound_suggestion(f, {**SUGGESTION, "value": ascii_value, "evidence": ascii_ev})["value"]) == 10


# --- multi-select rows: Scope 2 instrument types, source records ------------------------------

def pick(option: str, wording: str = "") -> dict[str, str]:
    return {"option": option, "wording": wording}


def test_the_two_multiselect_fields_have_their_options_and_are_optional() -> None:
    instruments = field("scope2:instruments")
    assert instruments["kind"] == "multiselect" and instruments["required"] is False and instruments["group"] == "scope2"
    assert instruments["allowed"] == ["RECs or other energy attribute certificates", "PPA or VPPA",
                                      "Green tariff or utility program", "Supplier-specific rate", "Residual mix", "None"]
    assert instruments["shown_if_yes"] == [f"category:market:{k}" for k in ("electricity", "heating", "steam", "cooling")]
    records = field("calculation:source_records")
    assert records["free"] is True and records["required"] is False and "None" not in records["allowed"]


def test_options_are_checked_against_the_list_and_keep_the_companys_wording() -> None:
    f = field("scope2:instruments")
    good = [pick("ppa or vppa", "  our PPA with W\u00e4rmewerke K\u00e4serei "), pick("Residual mix")]
    assert m.validate_value(f, good) == [pick("PPA or VPPA", "our PPA with W\u00e4rmewerke K\u00e4serei"), pick("Residual mix")]
    assert m.validate_value(f, [pick("None")]) == [pick("None")] and m.validate_value(f, []) == []
    for bad in ([pick("Carbon offsets")], [pick("PPA or VPPA"), pick(" ppa  OR vppa ")], [pick("None"), pick("PPA or VPPA")],
                [pick("PPA or VPPA", "x" * 201)], [pick("")], [{"option": "PPA or VPPA"}], ["PPA or VPPA"], "PPA or VPPA", None,
                [pick("PPA or VPPA", "a\x00b")]):
        with pytest.raises(m.MethodologyInvalid) as error:
            m.validate_value(f, bad)
        assert error.value.args[0].startswith("'Scope 2 instrument types (market-based)': ")


def test_source_records_take_free_additions_up_to_a_limit() -> None:
    f = field("calculation:source_records")
    value = [pick("utility invoices"), pick("Lieferscheine \u2013 \u7eb8\u8d28\u8bb0\u5f55", "Papier-Belege"), pick("Meter readings")]
    assert [e["option"] for e in m.validate_value(f, value)] == ["Utility invoices", "Lieferscheine \u2013 \u7eb8\u8d28\u8bb0\u5f55", "Meter readings"]
    ten = [pick(f"Other {i}") for i in range(m.MAX_FREE_OPTIONS)]
    assert len(m.validate_value(f, ten)) == 10
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(f, [*ten, pick("Other 10")])
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(f, [pick("Other"), pick("OTHER")])  # a free option twice
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(f, [pick("o" * 61)])


def rec(field_id: str, value: object, status: str = "accepted") -> dict:
    return {"field_id": field_id, "suggestion": None, "history": [],
            "decision": {"status": status, "value": value, "by": {}, "at": "x"}}


def test_market_based_scope2_is_reported_when_a_market_category_is_yes() -> None:
    market = m.MARKET_CATEGORY_IDS
    sugg = {"field_id": market[1], "decision": None, "history": [], "suggestion": {"value": "Yes"}}
    assert not m.market_based_reported({})
    assert m.market_based_reported({market[0]: rec(market[0], "Yes")})
    assert m.market_based_reported({market[2]: rec(market[2], "Yes", "edited")})
    assert m.market_based_reported({market[1]: sugg})  # undecided, Claude said Yes
    assert not m.market_based_reported({market[0]: rec(market[0], "No")})
    assert not m.market_based_reported({market[0]: rec(market[0], "Not detected")})
    assert not m.market_based_reported({market[0]: rec(market[0], None, "rejected")})
    assert not m.market_based_reported({market[1]: {**sugg, "decision": rec(market[1], "No")["decision"]}})  # decided No beats a Yes suggestion
    assert not m.market_based_reported({market[1]: {**sugg, "decision": rec(market[1], None, "rejected")["decision"]}})


def test_the_instrument_row_shows_on_a_market_yes_and_a_value_or_add_an_item_overrides_it() -> None:
    f = field("scope2:instruments")
    blank = m.new_record(f["field_id"])
    meta = m.new_meta()
    market = m.MARKET_CATEGORY_IDS
    assert not m.is_shown(f, blank, meta, {})
    assert m.is_shown(f, blank, meta, {market[0]: rec(market[0], "Yes")})
    assert m.is_shown(f, rec(f["field_id"], [pick("None")]), meta, {})  # it has a value
    assert m.is_shown(f, blank, {**meta, "revealed": [f["field_id"]]}, {})  # the reviewer added it
    assert not m.is_shown(field("calculation:source_records"), blank, meta, {market[0]: rec(market[0], "Yes")})
