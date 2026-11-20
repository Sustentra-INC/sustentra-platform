"""Review round 1 for the metric fuel table: a capacity column is never the fuel quantity, a unit in parentheses
needs a quantity word, a Description column stays the product unless the fuel column really names a fuel, and a
Month cell that is not a year and month gives the quantity with no date."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import CANONICAL_TYPE_ID, MobileCombustionExtractor
from backend.app.services.stationary_combustion_extractor import (
    CANONICAL_TYPE_ID as STATIONARY_TYPE,
)
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor

TITLE = "Müller Käserei Zürich – Kestrel Mietflotte – Fuel Report (METRIC UNITS)"


def _parsed(title: str, *lines: str) -> dict[str, Any]:
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": t, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, t in enumerate([title, *lines])
    ]
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def _rows(extractor: Any, type_id: str, parsed: dict[str, Any]) -> list[dict[str, Any]]:
    targets = ExtractionTargetService().get_targets_for_canonical_type(type_id)
    outcome = extractor.extract(parsed, targets, "EV-1")
    by_record: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        by_record.setdefault(c.get("record_index"), {})[c["field_name"]] = c["normalized_value"]
    return [r for _, r in sorted(by_record.items(), key=lambda kv: str(kv[0]))]


def _mobile(*lines: str) -> list[dict[str, Any]]:
    return _rows(MobileCombustionExtractor(), CANONICAL_TYPE_ID, _parsed(TITLE, *lines))


def test_a_tank_capacity_column_is_never_the_fuel_quantity() -> None:
    rows = _mobile("Unit | Fuel Type | Month | Tank Capacity (L) | Fuel Dispensed (L)",
                   "R-1 | Diesel | 2025-01 | 300 | 690.5")
    assert [r["activity_quantity"] for r in rows] == [690.5]
    for header in ("Fuel Tank Capacity (L)", "Tank Size (L)", "Fuel Level (L)", "Fuel Efficiency (L)"):
        assert MobileCombustionExtractor()._quantity_header_score(header.lower()) == 0, header


def test_a_report_with_only_a_capacity_column_invents_no_fuel_quantity() -> None:
    rows = _mobile("Unit | Fuel Type | Month | Distance (km) | Tank Capacity (L)", "R-1 | Diesel | 2025-01 | 2308 | 300")
    assert all(r.get("activity_quantity") is None for r in rows)


def test_a_unit_in_parentheses_needs_a_quantity_word_in_the_header() -> None:
    mobile = MobileCombustionExtractor()
    for header in ("pressure (bar)", "temp corr. (l/15c)", "range (l)"):
        assert mobile._quantity_header_score(header) == 0, header
    for header in ("fuel dispensed (l)", "volume (l)", "quantity (kg)", "gas used (m³)"):
        assert mobile._quantity_header_score(header) > 0, header


@pytest.mark.parametrize(
    ("header", "row", "fuel"),
    [
        ("Date | Description | Fuel | Gallons", "01/05/2025 | Unleaded Gasoline | Y | 18.2", "gasoline"),
        ("Date | Description | Product | Gallons", "01/05/2025 | Diesel #2 ULSD | 0412 | 18.2", "diesel"),
        ("Date | Description | Grade | Gallons", "01/05/2025 | Unleaded Gasoline | 87 | 18.2", "gasoline"),
        ("Date | Description | Fuel Type | Gallons", "01/05/2025 | Diesel | Diesel | 18.2", "diesel"),
        ("Date | Description | Fuel | Gallons", "01/05/2025 | Diesel für Müller | N | 18.2", "diesel"),
    ],
)
def test_a_description_column_stays_the_product_unless_the_fuel_column_names_a_fuel(
    header: str, row: str, fuel: str
) -> None:
    rows = _mobile(header, row)
    assert [(r["activity_quantity"], r["fuel_type"]) for r in rows] == [(18.2, fuel)]


def test_a_stationary_description_column_with_a_product_code_keeps_its_records() -> None:
    parsed = _parsed("Boreal Propane – Delivery statement", "Date | Description | Product | Gallons",
                     "01/05/2025 | Propane HD-5 | 0412 | 180.2")
    rows = _rows(StationaryCombustionExtractor(), STATIONARY_TYPE, parsed)
    assert [(r["activity_quantity"], r["fuel_type"]) for r in rows] == [(180.2, "propane")]


@pytest.mark.parametrize("month", ["2025-13", "2025-1", "Jan-25", "2025-00", "Q1 2025"])
def test_a_month_cell_that_is_not_a_year_and_month_gives_the_quantity_and_no_date(month: str) -> None:
    rows = _mobile("Unit | Fuel Type | Month | Fuel Dispensed (L)", f"R-1 | Diesel | {month} | 69.5")
    assert [r["activity_quantity"] for r in rows] == [69.5]
    assert rows[0].get("transaction_date") is None
