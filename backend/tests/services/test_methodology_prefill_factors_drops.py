"""Emission-factor, estimation and record answers on documents that lay a table out as short lines: invented
companies, the shapes of three public statements (a narrow factors table, a bulleted methods list, plain sentences)."""

from __future__ import annotations

from typing import Any

from backend.app.services.ai_locator import NotLocated
from backend.app.services import methodology_prefill as mp
from backend.tests.services.test_methodology_prefill import answer, check, doc

TABLE = [
    (1, "Scope 1 GHG emissions"),                      # L1
    (1, "Stationary"),                                 # L2
    (1, "combustion"),                                 # L3
    (1, "Northwind Grill Emission"),                   # L4
    (1, "Factors Hub, released"),                      # L5
    (1, "March 2024"),                                 # L6
    (1, "•"),                                     # L7
    (1, "Fuel receipts"),                              # L8
    (1, "Mobile fuel"),                                # L9
    (1, "Harbor Ministry Fleet"),                      # L10
    (1, "Conversion Factors for"),                     # L11
    (1, "Company Reporting,"),                         # L12
    (1, "released July 2022"),                         # L13
    (1, "Refrigerants"),                               # L14
    (1, "Tideway Climate Panel,"),                     # L15
    (1, "released April 2013;"),                       # L16
    (1, "Cooling Standard 12"),                        # L17
    (1, "Designation and"),                            # L18
    (1, "Classification"),                             # L19
    (1, "of Refrigerants,"),                           # L20
    (1, "released May 2020"),                          # L21
    (1, "Scope 2 GHG emissions"),                      # L22
    (1, "Grid Atlas Factors,"),                        # L23
    (1, "released August 2022;"),                      # L24
    (1, "Regional Grid Data, released"),               # L25
    (1, "February 2021"),                              # L26
]


def factor(scope: str, database: str, edition: str, line: str, quote: str) -> dict[str, Any]:
    return {"scope": scope, "database": database, "edition": edition, "document": "D1", "line": line, "quote": quote}


def kept_factors(item: dict[str, Any], lines: list[tuple[int, str]] = TABLE):
    kept, dropped = check(answer(factors=[item]), [doc(lines)])
    return kept, dropped


def test_a_name_quoted_without_its_edition_takes_the_edition_from_the_rest_of_its_cell() -> None:
    kept, dropped = kept_factors(factor("scope1", "Northwind Grill Emission Factors Hub", "March 2024", "L4",
                                        "Northwind Grill Emission Factors Hub"))
    assert not dropped and len(kept) == 1
    assert kept[0].suggestion["quote"].endswith("released March 2024")


def test_the_cell_may_run_over_several_short_lines() -> None:
    kept, dropped = kept_factors(factor("scope1", "Cooling Standard 12", "May 2020", "L17", "Cooling Standard 12"))
    assert not dropped and kept[0].suggestion["quote"].endswith("released May 2020")
    kept, dropped = kept_factors(factor("scope1", "Harbor Ministry Fleet Conversion Factors", "July 2022", "L10",
                                        "Harbor Ministry Fleet Conversion Factors"))
    assert not dropped and kept[0].suggestion["quote"].endswith("released July 2022")


