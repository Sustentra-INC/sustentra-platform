import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"

NEW_SCHEMA_FILES = [
    "vocabulary_canonical_type.schema.json",
    "vocabulary_variant.schema.json",
    "document_classification_result.schema.json",
    "parser_output.schema.json",
    "extraction_config.schema.json",
    "gap_record_v0.schema.json"
]

REQUIRED_SCHEMA_KEYS = [
    "$schema",
    "$id",
    "title",
    "type",
    "properties",
    "required",
    "additionalProperties"
]

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _load_schema(file_name: str) -> dict:
    with (CONTRACTS_DIR / file_name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _assert_properties_present(schema_file_name: str, expected_properties: list[str]) -> None:
    schema = _load_schema(schema_file_name)
    properties = schema.get("properties", {})
    missing = [name for name in expected_properties if name not in properties]
    assert not missing, f"{schema_file_name} missing properties: {missing}"


def test_pr1_schema_files_exist() -> None:
    missing = [name for name in NEW_SCHEMA_FILES if not (CONTRACTS_DIR / name).exists()]
    assert not missing, f"Missing PR1 schema files: {missing}"


def test_all_contract_schemas_parse_as_json() -> None:
    schema_files = sorted(CONTRACTS_DIR.glob("*.schema.json"))
    assert schema_files, "No contract schema files were found in contracts/"

    for schema_file in schema_files:
        with schema_file.open("r", encoding="utf-8") as handle:
            json.load(handle)


def test_new_schemas_have_expected_structure_and_draft() -> None:
    for schema_name in NEW_SCHEMA_FILES:
        schema = _load_schema(schema_name)
        for key in REQUIRED_SCHEMA_KEYS:
            assert key in schema, f"{schema_name} missing required top-level key: {key}"
        assert schema["$schema"] == DRAFT_2020_12, (
            f"{schema_name} does not use draft 2020-12"
        )


def test_vocabulary_canonical_type_properties() -> None:
    _assert_properties_present(
        "vocabulary_canonical_type.schema.json",
        [
            "canonical_type_id",
            "canonical_name",
            "definition",
            "data_category",
            "ghg_scope",
            "content_inventory_coarse",
            "common_aliases",
            "source_basis",
            "population_status",
            "source_version",
            "last_reviewed"
        ]
    )


def test_vocabulary_variant_properties() -> None:
    _assert_properties_present(
        "vocabulary_variant.schema.json",
        [
            "variant_id",
            "canonical_type_id",
            "variant_archetype",
            "issuer_origin",
            "jurisdiction_region",
            "filename_patterns",
            "layout_features",
            "header_terms",
            "key_phrases",
            "multi_type",
            "confidence_threshold_default",
            "calibration_status",
            "source_exemplar",
            "population_status"
        ]
    )


def test_document_classification_result_properties() -> None:
    _assert_properties_present(
        "document_classification_result.schema.json",
        [
            "classification_result_id",
            "document_id",
            "engagement_id",
            "status",
            "primary_canonical_type_id",
            "candidate_matches",
            "review_required",
            "created_at"
        ]
    )


def test_parser_output_properties() -> None:
    _assert_properties_present(
        "parser_output.schema.json",
        [
            "parser_output_id",
            "document_id",
            "processing_run_id",
            "parser_name",
            "parser_version",
            "status",
            "pages",
            "tables",
            "key_value_pairs",
            "text_blocks",
            "source_references",
            "warnings"
        ]
    )


def test_extraction_config_properties() -> None:
    _assert_properties_present(
        "extraction_config.schema.json",
        [
            "extraction_config_id",
            "field_id",
            "field_label",
            "canonical_type_id",
            "value_type",
            "required_status",
            "source_reference_required",
            "extraction_methods",
            "normalization",
            "population_status",
            "version"
        ]
    )


def test_gap_record_properties() -> None:
    _assert_properties_present(
        "gap_record_v0.schema.json",
        [
            "gap_record_id",
            "engagement_id",
            "stage",
            "status",
            "issue_type",
            "summary",
            "created_at",
            "source",
            "downstream_blocking"
        ]
    )


def test_document_schema_document_type_optional() -> None:
    schema = _load_schema("document.schema.json")
    required = schema.get("required", [])

    assert "document_type" not in required, "document_type must not be required on Document"
    assert "document_type" in schema.get("properties", {}), (
        "document_type must remain present as an optional property"
    )

    expected_required_upload_metadata = [
        "document_id",
        "engagement_id",
        "file_name",
        "mime_type",
        "storage_uri",
        "document_role",
        "uploaded_by",
        "uploaded_at",
        "processing_status"
    ]
    missing = [name for name in expected_required_upload_metadata if name not in required]
    assert not missing, f"Document schema missing required upload metadata fields: {missing}"
