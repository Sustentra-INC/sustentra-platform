"""Reading printed numbers without guessing what a comma means (MVP-238 review)."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.services import printed_numbers as pn
from backend.app.services.ai_locator import row_lines
from backend.app.services.parser_service import ParserService

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(("text", "expected"), [
    ("1,204", Decimal("1204")),
    ("12,345.6", Decimal("12345.6")),
    ("1,234,567", Decimal("1234567")),
    ("1915.3", Decimal("1915.3")),
    ("$1,915.30", Decimal("1915.30")),
    ("-42", Decimal("-42")),
    ("88,0", Decimal("88.0")),  # one digit after a lone comma: only a decimal comma
    ("€1.234,56", Decimal("1234.56")),
    ("1.234.567", Decimal("1234567")),
    ("1 204,5", Decimal("1204.5")),
    ("12'345", Decimal("12345")),
])
def test_unambiguous_numbers_are_read(text: str, expected: Decimal) -> None:
    assert pn.read_number(text) == expected


@pytest.mark.parametrize("text", ["0,500", "1234,567", "1,20", "12,34", "1,2345", "123,45",
                                  "1,23,456", "12 kWh", "1.2.3", "1,204.5,6", "", "abc", "1,"])
def test_a_comma_that_could_mean_two_things_is_not_read(text: str) -> None:
    assert pn.read_number(text) is None
    assert pn.read_number(text, decimal_comma=False) is None
    assert pn.read_number(text, decimal_comma=None) is None  # unsettled: never a guess


def test_a_decimal_comma_document_settles_the_ambiguous_commas() -> None:
    assert pn.read_number("0,500", decimal_comma=True) == Decimal("0.500")
    assert pn.read_number("1234,567", decimal_comma=True) == Decimal("1234.567")
    assert pn.read_number("12,34", decimal_comma=True) == Decimal("12.34")
    assert pn.read_number("1,204", decimal_comma=True) == Decimal("1.204")  # in such a document, a decimal
    assert pn.read_number("1.234", decimal_comma=True) == Decimal("1234")
    assert pn.read_number("1,204", decimal_comma=False) == Decimal("1204")  # thousands, as in US documents


def test_the_documents_convention_comes_from_its_unambiguous_numbers() -> None:
    assert pn.document_convention(["Total 1.234,56 EUR", "Menge 88,0 l"]) is True
    assert pn.document_convention(["Total 12,345.6 kWh", "1,204 therms"]) is False
    assert pn.document_convention(["1,204 therms", "Rate 0.12"]) is False  # no decimal comma: the default
    assert pn.document_convention(["1.234,56", "12,345.6"]) is None  # both: unsettled
    assert pn.document_convention(["Account 88-1200", "GEN-1"]) is False


def _read_in(document: list[str], token: str) -> Decimal | None:
    return pn.read_number(token, pn.document_convention(document))


def test_one_decimal_comma_number_does_not_switch_a_document() -> None:
    us = ["Total 1,204 gal", "Rate 0.12"]
    assert _read_in(us, "1,204") == Decimal("1204")
    # One "88,0": not enough to switch, and not enough to keep guessing: "1,204" is left for a person.
    assert pn.convention_of([*us, "Tank 88,0"]) == pn.Convention(None, 1, 0)
    assert _read_in([*us, "Tank 88,0"], "1,204") is None
    # With mixed evidence (a US-format number too): also left for a person.
    mixed = [*us, "Tank 88,0", "Total 12,345.6"]
    assert pn.convention_of(mixed) == pn.Convention(None, 1, 1)
    assert _read_in(mixed, "1,204") is None and _read_in(mixed, "1.234") is None
    assert _read_in(mixed, "88,0") == Decimal("88.0") and _read_in(mixed, "12,345.6") == Decimal("12345.6")


def test_two_decimal_comma_numbers_and_no_us_ones_switch_it() -> None:
    document = ["Menge 88,0 l", "Summe €1.234,56"]
    assert pn.convention_of(document) == pn.Convention(True, 2, 0)
    assert _read_in(document, "1,204") == Decimal("1.204")
    # Any US-format number makes it mixed, however many decimal commas there are.
    mixed = [*document, "Tank 5,0", "Total 1,234.56"]
    assert pn.convention_of(mixed) == pn.Convention(None, 3, 1)
    assert _read_in(mixed, "1,204") is None


def test_the_convention_is_recorded_with_its_evidence() -> None:
    assert pn.convention_of(["88,0", "5,0", "1,204"]).as_record() == {
        "convention": "decimal_comma", "decimal_comma_numbers": 2, "decimal_point_numbers": 0}
    assert pn.convention_of(["1,204"]).as_record()["convention"] == "decimal_point"
    assert pn.convention_of(["88,0"]).as_record()["convention"] == "unsettled"


def test_tokens_are_numbers_standing_on_their_own() -> None:
    assert pn.tokens("Account 88-1200, meter GEN-1, used 1,915.3 therms on 01/12/2025") == ["1,915.3"]
    assert pn.tokens("Diesel | 1 204,5 | €1.234,56") == ["1 204,5", "€1.234,56"]


# --- no previously correct US-format reading changes --------------------------------------------------------------

_US = re.compile(r"-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _old_reading(token: str) -> Decimal | None:
    """What the AI value check read before MVP-238: every comma dropped."""

    cleaned = token.replace("$", "").replace(",", "")
    try:
        return Decimal(cleaned)
    except ArithmeticError:
        return None


def _fixture_documents() -> list[Path]:
    roots = [REPO / "s1-test-suite", REPO / "parser_reliability_test_set"]
    kinds = {".csv", ".docx", ".pdf", ".xlsx", ".txt"}
    return sorted(p for root in roots if root.is_dir() for p in root.rglob("*") if p.suffix.lower() in kinds)


def test_no_us_format_reading_in_the_extraction_fixtures_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "false")
    documents = _fixture_documents()
    if not documents:
        pytest.skip("the fixture documents are not in this checkout")
    checked = 0
    parser = ParserService()
    for path in documents:
        try:
            output = parser.parse_document(file_path=path, document_id=path.stem, processing_run_id="numbers")
        except Exception:  # a fixture the local parser cannot open is not this test's subject
            continue
        texts = [line.text for line in row_lines(output)]
        convention = pn.document_convention(texts)
        assert convention is False, f"{path.name} not read as a decimal-point document"
        for text in texts:
            for token in pn.tokens(text):
                plain = token.replace(" ", "")
                if not _US.fullmatch(plain):
                    continue
                assert pn.read_number(token, convention) == _old_reading(plain), (path.name, token)
                checked += 1
    assert checked > 500
