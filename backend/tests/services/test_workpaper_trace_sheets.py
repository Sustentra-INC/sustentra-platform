"""The Excel workpaper's Warnings, Method and Sources sheets, its number formats and protection, and the guard
that keeps text from documents and users from being read as a formula."""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook, load_workbook

from backend.app.services.workpaper_export_service import build_workbook

ENGAGEMENT = {"name": "FY2026 GHG verification", "client_name": "Acme Foods", "settings": {}}


def _book(recalculation: dict[str, Any] | None = None, register: dict[str, Any] | None = None,
          items: list[dict[str, Any]] | None = None, engagement: dict[str, Any] | None = None) -> Workbook:
    content = build_workbook(engagement=engagement or ENGAGEMENT, recalculation=recalculation or {},
                             register=register or {}, items=items or [], exported_by="member@acme.test")
    return load_workbook(io.BytesIO(content))


def _rows(book: Workbook, name: str, header_row: int = 1) -> list[dict[str, Any]]:
    sheet = book[name]
    header = [c.value for c in sheet[header_row]]
    return [dict(zip(header, row, strict=False)) for row in sheet.iter_rows(min_row=header_row + 1, values_only=True)]


def _all_text(book: Workbook) -> str:
    return "\n".join(str(v) for s in book.worksheets for row in s.iter_rows(values_only=True) for v in row if v)


# --- order and protection ------------------------------------------------------------------------------------

def test_new_sheets_sit_after_data_points_and_after_working() -> None:
    names = _book().sheetnames
    assert names == ["Summary", "Data points", "Warnings", "Method", "Working", "Sources", "Evidence",
                     "Reviewed values", "Requests", "Findings", "Left out"]
    assert all(len(n) <= 31 for n in names)


def test_every_sheet_is_protected_without_a_password_and_still_usable() -> None:
    book = _book(recalculation={"rollup": {"categories": {}, "steps": [], "nodes": {}, "final_outputs": []}})
    assert "Roll-up" in book.sheetnames
    for sheet in book.worksheets:
        protection = sheet.protection
        assert protection.sheet is True, sheet.title
        assert not protection.password, sheet.title
        assert protection.selectLockedCells is False and protection.selectUnlockedCells is False  # may select, copy
        assert protection.formatColumns is False  # may change column widths


def test_the_summary_says_the_sheets_are_protected_without_a_password() -> None:
    rows = {r["Item"]: r["Value"] for r in _rows(_book(), "Summary")}
    assert "without a password" in rows["Protection"]


# --- Warnings ---------------------------------------------------------------------------------------------------

def _finding(**over: Any) -> dict[str, Any]:
    return {"check": "Q-001", "trigger": "missing_month", "severity": "warning", "category": "purchased_electricity",
            "facility": "Kansas City plant", "documents": ["doc-1a2b", "doc-3c4d"],
            "records": ["jan.pdf", "mar.pdf (record 2)"],
            "message": "Kansas City plant electricity: no bill covers Feb (91.0% of the reporting period is covered).",
            "detail": {"missing_months": ["Feb 2026"], "coverage_percent": 91.0}, **over}


def test_warnings_has_one_row_per_finding_in_plain_words() -> None:
    overlap = _finding(trigger="overlap_same_source_different_document_id", check="Q-004",
                       message="a.pdf and b.pdf both cover 2026-03-01 to 2026-03-05.",
                       detail={"overlap_start": "2026-03-01", "overlap_end": "2026-03-05", "overlap_days": 5})
    book = _book(recalculation={"quality_checks": [_finding(), overlap]})
    rows = _rows(book, "Warnings", header_row=2)
    assert [r["Check"] for r in rows] == ["Missing month", "Overlapping bills"]
    assert rows[0]["What it found"].startswith("Kansas City plant electricity: no bill covers Feb")
    assert rows[0]["Facility"] == "Kansas City plant"
    assert rows[0]["Documents"] == "jan.pdf; mar.pdf (record 2)"
    assert rows[0]["Dates"] == "Feb 2026"
    assert rows[1]["Dates"] == "Mar 1, 2026 – Mar 5, 2026"
    text = _all_text(book)
    assert "doc-1a2b" not in text and "Q-001" not in text and "missing_month" not in text


