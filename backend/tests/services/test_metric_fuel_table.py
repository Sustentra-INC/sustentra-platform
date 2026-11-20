"""A metric fuel table ("Fuel Dispensed (L)") is read one record per row: the unit in the header's parentheses
is the unit, the row's own fuel is kept, a distance column is not a fuel quantity, and a bare "L" in free text
stays ambiguous."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.domain import fuel_units
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import CANONICAL_TYPE_ID, MobileCombustionExtractor
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor

TITLE = "Müller Käserei Zürich – Kestrel Mietflotte – Fuel & Distance Report (METRIC UNITS)"


def _read(*lines: str) -> Any:
    text = [TITLE, *lines]
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": t, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, t in enumerate(text)
    ]
    parsed = {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    return MobileCombustionExtractor().extract(parsed, targets, "EV-1")


def _rows(outcome: Any) -> list[dict[str, Any]]:
    by_record: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        by_record.setdefault(c.get("record_index"), {})[c["field_name"]] = c
    return [r for _, r in sorted(by_record.items(), key=lambda kv: str(kv[0]))]


HEADER = "Unit | Description | Fuel Type | Month | Distance (km) | Fuel Dispensed (L) | L/100 km"
BODY = [
    "R-2201 | Flatbed Lkw | Diesel | 2025-01 | 2308 | 690.5 | 29.9",
    "R-2201 | Flatbed Lkw | Diesel | 2025-02 | 2817 | 935.4 | 33.2",
    "R-2207 | Utility pickup | Gasoline | 2025-06 | 1703 | 255.2 | 15",
]


def test_every_row_of_a_metric_table_is_a_record_in_litres() -> None:
    rows = _rows(_read(HEADER, *BODY, "TOTAL | Diesel | 5125 | 1625.9"))
    assert len(rows) == 3  # the TOTAL lines are not records
    assert [(r["activity_quantity"]["normalized_value"], r["activity_quantity"]["unit"]) for r in rows] == [
        (690.5, "L"), (935.4, "L"), (255.2, "L")]
    assert [r["fuel_type"]["normalized_value"] for r in rows] == ["diesel", "diesel", "gasoline"]
    assert [r["vehicle_or_equipment_id"]["normalized_value"] for r in rows] == ["R-2201", "R-2201", "R-2207"]


def test_each_row_takes_its_own_month_not_the_report_period() -> None:
    rows = _rows(_read("Period: 01/01/2025 – 12/31/2025", HEADER, *BODY))
    assert [r["transaction_date"]["normalized_value"] for r in rows] == ["2025-01-01", "2025-02-01", "2025-06-01"]


def test_the_distance_column_is_never_the_fuel_quantity() -> None:
    quantities = [r["activity_quantity"]["normalized_value"] for r in _rows(_read(HEADER, *BODY))]
    assert 2308 not in quantities and 1703 not in quantities


def test_litres_convert_to_us_gallons_by_the_exact_factor() -> None:
    assert fuel_units.convert_exact(690.5, "L", "gal") == pytest.approx(690.5 / 3.785411784, rel=1e-9)
    assert fuel_units.convert(690.5, "L", "gal") == pytest.approx(182.411, abs=1e-3)


@pytest.mark.parametrize(
    ("header", "unit"),
    [("Fuel Dispensed (L)", "L"), ("Fuel Dispensed (litres)", "L"), ("Fuel Dispensed (Liter)", "L"),
     ("Quantity (kg)", "kg"), ("Gas Used (m³)", "m3")],
)
def test_a_unit_in_parentheses_scores_as_a_quantity_header(header: str, unit: str) -> None:
    score = StationaryCombustionExtractor()._quantity_header_score(header.lower())
    assert score > 0, header
    assert fuel_units.canonical_unit(unit) == unit


def test_a_bare_l_in_free_text_is_still_not_a_unit() -> None:
    assert fuel_units.find_unit("the L of the tank") is None
    assert fuel_units.find_unit("Tank level L") is None
    # and a header with a bare L outside parentheses is not scored as a quantity either
    assert StationaryCombustionExtractor()._quantity_header_score("tank level l") == 0


def test_distance_and_rate_headers_do_not_score() -> None:
    mobile = MobileCombustionExtractor()
    assert mobile._quantity_header_score("distance (km)") == 0
    assert mobile._quantity_header_score("l/100 km") == 0


def test_a_row_without_a_number_ends_the_table_and_does_not_fail_the_page() -> None:
    rows = _rows(_read(HEADER, BODY[0], "R-2201 | Flatbed Lkw | Diesel | 2025-02 | n/a | – | –", BODY[2]))
    assert len(rows) == 1
