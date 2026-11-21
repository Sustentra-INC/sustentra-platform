"""What the second staging re-read of three public statements (a bank, a restaurant company, an engineering firm)
still got wrong. Paraphrased fixtures: the same shapes with invented names and numbers."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import methodology_prefill as mp
from backend.tests.services.test_methodology_prefill import answer, category, check, cite, doc, gas, gwp_item, period, selection

# --- 1. the GWP default belongs in the fixed field ---------------------------------------------------------

RESTAURANT = [(3, "GHG emissions are calculated using the 100-year GWPs from the IPCC Fifth Assessment Report with the exception of when "
                  "IEA Emission Factors are applied that use the IPCC Fourth Assessment Report.")]
SENTENCE = ("calculated using the 100-year GWPs from the IPCC Fifth Assessment Report with the exception of when "
            "IEA Emission Factors are applied that use the IPCC Fourth Assessment Report")


def _sets(kept: list[Any]) -> list[tuple[str | None, str | None, str, str]]:
    return [(k.field_id, k.row_group, f'{k.suggestion["value"]["set"]} {k.suggestion["value"]["horizon"]}',
             k.suggestion["value"].get("applies_to", "")) for k in kept if "gwp" in (k.field_id, k.row_group)]


def test_a_reply_with_only_the_exception_still_gets_the_default_from_the_same_sentence() -> None:
    kept, dropped = check(answer(gwp=[gwp_item("AR4", "Not stated", SENTENCE, "L1")]), [doc(RESTAURANT)])
    assert not dropped
    assert _sets(kept) == [("gwp", None, "AR5 100-year", ""), (None, "gwp", "AR4 Not stated", "inside IEA factors")]
    assert kept[0].suggestion["quote"] == SENTENCE and kept[0].suggestion["document_id"] == "DOC-1"  # the same words are the evidence


@pytest.mark.parametrize("order", ["default_first", "exception_first"])
def test_both_sets_in_one_sentence_come_out_with_the_default_in_the_field(order: str) -> None:
    default, exception = gwp_item("AR5", "100-year", SENTENCE, "L1"), gwp_item("AR4", "Not stated", SENTENCE, "L1")
    kept, dropped = check(answer(gwp=[default, exception] if order == "default_first" else [exception, default]), [doc(RESTAURANT)])
    assert not dropped
    assert _sets(kept) == [("gwp", None, "AR5 100-year", ""), (None, "gwp", "AR4 Not stated", "inside IEA factors")]


def test_the_exception_is_never_the_field_even_when_it_is_all_there_is() -> None:
    lines = [(4, "The DESNZ, CEDA and Ecoinvent factors embed GWPs from the IPCC Fifth Assessment Report (AR5).")]
    kept, dropped = check(answer(gwp=[gwp_item("AR5", "Not stated", "factors embed GWPs from the IPCC Fifth Assessment Report (AR5)", "L1")]), [doc(lines)])
    assert not dropped
    [(field, row, label, note)] = _sets(kept)
    assert field is None and row == "gwp" and label == "AR5 Not stated" and "factors" in note  # a row only, never the fixed field


def test_the_default_stated_apart_from_the_embedded_set_keeps_the_field_when_the_exception_comes_first() -> None:
    lines = [(4, "Where a GWP is not embedded in an emission factor, GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon."),
             (4, "The DESNZ, CEDA and Ecoinvent factors embed GWPs from the IPCC Fifth Assessment Report (AR5).")]
    kept, dropped = check(answer(gwp=[
        gwp_item("AR5", "Not stated", "embed GWPs from the IPCC Fifth Assessment Report (AR5)", "L2"),
        gwp_item("AR6", "100-year", "IPCC Sixth Assessment Report (AR6), 100-year horizon", "L1")]), [doc(lines)])
    assert not dropped
    assert [x[:3] for x in _sets(kept)] == [("gwp", None, "AR6 100-year"), (None, "gwp", "AR5 Not stated")]


def test_a_sentence_with_one_set_gives_no_made_up_default() -> None:
    lines = [(1, "We use the IPCC Fifth Assessment Report (AR5) except where a supplier states otherwise.")]
    kept, _ = check(answer(gwp=[gwp_item("AR5", "Not stated", "We use the IPCC Fifth Assessment Report (AR5) except", "L1")]), [doc(lines)])
    assert [x[:3] for x in _sets(kept)] == [("gwp", None, "AR5 Not stated")]


# --- 2. scopes covered from what is reported ---------------------------------------------------------------

def test_a_reported_scope_1_and_scope_2_category_offers_both_scopes_beside_scope_3() -> None:
    lines = [(2, "Stationary Combustion: restaurant equipment, boilers, furnaces and generators."),
             (2, "Purchased electricity is reported under the location-based and market-based methods."),
             (2, "Scope 3 emissions of franchise restaurants are reported separately.")]
    kept, dropped = check(answer(
        choices=[category("category:scope1:stationary", "Yes", "Stationary Combustion: restaurant equipment, boilers", "L1"),
                 category("category:location:electricity", "Yes", "Purchased electricity is reported under the location-based", "L2")],
        selections=[selection("scopes:covered", "Scope 3", "Scope 3 emissions of franchise restaurants are reported", "L3")]), [doc(lines)])
    assert not dropped
    scopes = next(k for k in kept if k.field_id == "scopes:covered")
    assert [v["option"] for v in scopes.suggestion["value"]] == ["Scope 3", "Scope 1", "Scope 2"]
    by_option = {e["label"]: e for e in scopes.suggestion["evidence"]}
    assert "Stationary Combustion" in by_option["Scope 1"]["quote"] and "location-based" in by_option["Scope 2"]["quote"]  # the category's own words


def test_a_scope_the_reply_already_gives_is_not_given_twice_and_a_no_category_offers_nothing() -> None:
    lines = [(1, "Scope 1 and Scope 2 emissions are reported."), (1, "Process emissions are not applicable to our operations.")]
    kept, dropped = check(answer(
        choices=[category("category:scope1:process", "No", "Process emissions are not applicable", "L2")],
        selections=[selection("scopes:covered", "Scope 1", "Scope 1 and Scope 2 emissions are reported", "L1")]), [doc(lines)])
    scopes = next(k for k in kept if k.field_id == "scopes:covered")
    assert [v["option"] for v in scopes.suggestion["value"]] == ["Scope 1"]  # a "No" shows no scope covered


# --- 3. the title year ----------------------------------------------------------------------------------------

PLAN = [
    (1, "Acme Engineering"),                                                               # L1
    (1, "2024 Greenhouse Gas Inventory Management Plan"),                                 # L2
    (1, "Revision 2, March 2025"),                                                         # L3
    (2, "This plan describes calendar year emissions for the corporate offices."),       # L4
]
CALENDAR = "calendar year emissions"


def test_a_cover_revision_date_does_not_hide_the_title_year() -> None:
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", CALENDAR, "L4", True,
                                                ("L2", "2024 Greenhouse Gas Inventory Management Plan"))]), [doc(PLAN)])
    assert not dropped and kept[0].suggestion["value"]["implied_from"] == "calendar year, year from title"


def test_a_second_reporting_year_on_the_cover_still_refuses_the_title_year() -> None:
    lines = [*PLAN[:2], (1, "Compared with the 2023 inventory"), PLAN[3]]
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", CALENDAR, "L4", True,
                                                ("L2", "2024 Greenhouse Gas Inventory Management Plan"))]), [doc(lines)])
    assert kept == [] and sum(dropped.values()) == 1


# --- 4. gases in a sentence ----------------------------------------------------------------------------------

def test_any_hydrofluorocarbon_is_the_hfcs_row_even_when_the_quote_is_cut_short() -> None:
    lines = [(3, "The plan covers carbon dioxide (CO2), methane (CH4), nitrous oxide (N2O) and any hydrofluorocarbon that applies.")]
    for quote in ("nitrous oxide (N2O) and any hydrofluorocarbon", "and any hydrofluorocarb", "any hydrofluorocarbon that applies"):
        kept, dropped = check(answer(gases=[gas("gas:hfcs", "Included", quote, "L1")]), [doc(lines)])
        assert not dropped and kept[0].suggestion["value"] == "Included", quote
    kept, dropped = check(answer(gases=[gas("gas:n2o", "Included", "nitrous oxide (N2O) and any", "L1")]), [doc(lines)])
    assert not dropped and len(kept) == 1


def test_a_footnote_mark_inside_the_gas_names_does_not_lose_the_gas() -> None:
    lines = [(5, "Gases: carbon dioxide (CO₂), methane (CH₄), nitrous oxide (N₂O¹), and nitrogen trifluoride (NF₃²).")]
    kept, dropped = check(answer(gases=[gas("gas:n2o", "Included", "nitrous oxide (N2O)", "L1"),
                                        gas("gas:nf3", "Included", "nitrogen trifluoride (NF3)", "L1")]), [doc(lines)])
    assert not dropped and {k.field_id for k in kept} == {"gas:n2o", "gas:nf3"}


# --- 5. a calculation approach built from per-category formulas ------------------------------------------------

FORMULAS = [
    (6, "Stationary combustion: fuel usage x emission factor x GWP."),                              # L1
    (6, "Mobile combustion: fuel volume x emission factor x GWP; distance is converted to fuel."),  # L2
    (6, "Fugitive emissions: refrigerant top-up quantity x GWP."),                                  # L3
    (6, "Electricity: grid purchases x regional emission factor."),                                 # L4
]


def test_an_approach_built_from_several_quoted_formulas_is_kept_with_each_piece_on_the_document() -> None:
    value = ("Stationary: fuel usage times factor times GWP. Mobile: fuel volume times factor times GWP. "
             "Fugitive: refrigerant top-up times GWP.")
    quote = ("Stationary combustion: fuel usage x emission factor x GWP ... Mobile combustion: fuel volume x emission factor x GWP"
             " ... Fugitive emissions: refrigerant top-up quantity x GWP")
    kept, dropped = check(answer(texts=[{"field_id": "calculation:approach", "value": value, **cite("L1", quote)}]), [doc(FORMULAS)])
    assert not dropped and kept[0].suggestion["quote"] == quote
    assert kept[0].suggestion["source_reference"]["text_snippet"].startswith("Stationary combustion")  # located on the first formula


def test_one_piece_that_is_not_on_the_document_drops_the_whole_approach() -> None:
    quote = "Stationary combustion: fuel usage x emission factor x GWP ... Heat and steam: usage x factor x GWP"
    kept, dropped = check(answer(texts=[{"field_id": "calculation:approach", "value": "Stationary and heat", **cite("L1", quote)}]), [doc(FORMULAS)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}


# --- 6. the bank: the period, and heating and cooling out of one line --------------------------------------------

def test_a_footnote_mark_after_the_year_does_not_hide_a_period_that_is_the_year_ended() -> None:
    lines = [(1, "Metrics for the year ended December 31, 2024¹ are shown below.")]
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", "year ended December 31, 2024", "L1", True)]), [doc(lines)])
    assert not dropped and kept[0].suggestion["value"]["start_implied"] is True
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", "year ended December 31, 2024¹", "L1", True)]), [doc(lines)])
    assert not dropped and len(kept) == 1


def test_steam_district_heat_and_chilled_water_in_one_line_give_all_three_for_the_same_method() -> None:
    line = "Purchased steam, district heat and chilled water are reported under both methods."
    kept, dropped = check(answer(choices=[category("category:location:steam", "Yes", "Purchased steam, district heat and chilled water", "L1"),
                                          category("category:market:steam", "Yes", "Purchased steam, district heat and chilled water", "L1")]),
                          [doc([(1, line)])])
    assert not dropped
    assert {k.field_id for k in kept if k.field_id.startswith("category:")} == {
        f"category:{m}:{c}" for m in ("location", "market") for c in ("steam", "heating", "cooling")}


def test_a_source_the_line_leaves_out_is_not_derived() -> None:
    line = "Purchased steam and district heat are reported, but not chilled water."
    kept, _ = check(answer(choices=[category("category:location:steam", "Yes", "Purchased steam and district heat", "L1")]), [doc([(1, line)])])
    assert {k.field_id for k in kept if k.field_id.startswith("category:")} == {"category:location:steam", "category:location:heating"}


def test_the_prompts_ask_for_the_rereads_items() -> None:
    text = " ".join(mp.SYSTEM_PROMPT.split())
    assert "give BOTH entries" in text and "Never leave the general set out" in text
    assert "Scope 1 and Scope 2 are covered when the report gives their totals" in text
    assert "any hydrofluorocarbon" in text and 'joined by " ... "' in text
    assert "a publication, revision or copyright date on the cover does not matter" in text


# --- the third re-read -------------------------------------------------------------------------------------------

def test_a_gas_quote_that_starts_in_the_middle_of_a_word_is_found_over_lines_and_footnotes() -> None:
    lines = [(3, "The plan covers gases: carbon"), (3, "dioxide (CO2)¹, methane (CH4)², nitrous oxide (N2O) and nitrogen trifluoride (NF3).")]
    for quote in ("ioxide (CO2), methane (CH4)", "dioxide (CO2), methane (CH4), nitrous oxide (N2O)"):
        kept, dropped = check(answer(gases=[gas("gas:co2", "Included", quote, "L1")]), [doc(lines)])
        assert not dropped and kept[0].suggestion["value"] == "Included", quote
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "ioxide (CO2), ethane (CH4)", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}  # a word in the middle must still be exact


def test_a_scope_2_category_of_either_method_offers_scope_2() -> None:
    lines = [(2, "Purchased electricity: 120 MWh, location-based."), (2, "Purchased electricity: 80 MWh, market-based.")]
    for field_id, line in (("category:location:electricity", "L1"), ("category:market:electricity", "L2")):
        kept, dropped = check(answer(choices=[category(field_id, "Yes", "Purchased electricity: ", line)]), [doc(lines)])
        scopes = next(k for k in kept if k.field_id == "scopes:covered")
        assert [v["option"] for v in scopes.suggestion["value"]] == ["Scope 2"], field_id


def test_a_negated_embedded_is_no_exception_cue() -> None:
    lines = [(4, "Where a GWP is not embedded in an emission factor, GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon.")]
    quote = "Where a GWP is not embedded in an emission factor, GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon"
    kept, dropped = check(answer(gwp=[gwp_item("AR6", "100-year", quote, "L1")]), [doc(lines)])
    assert not dropped and _sets(kept) == [("gwp", None, "AR6 100-year", "")]


def test_a_twelve_month_period_ended_is_one_year() -> None:
    lines = [(1, "Emissions for the twelve-month period ended December 31, 2024 are shown.")]
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", "twelve-month period ended December 31, 2024", "L1", True)]), [doc(lines)])
    assert not dropped and kept[0].suggestion["value"]["start_implied"] is True


def test_the_probe_reads_a_pdf_and_names_the_rule_for_each_line(capsys: pytest.CaptureFixture[str]) -> None:
    fitz = pytest.importorskip("fitz")
    import tempfile
    from pathlib import Path

    from backend.scripts import probe_methodology_period as probe

    pdf = fitz.open()
    page = pdf.new_page()
    for n, text in enumerate(["2024 Greenhouse Gas Inventory Management Plan", "Revision 2, March 2025",
                              "Metrics for the year ended December 31, 2024 are shown."]):
        page.insert_text((72, 72 + 24 * n), text)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "statement.pdf"
        pdf.save(str(path))
        assert probe.main([str(path), "--year", "2024"]) == 0
    out = capsys.readouterr().out
    assert "year_wording=True" in out and "start_would_be=2024-01-01" in out and "title_year=2024" in out
