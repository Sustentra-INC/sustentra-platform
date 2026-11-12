from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.services.electricity_extractor import (
    CANONICAL_TYPE_ID,
    ElectricityExtractor,
    detect_electricity,
)
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.stationary_combustion_extractor import HALT_UNREADABLE, HALT_UNSUPPORTED


@pytest.fixture(scope="module")
def targets() -> list[dict]:
    return ExtractionTargetService().get_targets_for_canonical_type(CANONICAL_TYPE_ID)


def _text_output(text: str, document_id: str = "DOC-1") -> dict[str, Any]:
    return {
        "document_id": document_id,
        "pages": [{"page_number": 1, "text": text}],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}],
        "tables": [], "key_value_pairs": [], "source_references": [],
    }


def _by_field(candidates: list[dict], record_index: int | None = None) -> dict[str, dict]:
    return {c["field_name"]: c for c in candidates if c["record_index"] == record_index}


LABELED_BILL = (
    "Riverside Electric Utility\n"
    "Electricity Bill\n"
    "Customer Name\tNorthfield Manufacturing Plant 2\n"
    "Service Address\t1200 Industrial Pkwy, Fresno, CA 93722\n"
    "Account Number\tRE-7781-2210\n"
    "Service Period\tJan 1, 2025 to Jan 31, 2025\n"
    "Total kWh Used\t12,450 kWh\n"
    "Demand (kW)\t85\n"
    "Amount Due\t$2,148.33\n"
)

METER_TABLE_BILL = (
    "Valley Power and Light - Electric Service Statement\n"
    "Facility\tWest Warehouse\n"
    "Service Address\t88 Harbor Rd, Oakland, CA 94607\n"
    "Account Number\tVPL-002-3391\n"
    "Billing Period\t03/01/2025 - 03/31/2025\n"
    "Meter Number\tPrevious Read\tCurrent Read\tMultiplier\tkWh Used\tDemand (kW)\n"
    "M-55012\t104,220\t116,670\t1\t12,450\t85\n"
    "M-55013\t20,100\t24,300\t1\t4,200\t30\n"
)

GAS_BILL = (
    "National Fuel Gas Company - Natural Gas Statement\n"
    "Account Number\tACC-1\n"
    "Service Period\tJan 1, 2023 to Jan 31, 2023\n"
    "Total Usage\t32,400 MMBtu\n"
)


# --- vocabulary ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["Electricity Bill", "Electric Service", "Total kWh", "3.2 MWh",
                                  "kilowatt hours"])
def test_detects_electricity(text: str) -> None:
    hit = detect_electricity(text)
    assert hit is not None and hit[0] == "electricity"


@pytest.mark.parametrize("text", ["Natural Gas Statement", "Diesel #2", "Thermostat", "Electrician visit fee"])
def test_non_electricity_text(text: str) -> None:
    assert detect_electricity(text) is None


def test_config_defines_the_scope2_electricity_fields(targets: list[dict]) -> None:
    assert {t["field_id"] for t in targets} >= {
        "facility_name", "service_address", "account_number", "service_period_start",
        "service_period_end", "energy_type", "activity_quantity", "activity_unit",
    }


# --- extraction ---------------------------------------------------------------------------
def test_labeled_bill_normalizes_kwh_to_mwh(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_text_output(LABELED_BILL), targets, "EV-1")
    assert outcome.halt_reason is None
    assert outcome.records == 1
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["raw_value"] == "12,450"
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(12.45)
    assert fields["activity_quantity"]["unit"] == "MWh"
    assert "unit_converted" in fields["activity_quantity"]["validation_flags"]
    assert fields["activity_unit"]["normalized_value"] == "MWh"
    assert fields["energy_type"]["normalized_value"] == "electricity"
    assert fields["facility_name"]["normalized_value"] == "Northfield Manufacturing Plant 2"
    assert fields["service_address"]["normalized_value"] == "1200 Industrial Pkwy, Fresno, CA 93722"
    assert fields["account_number"]["normalized_value"] == "RE-7781-2210"
    assert fields["supplier_name"]["normalized_value"] == "Riverside Electric Utility"
    assert fields["service_period_start"]["normalized_value"] == "2025-01-01"
    assert fields["service_period_end"]["normalized_value"] == "2025-01-31"
    # every extracted value points back to where it was read
    assert fields["activity_quantity"]["source_reference"]["text_snippet"]


