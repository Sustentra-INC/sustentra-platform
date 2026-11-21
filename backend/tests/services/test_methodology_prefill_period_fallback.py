"""The period the rules read when the AI gives none: "calendar year" said about the inventory, and one clean title
year. Paraphrased fixtures with invented names."""

from __future__ import annotations

from backend.tests.services.test_methodology_prefill import answer, check, doc, period

COVER = [
    (1, "© 2025 Acme Engineering."),                                           # L1
    (1, "2024"),                                                                 # L2
    (1, "GREENHOUSE GAS"),                                                       # L3
    (1, "INVENTORY"),                                                            # L4
    (1, "MANAGEMENT PLAN"),                                                      # L5
    (1, "GREENHOUSE GAS INVENTORY MANAGEMENT PLAN"),                             # L6
    (1, "© 2025 Acme Engineering."),                                           # L7
    (1, "2024 Greenhouse Gas Inventory Management Plan"),                        # L8
]
TARGET = (4, "We will maintain our carbon neutrality in each calendar year, beginning in 2024, by a combination")
TARGET_END = (4, "of reductions and offsets.")
METHOD = (9, "Location-based and market-based methods have been used to calculate calendar year office")
METHOD_END = (9, "emissions from purchased electricity.")
SENTENCE = "Location-based and market-based methods have been used to calculate calendar year office emissions from purchased electricity."


def test_a_calendar_year_sentence_and_a_title_year_give_the_year_by_rules() -> None:
    kept, dropped = check(answer(), [doc([*COVER, TARGET, TARGET_END, METHOD, METHOD_END])])
    assert not dropped and [k.field_id for k in kept] == ["reporting_period"]
    suggestion = kept[0].suggestion
    assert suggestion["value"] == {"start": "2024-01-01", "end": "2024-12-31", "basis": "Calendar year",
                                   "start_implied": True, "end_implied": True, "implied_from": "calendar year, year from title"}
    assert suggestion["origin"] == "rules" and suggestion["quote"] == SENTENCE
    assert "Sustentra's rules" in suggestion["reason"] and "claude" not in suggestion["reason"].lower()
    assert [e["quote"] for e in suggestion["evidence"]][1] == "2024 Greenhouse Gas Inventory Management Plan"


def test_a_target_sentence_alone_gives_nothing() -> None:
    kept, dropped = check(answer(), [doc([*COVER, TARGET, TARGET_END])])
    assert kept == [] and not dropped


def test_two_years_on_the_cover_give_nothing() -> None:
    lines = [*COVER[:2], (1, "2023"), *COVER[2:], METHOD, METHOD_END]
    kept, dropped = check(answer(), [doc(lines)])
    assert kept == [] and not dropped


def test_no_title_year_gives_nothing() -> None:
    lines = [(1, "Greenhouse Gas Inventory Management Plan"), METHOD, METHOD_END]
    kept, dropped = check(answer(), [doc(lines)])
    assert kept == [] and not dropped


def test_the_ais_kept_period_stands_alone() -> None:
    lines = [*COVER, METHOD, METHOD_END]
    ai = period("2024-01-01", "2024-12-31", "calendar year office emissions from purchased electricity.", "L10", True,
                ("L8", "2024 Greenhouse Gas Inventory Management Plan"))
    kept, dropped = check(answer(periods=[ai]), [doc(lines)])
    assert not dropped and len(kept) == 1 and kept[0].suggestion["origin"] == "ai"


def test_a_period_the_ai_gave_and_lost_is_not_replaced() -> None:
    lines = [*COVER, METHOD, METHOD_END]
    bad = period("2024-01-01", "2024-12-31", "calendar year office emissions from purchased electricity.", "L10", True,
                 ("L8", "a title that is not on the line"))
    kept, dropped = check(answer(periods=[bad]), [doc(lines)])
    assert kept == [] and sum(dropped.values()) == 1


def test_a_sentence_that_says_beginning_in_a_year_about_the_data_still_counts() -> None:
    lines = [*COVER, (9, "Location-based and market-based methods have been used to calculate calendar year office"),
             (9, "emissions beginning in 2022.")]
    kept, dropped = check(answer(), [doc(lines)])
    assert not dropped and kept[0].suggestion["value"]["start"] == "2024-01-01"
