"""Normalisers: synthetic values only (no test-set data belongs in this repo)."""

from datetime import date
from decimal import Decimal

import pytest

from backend.tools.accuracy.normalize import (
    convert, is_exact, norm_id, norm_name, norm_refrigerant, norm_unit, numbers_equal, parse_date, parse_number,
)


@pytest.mark.parametrize("text, expected", [
    ("1,200", "1200"), ("1,200 kWh", "1200"), ("$4,321.09", "4321.09"), ("(3.5)", "-3.5"), ("-3", "-3"),
    ("1 234 567", "1234567"), (".5", "0.5"), (7123.4, "7123.4"), ("approx 2,500 therms", "2500"),
])
def test_parse_number(text: object, expected: str) -> None:
    assert parse_number(text) == Decimal(expected)


@pytest.mark.parametrize("text", [None, "", "n/a", "kWh", True])
def test_parse_number_none(text: object) -> None:
    assert parse_number(text) is None


def test_number_tolerance_and_exact() -> None:
    assert numbers_equal(Decimal("100"), Decimal("100"))
    assert not numbers_equal(Decimal("100"), Decimal("100.05"))
    assert numbers_equal(Decimal("100"), Decimal("100.05"), rel_tol=Decimal("0.001"))
    assert not numbers_equal(Decimal("100"), Decimal("100.5"), rel_tol=Decimal("0.001"))
    assert is_exact(Decimal("1200"), Decimal("1200.00000000001"))
    assert not is_exact(Decimal("1200"), Decimal("1201"))


@pytest.mark.parametrize("text, expected", [
    ("03/14/2031", date(2031, 3, 14)), ("1/5/31", date(2031, 1, 5)), ("2031-03-14", date(2031, 3, 14)),
    ("Mar 14, 2031", date(2031, 3, 14)), ("14 March 2031", date(2031, 3, 14)),
    ("03/14/2031 to 04/13/2031", date(2031, 3, 14)), ("03-14-2031", date(2031, 3, 14)),
])
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", [None, "", "13/45/2031", "soon", "Mar 2031"])
def test_parse_date_none(text: object) -> None:
    assert parse_date(text) is None


def test_ids_ignore_case_spacing_and_punctuation() -> None:
    assert norm_id("1111-222-3333") == norm_id("1111 222 3333") == "11112223333"
    assert norm_id("abc-12345") == norm_id("ABC12345")
    assert norm_id("****9999") != norm_id("ZZZ-1111-2222")
    assert norm_id(None) == ""


def test_names_ignore_case_punctuation_accents() -> None:
    assert norm_name("Acme Power Co.") == norm_name("ACME POWER CO")
    assert norm_name("Zoë Müller") == norm_name("ZOE MULLER")
    assert norm_name("Acme Power Company") != norm_name("Acme Power Billing")


def test_units() -> None:
    assert norm_unit("Gallons") == "gal"
    assert norm_unit("gal diesel") == "gal"
    assert norm_unit("therms/CCF") == "therms"
    assert norm_unit("klb") == norm_unit("Mlb")
    assert norm_unit("") == ""
    assert convert(Decimal("1.2"), "MWh", "kWh") == Decimal("1200.0")
    assert convert(Decimal("10"), "therms", "MMBtu") == Decimal("1.0")
    assert convert(Decimal("1"), "CCF", "therms") is None  # depends on the bill's own heat factor: never guessed
    assert convert(Decimal("5"), "kWh", "kWh") == Decimal("5")


def test_refrigerant_names() -> None:
    assert norm_refrigerant("HFC-999z") == norm_refrigerant("R-999z") == norm_refrigerant("r999Z")
    assert norm_refrigerant("R-888y") != norm_refrigerant("R-777x")