def test_warnings_says_they_do_not_change_the_numbers_and_says_when_there_are_none() -> None:
    book = _book(recalculation={"quality_checks": []})
    note = book["Warnings"]["A1"].value
    assert "do not change the numbers" in note
    rows = _rows(book, "Warnings", header_row=2)
    assert len(rows) == 1 and "No warnings were found" in rows[0]["What it found"]


def test_warnings_skips_a_finding_it_cannot_read() -> None:
    book = _book(recalculation={"quality_checks": ["odd", None, {"message": "Only a message"}, _finding()]})
    rows = _rows(book, "Warnings", header_row=2)
    assert [r["What it found"] for r in rows][0] == "Only a message"
    assert len(rows) == 2


# --- Method -------------------------------------------------------------------------------------------------------

def _item(field_id: str, **payload: Any) -> dict[str, Any]:
    return {"kind": "methodology", "item_key": field_id, "payload": {"field_id": field_id, **payload}}


SUGGESTION = {"value": "Operational Control", "quote": "We use the operational control approach.",
              "document_id": "doc-9f", "file_name": "report.pdf", "origin": "ai", "model": "some-model-id",
              "source_reference": {"page_number": 14}}
BY = {"name": "Dana Reviewer", "login": "dana@acme.test"}


def test_method_shows_what_the_reviewer_decided_and_what_is_only_suggested() -> None:
    items = [
        _item("consolidation_approach", suggestion=SUGGESTION,
              decision={"status": "accepted", "value": "Operational Control", "by": BY, "at": "2026-11-02T10:30:00Z"}),
        _item("gas:ch4", suggestion={**SUGGESTION, "value": "Included"},
              decision={"status": "edited", "value": "Declared absent", "by": BY, "at": "2026-11-03T09:00:00Z"}),
        _item("gas:n2o", suggestion={**SUGGESTION, "value": "Included"},
              decision={"status": "rejected", "value": None, "reason": "Not in the report", "by": BY,
                        "at": "2026-11-03T09:05:00Z"}),
        _item("gas:co2", suggestion={**SUGGESTION, "value": "Included"}, decision=None),
        _item("gas:sf6", suggestion={"value": "Not mentioned", "origin": "rules"}, decision=None),
        _item("exclusion:boundary", suggestion=None, decision=None),
    ]
    rows = {(r["Question"]): r for r in _rows(_book(items=items), "Method")}
    accepted = rows["Consolidation approach"]
    assert accepted["Group"] == "Organizational boundary" and accepted["Status"] == "Accepted"
    assert accepted["Answer"] == "Operational Control"
    assert accepted["Quote"] == SUGGESTION["quote"] and accepted["Document"] == "report.pdf"
    assert accepted["Page"] == 14
    assert accepted["Decided by"] == "Dana Reviewer" and accepted["Decided at"] == "2026-11-02 10:30:00"
    assert rows["Gas: CH4"]["Status"] == "Edited" and rows["Gas: CH4"]["Answer"] == "Declared absent"
    rejected = rows["Gas: N2O"]
    assert rejected["Status"] == "Rejected" and not rejected["Answer"]
    pending = rows["Gas: CO2"]
    assert pending["Status"] == "Pending" and not pending["Decided by"] and not pending["Decided at"]
    assert pending["Answer"].startswith("Suggested by Sustentra's AI, not decided")
    assert rows["Gas: SF6"]["Answer"].startswith("Suggested by Sustentra's rules, not decided")
    assert rows["Excluded from organizational boundary"]["Status"] == "Pending"


