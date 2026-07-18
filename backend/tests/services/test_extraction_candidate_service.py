import copy

import pytest

from backend.app.services.extraction_candidate_service import ExtractionCandidateService

REQUIRED_CANDIDATE_FIELDS = [
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
]


def _target(
    field_id,
    methods,
    *,
    value_type="string",
    required_status="core",
    anchor_labels=(),
    value_patterns=(),
    unit_patterns=(),
    expected_units=(),
    sheet_hints=(),
    normalization=None,
    field_label=None,
):
    return {
        "target_id": f"target::CT-S1-FUELQTY::{field_id}",
        "extraction_config_id": f"EC-{field_id}",
        "field_id": field_id,
        "field_label": field_label or field_id,
        "canonical_type_id": "CT-S1-FUELQTY",
        "value_type": value_type,
        "required_status": required_status,
        "expected_units": tuple(expected_units),
        "source_reference_required": True,
        "anchor_labels": tuple(anchor_labels),
        "value_patterns": tuple(value_patterns),
        "unit_patterns": tuple(unit_patterns),
        "table_hints": (),
        "sheet_hints": tuple(sheet_hints),
        "validation_hints": (),
        "extraction_methods": tuple(methods),
        "normalization": normalization or {},
        "population_status": "provisional",
        "version": "v0.1",
    }


def _parser_output(**overrides):
    base = {
        "parser_output_id": "PO-1",
        "document_id": "DOC-1",
        "processing_run_id": "RUN-1",
        "parser_name": "text_parser",
        "parser_version": "v0",
        "status": "parsed",
        "created_at": "2026-07-18T00:00:00+00:00",
        "pages": [],
        "text_blocks": [],
        "tables": [],
        "key_value_pairs": [],
        "source_references": [],
        "warnings": [],
    }
    base.update(overrides)
    return base


def _assert_candidate_shape(candidate):
    for field in REQUIRED_CANDIDATE_FIELDS:
        assert field in candidate, f"missing candidate field: {field}"
    assert 0.0 <= candidate["confidence"] <= 1.0
    assert isinstance(candidate["validation_flags"], list)
    assert isinstance(candidate["source_reference"], dict)


def test_regex_extraction_creates_candidate():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "Usage 28,100 total", "confidence": None, "source_reference_id": None}]
    )
    target = _target("activity_quantity", ["regex"], value_type="number", value_patterns=[r"\d[\d,]*"])

    candidates = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")

    assert len(candidates) == 1
    candidate = candidates[0]
    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] == "28,100"
    assert candidate["normalized_value"] == 28100
    assert candidate["confidence"] == 0.85


def test_anchor_text_extraction_creates_candidate():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "Facility: Plant 42", "confidence": None, "source_reference_id": None}]
    )
    target = _target("facility_name", ["anchor_text"], anchor_labels=["Facility"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] == "Plant 42"
    assert candidate["normalized_value"] == "Plant 42"
    assert candidate["confidence"] == 0.80


def test_key_value_pair_extraction_creates_candidate():
    parser_output = _parser_output(
        key_value_pairs=[
            {
                "pair_id": "kv1",
                "page_number": 1,
                "sheet_name": None,
                "key": "Total Usage",
                "value": "28,100",
                "confidence": None,
                "key_source_reference_id": None,
                "value_source_reference_id": None,
            }
        ]
    )
    target = _target("activity_quantity", ["key_value_pair"], value_type="quantity", anchor_labels=["Total Usage"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] == "28,100"
    assert candidate["normalized_value"] == 28100
    assert candidate["confidence"] == 0.90


def test_table_lookup_extraction_creates_candidate():
    parser_output = _parser_output(
        tables=[
            {
                "table_id": "t1",
                "page_number": 1,
                "sheet_name": "Sheet1",
                "rows": [["Fuel Type", "Natural Gas"]],
                "confidence": None,
                "source_reference_id": None,
            }
        ]
    )
    target = _target("fuel_type", ["table_lookup"], anchor_labels=["Fuel Type"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] == "Natural Gas"
    assert candidate["confidence"] == 0.75


def test_excel_cell_extraction_creates_candidate():
    parser_output = _parser_output(
        source_references=[
            {
                "source_reference_id": "SRC-A1",
                "document_id": "DOC-1",
                "page_number": None,
                "sheet_name": "Sheet1",
                "cell_or_range": "A1",
                "text_snippet": "Facility",
                "bounding_box": None,
                "parser_block_ids": ["openpyxl-Sheet1-A1"],
                "source_kind": "excel_cell",
            },
            {
                "source_reference_id": "SRC-B1",
                "document_id": "DOC-1",
                "page_number": None,
                "sheet_name": "Sheet1",
                "cell_or_range": "B1",
                "text_snippet": "Plant 42",
                "bounding_box": None,
                "parser_block_ids": ["openpyxl-Sheet1-B1"],
                "source_kind": "excel_cell",
            },
        ]
    )
    target = _target("facility_name", ["excel_cell"], anchor_labels=["Facility"], sheet_hints=["Sheet1"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] == "Plant 42"
    assert candidate["source_reference"]["cell_or_range"] == "B1"
    assert candidate["confidence"] == 0.70


def test_missing_core_field_returns_flagged_candidate():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "no numbers here", "confidence": None, "source_reference_id": None}]
    )
    target = _target("activity_quantity", ["regex"], value_type="number", value_patterns=[r"\d+"], required_status="core")

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] is None
    assert candidate["normalized_value"] is None
    assert candidate["confidence"] == 0.20
    assert "field_not_found" in candidate["validation_flags"]


