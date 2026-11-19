"""A generator run log (run hours plus fuel added) types as stationary fuel use even when it names no fuel; the
fuel is left for the reviewer. The same log as an .xls (no fuel word) and as a CSV (a fuel word in a comment)
read the same way, 2024 lines stay out of a 2025 year, and repeated lines reach the duplicate check."""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.app.services.data_quality_checks import EvidenceRecord, run_checks
from backend.app.services.electricity_extractor import ElectricityExtractor
from backend.app.services.engagement_recalculation_service import _proration
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.mobile_combustion_extractor import MobileCombustionExtractor
from backend.app.services.pipeline_orchestration_service import (
    FUELQTY_TYPE_ID,
    MOBFUEL_TYPE_ID,
    PipelineOrchestrationService,
)
from backend.app.services.stationary_combustion_extractor import CANONICAL_TYPE_ID, StationaryCombustionExtractor

TITLE = "Müller Käserei Zürich – Standby Generator GEN-ZH-01 – Run Log (Nov 2024 – Feb 2025)"
HEADER = "date | generator_id | run_type | hour_meter_start | hour_meter_end | run_hours | gallons_added | operator"
LINES = [
    "11/05/2024 | GEN-ZH-01 | Monthly test | 1836.1 | 1836.6 | 0.5 | 0 | R. Ochoa",
    "11/21/2024 | GEN-ZH-01 | Utility outage | 1836.6 | 1839.8 | 3.2 | 85 | R. Ochoa",
    "01/28/2025 | GEN-ZH-01 | Utility outage | 1842.3 | 1846.4 | 4.1 | 118 | Jürgen Weiß",
    "02/19/2025 | GEN-ZH-01 | Transfer switch test | 1846.9 | 1848.1 | 1.2 | 34 | 田中 太郎",
]
TOTAL = "TOTAL | 4 | 237"
COMMENT = "# gallons_added = diesel added to day tank after the run."


def _parsed(*lines: str) -> dict[str, Any]:
    blocks = [
        {"block_id": f"B{i}", "page_number": 1, "text": line, "source_reference_id": f"S{i}", "confidence": 0.99}
        for i, line in enumerate(lines)
    ]
    return {"document_id": "DOC-1", "text_blocks": blocks, "pages": [], "tables": [], "source_references": []}


def _read(parsed: dict[str, Any]) -> Any:
    targets = ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)
    return StationaryCombustionExtractor().extract(parsed, targets, "EV-1")


def _records(outcome: Any) -> dict[Any, dict[str, Any]]:
    out: dict[Any, dict[str, Any]] = {}
    for c in outcome.candidates:
        out.setdefault(c.get("record_index"), {})[c["field_name"]] = c
    return out


XLS_LIKE = _parsed(TITLE, HEADER, *LINES, TOTAL)
CSV_LIKE = _parsed(HEADER, *LINES, COMMENT)


def test_a_run_log_with_no_fuel_word_is_read_one_record_per_run_with_the_fuel_left_empty() -> None:
    outcome = _read(XLS_LIKE)
    assert outcome.halt_reason is None
    records = _records(outcome)
    assert len(records) == 4  # the TOTAL line is not a run
    assert [(r["activity_quantity"]["normalized_value"], r["activity_quantity"]["unit"]) for r in records.values()] == [
        (0, "gal"), (85, "gal"), (118, "gal"), (34, "gal")]
    assert all(r["fuel_type"]["normalized_value"] is None for r in records.values())
    assert any("names no fuel" in n for n in outcome.notes)