def test_method_leaves_out_removed_rows_the_meta_row_and_payloads_it_cannot_read() -> None:
    items = [
        _item("entity:abcd1234", removed=True, decision={"status": "accepted", "value": {"name": "Gone"},
                                                         "by": BY, "at": "2026-11-02T10:30:00Z"}),
        {"kind": "methodology", "item_key": "meta:state", "payload": {"prefill_ran_at": "2026-11-01"}},
        {"kind": "methodology", "item_key": "gas:co2", "payload": "not a record"},
        {"kind": "methodology", "item_key": "no:such:field", "payload": {"decision": {"status": "accepted"}}},
        {"kind": "methodology", "item_key": "gwp", "payload": {"decision": {"status": "accepted", "value": 12}}},
        {"kind": "methodology", "item_key": "gas:ch4", "payload": None},
        {"kind": "finding", "item_key": "x", "payload": {"sentence": "not methodology"}},
        _item("gas:hfcs", decision={"status": "accepted", "value": "Included", "by": BY, "at": "2026-11-02T10:30:00Z"}),
    ]
    rows = _rows(_book(items=items), "Method")
    assert [r["Question"] for r in rows] == ["Gas: HFCs"]
    assert "Gone" not in str(rows)


def test_method_writes_structured_answers_in_words() -> None:
    items = [
        _item("reporting_period", decision={"status": "accepted", "value": {"start": "2026-01-01", "end": "2026-12-31",
              "basis": "Calendar year"}, "by": BY, "at": "2026-11-02T10:30:00Z"}),
        _item("gwp", decision={"status": "accepted", "value": {"set": "AR5", "horizon": "100-year"}, "by": BY,
                               "at": "2026-11-02T10:30:00Z"}),
        _item("entity:abcd1234", decision={"status": "accepted", "by": BY, "at": "2026-11-02T10:30:00Z",
              "value": {"name": "Acme West", "facilities": ["KC plant"], "equity_share_pct": 100,
                        "financial_control": None, "included": "Yes"}}),
        _item("calculation:source_records", decision={"status": "accepted", "by": BY, "at": "2026-11-02T10:30:00Z",
              "value": [{"option": "Utility bills", "wording": "monthly bills"}]}),
    ]
    rows = {r["Question"]: r["Answer"] for r in _rows(_book(items=items), "Method")}
    assert rows["Reporting period"] == "Jan 1, 2026 – Dec 31, 2026 (Calendar year)"
    assert rows["GWP factors source"] == "IPCC Fifth Assessment Report (AR5), 100-year"
    assert "Acme West" in rows["Entity"] and "KC plant" in rows["Entity"] and "100" in rows["Entity"]
    assert rows["Source records"] == "Utility bills (monthly bills)"


def test_nothing_says_claude_or_a_model_name() -> None:
    items = [_item("gas:co2", suggestion=SUGGESTION, decision=None)]
    text = _all_text(_book(items=items))
    assert "some-model-id" not in text and "doc-9f" not in text
    assert "claude" not in text.lower()


# --- Sources -------------------------------------------------------------------------------------------------------

LINE = {"key": "s1:stationary:natural-gas:fac-kc01", "category": "stationary", "level2": "Natural Gas",
        "label": "Kansas City plant",
        "step1": {"rows": [
            {"document_id": "doc-1", "file_name": "gas-jan.pdf", "candidate_id": "c-1", "quantity": 1000.5,
             "unit": "therm", "share_in_period": 1.0},
            {"document_id": "doc-2", "file_name": "gas-dec.pdf", "candidate_id": "c-2", "quantity": 400.0,
             "unit": "therm", "share_in_period": 0.4838709677},
            {"document_id": "doc-3", "file_name": "gas-feb.pdf", "candidate_id": "c-3", "quantity": 10.0,
             "unit": "therm", "share_in_period": 1.0},
        ], "total": {"quantity": 1410.5, "unit": "therm"}}}
