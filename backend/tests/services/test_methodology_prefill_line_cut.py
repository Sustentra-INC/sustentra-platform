"""A quote that stops exactly where a printed line ends: the value is on the next line, so the reading goes on.

Fixtures are invented and paraphrased; the line splits follow shapes seen in real reports."""

from __future__ import annotations

from backend.tests.services.test_methodology_prefill import answer, check, cite, doc, gas, gwp_item, period

GASES = [
    (1, "Our footprint covers carbon dioxide (CO2), methane (CH4), nitrous"),                   # L1
    (1, "oxide (N2O), hydrofluorocarbons (HFCs), sulfur hexafluoride (SF6), and nitrogen"),    # L2
    (1, "trifluoride (NF3). Gas-level data is not shown because most of it is CO2."),         # L3
    (1, "Further notes follow."),                                                              # L4
]


def test_a_gas_whose_name_is_on_the_next_line_is_kept_with_the_longer_quote() -> None:
    quote = "sulfur hexafluoride (SF6), and nitrogen"
    kept, dropped = check(answer(gases=[gas("gas:nf3", "Included", quote, "L2")]), [doc(GASES)])
    assert dict(dropped) == {} and len(kept) == 1
    suggestion = kept[0].suggestion
    assert suggestion["quote"] == f"{quote} trifluoride (NF3)."  # up to the sentence end
    assert suggestion["source_reference"] == doc(GASES).lines[1].source_reference  # the line it started on


def test_a_gas_cut_after_a_word_is_kept() -> None:
    lines = [(1, "Emissions include four gases under the protocol, namely carbon"),
             (1, "dioxide (CO2), methane (CH4), nitrous oxide (N2O) and HFCs.")]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "four gases under the protocol, namely carbon", "L1")]),
                          [doc(lines)])
    assert dict(dropped) == {} and len(kept) == 1
    assert kept[0].suggestion["quote"].endswith("carbon dioxide (CO2), methane (CH4), nitrous oxide (N2O) and HFCs.")


def test_a_set_named_one_line_on_is_read_across_one_extra_line() -> None:
    lines = [(1, "Factors are applied as described below, and GWPs are defined by the Intergovernmental"),   # L1
             (1, "Panel on Climate Change (IPCC) Sixth Assessment"),                                       # L2
             (1, "Report (AR6, 100-year horizon) for methane."),                                          # L3
             (1, "Other text.")]
    quote = "GWPs are defined by the Intergovernmental Panel on Climate Change (IPCC) Sixth Assessment"
    kept, dropped = check(answer(gwp=[gwp_item("AR6", "100-year", quote, "L1")]), [doc(lines)])
    assert dict(dropped) == {} and len(kept) == 1
    assert kept[0].suggestion["quote"] == f"{quote} Report (AR6, 100-year horizon) for methane."


def test_a_set_two_lines_on_is_read_across_two_extra_lines() -> None:
    lines = [(1, "Emissions use the 100-year Global Warming Potentials from the"),   # L1
             (1, "International Panel on Climate Change (IPCC) assessment with the exception of"),  # L2
             (1, "Fifth Assessment Report (AR5) values where the factors embed them.")]  # L3
    quote = "the 100-year Global Warming Potentials from the"
    kept, dropped = check(answer(gwp=[gwp_item("AR5", "100-year", quote, "L1")]), [doc(lines)])
    assert dict(dropped) == {} and len(kept) == 1
    assert "Fifth Assessment Report (AR5)" in kept[0].suggestion["quote"]


def test_a_period_whose_year_is_on_the_next_line_is_kept() -> None:
    lines = [(1, "Metrics are presented in the table below for the year ended December 31,"),  # L1
             (1, "2024 and reflect our operations.")]                                           # L2
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", "for the year ended December 31,", "L1")]),
                          [doc(lines)])
    assert dict(dropped) == {} and [k.field_id for k in kept] == ["reporting_period"]
    assert kept[0].suggestion["quote"].startswith("for the year ended December 31, 2024")
    assert kept[0].suggestion["value"]["end"] == "2024-12-31"


