from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from backend.app.services.classification_service import ClassificationService  # noqa: E402


def _canonical_headers() -> list[str]:
    return [
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
        "last_reviewed",
    ]


def _variant_headers() -> list[str]:
    return [
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
        "population_status",
    ]


def _write_vocab_workbook(path: Path) -> Path:
    workbook = openpyxl.Workbook()

    canonical = workbook.active
    canonical.title = "Canonical_Types"
    canonical.append(_canonical_headers())
    canonical.append([
        "CT-GAS-BILL",
        "Natural gas utility bill",
        "Natural gas bill",
        "activity_data",
        "Scope 1",
        "stationary_combustion",
        "gas|utility|invoice",
        "Vocabulary_Library_v1.0",
        "provisional",
        "v1.0",
        "2026-07-01",
    ])
    canonical.append([
        "CT-ELEC-BILL",
        "Electricity utility bill",
        "Electricity bill",
        "activity_data",
        "Scope 2",
        "purchased_electricity",
        "electric|utility|invoice",
        "Vocabulary_Library_v1.0",
        "provisional",
        "v1.0",
        "2026-07-01",
    ])

    variants = workbook.create_sheet("Variants")
    variants.append(_variant_headers())
    variants.append([
        "VR-GAS-FILENAME",
        "CT-GAS-BILL",
        "Gas utility filename",
        "utility",
        "US",
        "gas bill|natural gas bill",
        "usage table",
        "Natural Gas",
        "MMBtu",
        "FALSE",
        0.35,
        "provisional",
        "sample-gas.pdf",
        "provisional",
    ])
    variants.append([
        "VR-ELEC-HEADER",
        "CT-ELEC-BILL",
        "Electric utility header",
        "utility",
        "US",
        "electric invoice",
        "account summary",
        "Electric Service",
        "kWh",
        "FALSE",
        0.50,
        "provisional",
        "sample-elec.pdf",
        "provisional",
    ])
    variants.append([
        "VR-GAS-MULTI",
        "CT-GAS-BILL",
        "Gas multi-type",
        "utility",
        "US",
        "gas package",
        "usage table",
        "Natural Gas",
        "MMBtu",
        "TRUE",
        0.50,
        "provisional",
        "sample-multi-gas.pdf",
        "provisional",
    ])
    variants.append([
        "VR-ELEC-MULTI",
        "CT-ELEC-BILL",
        "Electric multi-type",
        "utility",
        "US",
        "electric package",
        "account summary",
        "Electric Service",
        "kWh",
        "TRUE",
        0.50,
        "provisional",
        "sample-multi-elec.pdf",
        "provisional",
    ])

    workbook.save(path)
    return path


def _service(tmp_path: Path) -> ClassificationService:
    workbook_path = _write_vocab_workbook(tmp_path / "Vocabulary_Library_v1.0.xlsx")
    return ClassificationService(workbook_path=workbook_path)


def test_filename_only_match_classifies(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-1",
            "engagement_id": "eng-1",
            "file_name": "January natural gas bill.pdf",
        }
    )

    assert result["status"] == "classified"
    assert result["primary_canonical_type_id"] == "CT-GAS-BILL"
    assert result["review_required"] is False


def test_header_and_key_phrase_match_classifies(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-2",
            "engagement_id": "eng-1",
            "file_name": "statement.pdf",
            "parser_output": {
                "pages": [{"page_number": 1, "text": "Electric Service details"}],
                "text_blocks": [{"block_id": "b1", "text": "Total kWh usage"}],
                "tables": [],
            },
        }
    )

    assert result["status"] == "classified"
    assert result["primary_canonical_type_id"] == "CT-ELEC-BILL"


def test_low_confidence_returns_review_required(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-3",
            "engagement_id": "eng-1",
            "file_name": "just-an-invoice.pdf",
            "parser_output": {
                "pages": [{"page_number": 1, "text": "account summary"}],
                "text_blocks": [],
                "tables": [],
            },
        }
    )

    assert result["status"] == "low_confidence"
    assert result["review_required"] is True


def test_no_match_returns_unclassified(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-4",
            "engagement_id": "eng-1",
            "file_name": "meeting_notes.txt",
            "extracted_text": "No utility content",
        }
    )

    assert result["status"] == "unclassified"
    assert result["review_required"] is True
    assert result["primary_canonical_type_id"] is None


def test_multi_type_candidate_when_multiple_types_pass(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-5",
            "engagement_id": "eng-1",
            "file_name": "gas package electric package.pdf",
            "extracted_text": "Natural Gas and Electric Service with MMBtu and kWh",
        }
    )

    assert result["status"] == "multi_type_candidate"
    assert result["review_required"] is True
    assert len({c["canonical_type_id"] for c in result["candidate_matches"]}) > 1


def test_result_contains_required_contract_fields(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-6",
            "engagement_id": "eng-1",
            "file_name": "natural gas bill.pdf",
        }
    )

    required_fields = [
        "classification_result_id",
        "document_id",
        "engagement_id",
        "status",
        "primary_canonical_type_id",
        "candidate_matches",
        "review_required",
        "created_at",
    ]

    missing = [field for field in required_fields if field not in result]
    assert not missing, f"Missing required classification result fields: {missing}"


def test_candidate_matches_include_matched_signals(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-7",
            "engagement_id": "eng-1",
            "file_name": "natural gas bill.pdf",
        }
    )

    assert result["candidate_matches"], "Expected at least one candidate match"
    first_candidate = result["candidate_matches"][0]
    assert "matched_signals" in first_candidate


def test_outputs_canonical_type_id_not_name(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-8",
            "engagement_id": "eng-1",
            "file_name": "natural gas bill.pdf",
        }
    )

    assert result["primary_canonical_type_id"].startswith("CT-")
    assert result["primary_canonical_type_id"] != "Natural gas utility bill"


def test_classify_method_returns_dict(tmp_path: Path) -> None:
    service = _service(tmp_path)

    result = service.classify(
        {
            "document_id": "doc-9",
            "engagement_id": "eng-1",
            "file_name": "natural gas bill.pdf",
        }
    )

    assert hasattr(service, "classify")
    assert isinstance(result, dict)