DETAILS = {"stationary_combustion": {"details": {"inputs": [{"fuel": "Natural Gas", "documents": [
    {"document_id": "doc-1", "record": "gas-jan.pdf (record 3)", "quantity": 1000.5, "unit": "therm",
     "share_in_period": 1.0},
    {"document_id": "doc-2", "record": "gas-dec.pdf", "quantity": 400.0, "unit": "therm",
     "share_in_period": 0.4838709677},
]}]}}}


def _value(document_id: str, candidate_id: str, page: Any) -> dict[str, Any]:
    return {"file_name": "x.pdf", "document_id": document_id, "candidate_id": candidate_id, "page": page}


def test_sources_go_from_a_calculation_line_to_its_documents() -> None:
    book = _book(recalculation={"calculation_lines": [LINE], "categories": DETAILS},
                 register={"values": [_value("doc-1", "c-1", 4), _value("doc-2", "c-2", None)]})
    rows = _rows(book, "Sources", header_row=2)
    assert [r["Document"] for r in rows] == ["gas-jan.pdf", "gas-dec.pdf", "gas-feb.pdf"]
    first = rows[0]
    assert first["Category"] == "Stationary combustion" and first["Line"] == "Natural Gas, Kansas City plant"
    assert first["Record"] == "Record 3" and first["Quantity"] == 1000.5 and first["Unit"] == "therm"
    assert first["Share counted in the period"] == 1.0 and first["Page"] == 4
    assert rows[1]["Share counted in the period"] == 0.4838709677  # full precision kept
    assert rows[1]["Page"] is None and rows[1]["Record"] is None  # no record number on that bill
    assert rows[2]["Record"] is None and rows[2]["Page"] is None  # no match in the register: left empty


def test_a_page_is_only_given_when_one_reviewed_value_matches_for_certain() -> None:
    # Two values for the same document and candidate that disagree, and one candidate in two documents.
    register = {"values": [_value("doc-1", "c-1", 4), _value("doc-1", "c-1", 5), _value("doc-2", "c-1", 9)]}
    rows = _rows(_book(recalculation={"calculation_lines": [LINE]}, register=register), "Sources", header_row=2)
    assert rows[0]["Page"] is None  # the two readings disagree
    assert rows[1]["Page"] is None  # nothing for (doc-2, c-2)


def test_sources_falls_back_to_the_category_inputs_without_calculation_lines() -> None:
    rows = _rows(_book(recalculation={"categories": DETAILS}), "Sources", header_row=2)
    assert [r["Document"] for r in rows] == ["gas-jan.pdf", "gas-dec.pdf"]
    assert rows[0]["Line"] == "Natural Gas" and rows[0]["Category"] == "Stationary combustion"


def test_sources_tolerates_odd_payloads() -> None:
    odd = {"calculation_lines": [None, "x", {"step1": None}, {"step1": {"rows": ["bad", {"file_name": "ok.pdf"}]}}],
           "categories": {"stationary_combustion": None, "x": {"details": {"inputs": "nope"}}}}
    rows = _rows(_book(recalculation=odd), "Sources", header_row=2)
    assert [r["Document"] for r in rows] == ["ok.pdf"]


# --- number formats ------------------------------------------------------------------------------------------------

def test_figures_keep_full_precision_and_read_well() -> None:
    comparison = {"workbook_row": 5, "data_point": "Scope 1", "unit": "t CO2e", "reported": 1234.56789,
                  "recalculated": 1234.5678912345, "difference": 0.0000012345, "difference_pct": 0.123456,
                  "status": "within_tolerance"}
    book = _book(recalculation={"comparisons": [comparison]})
    sheet = book["Data points"]
    cells = {c.value: c for c in sheet[2]}
    assert cells[1234.5678912345].number_format == "#,##0.000"
    assert cells[1234.5678912345].value == 1234.5678912345  # not rounded
    assert cells[0.123456].number_format == '0.0"%"'
    assert cells[0.0000012345].number_format == "0.00E+00"  # a very small mass stays visible, never 0.000


