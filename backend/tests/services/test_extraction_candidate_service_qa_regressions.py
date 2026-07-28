from __future__ import annotations

from backend.app.services.extraction_candidate_service import ExtractionCandidateService

REQUIRED_CANDIDATE_KEYS = {
    "candidate_id",
    "evidence_id",
    "document_id",
    "field_name",
    "display_label",
    "raw_value",
    "normalized_value",
    "unit",
    "confidence",
    "source_reference",
    "validation_flags",
}


def _base_parser_output(*, document_id: str, pages=None, tables=None, key_value_pairs=None):
    return {
        "parser_output_id": f"PO::{document_id}",
        "document_id": document_id,
        "processing_run_id": f"RUN::{document_id}",
        "parser_name": "text_parser",
        "parser_version": "v0",
        "status": "parsed",
        "created_at": "2026-07-24T00:00:00+00:00",
        "pages": pages or [],
        "text_blocks": [],
        "tables": tables or [],
        "key_value_pairs": key_value_pairs or [],
        "source_references": [],
        "warnings": [],
    }


def _target(
    *,
    field_id: str,
    methods: tuple[str, ...],
    value_type: str,
    anchor_labels: tuple[str, ...],
    value_patterns: tuple[str, ...],
    expected_units: tuple[str, ...] = (),
    unit_patterns: tuple[str, ...] = (),
    normalization: dict | None = None,
    validation_hints: tuple[str, ...] = (),
):
    return {
        "target_id": f"target::QA::{field_id}",
        "extraction_config_id": f"EC::{field_id}",
        "field_id": field_id,
        "field_label": field_id,
        "canonical_type_id": "CT-S1-TEST",
        "value_type": value_type,
        "required_status": "core",
        "expected_units": expected_units,
        "source_reference_required": True,
        "anchor_labels": anchor_labels,
        "value_patterns": value_patterns,
        "unit_patterns": unit_patterns,
        "table_hints": (),
        "sheet_hints": (),
        "validation_hints": validation_hints,
        "extraction_methods": methods,
        "normalization": normalization or {},
        "population_status": "provisional",
        "version": "v0.1",
    }


def _assert_candidate_keys(candidate: dict) -> None:
    assert set(candidate.keys()) == REQUIRED_CANDIDATE_KEYS