def test_the_xls_and_the_csv_of_one_log_read_the_same_lines() -> None:
    def signature(parsed: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
        return [(r["service_period_start"]["normalized_value"], r["activity_quantity"]["normalized_value"],
                 r["activity_quantity"]["unit"]) for r in _records(_read(parsed)).values()]

    assert signature(XLS_LIKE) == signature(CSV_LIKE)
    # The CSV names the fuel in its comment, so it keeps it; the XLS does not guess one.
    assert _records(_read(CSV_LIKE))[1]["fuel_type"]["normalized_value"] == "diesel"


def test_only_a_run_log_with_hours_and_fuel_added_confirms_without_a_fuel_word() -> None:
    stationary = StationaryCombustionExtractor()
    assert stationary.confirms(XLS_LIKE)
    assert stationary.reads_as_fuelless_run_log(XLS_LIKE)
    # run hours without fuel added, and fuel added without run hours, name no fuel and are not a run log
    assert not stationary.confirms(_parsed(TITLE, "date | run_hours | operator", "01/28/2025 | 4.1 | R. Ochoa"))
    assert not stationary.confirms(_parsed("Wasserwerk Zürich", "date | site | gallons_added", "01/28/2025 | A | 118"))
    # the other types keep their own checks
    assert not ElectricityExtractor().confirms(XLS_LIKE)
    assert not MobileCombustionExtractor().confirms(XLS_LIKE)


def _low_confidence(parsed: dict[str, Any]) -> str | None:
    result = {"status": "low_confidence",
              "candidate_matches": [{"canonical_type_id": MOBFUEL_TYPE_ID, "confidence": 0.41}]}
    return PipelineOrchestrationService._fuel_content_confirmed(result, parsed)


def test_a_low_confidence_run_log_that_reads_as_a_generator_is_typed_stationary() -> None:
    assert _low_confidence(XLS_LIKE) == FUELQTY_TYPE_ID


def test_a_low_confidence_fleet_log_is_still_not_read_as_stationary() -> None:
    fleet = _parsed("Fleet fuel card statement – odometer", "date | vehicle | gallons", "01/28/2025 | V-12 | 18.2")
    assert _low_confidence(fleet) != FUELQTY_TYPE_ID
    # a generator log with a vehicle cue too is mixed: no one-sided cue, nothing is guessed
    mixed = _parsed(TITLE, "Fleet fuel card", HEADER, *LINES)
    assert _low_confidence(mixed) is None


def test_a_bulk_diesel_statement_for_a_generator_plant_stays_untyped_for_the_reviewer() -> None:
    statement = _parsed("Summit Bulk Fuels – Standby Generator Plant, Lodi", "Delivery | Product | Gallons",
                        "05/03/2024 | Diesel | 1,200.0")
    assert _low_confidence(statement) is None


def test_2024_lines_keep_their_2024_dates_and_fall_outside_a_2025_year() -> None:
    records = _records(_read(XLS_LIKE))
    year = (date(2025, 1, 1), date(2025, 12, 31))
    shares = [_proration(r["service_period_start"]["normalized_value"], r["service_period_end"]["normalized_value"],
                         year) for r in records.values()]
    assert [reason for _, reason in shares] == ["outside_reporting_period", "outside_reporting_period", None, None]


def _evidence(document: str, file_name: str, parsed: dict[str, Any], fuel: str) -> list[EvidenceRecord]:
    """What the reviewer's accepted values give the duplicate check: the extracted dates and amounts, the fuel
    the reviewer chose."""

    out = []
    for index, r in _records(_read(parsed)).items():
        out.append(EvidenceRecord(
            category="stationary_combustion", document_id=document, file_name=file_name,
            label=f"{file_name} (record {index})", facility="Fresno Plant", item=fuel, account=None,
            start=date.fromisoformat(r["service_period_start"]["normalized_value"]),
            end=date.fromisoformat(r["service_period_end"]["normalized_value"]),
            amounts=(float(r["activity_quantity"]["normalized_value"]),), unit="gal", periodic=False))
    return out


def test_lines_repeated_in_the_csv_reach_the_duplicate_check() -> None:
    records = (_evidence("XLS", "log.xls", XLS_LIKE, "diesel") + _evidence("CSV", "log.csv", CSV_LIKE, "diesel"))
    findings = run_checks(records, (date(2025, 1, 1), date(2025, 12, 31)))
    dupes = [f for f in findings if f["check"] == "Q-003"]
    assert len(dupes) == 1
    assert dupes[0]["detail"]["matching_records"] == 4  # all four lines of the xls sit in the CSV too
