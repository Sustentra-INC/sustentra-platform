"""Run-log round 2: only a dateless carried-forward line inside a run log is skipped (never a meter "BAL 7" or a
run called "Balance test"), and the generator cues cover how real logs name their machine."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.pipeline_orchestration_service import FUELQTY_TYPE_ID, MOBFUEL_TYPE_ID, PipelineOrchestrationService
from backend.app.services.stationary_combustion_extractor import CANONICAL_TYPE_ID, StationaryCombustionExtractor

HEADER = "date | generator_id | run_hours | gallons_added | operator"


def _parsed(*lines: str) -> dict[str, Any]:
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": t, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, t in enumerate(lines)
    ]
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def _quantities(parsed: dict[str, Any]) -> list[Any]:
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    outcome = StationaryCombustionExtractor().extract(parsed, targets, "EV-1")
    return [c["normalized_value"] for c in outcome.candidates if c["field_name"] == "activity_quantity"]


def _types_as_stationary(parsed: dict[str, Any]) -> bool:
    result = {"status": "low_confidence",
              "candidate_matches": [{"canonical_type_id": MOBFUEL_TYPE_ID, "confidence": 0.41}]}
    return (StationaryCombustionExtractor().confirms(parsed)
            or PipelineOrchestrationService._fuel_content_confirmed(result, parsed) == FUELQTY_TYPE_ID)


def test_a_gas_bill_meter_called_bal_7_keeps_its_line() -> None:
    parsed = _parsed("Gasversorgung Zürich – Erdgas Müller Käserei", "Natural gas usage", "Meter | Read Date | Usage (MMBtu)",
                     "BAL 7 | 01/31/2025 | 12", "CF 2 | 01/31/2025 | 8", "BF 1 | 01/31/2025 | 5")
    assert _quantities(parsed) == [12, 8, 5]


def test_a_run_called_balance_test_is_a_run() -> None:
    parsed = _parsed("Standby Generator Run Log", "run_type | date | run_hours | gallons_added",
                     "Balance test | 01/05/2025 | 3.2 | 85", "Outage | 01/28/2025 | 4.1 | 118")
    assert _quantities(parsed) == [85, 118]


def test_a_dated_line_starting_with_a_carried_forward_phrase_is_kept() -> None:
    parsed = _parsed("Standby Generator Run Log", "note | date | run_hours | gallons_added",
                     "Carried forward | 01/05/2025 | 3.2 | 85")
    assert _quantities(parsed) == [85]


@pytest.mark.parametrize("first", ["b/f", "C/F", "Brought forward", "Carried forward", "Opening balance",
                                   "Closing balance", "Balance b/f", "Balance c/f"])
def test_only_whole_carried_forward_phrases_without_a_date_are_skipped(first: str) -> None:
    parsed = _parsed("Standby Generator Run Log", HEADER, f"{first} | GEN-1 | 7.3 | 203 | -",
                     "01/28/2025 | GEN-1 | 4.1 | 118 | RO")
    assert _quantities(parsed) == [118]


@pytest.mark.parametrize(
    "title", ["Gen 1 Run Log – Plant Zürich", "Emergency Gen run sheet", "DG set run log", "Emergency generator – Log",
              "Standby Generator – Equipment Run Log", "GEN-2 log"])
def test_real_generator_wordings_type_as_a_run_log(title: str) -> None:
    assert _types_as_stationary(_parsed(title, "date | run_hours | gallons_added | operator",
                                        "01/05/2025 | 3.2 | 85 | J. Driver"))


def test_driver_counts_only_as_a_column_heading() -> None:
    assert _types_as_stationary(_parsed("Standby Generator Run Log", "date | run_hours | gallons_added | operator",
                                        "01/05/2025 | 3.2 | 85 | J. Driver"))
    assert not _types_as_stationary(_parsed("Standby Generator Run Log", "date | run_hours | gallons_added | driver",
                                            "01/05/2025 | 3.2 | 85 | A. Müller"))