def test_a_zero_and_a_normal_mass_use_the_plain_format() -> None:
    book = _book(recalculation={"comparisons": [{"unit": "t", "reported": 0, "recalculated": 0.0005}]})
    formats = {c.value: c.number_format for c in book["Data points"][2] if isinstance(c.value, (int, float))}
    assert formats[0] == "#,##0.000" and formats[0.0005] == "#,##0.000"


def test_summary_tonnes_and_tolerance_have_formats() -> None:
    book = _book(recalculation={"scope_totals": {"scope1": {"total_co2e": 1234.5678}}, "tolerance_pct": 5})
    rows = {r[0].value: r[1] for r in book["Summary"].iter_rows(min_row=2)}
    assert rows["Scope 1 recalculated (t CO2e)"].number_format == "#,##0.000"
    assert rows["Materiality tolerance (%)"].number_format == '0.0"%"'


def test_the_share_counted_is_shown_as_a_percentage_with_one_decimal() -> None:
    book = _book(recalculation={"calculation_lines": [LINE]})
    sheet = book["Sources"]
    header = [c.value for c in sheet[2]]
    share = sheet.cell(row=4, column=header.index("Share counted in the period") + 1)
    assert share.number_format == "0.0%" and share.value == 0.4838709677


# --- formula injection and illegal characters ---------------------------------------------------------------------

DANGEROUS = ["=HYPERLINK(\"http://evil.test\",\"x\")", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1", "=1+1"]


def test_text_that_looks_like_a_formula_is_stored_as_text_and_reads_the_same() -> None:
    documents = [{"file_name": text, "uploaded_by": text, "candidate_count": 1} for text in DANGEROUS]
    book = _book(register={"documents": documents}, engagement={**ENGAGEMENT, "name": "=cmd|' /C calc'!A0"})
    sheet = book["Evidence"]
    for row, text in enumerate(DANGEROUS, start=2):
        for column in (1, 4):
            cell = sheet.cell(row=row, column=column)
            assert cell.data_type == "s", (row, column)
            assert cell.value == text
            assert cell.quotePrefix is True
    name = book["Summary"]["B2"]
    assert name.data_type == "s" and name.value == "=cmd|' /C calc'!A0"


def test_the_raw_file_holds_no_formula_cell_for_that_text() -> None:
    content = build_workbook(engagement=ENGAGEMENT, recalculation={}, register={
        "documents": [{"file_name": "=1+1", "candidate_count": 1}]}, items=[], exported_by="a@b.test")
    import zipfile
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        sheets = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets/"))
    assert "<f>" not in sheets and "<f " not in sheets


def test_ordinary_text_and_numbers_are_unchanged() -> None:
    book = _book(register={"documents": [{"file_name": "bill 2026-01.pdf", "candidate_count": 3}]})
    sheet = book["Evidence"]
    assert sheet["A2"].value == "bill 2026-01.pdf" and not sheet["A2"].quotePrefix
    assert sheet["E2"].value == 3 and sheet["E2"].data_type == "n"


def test_illegal_characters_are_removed_so_the_download_still_works() -> None:
    bad = "bill\x00\x07\x1f.pdf"
    book = _book(register={"documents": [{"file_name": bad, "uploaded_by": "ok\x0bperson", "candidate_count": 1}]},
                 items=[{"kind": "ask", "item_key": "a", "payload": {"whatIsNeeded": "send\x01 it"}}])
    assert book["Evidence"]["A2"].value == "bill.pdf"
    assert book["Evidence"]["D2"].value == "okperson"
    assert book["Requests"]["C2"].value == "send it"


def test_text_longer_than_excel_allows_is_cut_with_a_note() -> None:
    book = _book(register={"documents": [{"file_name": "x" * 40000, "candidate_count": 1}]})
    value = book["Evidence"]["A2"].value
    assert len(value) <= 32767 and value.startswith("xxxx") and "cut" in value
