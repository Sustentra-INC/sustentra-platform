import pytest

from backend.app.reference.extraction_config_loader import ExtractionConfig
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService

ALLOWED_CANDIDATE_KEYS = {
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


def _config(field_id, canonical_type_id="CT-S1-FUELQTY", methods=("anchor_text",)):
    return ExtractionConfig(
        extraction_config_id=f"EC-{field_id}",
        field_id=field_id,
        field_label=field_id.replace("_", " ").title(),
        description=None,
        canonical_type_id=canonical_type_id,
        value_type="string",
        required_status="core",
        expected_units=(),
        source_reference_required=True,
        anchor_labels=("Facility",),
        value_patterns=(),
        unit_patterns=(),
        table_hints=(),
        sheet_hints=(),
        validation_hints=(),
        extraction_methods=tuple(methods),
        normalization={},
        regulatory_field_id=None,
        notes=None,
        population_status="provisional",
        version="v0.1",
        last_reviewed=None,
    )


def _parser_output():
    return {
        "parser_output_id": "PO-1",
        "document_id": "DOC-1",
        "processing_run_id": "RUN-1",
        "parser_name": "text_parser",
        "parser_version": "v0",
        "status": "parsed",
        "created_at": "2026-07-18T00:00:00+00:00",
        "pages": [],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": "Facility: Plant 42", "confidence": None, "source_reference_id": None}],
        "tables": [],
        "key_value_pairs": [],
        "source_references": [],
        "warnings": [],
    }


def _target(field_id="facility_name"):
    return {
        "target_id": f"target::CT-S1-FUELQTY::{field_id}",
        "extraction_config_id": f"EC-{field_id}",
        "field_id": field_id,
        "field_label": "Facility name",
        "canonical_type_id": "CT-S1-FUELQTY",
        "value_type": "string",
        "required_status": "core",
        "expected_units": (),
        "source_reference_required": True,
        "anchor_labels": ("Facility",),
        "value_patterns": (),
        "unit_patterns": (),
        "table_hints": (),
        "sheet_hints": (),
        "validation_hints": (),
        "extraction_methods": ("anchor_text",),
        "normalization": {},
        "population_status": "provisional",
        "version": "v0.1",
    }


def test_extract_returns_items():
    service = ExtractionService()
    payload = {
        "parser_output": _parser_output(),
        "extraction_targets": [_target()],
        "evidence_id": "EV-1",
    }
    result = service.extract(payload)

    assert result["evidence_id"] == "EV-1"
    assert result["document_id"] == "DOC-1"
    assert isinstance(result["items"], list)
    assert result["items"][0]["field_name"] == "facility_name"


def test_candidate_count_matches_items():
    service = ExtractionService()
    payload = {
        "parser_output": _parser_output(),
        "extraction_targets": [_target("facility_name"), _target("supplier_name")],
        "evidence_id": "EV-1",
    }
    result = service.extract(payload)
    assert result["candidate_count"] == len(result["items"]) == 2


def test_missing_payload_keys_raises():
    service = ExtractionService()
    with pytest.raises(ValueError):
        service.extract({})
    with pytest.raises(ValueError):
        service.extract({"parser_output": _parser_output()})
    with pytest.raises(ValueError):
        service.extract({"extraction_targets": [_target()]})


def test_plan_targets_still_delegates():
    target_service = ExtractionTargetService(configs=[_config("facility_name")])
    service = ExtractionService(target_service=target_service)
    result = {"status": "classified", "primary_canonical_type_id": "CT-S1-FUELQTY"}

    targets = service.plan_targets(result)
    assert [t["field_id"] for t in targets] == ["facility_name"]


def test_extract_for_classification_result_end_to_end():
    target_service = ExtractionTargetService(configs=[_config("facility_name")])
    service = ExtractionService(target_service=target_service)
    classification_result = {"status": "classified", "primary_canonical_type_id": "CT-S1-FUELQTY"}

    result = service.extract_for_classification_result(
        parser_output=_parser_output(),
        classification_result=classification_result,
        evidence_id="EV-9",
    )

    assert result["evidence_id"] == "EV-9"
    assert result["candidate_count"] == 1
    assert result["items"][0]["raw_value"] == "Plant 42"


def test_no_review_or_approved_evidence_fields():
    service = ExtractionService()
    result = service.extract(
        {
            "parser_output": _parser_output(),
            "extraction_targets": [_target()],
            "evidence_id": "EV-1",
        }
    )
    assert set(result.keys()) == {"evidence_id", "document_id", "candidate_count", "items"}
    for candidate in result["items"]:
        assert set(candidate.keys()) == ALLOWED_CANDIDATE_KEYS