def test_the_cell_ends_at_its_semicolon_so_the_next_sources_edition_is_never_taken() -> None:
    # "Tideway Climate Panel" is released April 2013; the August 2022 on the next line is Grid Atlas's.
    kept, dropped = kept_factors(factor("scope1", "Tideway Climate Panel", "April 2013", "L15", "Tideway Climate Panel"))
    assert not dropped and len(kept) == 1
    kept, dropped = kept_factors(factor("scope2", "Tideway Climate Panel", "August 2022", "L15", "Tideway Climate Panel"))
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    kept, dropped = kept_factors(factor("scope2", "Grid Atlas Factors", "February 2021", "L23", "Grid Atlas Factors"))
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_an_edition_the_cell_does_not_print_is_still_dropped() -> None:
    kept, dropped = kept_factors(factor("scope1", "Northwind Grill Emission Factors Hub", "March 2025", "L4",
                                        "Northwind Grill Emission Factors Hub"))
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_a_list_mark_ends_the_cell() -> None:
    lines = [(1, "Plant Registry Table"), (1, "•"), (1, "released June 2019")]
    kept, dropped = kept_factors(factor("scope1", "Plant Registry Table", "June 2019", "L1", "Plant Registry Table"), lines)
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_an_edition_with_a_year_range_and_a_release_date_is_read_part_by_part() -> None:
    lines = [(1, "Zenith Environment Agency National Inventory Report 1990 –2021: Greenhouse Gas"),
             (1, "Sources and Sinks (2023)."),
             (1, "Other countries: Ridge Institute Emission factor(s), 1990-2021, for each country’s grid"),
             (1, "(October 2023).")]
    kept, dropped = kept_factors(factor("scope2", "Zenith NIR", "1990-2021 (2023)", "L1",
                                        "Zenith Environment Agency National Inventory Report 1990 –2021: Greenhouse Gas Sources and Sinks (2023)"), lines)
    assert not dropped and len(kept) == 1
    kept, dropped = kept_factors(factor("scope2", "Ridge Institute", "1990-2021 (Oct 2023)", "L3",
                                        "Ridge Institute Emission factor(s), 1990-2021, for each country’s grid"), lines)
    assert not dropped and len(kept) == 1
    kept, dropped = kept_factors(factor("scope2", "Ridge Institute", "1990-2022 (October 2023)", "L3",
                                        "Ridge Institute Emission factor(s), 1990-2021, for each country’s grid"), lines)
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_edition_matching_ignores_filler_words_and_month_spelling() -> None:
    assert mp.edition_in("released March 2024", "Hub, released March 2024")
    assert mp.edition_in("Sept 2023", "Grid (September 2023).")
    assert mp.edition_in("version 3.10", "Databank (Databank 3.10)")
    assert not mp.edition_in("2023 data (January 2025)", "grid data 2023")
    assert not mp.edition_in("", "anything 2024")
    assert not mp.edition_in("June 2024", "June 20245")


REPEATED = [
    (1, "Territory A January to June 2024: Federal Office for Climate, Energy,"),   # L1
    (1, "the Environment and Water, National Accounts Factors (February 2023)."),   # L2
    (1, "•"),                                                                  # L3
    (1, "Territory A July to December 2024: Federal Office for Climate, Energy,"),  # L4
    (1, "the Environment and Water, National Accounts Factors (August 2024)."),     # L5
    (2, "Heating: Territory A January to June 2024: Federal Office for Climate, Energy,"),  # L6
    (2, "the Environment and Water, National Accounts Factors (February 2023)."),   # L7
]


def test_a_repeated_quote_is_placed_by_the_cited_line_when_it_starts_next_to_it() -> None:
    quote = "National Accounts Factors (February 2023)"
    # cited L1, but the words start on L2; the same words repeat on L7 (another page, 5 lines away)
    kept, dropped = check(answer(factors=[factor("scope1", "National Accounts Factors", "February 2023", "L1", quote)]), [doc(REPEATED)])
    assert not dropped and kept[0].suggestion["source_reference"]["page_number"] == 1
    kept, dropped = check(answer(factors=[factor("scope1", "National Accounts Factors", "February 2023", "L8", quote)]), [doc(REPEATED)])
    assert kept == [] and dict(dropped) == {"unknown_line": 1}


def test_a_repeated_quote_cited_far_from_both_places_stays_ambiguous() -> None:
    lines = [(1, "Total emissions (June 2024) were reviewed.")] + [(1, f"filler line number {i}") for i in range(8)] \
        + [(1, "Water use (June 2024) was reviewed.")]
    found = mp.locate_quote_across_lines("(June 2024)", "L5", doc(lines).lines)
    assert isinstance(found, NotLocated) and found.reason == "ambiguous_quote"
    near = mp.locate_quote_across_lines("(June 2024)", "L9", doc(lines).lines)
    assert not isinstance(near, NotLocated) and near.alias == "L10"


