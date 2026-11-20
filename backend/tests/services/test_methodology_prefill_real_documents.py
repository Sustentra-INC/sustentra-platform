"""What two public GHG statements (a bank's and a restaurant company's) taught the prefill.

The fixtures paraphrase the real wording: the same shapes (a sentence that runs over lines, a bulleted
list, a footnote mark stuck to a scope, a gas list cut in the middle of a word) with invented names and
numbers. Every value must still trace to a quote.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import methodology_prefill as mp
from backend.tests.services.test_methodology_prefill import answer, check, cite, doc, gas, gwp_item, selection

# --- 1. the GWP default ----------------------------------------------------------------------------

RESTAURANT_GWP = [
    (3, "GHG emissions are calculated using the 100-year GWPs from the IPCC Fifth Assessment Report"),  # L1
    (3, "with the exception of when IEA Emission Factors are applied that use the IPCC Fourth Assessment Report."),  # L2
]
RESTAURANT_SENTENCE = ("calculated using the 100-year GWPs from the IPCC Fifth Assessment Report with the exception of when "
                       "IEA Emission Factors are applied that use the IPCC Fourth Assessment Report")
BANK_GWP = [
    (4, "Where a GWP is not embedded in an emission factor, GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon."),
    (4, "The DESNZ, CEDA and Ecoinvent factors embed GWPs from the IPCC Fifth Assessment Report (AR5)."),
    (4, "DESNZ conversion factors, October 2024, for UK vehicles and district heat, using AR5."),
]


def _gwps(kept: list[Any]) -> list[tuple[str | None, str | None, str, str]]:
    return [(k.field_id, k.row_group, f'{k.suggestion["value"]["set"]} {k.suggestion["value"]["horizon"]}',
             k.suggestion["value"].get("applies_to", "")) for k in kept]


@pytest.mark.parametrize("flip", [False, True])
def test_a_set_stated_as_the_exception_inside_iea_factors_is_not_the_default(flip: bool) -> None:
    items = [gwp_item("AR5", "100-year", RESTAURANT_SENTENCE, "L1"), gwp_item("AR4", "Not stated", RESTAURANT_SENTENCE, "L1")]
    kept, dropped = check(answer(gwp=items[::-1] if flip else items), [doc(RESTAURANT_GWP)])
    assert not dropped
    assert _gwps(kept) == [("gwp", None, "AR5 100-year", ""), (None, "gwp", "AR4 Not stated", "inside IEA factors")]


@pytest.mark.parametrize("embedded_line", [("L2", "The DESNZ, CEDA and Ecoinvent factors embed GWPs from the IPCC Fifth Assessment Report (AR5)"),
                                           ("L3", "DESNZ conversion factors, October 2024, for UK vehicles and district heat, using AR5")])
def test_a_set_taken_from_a_factor_source_line_is_never_the_default(embedded_line: tuple[str, str]) -> None:
    default = gwp_item("AR6", "100-year", "GWPs come from the IPCC Sixth Assessment Report (AR6), 100-year horizon", "L1")
    embedded = gwp_item("AR5", "Not stated", embedded_line[1], embedded_line[0])
    for items in ([embedded, default], [default, embedded]):
        kept, dropped = check(answer(gwp=items), [doc(BANK_GWP)])
        assert not dropped
        rows = _gwps(kept)
        assert rows[0][:3] == ("gwp", None, "AR6 100-year")
        assert rows[1][:3] == (None, "gwp", "AR5 Not stated") and rows[1][3]  # a note says where it sits


def test_a_lone_set_on_a_factor_line_stays_the_method() -> None:
    kept, _ = check(answer(gwp=[gwp_item("AR5", "Not stated", "DESNZ conversion factors, October 2024, for UK vehicles and district heat, using AR5", "L3")]),
                    [doc(BANK_GWP)])
    assert _gwps(kept) == [("gwp", None, "AR5 Not stated", "")]  # nothing else states a method: it is not demoted


# --- 2. a quote that runs over lines, bullets and hyphens ---------------------------------------------

FACTOR_LIST = [
    (5, "Emission factors used"),                                                                    # L1
    (5, "• US EPA Emission Factors Hub, June 2024: Scope 1 fuels; US steam"),                      # L2
    (5, "• Australian National Green-"),                                                          # L3
    (5, "house Accounts Factors, February 2023 and August 2024: Australia"),                          # L4
    (5, "• New Zealand Ministry for the"),                                                        # L5
    (5, "Environment, 2024: New Zealand"),                                                           # L6
    (5, "3. DESNZ UK conversion factors, October 2024: UK vehicles"),                                 # L7
    (5, "4) US EPA eGRID, 2023 data (January 2025): Scope 2 location-based"),                         # L8
]


def test_a_quote_over_several_lines_is_found_and_cites_the_line_it_starts_on() -> None:
    lines = doc(FACTOR_LIST).lines
    found = mp.locate_quote_across_lines("Australian National Greenhouse Accounts Factors, February 2023", "L3", lines)
    assert found.alias == "L3"  # type: ignore[union-attr]
    found = mp.locate_quote_across_lines("New Zealand Ministry for the Environment, 2024", "L2", lines)  # the cited line is wrong
    assert found.alias == "L5"  # type: ignore[union-attr]
    assert mp.locate_quote_across_lines("DESNZ UK conversion factors, October 2024", "L7", lines).alias == "L7"  # type: ignore[union-attr]
    assert mp.locate_quote_across_lines("US EPA eGRID, 2023 data", "L8", lines).alias == "L8"  # type: ignore[union-attr]


def test_the_words_must_still_be_exact_across_lines() -> None:
    lines = doc(FACTOR_LIST).lines
    for wrong in ("Australian National Greenhouse Account Factors", "New Zealand Ministry of the Environment",
                  "Australian Greenhouse Accounts Factors"):
        assert isinstance(mp.locate_quote_across_lines(wrong, "L3", lines), mp.NotLocated), wrong


def test_every_source_in_a_list_is_kept_with_its_own_quote() -> None:
    def factor(line: str, quote: str, database: str, edition: str, scope: str = "scope1") -> dict[str, str]:
        return {"scope": scope, "database": database, "edition": edition, **cite(line, quote)}

    kept, dropped = check(answer(factors=[
        factor("L2", "US EPA Emission Factors Hub, June 2024", "US EPA Emission Factors Hub", "June 2024"),
        factor("L3", "Australian National Greenhouse Accounts Factors, February 2023 and August 2024", "Australian National Greenhouse Accounts Factors", "February 2023"),
        factor("L5", "New Zealand Ministry for the Environment, 2024", "New Zealand Ministry for the Environment", "2024"),
        factor("L7", "DESNZ UK conversion factors, October 2024", "DESNZ UK conversion factors", "October 2024"),
        factor("L8", "US EPA eGRID, 2023 data (January 2025)", "US EPA eGRID", "2023", "scope2")]), [doc(FACTOR_LIST)])
    assert not dropped
    assert len([k for k in kept if k.row_group in ("factor:scope1", "factor:scope2")]) == 5
    start = {k.suggestion["value"]["database"]: k.suggestion["source_reference"] for k in kept}
    assert start["Australian National Greenhouse Accounts Factors"]["text_snippet"].startswith("• Australian National Green")


def test_a_sentence_that_runs_over_lines_is_kept_as_the_boundary_sentence() -> None:
    lines = [(4, "Company-owned or leased buildings, vehicles and"), (4, "aircraft are included in the boundary where the company controls the energy.")]
    sentence = "Company-owned or leased buildings, vehicles and aircraft are included in the boundary where the company controls the energy."
    kept, dropped = check(answer(texts=[{"field_id": "boundary:entities", "value": sentence, **cite("L1", sentence)}]), [doc(lines)])
    assert not dropped and kept[0].suggestion["value"] == sentence


# --- 3. the boundary sentence ------------------------------------------------------------------------

@pytest.mark.parametrize("sentence", [
    "Company-owned restaurants and offices; company-owned and leased vehicles.",
    "Company-owned or leased buildings, vehicles and aircraft are included in the boundary where the company controls the energy.",
    "Our boundary covers all offices where we have full authority.",
])
def test_a_sentence_that_lists_what_the_boundary_covers_is_accepted(sentence: str) -> None:
    assert mp.states_boundary_coverage(sentence)
    kept, dropped = check(answer(texts=[{"field_id": "boundary:entities", "value": sentence, **cite("L1", sentence)}]), [doc([(1, sentence)])])
    assert not dropped and len(kept) == 1


@pytest.mark.parametrize("sentence", [
    "Data centers used by a subsidiary are excluded due to limited availability of data.",
    "Joint ventures outside operational control are excluded.",
    "Franchisee-owned restaurants are not owned or operated by the Company.",
    "Leased offices are not included in the inventory.",
])
def test_a_sentence_that_leaves_something_out_is_never_the_boundary_sentence(sentence: str) -> None:
    assert not mp.states_boundary_coverage(sentence)
    kept, dropped = check(answer(texts=[{"field_id": "boundary:entities", "value": sentence, **cite("L1", sentence)}]), [doc([(1, sentence)])])
    assert kept == [] and dict(dropped) == {"not_a_boundary_sentence": 1}


# --- 4. scopes covered -------------------------------------------------------------------------------

def test_a_footnote_mark_on_a_scope_does_not_change_which_scope_it_is() -> None:
    for quote, option in (("Scope 1¹ emissions", "Scope 1"), ("Scope 2² emissions (location-based)", "Scope 2"),
                          ("Scope 3³ emissions", "Scope 3"), ("Scope 2¹², Scope 3", "Scope 3")):
        assert mp.names_scope(quote, option) == "yes", quote


def test_scope_3_beside_location_based_figures_is_covered_and_footnotes_do_not_hide_it() -> None:
    lines = [(2, "Scope 1 emissions¹ and Scope 2 emissions² (location-based) are reported in the table."),
             (2, "Scope 3 emissions are reported with the location-based figures for franchise restaurants.")]
    kept, dropped = check(answer(selections=[
        selection("scopes:covered", "Scope 1", "Scope 1 emissions¹ and Scope 2 emissions²", "L1"),
        selection("scopes:covered", "Scope 2", "Scope 1 emissions¹ and Scope 2 emissions²", "L1"),
        selection("scopes:covered", "Scope 3", "Scope 3 emissions are reported with the location-based figures", "L2")]), [doc(lines)])
    assert not dropped and [o["option"] for o in kept[0].suggestion["value"]] == ["Scope 1", "Scope 2", "Scope 3"]


# --- 5. gases ----------------------------------------------------------------------------------------

GASES = [
    (6, "Greenhouse gases reported: carbon dioxide (CO2), methane (CH4), nitrous oxide (N2O) and HFCs."),
    (6, "PFCs, NF3 and SF6 emissions have been omitted from reporting as they are not a material source of GHG emissions."),
]


def test_gases_omitted_as_not_material_are_declared_absent_one_row_each() -> None:
    quote = "PFCs, NF3 and SF6 emissions have been omitted from reporting as they are not a material source"
    kept, dropped = check(answer(gases=[gas("gas:pfcs", "Declared absent", quote, "L2"), gas("gas:nf3", "Declared absent", quote, "L2"),
                                        gas("gas:sf6", "Declared absent", quote, "L2")]), [doc(GASES)])
    assert not dropped and {k.field_id: k.suggestion["value"] for k in kept} == {
        "gas:pfcs": "Declared absent", "gas:nf3": "Declared absent", "gas:sf6": "Declared absent"}


@pytest.mark.parametrize("quote", ["carbon dioxide (CO", "arbon dioxide (CO2)", "carbon dioxide (CO2), methane (CH"])
def test_a_quote_cut_in_the_middle_of_a_word_is_completed_from_the_line(quote: str) -> None:
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", quote, "L1")]), [doc(GASES)])
    assert not dropped and kept[0].suggestion["value"] == "Included"
    assert kept[0].suggestion["quote"].split()[-1][-1] not in ("(",) and "CO2" in kept[0].suggestion["quote"]


def test_a_gas_still_needs_its_own_name_in_the_quote() -> None:
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "methane (CH4), nitrous oxide (N2O)", "L1")]), [doc(GASES)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


# --- 6 and 7. what is asked ----------------------------------------------------------------------------

def test_the_prompts_ask_for_each_of_the_missing_items_explicitly() -> None:
    cats, method, factors = mp.PART_PROMPTS["categories"], mp.PART_PROMPTS["method"], mp.PART_PROMPTS["factors"]
    assert "exclusion:boundary" in cats and "Reported\n  instead: Scope 3" in cats and "exclusion:inventory" in cats
    assert "limited availability of\n  data" in cats and "Declared absent" in cats and "not a material\n  source" in cats
    assert "boundary:acquisitions" in method and "base year recalculation" in method and "subsequent event" in method
    assert "calculation:process" in method and "tools" in method and "estimations" in method
    assert "Do NOT put the estimation" in method and "source records" in method
    assert "EVERY source" in factors and "one entry\n  each" in factors and "never taken from a line about an emission factor" in " ".join(factors.split())
    assert "Company-owned restaurants and offices" in mp.PART_PROMPTS["boundary"]
    assert "Scope 3" in mp.PART_PROMPTS["boundary"] and "location-based" in mp.PART_PROMPTS["boundary"]
    assert "start and end the quote on whole words" in " ".join(mp.PART_PROMPTS["boundary"].split())


# --- 8. option wording ----------------------------------------------------------------------------------

OPTIONS = [
    (7, "Source records: utility bills/metered consumption and fuel receipts and invoices."),                 # L1
    (7, "Utility and third-party invoices are the source of electricity data; landlords supply shared meters."),  # L2
    (7, "Unbundled EACs are retained; Green-e and AIB residual factors are used for the rest."),               # L3
    (7, "Sub-metering is referred to for some buildings."),                                                  # L4
]


def test_company_wording_selects_the_options_it_names() -> None:
    rec = "RECs or other energy attribute certificates"
    kept, dropped = check(answer(selections=[
        selection("calculation:source_records", "Utility invoices", "utility bills/metered consumption", "L1"),
        selection("calculation:source_records", "Meter readings", "utility bills/metered consumption", "L1"),
        selection("calculation:source_records", "Fuel receipts or logs", "fuel receipts and invoices", "L1"),
        selection("calculation:source_records", "Landlord reports", "landlords supply shared meters", "L2"),
        selection("scope2:instruments", rec, "Unbundled EACs are retained", "L3"),
        selection("scope2:instruments", "Residual mix", "Green-e and AIB residual factors", "L3")]), [doc(OPTIONS)])
    assert not dropped
    by_field = {k.field_id: [v["option"] for v in k.suggestion["value"]] for k in kept}
    assert by_field["calculation:source_records"] == ["Utility invoices", "Meter readings", "Fuel receipts or logs", "Landlord reports"]
    assert by_field["scope2:instruments"] == [rec, "Residual mix"]
    kept, dropped = check(answer(selections=[selection("calculation:source_records", "Utility invoices", "Utility and third-party invoices are the source", "L2")]), [doc(OPTIONS)])
    assert not dropped


def test_sub_metering_alone_is_not_a_meter_readings_source() -> None:
    kept, dropped = check(answer(selections=[selection("calculation:source_records", "Meter readings", "Sub-metering is referred to for some buildings", "L4")]), [doc(OPTIONS)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


# --- every value still traces to a quote ---------------------------------------------------------------

def test_a_value_that_is_not_in_its_quote_is_still_dropped() -> None:
    kept, dropped = check(answer(selections=[selection("scope2:instruments", "PPA or VPPA", "Unbundled EACs are retained", "L3")]), [doc(OPTIONS)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
