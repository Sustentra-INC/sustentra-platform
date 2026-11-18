"""A thermal bill with several usage tables keeps every one, each typed by its own evidence (its label, its
unit, the heading above it, a bill that names one type only). A table that cannot be read says so, naming
the page, instead of dropping out."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.thermal_extractor import CANONICAL_TYPE_ID, ThermalExtractor

TAGLINE = "Harborline District Energy\nSteam & chilled water utility - 60 Quay Way, Zürich"
HEAD = (
    "Account: HDE-00417\nService Location: Müller Käserei – Zürich Plant, 10 Quay Way\n"
    "From: 01/01/2025\nTo: 01/31/2025"
)


def _parser(*pages: str) -> dict[str, Any]:
    blocks = []
    for number, text in enumerate(pages, start=1):
        for line in text.splitlines():
            blocks.append({"block_id": f"B{len(blocks)}", "page_number": number, "text": line,
                           "source_reference_id": f"S{len(blocks)}", "confidence": 0.99})
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def _read(*pages: str) -> Any:
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    return ThermalExtractor().extract(_parser(*pages), targets, "EV-1")


def _energy(outcome: Any) -> list[tuple[Any, Any, Any]]:
    by_record: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        by_record.setdefault(c.get("record_index"), {})[c["field_name"]] = c
    return sorted(
        ((r["energy_type"]["normalized_value"], r["activity_quantity"]["normalized_value"],
          r["activity_quantity"].get("unit")) for r in by_record.values() if "activity_quantity" in r),
        key=str,
    )


def _table(header: str, *rows: str) -> str:
    return "\n".join([header, *rows])


GENERIC = "Meter | Start Read | End Read | Usage (MMBtu)"


def test_two_generic_tables_under_their_headings_keep_both_commodities() -> None:
    text = "\n".join([
        TAGLINE, HEAD,
        "Steam Consumption", _table(GENERIC, "STM-17-B | 100 | 510 | 410"),
        "Chilled Water Consumption", _table(GENERIC, "CHW-02 | 900 | 1,404 | 504"),
    ])
    outcome = _read(text)
    assert outcome.halt_reason is None
    assert _energy(outcome) == [("chilled_water", 504, "MMBtu"), ("steam", 410, "MMBtu")]
    assert outcome.notes == []


def test_two_generic_tables_are_told_apart_by_their_units() -> None:
    text = "\n".join([
        TAGLINE, HEAD,
        _table("Meter | Start Read | End Read | Usage (Mlb)", "STM-17-B | 14,882.6 | 15,695.0 | 812.4"),
        _table("Meter | Start Read | End Read | Usage (ton-hours)", "CHW-02 | 100 | 42,100 | 42,000"),
    ])
    assert _energy(_read(text)) == [("chilled_water", pytest.approx(504), "MMBtu"), ("steam", 812.4, "klb")]


def test_a_labelled_table_and_a_generic_one_both_read() -> None:
    text = "\n".join([
        TAGLINE, HEAD,
        _table("Meter | Start Read | End Read | Steam Usage (MMBtu)", "STM-17-B | 100 | 510 | 410"),
        "Chilled Water", _table(GENERIC, "CHW-02 | 900 | 1,404 | 504"),
    ])
    assert _energy(_read(text)) == [("chilled_water", 504, "MMBtu"), ("steam", 410, "MMBtu")]


def test_a_combined_bill_across_two_pages_reads_the_table_on_each() -> None:
    page_one = "\n".join([TAGLINE, HEAD, "Steam Consumption", _table(GENERIC, "STM-17-B | 100 | 510 | 410")])
    page_two = "\n".join(["Chilled Water Consumption", _table(GENERIC, "CHW-02 | 900 | 1,404 | 504")])
    outcome = _read(page_one, page_two)
    assert _energy(outcome) == [("chilled_water", 504, "MMBtu"), ("steam", 410, "MMBtu")]


def test_one_table_continued_under_a_repeated_header_is_still_one_table() -> None:
    page_one = "\n".join([TAGLINE, HEAD, "Steam Consumption", _table(GENERIC, "STM-1 | 1 | 11 | 10", "STM-2 | 1 | 21 | 20")])
    page_two = _table(GENERIC, "STM-3 | 1 | 31 | 30")
    assert _energy(_read(page_one, page_two)) == [("steam", 10, "MMBtu"), ("steam", 20, "MMBtu"), ("steam", 30, "MMBtu")]


def test_a_single_type_bill_with_two_generic_tables_reads_both() -> None:
    text = "\n".join([
        "Northside Thermal\nDistrict Heating Statement", HEAD,
        "Building A", _table(GENERIC, "HW-1 | 1 | 341 | 340"),
        "Building B", _table(GENERIC, "HW-2 | 1 | 201 | 200"),
    ])
    assert _energy(_read(text)) == [("hot_water", 200, "MMBtu"), ("hot_water", 340, "MMBtu")]


def test_a_table_that_cannot_be_read_is_named_by_page_and_the_others_still_read() -> None:
    page_one = "\n".join([TAGLINE, HEAD, "Steam Consumption", _table(GENERIC, "STM-17-B | 100 | 510 | 410")])
    page_two = "\n".join(["Chilled Water Consumption", _table(GENERIC, "CHW-02 | n/a | n/a | not read")])
    outcome = _read(page_one, page_two)
    assert _energy(outcome) == [("steam", 410, "MMBtu")]
    warnings = [n for n in outcome.notes if "page 2" in n]
    assert len(warnings) == 1 and "usage table" in warnings[0] and "could not be read" in warnings[0]
    assert not any("page 1" in n for n in outcome.notes)


def test_a_table_in_a_unit_that_is_not_thermal_is_named_not_dropped() -> None:
    page_one = "\n".join([TAGLINE, HEAD, "Steam Consumption", _table(GENERIC, "STM-17-B | 100 | 510 | 410")])
    page_two = "\n".join(["Chilled Water Consumption",
                          _table("Meter | Start Read | End Read | Usage (gallons)", "CHW-02 | 1 | 91 | 90")])
    outcome = _read(page_one, page_two)
    assert _energy(outcome) == [("steam", 410, "MMBtu")]
    assert any("page 2" in n and "usage table" in n for n in outcome.notes)


def test_a_bill_with_no_readable_table_at_all_still_halts_as_before() -> None:
    outcome = _read("\n".join([TAGLINE, HEAD, "Steam Consumption", _table(GENERIC, "STM-1 | x | y | none")]))
    assert outcome.halt_reason is not None
