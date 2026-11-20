"""Finding a methodology quote on a PDF page from its own text layer: located only when printed."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.app.services import quote_locator as ql


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Organizational boundary: we use the operational control approach.", fontsize=11)
    page.insert_text((72, 130), "Emissions are reported in tCO2e.", fontsize=11)
    page2 = doc.new_page()
    page2.insert_text((72, 100), "Operational control again, and Operational Control once more.", fontsize=11)
    page3 = doc.new_page()
    page3.insert_text((72, 100), "Scope 1 emissions were 1,234 tCO2e.", fontsize=11)
    path = tmp_path / "statement.pdf"
    doc.save(path)
    doc.close()
    return path


def test_a_quote_printed_on_its_page_is_placed_inside_the_page(pdf: Path) -> None:
    placed = ql.locate_on_pdf(pdf, "the operational control approach", 1)
    assert placed is not None and placed.page == 1 and len(placed.rects) == 1
    box = placed.rects[0]
    assert 0 < box["x"] < 1 and 0 < box["y"] < 0.5 and 0 < box["w"] < 1 and 0 < box["h"] < 0.1
    assert box["x"] + box["w"] <= 1 and box["y"] + box["h"] <= 1


def test_quotes_compare_as_printed_ignoring_case_quotes_and_spacing(pdf: Path) -> None:
    assert ql.locate_on_pdf(pdf, "  EMISSIONS   are reported in tCO2e. ", 1) is not None


def test_a_quote_not_on_that_page_is_not_located_even_if_another_page_has_it(pdf: Path) -> None:
    assert ql.locate_on_pdf(pdf, "Scope 1 emissions were 1,234 tCO2e", 1) is None
    assert ql.locate_on_pdf(pdf, "words that are printed nowhere", 1) is None


def test_a_page_outside_the_document_is_not_located(pdf: Path) -> None:
    assert ql.locate_on_pdf(pdf, "Scope 1 emissions", 9) is None
    assert ql.locate_on_pdf(pdf, "Scope 1 emissions", 0) is None


def test_a_repeated_phrase_is_highlighted_at_each_place_it_is_printed(pdf: Path) -> None:
    placed = ql.locate_on_pdf(pdf, "operational control", 2)
    assert placed is not None and placed.page == 2 and len(placed.rects) == 2


def test_without_a_page_the_quote_must_be_printed_on_exactly_one_page(pdf: Path) -> None:
    unique = ql.locate_on_pdf(pdf, "Scope 1 emissions were 1,234 tCO2e", None)
    assert unique is not None and unique.page == 3
    assert ql.locate_on_pdf(pdf, "operational control", None) is None  # pages 1 and 2


def test_an_empty_quote_or_unreadable_file_is_not_located(pdf: Path, tmp_path: Path) -> None:
    assert ql.locate_on_pdf(pdf, "   ", 1) is None
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert ql.locate_on_pdf(broken, "anything here", 1) is None


def test_sources_on_document_reads_the_suggestion_and_each_list_entry() -> None:
    single = {"suggestion": {"quote": "We use operational control.", "document_id": "D1", "source_reference": {"page_number": 4}}}
    assert ql.sources_on_document(single, "D1") == [{"entry": None, "quote": "We use operational control.", "page": 4}]
    assert ql.sources_on_document(single, "D2") == []
    listed = {"suggestion": {"quote": "", "document_id": "D1", "evidence": [
        {"label": "a", "quote": "first quote", "document_id": "D1", "source_reference": {"page_number": 2}},
        {"label": "b", "quote": "second quote", "document_id": "D2"},
        {"label": "c", "quote": "third quote", "document_id": "D1", "source_reference": "p. 3"}]}}
    assert ql.sources_on_document(listed, "D1") == [
        {"entry": 0, "quote": "first quote", "page": 2}, {"entry": 2, "quote": "third quote", "page": None}]
    assert ql.sources_on_document({"suggestion": None}, "D1") == []
