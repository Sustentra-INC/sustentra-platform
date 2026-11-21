"""Scopes read from a statement table whose row labels are short heading cells, one per line, with a footnote
mark stuck to a name ("Scope 31"): invented numbers, the shape of a public restaurant-group statement."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services import methodology_prefill as mp
from backend.tests.services.test_methodology_prefill import answer, check, doc

TABLE = [
    (1, "Greenhouse gas emissions (tCO2e)"),      # L1
    (1, "Scope 1"),                               # L2
    (1, "41,100"),                                # L3
    (1, "Scope 2"),                               # L4
    (1, "7,250"),                                 # L5
    (1, "Subtotal: Scope 1 & 2"),                 # L6
    (1, "48,350"),                                # L7
    (1, "Scope 31"),                              # L8
    (1, "29,000,500"),                            # L9
    (1, "Scope 4"),                               # L10
    (1, "Scope 41"),                              # L11
    (1, "Notes"),                                 # L12
]


def pick(option: str, line: str, quote: str, wording: str | None = None):
    sel = {"field_id": "scopes:covered", "option": option, "document": "D1", "line": line, "quote": quote,
           "wording": quote if wording is None else wording}
    return check(answer(selections=[sel]), [doc(TABLE)])


def options(kept: list[Any]) -> list[str]:
    return [p["option"] for v in kept if v.field_id == "scopes:covered" for p in v.suggestion["value"]]


@pytest.mark.parametrize("option,line,quote", [("Scope 1", "L2", "Scope 1"), ("Scope 2", "L4", "Scope 2")])
def test_a_heading_cell_quoted_whole_is_kept(option: str, line: str, quote: str) -> None:
    kept, dropped = pick(option, line, quote)
    assert not dropped and options(kept) == [option]
    assert kept[0].suggestion["value"][0]["wording"] == quote


def test_a_footnote_digit_on_a_scope_heading_is_not_part_of_the_name() -> None:
    kept, dropped = pick("Scope 3", "L8", "Scope 31")
    assert not dropped and options(kept) == ["Scope 3"]
    kept, dropped = pick("Scope 3", "L8", "Scope 31 29,000,500")  # a longer quote on the same line
    assert not dropped
    kept, dropped = pick("Scope 1", "L8", "Scope 31")  # the mark never makes it another scope
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}


def test_scopes_past_three_never_map() -> None:
    for line, quote in (("L10", "Scope 4"), ("L11", "Scope 41")):
        for option in ("Scope 1", "Scope 2", "Scope 3"):
            kept, dropped = pick(option, line, quote)
            assert kept == [] and sum(dropped.values()) == 1


def test_a_subtotal_still_names_both_scopes() -> None:
    assert mp.names_scope("Subtotal: Scope 1 & 2", "Scope 1") == "yes"
    assert mp.names_scope("Subtotal: Scope 1 & 2", "Scope 2") == "yes"
    assert mp.names_scope("Subtotal: Scope 1 & 2", "Scope 3") == "no"
    assert mp.names_scope("Scope 12", "Scope 1") == "yes" and mp.names_scope("Scope 12", "Scope 2") == "no"
    assert mp.names_scope("Scope 31,258", "Scope 3") == "no"  # a number, not a mark


def test_a_short_quote_that_is_not_the_whole_cited_line_is_dropped() -> None:
    kept, dropped = pick("Scope 1", "L6", "Scope 1")  # inside "Subtotal: Scope 1 & 2", not the whole line
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}
    kept, dropped = pick("Scope 3", "L8", "Scope 3")  # "Scope 3" is not all of "Scope 31"
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}


def test_a_whole_line_on_another_line_than_the_cited_one_is_dropped() -> None:
    kept, dropped = pick("Scope 1", "L4", "Scope 1")  # L2 says it, L4 does not
    assert kept == [] and dict(dropped) == {"quote_not_on_document": 1}
    kept, dropped = pick("Scope 2", "L99", "Scope 2")
    assert kept == [] and sum(dropped.values()) == 1


def test_a_short_whole_line_quote_that_does_not_carry_the_value_is_still_dropped() -> None:
    lines = [(1, "Biogenic"), (1, "Totals")]
    out = answer(choices=[{"field_id": "consolidation_approach", "value": "Equity Share", "document": "D1",
                           "line": "L2", "quote": "Totals"}])
    kept, dropped = check(out, [doc(lines)])
    assert kept == [] and dict(dropped) == {"value_not_in_quote": 1}