def test_unsupported_method_returns_flagged_candidate():
    parser_output = _parser_output()
    target = _target("facility_name", ["llm_structured", "manual_entry"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    _assert_candidate_shape(candidate)
    assert candidate["raw_value"] is None
    assert candidate["confidence"] == 0.10
    assert "unsupported_extraction_method" in candidate["validation_flags"]


def test_candidate_source_reference_includes_document_id():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "Facility: Plant 42", "confidence": None, "source_reference_id": None}]
    )
    target = _target("facility_name", ["anchor_text"], anchor_labels=["Facility"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["source_reference"]["document_id"] == "DOC-1"


def test_number_with_comma_normalizes():
    parser_output = _parser_output(
        key_value_pairs=[
            {"pair_id": "kv1", "page_number": 1, "sheet_name": None, "key": "Usage", "value": "1,234,567", "confidence": None, "key_source_reference_id": None, "value_source_reference_id": None}
        ]
    )
    target = _target("activity_quantity", ["key_value_pair"], value_type="number", anchor_labels=["Usage"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["normalized_value"] == 1234567


def test_unit_detection_for_simple_pattern():
    parser_output = _parser_output(
        key_value_pairs=[
            {"pair_id": "kv1", "page_number": 1, "sheet_name": None, "key": "Total Usage", "value": "28,100 MMBtu", "confidence": None, "key_source_reference_id": None, "value_source_reference_id": None}
        ]
    )
    target = _target(
        "activity_quantity",
        ["key_value_pair"],
        value_type="quantity",
        anchor_labels=["Total Usage"],
        unit_patterns=["MMBtu", "therms?"],
        expected_units=["MMBtu"],
        normalization={"target_unit": "MMBtu"},
    )

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["normalized_value"] == 28100
    assert candidate["unit"] == "MMBtu"
    assert "unit_missing" not in candidate["validation_flags"]


def test_unit_conversion_flag_when_units_differ():
    parser_output = _parser_output(
        key_value_pairs=[
            {"pair_id": "kv1", "page_number": 1, "sheet_name": None, "key": "Usage", "value": "500 therms", "confidence": None, "key_source_reference_id": None, "value_source_reference_id": None}
        ]
    )
    target = _target(
        "activity_quantity",
        ["key_value_pair"],
        value_type="quantity",
        anchor_labels=["Usage"],
        unit_patterns=["MMBtu", "therms?"],
        expected_units=["MMBtu"],
        normalization={"target_unit": "MMBtu"},
    )

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["unit"] == "therms"
    assert "unit_conversion_not_implemented" in candidate["validation_flags"]


def test_date_normalization():
    parser_output = _parser_output(
        key_value_pairs=[
            {"pair_id": "kv1", "page_number": 1, "sheet_name": None, "key": "Service Period", "value": "10/01/2023", "confidence": None, "key_source_reference_id": None, "value_source_reference_id": None}
        ]
    )
    target = _target("service_period_start", ["key_value_pair"], value_type="date", anchor_labels=["Service Period"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["normalized_value"] == "2023-10-01"


def test_inputs_are_not_mutated():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "Facility: Plant 42", "confidence": None, "source_reference_id": None}]
    )
    target = _target("facility_name", ["anchor_text"], anchor_labels=["Facility"])
    parser_snapshot = copy.deepcopy(parser_output)
    target_snapshot = copy.deepcopy(target)

    ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")

    assert parser_output == parser_snapshot
    assert target == target_snapshot


def test_missing_document_id_raises():
    parser_output = _parser_output(document_id="")
    target = _target("facility_name", ["anchor_text"], anchor_labels=["Facility"])

    with pytest.raises(ValueError):
        ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")


def test_deterministic_candidate_id():
    parser_output = _parser_output(
        text_blocks=[{"block_id": "b1", "page_number": 1, "text": "Facility: Plant 42", "confidence": None, "source_reference_id": None}]
    )
    target = _target("facility_name", ["anchor_text"], anchor_labels=["Facility"])

    candidate = ExtractionCandidateService().generate_candidates(parser_output, [target], "EV-1")[0]

    assert candidate["candidate_id"] == "candidate::EV-1::DOC-1::facility_name"