def test_service_period_end_to_does_not_match_total_usage() -> None:
    parser_output = _base_parser_output(
        document_id="EV-FUELQTY-001",
        pages=[
            {
                "page_number": 1,
                "text": (
                    "Service Period: Jan 1, 2023 to Jan 31, 2023\n"
                    "From: 01/01/2023\n"
                    "To: 01/31/2023\n"
                    "Total Usage: 32,400 MMBtu"
                ),
            }
        ],
        key_value_pairs=[
            {
                "pair_id": "kv-qty",
                "page_number": 1,
                "sheet_name": None,
                "key": "Total Usage",
                "value": "32,400 MMBtu",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
            {
                "pair_id": "kv-to",
                "page_number": 1,
                "sheet_name": None,
                "key": "To",
                "value": "01/31/2023",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
        ],
    )
    target = _target(
        field_id="service_period_end",
        methods=("key_value_pair", "anchor_text", "regex"),
        value_type="date",
        anchor_labels=("Service Period", "Billing Period", "To", "Period End", "Read Date"),
        value_patterns=(r"\d{4}-\d{2}-\d{2}", r"\d{1,2}/\d{1,2}/\d{2,4}"),
    )

    candidate = ExtractionCandidateService().generate_candidates(
        parser_output=parser_output,
        extraction_targets=[target],
        evidence_id="EV-QA-1",
    )[0]

    _assert_candidate_keys(candidate)
    assert candidate["field_name"] == "service_period_end"
    assert candidate["raw_value"] == "01/31/2023"
    assert candidate["normalized_value"] == "2023-01-31"
    assert candidate["unit"] is None
    assert candidate["validation_flags"] == []
    assert "To: 01/31/2023" in str(candidate["source_reference"].get("text_snippet") or "")
    assert candidate["raw_value"] != "32,400 MMBtu"


def test_split_usage_unit_inferred_from_neighboring_kv_pair() -> None:
    parser_output = _base_parser_output(
        document_id="EV-FUELQTY-002",
        pages=[
            {
                "page_number": 1,
                "text": "Usage: 32,400\nUsage Unit: MMBtu",
            }
        ],
        key_value_pairs=[
            {
                "pair_id": "kv-usage",
                "page_number": 1,
                "sheet_name": None,
                "key": "Usage",
                "value": "32,400",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
            {
                "pair_id": "kv-unit",
                "page_number": 1,
                "sheet_name": None,
                "key": "Usage Unit",
                "value": "MMBtu",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
        ],
    )
    target = _target(
        field_id="activity_quantity",
        methods=("key_value_pair", "regex"),
        value_type="quantity",
        anchor_labels=("Total Usage", "Gas Used", "Usage", "Quantity", "Consumption"),
        value_patterns=(r"\d[\d,]*(?:\.\d+)?",),
        expected_units=("MMBtu", "therm", "ccf", "gallon", "liter"),
        unit_patterns=("MMBtu", "therms?", "ccf", "gallons?", "liters?"),
        normalization={"target_unit": "MMBtu"},
    )

    candidate = ExtractionCandidateService().generate_candidates(
        parser_output=parser_output,
        extraction_targets=[target],
        evidence_id="EV-QA-2",
    )[0]

    _assert_candidate_keys(candidate)
    assert candidate["field_name"] == "activity_quantity"
    assert candidate["raw_value"] == "32,400"
    assert candidate["normalized_value"] == 32400
    assert candidate["unit"] == "MMBtu"
    assert "unit_missing" not in candidate["validation_flags"]


def test_no_activity_statement_does_not_extract_year() -> None:
    parser_output = _base_parser_output(
        document_id="EV-FUELQTY-004",
        pages=[
            {
                "page_number": 1,
                "text": (
                    "Document ID: EV-RFO-2023-001\n"
                    "Residual fuel oil backup boiler standby statement\n"
                    "Fuel Deliveries Recorded: 0 gallons\n"
                    "Fuel Consumption Recorded: 0 gallons\n"
                    "Combustion Hours Recorded: 0 hours\n"
                    "Annual Emissions Activity: No activity"
                ),
            }
        ],
        key_value_pairs=[
            {
                "pair_id": "kv-deliveries",
                "page_number": 1,
                "sheet_name": None,
                "key": "Fuel Deliveries Recorded",
                "value": "0 gallons",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
            {
                "pair_id": "kv-activity",
                "page_number": 1,
                "sheet_name": None,
                "key": "Annual Emissions Activity",
                "value": "No activity",
                "confidence": 0.99,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            },
        ],
    )
    target = _target(
        field_id="activity_quantity",
        methods=("regex", "anchor_text", "key_value_pair"),
        value_type="quantity",
        anchor_labels=("Total Usage", "Gas Used", "Usage", "Quantity", "Consumption"),
        value_patterns=(r"\d[\d,]*(?:\.\d+)?",),
        expected_units=("MMBtu", "therm", "ccf", "gallon", "liter"),
        unit_patterns=("MMBtu", "therms?", "ccf", "gallons?", "liters?", "hours?"),
        normalization={"target_unit": "MMBtu"},
    )

    candidate = ExtractionCandidateService().generate_candidates(
        parser_output=parser_output,
        extraction_targets=[target],
        evidence_id="EV-QA-3",
    )[0]

    _assert_candidate_keys(candidate)
    assert candidate["field_name"] == "activity_quantity"
    assert candidate["raw_value"] is None
    assert candidate["normalized_value"] is None
    assert candidate["unit"] is None
    assert candidate["confidence"] == 0.20
    assert "field_not_found" in candidate["validation_flags"]
    assert candidate["raw_value"] not in {"2023", "0", "0 gallons", "0 hours"}


def test_mobile_fuel_ticket_row_binding_first_ticket() -> None:
    parser_output = _base_parser_output(
        document_id="EV-MOBFUEL-002",
        pages=[
            {
                "page_number": 1,
                "text": (
                    "Delivery Date | Ticket No. | Gallons Delivered | Tank / Equipment | Use Category\n"
                    "03/14/2023 | D2-23-0412 | 900 | GEN-001 day tank / bulk tank | Emergency standby\n"
                    "07/21/2023 | D2-23-1187 | 850 | GEN-001 day tank / bulk tank | Emergency standby\n"
                    "11/08/2023 | D2-23-1964 | 1,050 | GEN-001 day tank / bulk tank | Emergency standby"
                ),
            }
        ],
        tables=[
            {
                "table_id": "t-mobfuel-1",
                "page_number": 1,
                "sheet_name": None,
                "rows": [
                    [
                        "Delivery Date",
                        "Ticket No.",
                        "Gallons Delivered",
                        "Tank / Equipment",
                        "Use Category",
                    ],
                    [
                        "03/14/2023",
                        "D2-23-0412",
                        "900",
                        "GEN-001 day tank / bulk tank",
                        "Emergency standby",
                    ],
                    [
                        "07/21/2023",
                        "D2-23-1187",
                        "850",
                        "GEN-001 day tank / bulk tank",
                        "Emergency standby",
                    ],
                ],
                "confidence": 0.95,
                "source_reference_id": None,
            }
        ],
    )
    target = _target(
        field_id="activity_quantity",
        methods=("table_lookup", "regex", "key_value_pair"),
        value_type="quantity",
        anchor_labels=("Quantity", "Gallons", "Liters", "Volume", "Total"),
        value_patterns=(r"\d[\d,]*(?:\.\d+)?",),
        expected_units=("gallon", "liter"),
        unit_patterns=("gallons?", "liters?", "gal", "L"),
        normalization={"target_unit": "gallon", "record_id": "D2-23-0412"},
    )

    candidate = ExtractionCandidateService().generate_candidates(
        parser_output=parser_output,
        extraction_targets=[target],
        evidence_id="EV-QA-4",
    )[0]

    _assert_candidate_keys(candidate)
    assert candidate["field_name"] == "activity_quantity"
    assert candidate["raw_value"] == "900"
    assert candidate["normalized_value"] == 900
    assert candidate["unit"] == "gallons"
    assert "unit_missing" not in candidate["validation_flags"]
    assert "D2-23-0412" in str(candidate["source_reference"].get("text_snippet") or "")


def test_mobile_fuel_ticket_row_binding_second_ticket() -> None:
    parser_output = _base_parser_output(
        document_id="EV-MOBFUEL-002",
        pages=[
            {
                "page_number": 1,
                "text": (
                    "Delivery Date | Ticket No. | Gallons Delivered | Tank / Equipment | Use Category\n"
                    "03/14/2023 | D2-23-0412 | 900 | GEN-001 day tank / bulk tank | Emergency standby\n"
                    "07/21/2023 | D2-23-1187 | 850 | GEN-001 day tank / bulk tank | Emergency standby\n"
                    "11/08/2023 | D2-23-1964 | 1,050 | GEN-001 day tank / bulk tank | Emergency standby"
                ),
            }
        ],
        tables=[
            {
                "table_id": "t-mobfuel-1",
                "page_number": 1,
                "sheet_name": None,
                "rows": [
                    [
                        "Delivery Date",
                        "Ticket No.",
                        "Gallons Delivered",
                        "Tank / Equipment",
                        "Use Category",
                    ],
                    [
                        "03/14/2023",
                        "D2-23-0412",
                        "900",
                        "GEN-001 day tank / bulk tank",
                        "Emergency standby",
                    ],
                    [
                        "07/21/2023",
                        "D2-23-1187",
                        "850",
                        "GEN-001 day tank / bulk tank",
                        "Emergency standby",
                    ],
                ],
                "confidence": 0.95,
                "source_reference_id": None,
            }
        ],
    )
    target = _target(
        field_id="activity_quantity",
        methods=("table_lookup", "regex", "key_value_pair"),
        value_type="quantity",
        anchor_labels=("Quantity", "Gallons", "Liters", "Volume", "Total"),
        value_patterns=(r"\d[\d,]*(?:\.\d+)?",),
        expected_units=("gallon", "liter"),
        unit_patterns=("gallons?", "liters?", "gal", "L"),
        normalization={"target_unit": "gallon"},
        validation_hints=("record_id:D2-23-1187",),
    )

    candidate = ExtractionCandidateService().generate_candidates(
        parser_output=parser_output,
        extraction_targets=[target],
        evidence_id="EV-QA-5",
    )[0]

    _assert_candidate_keys(candidate)
    assert candidate["field_name"] == "activity_quantity"
    assert candidate["raw_value"] == "850"
    assert candidate["normalized_value"] == 850
    assert candidate["unit"] == "gallons"
    assert "unit_missing" not in candidate["validation_flags"]
    assert "D2-23-1187" in str(candidate["source_reference"].get("text_snippet") or "")
