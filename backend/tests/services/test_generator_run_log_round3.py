"""Run-log round 3: a bare "Gen." (a general contractor) is not a generator cue, and portable-equipment words
rule a log out of the stationary run-log route."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.pipeline_orchestration_service import FUELQTY_TYPE_ID, MOBFUEL_TYPE_ID, PipelineOrchestrationService
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor

COLUMNS = "date | hours run | gallons added | operator"


def _parsed(*lines: str) -> dict[str, Any]:
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": t, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, t in enumerate(lines)
    ]
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def _stationary(parsed: dict[str, Any]) -> bool:
    result = {"status": "low_confidence",
              "candidate_matches": [{"canonical_type_id": MOBFUEL_TYPE_ID, "confidence": 0.41}]}
    return (StationaryCombustionExtractor().confirms(parsed)
            or PipelineOrchestrationService._fuel_content_confirmed(result, parsed) == FUELQTY_TYPE_ID)


def test_a_gen_contractor_skid_steer_log_is_not_typed_as_stationary() -> None:
    assert not _stationary(_parsed("Gen. Contractor – Equipment Log", COLUMNS, "01/05/2025 | 3.2 | 40 | Skid steer"))
    assert not _stationary(_parsed("Gen. Contractor Müller & Söhne – Log", COLUMNS, "01/05/2025 | 3.2 | 40 | R. Ochoa"))


@pytest.mark.parametrize("title", ["Gen 1 Run Log", "GEN-2 log", "Gen2 run sheet", "Gen set run log", "Emergency Gen",
                                   "Generator log", "Standby generator – Zürich"])
def test_real_generator_titles_are_still_typed_as_stationary(title: str) -> None:
    assert _stationary(_parsed(title, COLUMNS, "01/05/2025 | 3.2 | 85 | J. Driver"))


@pytest.mark.parametrize("machine", ["Skid steer", "Dozer", "Bulldozer", "Grader", "Loader", "Backhoe", "Pickup",
                                     "Van", "Truck", "Rental unit", "Light tower", "Portable compressor"])
def test_portable_equipment_rules_a_generator_titled_log_out(machine: str) -> None:
    assert not _stationary(_parsed("Standby Generator Run Log", COLUMNS, f"01/05/2025 | 3.2 | 40 | {machine}"))