def test_meter_table_one_record_per_meter_and_demand_is_ignored(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_text_output(METER_TABLE_BILL), targets, "EV-1")
    assert outcome.halt_reason is None
    assert outcome.records == 2
    first, second = _by_field(outcome.candidates, 1), _by_field(outcome.candidates, 2)
    assert first["activity_quantity"]["normalized_value"] == pytest.approx(12.45)  # not 85 kW demand
    assert second["activity_quantity"]["normalized_value"] == pytest.approx(4.2)
    assert first["supplier_name"]["normalized_value"] == "Valley Power and Light"
    assert first["service_period_end"]["normalized_value"] == "2025-03-31"
    assert first["activity_quantity"]["source_reference"]["record_key"] != \
        second["activity_quantity"]["source_reference"]["record_key"]


def test_time_of_use_bill_reads_the_total_column(targets: list[dict]) -> None:
    text = (
        "Coastal Electric Cooperative\n"
        "Account Number\tCEC-77\n"
        "Service Period\tFeb 1, 2025 to Feb 28, 2025\n"
        "Meter Number\tOn-Peak kWh\tOff-Peak kWh\tTotal kWh\n"
        "M-1\t3,000\t5,000\t8,000\n"
    )
    outcome = ElectricityExtractor().extract(_text_output(text), targets, "EV-1")
    assert outcome.halt_reason is None
    assert _by_field(outcome.candidates)["activity_quantity"]["normalized_value"] == pytest.approx(8.0)


