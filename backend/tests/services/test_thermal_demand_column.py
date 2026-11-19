"""A steam bill's usage line is judged by its own quantity column. A demand column beside it ("Peak Demand
(Mlb/hr)") must not make the usage line demand, and a table that holds only demand still never counts."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.thermal_extractor import CANONICAL_TYPE_ID, ThermalExtractor

HEAD = (
    "Harborline Fernwärme GmbH – Dampf & Kälte\nAccount: HDE-00417\n"
    "Service Location: Müller Käserei – Zürich Plant, 10 Quay Way\n"
    "From: 01/01/2025\nTo: 01/31/2025"
)


def _read(*table_lines: str) -> Any:
    text = "\n".join([HEAD, *table_lines])
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": line, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, line in enumerate(text.splitlines())
    ]
    parsed = {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    return ThermalExtractor().extract(parsed, targets, "EV-1")


def _quantities(outcome: Any) -> list[tuple[Any, Any]]:
    return sorted(
        ((c["normalized_value"], c.get("unit")) for c in outcome.candidates if c["field_name"] == "activity_quantity"),
        key=str,
    )


def test_usage_column_counts_when_a_peak_demand_column_sits_beside_it() -> None:
    outcome = _read(
        "Steam Meter | Previous Read (Mlb) | Current Read (Mlb) | Steam Used (Mlb) | Peak Demand (Mlb/hr)",
        "STM-0417-A | 3,482.6 | 3,701.1 | 218.5 | 1.42",
    )
    assert _quantities(outcome) == [(218.5, "klb")]


def test_usage_column_counts_when_demand_comes_before_it() -> None:
    outcome = _read(
        "Meter | Peak Demand (Mlb/hr) | Usage (Mlb) | Zähler-Nr. (°F)",
        "STM-0417-A | 1.42 | 218.5 | 12",
    )
    assert _quantities(outcome) == [(218.5, "klb")]


def test_a_table_with_only_a_demand_column_never_counts() -> None:
    outcome = _read(
        "Steam Meter | Previous Read | Current Read | Peak Demand (Mlb/hr)",
        "STM-0417-A | 3,482.6 | 3,701.1 | 1.42",
    )
    assert _quantities(outcome) == []


@pytest.mark.parametrize("header", ["Demand (Mlb/hr)", "Peak Demand", "Condensate Returned (Mlb)", "Credit (Mlb)"])
def test_a_quantity_column_that_is_itself_demand_or_condensate_does_not_count(header: str) -> None:
    outcome = _read(f"Steam Meter | Previous Read | Current Read | {header}", "STM-0417-A | 100 | 200 | 5.5")
    assert _quantities(outcome) == []


def test_a_demand_row_inside_a_usage_table_does_not_count() -> None:
    outcome = _read(
        "Meter | Description | Usage (Mlb)",
        "STM-0417-A | Peak demand 1.42 Mlb/hr | 1.42",
    )
    assert _quantities(outcome) == []
