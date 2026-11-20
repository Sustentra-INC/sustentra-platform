"""The methodology review's field catalog, value validation and action rules (pure)."""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime

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
    assert len(ids) == len(set(ids)) == 36  # 34 + scopes:covered + boundary:entities
    assert all(ITEM_KEY.match(i) for i in ids)
    for expected in ("reporting_period", "consolidation_approach", "category:scope1:fugitive",
                     "category:location:cooling", "category:market:steam", "category:biogenic:indirect",
                     "exclusion:materiality", "gwp", "calculation:process"):
        assert expected in ids
    groups = {g for g, _ in m.GROUPS}
    assert {f["group"] for f in m.CATALOG} <= groups
    assert field("consolidation_approach")["allowed"] == ["Equity Share", "Financial Control", "Operational Control"]
    assert field("category:scope1:process")["allowed"] == ["Yes", "No", "Not detected"]
    assert field("gwp")["allowed"] == {"set": ["AR4", "AR5", "AR6"], "horizon": ["100-year", "20-year", "500-year", "Not stated"]}
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
            "financial_control": 100, "included": "Yes"}
    assert m.validate_value(entity, good)["name"] == "Cascade Co."  # type: ignore[arg-type]
    for change in ({"name": " "}, {"facilities": "Kent"}, {"facilities": [""]}, {"equity_share_pct": 101},
                   {"equity_share_pct": True}, {"financial_control": -1}, {"financial_control": "5"},
                   {"included": "Maybe"}, {"facilities": ["x"] * 51}):
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
    assert set(m.public(row)) == {"field_id", "suggestion", "decision", "history", "value_history", "user_added"}
    assert m.public(m.new_record("gwp"))["user_added"] is False


# --- reporting period: two dates -------------------------------------------------------------

def test_the_reporting_period_is_two_dates() -> None:
    f = field("reporting_period")
    assert f["kind"] == "date_range"
    assert m.validate_value(f, {"start": "2025-01-01", "end": "2025-12-31"}) == {
        "start": "2025-01-01", "end": "2025-12-31", "basis": "Calendar year"}
    assert m.validate_value(f, {"start": "2024-02-29", "end": "2024-02-29"})["end"] == "2024-02-29"  # one day, leap day


def test_the_period_basis_is_derived_from_the_two_dates() -> None:
    f = field("reporting_period")
    derive = lambda a, b: m.validate_value(f, {"start": a, "end": b})["basis"]  # noqa: E731
    assert derive("2024-01-01", "2024-12-31") == "Calendar year"
    assert derive("2024-07-01", "2025-06-30") == "Fiscal year"
    assert derive("2023-03-01", "2024-02-29") == "Fiscal year"  # a leap day does not break the year
    assert derive("2024-01-01", "2024-06-30") == "Not stated"  # six months: neither
    assert derive("2024-02-29", "2024-02-29") == "Not stated"
    assert m.year_start_for(date(2025, 2, 28)) == date(2024, 3, 1)
    assert m.year_start_for(date(2024, 2, 28)) == date(2023, 3, 1)


def test_the_implied_flags_are_kept_only_when_true_and_a_valid_basis_is_kept_else_derived() -> None:
    f = field("reporting_period")
    kept = m.validate_value(f, {"start": "2024-01-01", "end": "2024-12-31", "start_implied": True, "basis": "Fiscal year"})
    assert kept == {"start": "2024-01-01", "end": "2024-12-31", "start_implied": True, "basis": "Fiscal year"}  # the quote said fiscal
    assert m.validate_value(f, {"start": "2024-01-01", "end": "2024-12-31", "basis": "Moon cycle"})["basis"] == "Calendar year"
    assert "start_implied" not in m.validate_value(f, {"start": "2024-01-01", "end": "2024-12-31", "start_implied": False})
    both = {"start": "2023-01-01", "end": "2023-12-31", "start_implied": True, "end_implied": True, "implied_from": m.IMPLIED_FROM_TITLE}
    assert m.validate_value(f, both) == {**both, "basis": "Calendar year"}
    for bad in ({"start_implied": "yes"}, {"end_implied": 1}, {"implied_from": "because I said so"}):
        with pytest.raises(m.MethodologyInvalid):
            m.validate_value(f, {"start": "2024-01-01", "end": "2024-12-31", **bad})
    # a reviewer's edit sends two dates only: no flag survives a typed date, and the basis is worked out again
    edited = m.edit(m.new_record("reporting_period"), f, {"start": "2024-02-01", "end": "2024-12-31"}, ACTOR, NOW)
    assert "start_implied" not in edited["decision"]["value"] and edited["decision"]["value"]["basis"] == "Not stated"


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
    assert edited["decision"]["value"] == {"start": "2024-01-01", "end": "2024-12-31", "basis": "Calendar year"}