def test_two_equally_near_starts_stay_ambiguous() -> None:
    lines = [(1, "Report (June 2024)"), (1, "Notes"), (1, "Report (June 2024)")]
    found = mp.locate_quote_across_lines("(June 2024)", "L2", doc(lines).lines)
    assert isinstance(found, NotLocated) and found.reason == "ambiguous_quote"


ESTIMATES = [
    (1, "Where electricity use was not available, an estimate was made as follows:"),   # L1
    (1, "For primary-use server rooms (buildings where server rooms are the main use), electricity"),  # L2
    (1, "use in kWh was estimated from load capacity times the hours of the month."),   # L3
    (1, "Where vehicle mileage was unavailable, mileage was estimated from the trip"),   # L4
    (1, "count and an average trip length."),                                          # L5
]


def estimate(source: str, line: str, quote: str) -> dict[str, Any]:
    return {"source_type": source, "method": "load x hours", "document": "D1", "line": line, "quote": quote}


def test_a_source_type_whose_every_word_is_in_the_quote_is_kept() -> None:
    kept, dropped = check(answer(estimations=[estimate("Electricity for server rooms", "L2", "For primary-use server rooms (buildings where server rooms are the main use), electricity")]), [doc(ESTIMATES)])
    assert not dropped and len(kept) == 1
    kept, dropped = check(answer(estimations=[estimate("Vehicle mileage", "L4", "Where vehicle mileage was unavailable")]), [doc(ESTIMATES)])
    assert not dropped and len(kept) == 1


def test_a_source_type_with_a_word_the_quote_lacks_is_dropped() -> None:
    kept, dropped = check(answer(estimations=[estimate("Aviation fuel", "L4", "Where vehicle mileage was unavailable")]), [doc(ESTIMATES)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    kept, dropped = check(answer(estimations=[estimate("Vehicle fuel economy", "L4", "Where vehicle mileage was unavailable")]), [doc(ESTIMATES)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_a_source_type_in_the_rest_of_the_sentence_is_found() -> None:
    kept, dropped = check(answer(estimations=[estimate("Trip count", "L4", "Where vehicle mileage was unavailable, mileage was estimated")]), [doc(ESTIMATES)])
    assert not dropped and kept[0].suggestion["quote"].endswith("trip count and an average trip length.")


RECORDS = [
    (1, "Activity data for company cars comes from fuel purchase receipts and/or trip logbook"),  # L1
    (1, "records. For most sites, power use comes from landlords or monthly electric utility"),   # L2
    (1, "bills, as applicable."),                                                                   # L3
]


def record(option: str, line: str, quote: str) -> dict[str, Any]:
    return {"field_id": "calculation:source_records", "option": option, "wording": "", "document": "D1", "line": line, "quote": quote}


def test_records_named_later_in_the_same_sentence_are_kept_and_unnamed_ones_dropped() -> None:
    kept, dropped = check(answer(selections=[record("Utility invoices", "L2", "For most sites, power use comes from landlords")]), [doc(RECORDS)])
    assert not dropped and len(kept) == 1 and kept[0].suggestion["value"][0]["option"] == "Utility invoices"
    kept, dropped = check(answer(selections=[record("Fuel receipts or logs", "L1", "Activity data for company cars comes from fuel purchase receipts and/or trip logbook")]), [doc(RECORDS)])
    assert not dropped and len(kept) == 1
    kept, dropped = check(answer(selections=[record("Fuel cards", "L1", "Activity data for company cars comes from fuel purchase")]), [doc(RECORDS)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    kept, dropped = check(answer(selections=[record("Meter readings", "L2", "For most sites, power use comes from landlords")]), [doc(RECORDS)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_a_negation_in_the_rest_of_the_sentence_never_extends_a_quote() -> None:
    lines = [(1, "Vendor Registry Edition 4 is used for steam, but not for"), (1, "Release 2019 of the Aspen Table.")]
    kept, dropped = kept_factors(factor("scope1", "Vendor Registry", "2019", "L1", "Vendor Registry Edition 4"), lines)
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
