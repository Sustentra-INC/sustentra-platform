"""Portal-export period columns ("Bill Start Date" / "Bill End Date" and the like) are read as each line's
service period. A meter-read column or a lone delivery "Date:" is never a period."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.stationary_combustion_extractor import CANONICAL_TYPE_ID, StationaryCombustionExtractor

TITLE = "Gasversorgung Zürich AG – Erdgas Müller Käserei\nAccount: 4417-2290-31\nNatural gas usage export"


def _read(*lines: str) -> Any:
    text = "\n".join([TITLE, *lines])
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": line, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, line in enumerate(text.splitlines())
    ]
    parsed = {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    return StationaryCombustionExtractor().extract(parsed, targets, "EV-1")


def _periods(outcome: Any) -> list[tuple[Any, Any, Any]]:
    by_record: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        by_record.setdefault(c.get("record_index"), {})[c["field_name"]] = c["normalized_value"]
    return [
        (r.get("service_period_start"), r.get("service_period_end"), r.get("activity_quantity"))
        for _, r in sorted(by_record.items(), key=lambda kv: str(kv[0]))
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("Bill Start Date", "Bill End Date"),
        ("Bill_Start_Date", "Bill_End_Date"),
        ("Billing Period Start", "Billing Period End"),
        ("Service Start Date", "Service End Date"),
        ("Service From", "Service To"),
        ("Period Start Date", "Period End Date"),
        ("From Date", "To Date"),
    ],
)
def test_period_columns_in_common_wordings_are_read_per_line(start: str, end: str) -> None:
    outcome = _read(
        f"Meter Number | {start} | {end} | Days | Usage (MMBtu)",
        "GM-0083315 | 04/01/2025 | 04/30/2025 | 30 | 4730",
        "GM-0083315 | 05/01/2025 | 05/31/2025 | 31 | 3558.7",
    )
    assert _periods(outcome) == [("2025-04-01", "2025-04-30", 4730), ("2025-05-01", "2025-05-31", 3558.7)]


def test_a_start_read_column_is_a_meter_read_not_a_period_start() -> None:
    outcome = _read(
        "Meter Number | Start Read (CCF) | End Read (CCF) | Usage (MMBtu)",
        "GM-0083315 | 71680 | 76250 | 4730",
    )
    assert _periods(outcome) == [(None, None, 4730)]


def test_one_delivery_date_is_a_delivery_date_not_a_period() -> None:
    outcome = _read("DELIVERY TICKET No. NF-224718", "Date: 06/23/2025 Time: 10:42", "Product | Gallons", "Diesel | 275.0")
    starts = [c for c in outcome.candidates if c["field_name"] == "service_period_start" and c["normalized_value"]]
    assert starts == []


def test_a_period_column_with_a_bad_date_leaves_that_line_without_a_period() -> None:
    outcome = _read(
        "Meter Number | Bill Start Date | Bill End Date | Usage (MMBtu)",
        "GM-1 | 04/01/2025 | 04/30/2025 | 100",
        "GM-1 | n/a | – | 120",
    )
    assert _periods(outcome) == [("2025-04-01", "2025-04-30", 100), (None, None, 120)]