def test_a_quote_that_ends_mid_line_is_not_extended() -> None:
    lines = [(1, "We report nitrous oxide (N2O), sulfur hexafluoride (SF6), and nitrogen"),
             (1, "trifluoride (NF3) as well.")]
    kept, dropped = check(answer(gases=[gas("gas:nf3", "Included", "nitrous oxide (N2O), sulfur hexafluoride", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_a_next_line_that_negates_the_gas_never_makes_it_included() -> None:
    lines = [(1, "We emit methane, sulfur hexafluoride (SF6), and nitrogen"),
             (1, "trifluoride (NF3) are not emitted at any of our sites.")]
    quote = "methane, sulfur hexafluoride (SF6), and nitrogen"
    kept, dropped = check(answer(gases=[gas("gas:nf3", "Included", quote, "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    assert dropped.detail[0]["field"] == "gas:nf3"
    # the same words read as an absence are kept
    kept, dropped = check(answer(gases=[gas("gas:nf3", "Declared absent", quote, "L1")]), [doc(lines)])
    assert dict(dropped) == {} and kept[0].suggestion["value"] == "Declared absent"


def test_a_value_three_lines_on_is_still_dropped_as_before() -> None:
    lines = [(1, "We report carbon, methane, and the other gases the protocol lists:"),
             (1, "this covers every gas the company controls and"),
             (1, "everything else that is reported by the group and"),
             (1, "nitrogen trifluoride (NF3) too.")]
    kept, dropped = check(answer(gases=[gas("gas:nf3", "Included", "We report carbon, methane, and the other gases the protocol lists:", "L1")]),
                          [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    assert len(dropped.detail) == 1 and dropped.detail[0]["reason"] == "value_not_in_quote"


def test_a_period_that_cannot_be_completed_keeps_its_original_drop_entry() -> None:
    lines = [(1, "Metrics are presented in the table below for the year ended December 31,"),
             (1, "and reflect our operations.")]
    kept, dropped = check(answer(periods=[period("2024-01-01", "2024-12-31", "for the year ended December 31,", "L1")]),
                          [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
    assert len(dropped.detail) == 1 and dropped.detail[0]["rule"] == "no_date_printed_and_not_a_calendar_year"


def test_an_answer_for_another_document_is_not_read_across_documents() -> None:
    first = doc([(1, "We cover sulfur hexafluoride (SF6), and nitrogen")], alias="D1", document_id="DOC-1")
    second = doc([(1, "trifluoride (NF3) is covered too.")], alias="D2", document_id="DOC-2")
    kept, dropped = check(answer(gases=[{"field_id": "gas:nf3", "value": "Included", **cite("L1", "sulfur hexafluoride (SF6), and nitrogen")}]),
                          [first, second])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_a_quote_that_ends_a_sentence_is_not_read_into_the_next_one() -> None:
    lines = [(1, "We consolidate our emissions using the operational control approach."),
             (1, "Our partner reports under financial control.")]
    from backend.tests.services.test_methodology_prefill import cite as c
    kept, dropped = check(answer(choices=[{"field_id": "consolidation_approach", "value": "Financial Control",
                                           **c("L1", "operational control approach.")}]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


SHORT_TAIL = [(1, "Emissions include four of the seven gases covered by the protocol \u2013 carbon"),   # L1
              (1, "dioxide (CO2), methane (CH4), nitrous oxide (N2O), and hydrofluorocarbons (HFCs). Others")]  # L2


def test_a_one_word_quote_at_the_end_of_its_line_reads_on_and_is_kept() -> None:
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(SHORT_TAIL)])
    assert dict(dropped) == {} and [k.field_id for k in kept] == ["gas:co2"]
    assert kept[0].suggestion["quote"].startswith("carbon dioxide (CO2)")
    assert kept[0].suggestion["source_reference"] == doc(SHORT_TAIL).lines[0].source_reference


def test_a_one_word_quote_in_the_middle_of_its_line_is_still_dropped() -> None:
    lines = [(1, "Our carbon footprint covers the following gases in"), (1, "dioxide (CO2), methane (CH4) and others.")]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}


def test_a_one_word_tail_of_a_longer_word_is_still_dropped() -> None:
    lines = [(1, "Emissions include the covered gases such as hydrocarbon"), (1, "dioxide (CO2), methane (CH4).")]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}


def test_a_one_word_tail_on_another_line_than_the_cited_one_is_dropped() -> None:
    lines = [(1, "Title line"), *SHORT_TAIL]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}


def test_a_one_word_tail_whose_next_line_lacks_the_value_is_dropped_once() -> None:
    lines = [(1, "Emissions include the covered gases, mainly carbon"), (1, "monoxide and soot from boilers.")]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}
    assert len(dropped.detail) == 1 and dropped.detail[0]["reason"] == "quote_not_on_document"


def test_a_one_word_tail_whose_next_line_negates_is_not_included() -> None:
    lines = [(1, "Emissions of some gases are reported, but carbon"), (1, "dioxide is not emitted at any site.")]
    kept, dropped = check(answer(gases=[gas("gas:co2", "Included", "carbon", "L1")]), [doc(lines)])
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}