# --- GWP: the 500-year horizon, and one row per extra set --------------------------------------

def test_the_500_year_horizon_is_allowed_and_nothing_else_is() -> None:
    f = field("gwp")
    assert m.validate_value(f, {"set": "AR6", "horizon": "500-year"}) == {"set": "AR6", "horizon": "500-year"}
    for bad in ({"set": "AR6", "horizon": "50-year"}, {"set": "AR6", "horizon": "500"}, {"set": "AR7", "horizon": "500-year"}):
        with pytest.raises(m.MethodologyInvalid):
            m.validate_value(f, bad)


def test_a_gwp_row_has_its_own_definition_and_a_blank_value() -> None:
    row_id = m.new_row_id("gwp")
    assert ITEM_KEY.match(row_id) and row_id.startswith("gwp:") and row_id != "gwp"
    row = m.row_field(row_id)
    assert row is not None and row["kind"] == "gwp" and row["group"] == "gwp" and row["user_added"] is True
    assert row["allowed"]["horizon"] == ["100-year", "20-year", "500-year", "Not stated"] and row["allowed_labels"]["set"]["AR5"]
    assert m.row_field("gwp") is None  # the fixed field is not a row
    assert m.blank_value(row_id) == {"set": "", "horizon": ""}
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(row, m.blank_value(row_id))  # a blank set cannot be accepted as it is
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
    assert m.validate_value(f, [pick("None")]) == [pick("None")]
    for bad in ([], [pick("Carbon offsets")], [pick("PPA or VPPA"), pick(" ppa  OR vppa ")], [pick("None"), pick("PPA or VPPA")],
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


def test_an_empty_selection_is_refused_and_none_is_not_a_free_option() -> None:
    instruments = field("scope2:instruments")
    with pytest.raises(m.MethodologyInvalid, match="or None if there are none"):
        m.validate_value(instruments, [])
    records = field("calculation:source_records")
    with pytest.raises(m.MethodologyInvalid, match="reject this row"):
        m.validate_value(records, [])
    for text in ("none", "NONE", "  None ", "no\u006ee"):
        with pytest.raises(m.MethodologyInvalid, match="'None' can't be added"):
            m.validate_value(records, [pick(text)])
    # a free option that is a listed option, in any case or spacing, selects the listed one
    assert m.validate_value(records, [pick(" METER   readings ")]) == [pick("Meter readings")]
    with pytest.raises(m.MethodologyInvalid, match="chosen twice"):
        m.validate_value(records, [pick("Meter readings"), pick("meter READINGS")])


def test_a_conditional_row_shown_only_by_claudes_suggestion_says_so() -> None:
    f = field("scope2:instruments")
    meta = m.new_meta()
    market = m.MARKET_CATEGORY_IDS
    claude_only = {**m.new_record(f["field_id"]), "suggestion": {"value": [pick("PPA or VPPA")]}}
    note = m.shown_note(f, claude_only, meta, {})
    assert note == "Shown because Sustentra's AI found it, although no market-based category is Yes."
    assert m.shown_note(f, claude_only, meta, {market[0]: rec(market[0], "Yes")}) is None  # the condition holds
    assert m.shown_note(f, {**claude_only, "decision": rec(f["field_id"], [pick("None")])["decision"]}, meta, {}) is None
    assert m.shown_note(f, claude_only, {**meta, "revealed": [f["field_id"]]}, {}) is None  # the reviewer added it
    assert m.shown_note(field("calculation:source_records"), claude_only, meta, {}) is None


def test_equity_and_financial_control_percentages_are_optional_per_entity() -> None:
    entity = m.row_field("entity:abcd1234")
    named = {"name": "Caf\u00e9 Qu\u00e9bec Holdings", "facilities": [], "equity_share_pct": None, "financial_control": None,
             "included": "Yes"}
    assert m.validate_value(entity, named) == named  # type: ignore[arg-type]
    only_equity = {**named, "equity_share_pct": 51}
    assert m.validate_value(entity, only_equity)["financial_control"] is None  # type: ignore[arg-type]
    assert m.validate_value(entity, {**named, "equity_share_pct": 0})["equity_share_pct"] == 0  # type: ignore[arg-type]  # a stated 0 is not "not stated"
    for bad in ({"equity_share_pct": "50"}, {"equity_share_pct": 101}, {"financial_control": True}, {"financial_control": -0.5}):
        with pytest.raises(m.MethodologyInvalid, match="number from 0 to 100"):
            m.validate_value(entity, {**named, **bad})  # type: ignore[arg-type]
    del named["equity_share_pct"]  # the key itself is still required: the value always has the same shape
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(entity, named)  # type: ignore[arg-type]
    assert m.blank_value("entity:abcd1234")["equity_share_pct"] is None  # a new row has not been given a percentage


def test_a_corrected_entity_name_is_saved_and_the_included_yes_no_is_still_there() -> None:
    entity = m.row_field("entity:abcd1234")
    assert entity is not None
    assert [p["key"] for p in entity["parts"]] == ["name", "facilities", "equity_share_pct", "financial_control", "included", "control_quoted"]
    assert entity["parts"][4]["allowed"] == ["Yes", "No"] and entity["parts"][4]["label"] == "Included"  # the per-entity Yes / No stays, as "Included"
    assert entity["parts"][5]["label"] == "Operational control (as quoted)" and entity["parts"][5]["show_if_present"] is True
    suggested = {"name": "Acme Foods Kent", "facilities": [], "equity_share_pct": None, "financial_control": None,
                 "included": "Yes"}
    record = m.with_suggestion(m.new_record("entity:abcd1234"), entity, {"value": suggested, "quote": "Acme Foods Kent is in the boundary"})
    fixed = m.edit(record, entity, {**suggested, "name": "Acme Foods K\u00e4serei GmbH"}, ACTOR, NOW)
    assert fixed["decision"]["value"]["name"] == "Acme Foods K\u00e4serei GmbH" and fixed["suggestion"]["value"]["name"] == "Acme Foods Kent"
    with pytest.raises(m.MethodologyInvalid):
        m.edit(record, entity, {**suggested, "name": "  "}, ACTOR, NOW)  # a name can be corrected, not blanked


def test_the_boundary_sentence_field_is_a_must_appear_text_row_marked_boundary_sentence_only() -> None:
    f = field(m.BOUNDARY_SENTENCE_ID)
    assert f["kind"] == "text" and f["required"] is True and f["value_note"] == "Boundary sentence only"
    record = m.new_record(m.BOUNDARY_SENTENCE_ID)
    ran = {**m.new_meta(), "prefill_ran_at": "2026-11-20T09:00:00.000Z", "prefill_covered": [x["field_id"] for x in m.CATALOG]}
    assert m.display_state(record, ran) == "not_detected" and m.display_state(record, m.new_meta()) == "not_checked"
    assert m.validate_value(f, "Alle B\u00fcros und Fahrzeuge") == "Alle B\u00fcros und Fahrzeuge"


def test_the_per_entity_yes_no_is_nullable_and_a_new_row_starts_blank() -> None:
    entity = m.row_field("entity:abcd1234")
    assert entity is not None
    base = {"name": "Z\u00fcrich B\u00fcro AG", "facilities": [], "equity_share_pct": None, "financial_control": None}
    for control in ("Yes", "No", None):
        assert m.validate_value(entity, {**base, "included": control})["included"] == control  # type: ignore[arg-type]
    for bad in ("Maybe", "", "yes", 1, True):
        with pytest.raises(m.MethodologyInvalid, match="Yes or No, or left blank"):
            m.validate_value(entity, {**base, "included": bad})  # type: ignore[arg-type]
    assert m.blank_value("entity:abcd1234")["included"] is None
    part = next(p for p in entity["parts"] if p["key"] == "included")
    assert part["allowed"] == ["Yes", "No"] and part["optional"] is True


def test_a_gwp_set_can_have_no_stated_horizon_and_a_use_note() -> None:
    f = field("gwp")
    assert m.validate_value(f, {"set": "AR5", "horizon": "Not stated"}) == {"set": "AR5", "horizon": "Not stated"}
    assert m.validate_value(f, {"set": "AR6", "horizon": "100-year", "applies_to": "  default; refrigerants é纸 "}) == {
        "set": "AR6", "horizon": "100-year", "applies_to": "default; refrigerants é纸"}
    assert m.validate_value(f, {"set": "AR6", "horizon": "100-year", "applies_to": "  "}) == {"set": "AR6", "horizon": "100-year"}
    for bad in ({"set": "AR6", "horizon": "Not stated", "applies_to": "x" * 201}, {"set": "AR6", "horizon": "Not stated", "applies_to": 5},
                {"set": "AR6", "horizon": "Not stated", "applies_to": "a\x00b"}, {"set": "AR6", "horizon": "Not stated", "note": "x"},
                {"set": "AR6", "horizon": "none"}, {"set": "", "horizon": "Not stated"}):
        with pytest.raises(m.MethodologyInvalid):
            m.validate_value(f, bad)
    assert [p["key"] for p in f["parts"]] == ["set", "horizon", "applies_to"] and f["parts"][2]["kind"] == "text"


def test_not_stated_stands_alone_on_the_scopes_field_and_is_never_a_free_option() -> None:
    scopes = field(m.SCOPES_ID)
    assert m.validate_value(scopes, [pick("scope 2"), pick("Scope 1")]) == [pick("Scope 2"), pick("Scope 1")]
    assert m.validate_value(scopes, [pick("not  STATED")]) == [pick("Not stated")]
    with pytest.raises(m.MethodologyInvalid, match="or Not stated if the document does not say"):
        m.validate_value(scopes, [])
    with pytest.raises(m.MethodologyInvalid, match="'Not stated' can't be chosen together"):
        m.validate_value(scopes, [pick("Not stated"), pick("Scope 3")])
    with pytest.raises(m.MethodologyInvalid, match="choose options from the list"):
        m.validate_value(scopes, [pick("Scope 4")])
    records = field("calculation:source_records")  # a field with free additions refuses it as an option of the reviewer's own
    with pytest.raises(m.MethodologyInvalid, match="'Not stated' can't be added"):
        m.validate_value(records, [pick("not stated")])
    assert m.validate_value(field("scope2:instruments"), [pick("None")]) == [pick("None")]  # None still stands alone there


# --- Revert goes back to the PREVIOUS value (Claire C-M3) ---------------------------------------

def test_revert_restores_the_previous_value_one_step_at_a_time() -> None:
    f = field("calculation:approach")
    a = m.edit(m.new_record("calculation:approach"), f, "Fuel \u00d7 factor (\u0e17\u0e14\u0e2a\u0e2d\u0e1a)", ACTOR, NOW)
    b = m.edit(a, f, "Activity data \u00d7 emission factor", ACTOR, NOW)
    c = m.edit(b, f, "Spend-based", ACTOR, NOW)
    assert [d["value"] for d in c["value_history"]] == ["Fuel \u00d7 factor (\u0e17\u0e14\u0e2a\u0e2d\u0e1a)", "Activity data \u00d7 emission factor"]
    r1 = m.revert(c, f, ACTOR, NOW)
    assert r1["decision"]["value"] == "Activity data \u00d7 emission factor" and m.status_of(r1) == "edited"
    r2 = m.revert(r1, f, ACTOR, NOW)
    assert r2["decision"]["value"] == "Fuel \u00d7 factor (\u0e17\u0e14\u0e2a\u0e2d\u0e1a)" and "value_history" not in r2
    r3 = m.revert(r2, f, ACTOR, NOW)  # nothing before it and nothing detected: empty
    assert m.status_of(r3) == "pending" and r3["decision"]["value"] is None
    assert [h.get("restored") for h in r3["history"] if h["action"] == "revert"] == ["previous", "previous", "empty"]
    assert c["decision"]["value"] == "Spend-based"  # the input is not changed


def test_revert_keeps_the_status_of_the_previous_decision_and_never_revives_a_reason_into_a_value() -> None:
    f = field("calculation:approach")
    accepted = m.accept(m.with_suggestion(m.new_record("calculation:approach"), f, {**SUGGESTION, "value": "Detected text"}), f, ACTOR, NOW)
    edited = m.edit(accepted, f, "Reviewer text", ACTOR, NOW)
    back = m.revert(edited, f, ACTOR, NOW)
    assert m.status_of(back) == "accepted" and back["decision"]["value"] == "Detected text"
    rejected = m.reject(m.new_record("calculation:approach"), f, "Wrong section", ACTOR, NOW)
    edited2 = m.edit(rejected, f, "Typed after rejecting", ACTOR, NOW)
    back2 = m.revert(edited2, f, ACTOR, NOW)
    assert m.status_of(back2) == "rejected" and back2["decision"]["value"] is None and back2["decision"]["reason"] == "Wrong section"


def test_with_no_previous_decision_revert_restores_the_detected_value_else_empty_else_the_blank_row() -> None:
    f = field("calculation:approach")
    detected = m.with_suggestion(m.new_record("calculation:approach"), f, {**SUGGESTION, "value": "Detected text"})
    edited = m.edit(detected, f, "Reviewer text", ACTOR, NOW)
    back = m.revert(edited, f, ACTOR, NOW)
    assert m.status_of(back) == "pending" and back["suggestion"]["value"] == "Detected text"  # ready to accept again
    assert [h["restored"] for h in back["history"] if h["action"] == "revert"] == ["detected"]
    accepted_again = m.accept(back, f, ACTOR, NOW)
    assert accepted_again["decision"]["value"] == "Detected text"
    row = m.new_row("factor:scope2:abcd1234", ACTOR, NOW)
    d = m.row_field("factor:scope2:abcd1234")
    edited_row = m.edit(row, d, {"database": "EPA", "edition": "1"}, ACTOR, NOW)  # type: ignore[arg-type]
    assert m.revert(edited_row, d, ACTOR, NOW)["decision"]["value"] == {"database": "", "edition": ""}  # type: ignore[arg-type]


def test_the_value_history_is_bounded_and_pending_decisions_are_not_kept() -> None:
    f = field("calculation:approach")
    record = m.new_record("calculation:approach")
    for i in range(25):
        record = m.edit(record, f, f"v{i} \u00e9\u7eb8", ACTOR, NOW)
    assert len(record["value_history"]) == m.MAX_VALUE_HISTORY and record["value_history"][-1]["value"] == "v23 \u00e9\u7eb8"
    assert m.revert(record, f, ACTOR, NOW)["decision"]["value"] == "v23 \u00e9\u7eb8"
    blank_row = m.new_row("factor:scope1:abcd1234", ACTOR, NOW)  # its pending blank value is not a previous value
    d = m.row_field("factor:scope1:abcd1234")
    first = m.edit(blank_row, d, {"database": "EPA", "edition": "1"}, ACTOR, NOW)  # type: ignore[arg-type]
    assert "value_history" not in first


def test_a_previous_value_that_no_longer_validates_refuses_the_revert_and_changes_nothing() -> None:
    f = field("calculation:approach")
    record = m.edit(m.new_record("calculation:approach"), f, "ok", ACTOR, NOW)
    before = copy.deepcopy(record)
    for entry, reason in (
            ({"status": "edited", "value": "Maybe <script> \u202e\u7eb8\x00", "by": {}, "at": "t"}, "null character"),
            ({"status": "edited", "value": 5}, "must be text"),
            ({"status": "weird", "value": "x"}, "not a decision"),
            ("not a decision", "not a decision"),
            ({"status": "edited", "value": "x" * (m.MAX_TEXT + 1)}, "too long")):
        record["value_history"] = [entry]
        with pytest.raises(m.MethodologyConflict, match=rf"^The previous value can no longer be restored \(.*{reason}.*\)\. Edit the value instead\.$"):
            m.revert(record, f, ACTOR, NOW)
    record["value_history"] = [{"status": "edited", "value": "older \u00e9", "by": {}, "at": "t"}, {"status": "edited", "value": 5}]
    with pytest.raises(m.MethodologyConflict):  # the newest is the previous value: no looking further back
        m.revert(record, f, ACTOR, NOW)
    record["value_history"] = [{"status": "edited", "value": "kept <b>\u00e9</b>", "by": {}, "at": "t", "evil": 1}]
    back = m.revert(record, f, ACTOR, NOW)
    assert back["decision"]["value"] == "kept <b>\u00e9</b>" and "evil" not in back["decision"]
    assert before["decision"]["value"] == "ok"  # nothing was changed by the refusals


def test_a_previous_decision_that_was_lost_refuses_the_revert_but_an_old_record_without_history_does_not() -> None:
    f = field("calculation:approach")
    lost = {**m.edit(m.new_record("calculation:approach"), f, "ok", ACTOR, NOW), "previous_lost": True}
    with pytest.raises(m.MethodologyConflict, match="too large to keep"):
        m.revert(lost, f, ACTOR, NOW)
    old = m.edit(m.new_record("calculation:approach"), f, "ok", ACTOR, NOW)  # never had a previous decision
    assert m.revert(old, f, ACTOR, NOW)["history"][-1]["restored"] == "empty"


def test_an_entity_saved_before_included_had_its_own_key_reads_as_quoted_operational_control_not_included() -> None:
    legacy_yes = {"name": "Z\u00fcrich B\u00fcro AG", "facilities": [], "equity_share_pct": 51, "financial_control": None,
                  "operational_control": "Yes"}
    legacy_no = {**legacy_yes, "operational_control": "No"}
    legacy_none = {**legacy_yes, "operational_control": None}
    for old, quoted in ((legacy_yes, "Yes"), (legacy_no, "No"), (legacy_none, None)):
        upgraded = m.upgrade_entity_value(old)
        assert upgraded["included"] is None and "operational_control" not in upgraded  # never "Included: No"
        assert upgraded.get("control_quoted") == quoted
        assert m.validate_value(m.row_field("entity:abcd1234"), old) == {  # type: ignore[arg-type]
            k: v for k, v in {**upgraded}.items() if not (k == "control_quoted" and v is None)}
    assert m.upgrade_entity_value({**legacy_yes, "included": "Yes"})["operational_control"] == "Yes"  # already new: untouched
    for odd in ("text", None, 5, [], {"name": "x"}):
        assert m.upgrade_entity_value(odd) == odd
    record = {**m.new_record("entity:abcd1234"), "suggestion": {"value": legacy_yes, "quote": "q"},
              "decision": {"status": "edited", "value": legacy_no, "by": {}, "at": "t"},
              "value_history": [{"status": "accepted", "value": legacy_yes, "by": {}, "at": "t"}, "junk"]}
    shown = m.public(record)
    assert shown["suggestion"]["value"]["included"] is None and shown["suggestion"]["value"]["control_quoted"] == "Yes"
    assert shown["decision"]["value"]["included"] is None and shown["decision"]["value"]["control_quoted"] == "No"
    assert shown["value_history"][0]["value"]["control_quoted"] == "Yes" and shown["value_history"][1] == "junk"
    assert record["decision"]["value"] == legacy_no  # the stored record itself is not touched by a read



def test_a_quoted_operational_control_is_a_separate_optional_part_of_an_entity() -> None:
    entity = m.row_field("entity:abcd1234")
    base = {"name": "Z\u00fcrich B\u00fcro AG", "facilities": [], "equity_share_pct": None, "financial_control": None,
            "included": "Yes"}
    assert "control_quoted" not in m.validate_value(entity, base)  # type: ignore[arg-type]
    assert "control_quoted" not in m.validate_value(entity, {**base, "control_quoted": None})  # type: ignore[arg-type]
    assert m.validate_value(entity, {**base, "control_quoted": "No"})["control_quoted"] == "No"  # type: ignore[arg-type]
    for bad in ("Maybe", "", 1, True):
        with pytest.raises(m.MethodologyInvalid, match="operational control must be Yes or No"):
            m.validate_value(entity, {**base, "control_quoted": bad})  # type: ignore[arg-type]
    with pytest.raises(m.MethodologyInvalid):
        m.validate_value(entity, {**base, "control_quoted": "Yes", "other": 1})  # type: ignore[arg-type]