def test_mwh_bill_is_not_converted(targets: list[dict]) -> None:
    text = (
        "Grid Co Electricity Invoice\n"
        "Account Number: GC-1\n"
        "Service Period: 2025-04-01 to 2025-04-30\n"
        "Total Consumption: 3.2 MWh\n"
    )
    fields = _by_field(ElectricityExtractor().extract(_text_output(text), targets, "EV-1").candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(3.2)
    assert "unit_converted" not in fields["activity_quantity"]["validation_flags"]


def test_gas_bill_is_not_electricity_evidence(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_text_output(GAS_BILL), targets, "EV-1")
    assert outcome.candidates == []
    assert outcome.halt_reason["code"] == HALT_UNSUPPORTED


def test_empty_document_is_unreadable(targets: list[dict]) -> None:
    outcome = ElectricityExtractor().extract(_text_output(""), targets, "EV-1")
    assert outcome.halt_reason["code"] == HALT_UNREADABLE


def test_confirms_electricity_but_not_gas() -> None:
    extractor = ElectricityExtractor()
    assert extractor.confirms(_text_output(LABELED_BILL)) is True
    assert extractor.confirms(_text_output(METER_TABLE_BILL)) is True
    assert extractor.confirms(_text_output(GAS_BILL)) is False


def test_extraction_service_routes_scope2_targets(targets: list[dict]) -> None:
    result = ExtractionService().extract(
        {"parser_output": _text_output(LABELED_BILL), "extraction_targets": targets, "evidence_id": "EV-1"}
    )
    assert result["record_count"] == 1
    assert {item["field_name"] for item in result["items"]} >= {"activity_quantity", "energy_type"}


# --- pipeline routing ---------------------------------------------------------------------
def test_reroute_only_moves_electric_bills_off_stationary_fuel() -> None:
    reroute = PipelineOrchestrationService._electricity_reroute
    assert reroute("CT-S1-FUELQTY", _text_output(METER_TABLE_BILL)) is True
    assert reroute("CT-S1-FUELQTY", _text_output(GAS_BILL)) is False
    assert reroute("CT-S1-MOBFUEL", _text_output(METER_TABLE_BILL)) is False


@pytest.mark.parametrize(("bill", "file_name"), [(LABELED_BILL, "riverside_jan.txt"),
                                                  (METER_TABLE_BILL, "scan_0042.txt")])
def test_pipeline_extracts_electricity_end_to_end(tmp_path: Path, bill: str, file_name: str) -> None:
    path = tmp_path / file_name
    path.write_text(bill, encoding="utf-8")
    result = PipelineOrchestrationService().process_local_document(
        str(path), engagement_id="ENG-1", persist_run=False, org_id="org-1"
    )
    assert result["pipeline_run"]["canonical_type_id"] == CANONICAL_TYPE_ID
    items = result["extraction_result"]["items"]
    quantities = [i["normalized_value"] for i in items if i["field_name"] == "activity_quantity"]
    assert quantities and all(q is not None for q in quantities)
    assert {i["unit"] for i in items if i["field_name"] == "activity_quantity"} == {"MWh"}


def test_pipeline_still_sends_gas_bills_to_stationary_combustion(tmp_path: Path) -> None:
    path = tmp_path / "gas.txt"
    path.write_text(GAS_BILL, encoding="utf-8")
    result = PipelineOrchestrationService().process_local_document(
        str(path), engagement_id="ENG-1", persist_run=False, org_id="org-1"
    )
    assert result["pipeline_run"]["canonical_type_id"] == "CT-S1-FUELQTY"


# A phone photo of a bill reads as two lines: a total in kWh and a period. The classifier's best
# (weak) guess for so little text is a vehicle fuel log, so the electricity check must still run.
SPARSE_PHOTO_BILL = "City Water & Power\nTotal kWh Used: 41,200 kWh\nService Period: 05/01/2025 to 05/31/2025\n"


def test_a_sparse_photo_of_an_electric_bill_is_read_as_electricity(tmp_path: Path) -> None:
    path = tmp_path / "photo_electric_bill_may2025.txt"
    path.write_text(SPARSE_PHOTO_BILL, encoding="utf-8")
    result = PipelineOrchestrationService().process_local_document(str(path), engagement_id="ENG-1", persist_run=False)
    assert result["classification_result"]["primary_canonical_type_id"] == "CT-S1-MOBFUEL"  # the weak guess
    assert result["pipeline_run"]["canonical_type_id"] == CANONICAL_TYPE_ID
    items = {i["field_name"]: i for i in result["extraction_result"]["items"]}
    assert (items["activity_quantity"]["normalized_value"], items["activity_quantity"]["unit"]) == (41.2, "MWh")
    assert items["service_period_start"]["normalized_value"] == "2025-05-01"


# --- a labelled value that follows other text in the same line ---------------------------------
# Staging walkthrough, 11 Nov: OCR of a phone photo returns one line, so "Service Period" is not at
# the start of its cell, and the letterhead is a lone line with nothing larger beside it.
OCR_LINE = "Total kWh Used: 41,200 kWh   Service Period: 05/01/2025 to 05/31/2025"


def _ocr_blocks(*lines: tuple[str, float, float]) -> dict[str, Any]:
    """parser_output as OCR returns it: one boxed block per line, (text, top, height)."""
    blocks = [{"block_id": f"b{i}", "page_number": 1, "text": text, "confidence": 98.0,
               "bounding_box": {"left": 0.1, "top": top, "width": 0.6, "height": height},
               "source_reference_id": None} for i, (text, top, height) in enumerate(lines)]
    return {"document_id": "DOC-OCR", "pages": [], "text_blocks": blocks, "tables": [], "key_value_pairs": [],
            "source_references": []}


@pytest.mark.parametrize("output", [
    _text_output("City Water & Power\n" + OCR_LINE),
    _ocr_blocks(("City Water & Power", 0.05, 0.03), (OCR_LINE, 0.2, 0.012)),
    _ocr_blocks(("City Water & Power", 0.05, 0.012), (OCR_LINE, 0.3, 0.012)),  # same text size, line below 0.2
    _ocr_blocks(("City Water & Power", 0.05, 0.03), (OCR_LINE, 0.1, 0.012)),   # a second line within the top fifth
], ids=["plain-text", "ocr-larger-letterhead", "ocr-same-size", "ocr-two-lines-near-top"])
def test_period_and_supplier_are_read_from_the_one_line_ocr_text(targets: list[dict], output: dict[str, Any]) -> None:
    outcome = ElectricityExtractor().extract(output, targets, "EV-1")
    assert outcome.halt_reason is None
    fields = _by_field(outcome.candidates)
    assert fields["activity_quantity"]["normalized_value"] == pytest.approx(41.2)
    assert fields["service_period_start"]["normalized_value"] == "2025-05-01"
    assert fields["service_period_end"]["normalized_value"] == "2025-05-31"
    assert fields["supplier_name"]["normalized_value"] == "City Water & Power"
    assert fields["service_period_start"]["source_reference"]["text_snippet"]


def test_a_period_label_after_other_text_needs_a_colon_or_dates(targets: list[dict]) -> None:
    # "period" and "from"/"to" are common words: running text must not be read as a period
    prose = ("Total kWh Used: 41,200 kWh   Questions about this period? Call us. "
             "Meter read from the street, due to 06/10/2025")
    fields = _by_field(ElectricityExtractor().extract(
        _ocr_blocks(("City Water & Power", 0.05, 0.03), (prose, 0.2, 0.012)), targets, "EV-1").candidates)
    assert fields["service_period_start"]["raw_value"] is None
    assert fields["service_period_end"]["raw_value"] is None
    # a colon, or dates directly after a long enough label, is enough
    for line in ("Total kWh Used: 41,200 kWh Billing Period: 05/01/2025 to 05/31/2025",
                 "Total kWh Used: 41,200 kWh Statement period 05/01/2025 - 05/31/2025"):
        fields = _by_field(ElectricityExtractor().extract(
            _ocr_blocks(("City Water & Power", 0.05, 0.03), (line, 0.2, 0.012)), targets, "EV-1").candidates)
        assert (fields["service_period_start"]["normalized_value"],
                fields["service_period_end"]["normalized_value"]) == ("2025-05-01", "2025-05-31")


def test_an_inline_value_stops_at_the_next_label(targets: list[dict]) -> None:
    line = "Total kWh Used: 41,200 kWh Account Number: AB-1234 Service Period: 05/01/2025 to 05/31/2025"
    fields = _by_field(ElectricityExtractor().extract(
        _ocr_blocks(("City Water & Power", 0.05, 0.03), (line, 0.2, 0.012)), targets, "EV-1").candidates)
    assert fields["account_number"]["normalized_value"] == "AB-1234"
    assert fields["service_period_end"]["normalized_value"] == "2025-05-31"


def test_a_lone_first_line_is_not_a_supplier_unless_it_names_an_organization(targets: list[dict]) -> None:
    for title in ("Electricity Bill", "Natural Gas Utility Bill", "Customer Copy"):
        fields = _by_field(ElectricityExtractor().extract(
            _ocr_blocks((title, 0.05, 0.03), (OCR_LINE, 0.2, 0.012)), targets, "EV-1").candidates)
        assert fields["supplier_name"]["raw_value"] is None, title
    # an address after the name is not part of it
    fields = _by_field(ElectricityExtractor().extract(
        _ocr_blocks(("Shell Energy UK Limited, Elder House, 586 Elder Gate", 0.05, 0.03), (OCR_LINE, 0.2, 0.012)),
        targets, "EV-1").candidates)
    assert fields["supplier_name"]["normalized_value"] == "Shell Energy UK Limited"


def test_thermal_extractor_reads_the_same_one_line_layout() -> None:
    from backend.app.services.thermal_extractor import CANONICAL_TYPE_ID as THERMAL_ID
    from backend.app.services.thermal_extractor import ThermalExtractor

    thermal_targets = ExtractionTargetService().get_targets_for_canonical_type(THERMAL_ID)
    line = "Steam Usage: 1,250 MMBtu   Service Period: 05/01/2025 to 05/31/2025"
    outcome = ThermalExtractor().extract(
        _ocr_blocks(("Metro District Energy", 0.05, 0.03), (line, 0.2, 0.012)), thermal_targets, "EV-1")
    assert outcome.halt_reason is None
    fields = _by_field(outcome.candidates)
    assert fields["energy_type"]["normalized_value"] == "steam"
    assert fields["service_period_start"]["normalized_value"] == "2025-05-01"
    assert fields["service_period_end"]["normalized_value"] == "2025-05-31"
    assert fields["supplier_name"]["normalized_value"] == "Metro District Energy"
