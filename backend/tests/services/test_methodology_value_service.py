from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.reference.approved_evidence_mapping_loader import (
    ApprovedEvidenceFieldMapping,
    load_default_approved_evidence_mappings,
)
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.repositories.methodology_value_repository import (
    InMemoryMethodologyValueRepository,
)
from backend.app.services.approved_evidence_mapping_service import (
    ApprovedEvidenceMappingService,
)
from backend.app.services.methodology_registry_service import MethodologyRegistryService
from backend.app.services.methodology_value_service import MethodologyValueService


def test_project_approved_evidence_creates_methodology_values_from_seed() -> None:
    service = _service()

    result = service.project_approved_evidence(_approved_evidence())

    assert result["methodology_value_count"] == 3
    assert result["unmapped_fields"] == []
    fields = {
        (value["methodology_field_id"], value["data_schema_field"])
        for value in result["methodology_values"]
    }
    assert fields == {
        ("S1-STC-010", "fuel_type"),
        ("S1-STC-010", "quantity_combusted"),
        ("S1-STC-010", "quantity_unit"),
    }


def test_projected_methodology_values_preserve_traceability_and_grain() -> None:
    service = _service()

    result = service.project_approved_evidence(_approved_evidence())
    quantity = next(
        value
        for value in result["methodology_values"]
        if value["data_schema_field"] == "quantity_combusted"
    )

    assert quantity["engagement_id"] == "ENG-1"
    assert quantity["evidence_id"] == "EV-1"
    assert quantity["document_id"] == "DOC-1"
    assert quantity["approved_evidence_id"] == "approved-001"
    assert quantity["review_decision_id"] == "review-quantity"
    assert quantity["approved_value"] == 28100
    assert quantity["approved_unit"] == "MMBtu"
    assert quantity["source_reference"]["text_snippet"] == "Total Usage 28,100 MMBtu"
    assert quantity["grain"] == "fuel_record"
    assert quantity["value_origin"] == "approved_evidence"
    assert quantity["created_at"] == "2026-01-01T00:00:00+00:00"


def test_unmapped_approved_field_is_reported_and_not_projected() -> None:
    service = _service()
    approved = _approved_evidence(
        fields=[
            _field("activity_quantity", 28100, "MMBtu", "review-quantity"),
            _field("supplier_name", "Demo Utility", None, "review-supplier"),
        ]
    )

    result = service.project_approved_evidence(approved)

    assert result["methodology_value_count"] == 1
    assert result["unmapped_fields"] == ["supplier_name"]


def test_deprecated_mapping_is_excluded_by_default() -> None:
    service = _service(
        mappings=(
            ApprovedEvidenceFieldMapping(
                canonical_type_id="CT-S1-FUELQTY",
                approved_field_name="activity_quantity",
                methodology_field_id="S1-STC-010",
                data_schema_field="quantity_combusted",
                mapping_status="deprecated",
                notes=None,
            ),
        )
    )

    result = service.project_approved_evidence(
        _approved_evidence(fields=[_field("activity_quantity", 28100, "MMBtu")])
    )

    assert result["methodology_value_count"] == 0
    assert result["unmapped_fields"] == ["activity_quantity"]


def test_one_approved_field_can_project_to_multiple_methodology_values() -> None:
    service = _service(
        mappings=(
            ApprovedEvidenceFieldMapping(
                canonical_type_id="CT-S1-FUELQTY",
                approved_field_name="activity_quantity",
                methodology_field_id="S1-STC-010",
                data_schema_field="quantity_combusted",
                mapping_status="provisional",
                notes=None,
            ),
            ApprovedEvidenceFieldMapping(
                canonical_type_id="CT-S1-FUELQTY",
                approved_field_name="activity_quantity",
                methodology_field_id="S1-STC-010",
                data_schema_field="quantity_unit",
                mapping_status="provisional",
                notes=None,
            ),
        )
    )

    result = service.project_approved_evidence(
        _approved_evidence(fields=[_field("activity_quantity", 28100, "MMBtu")])
    )

    assert result["methodology_value_count"] == 2
    assert {
        value["data_schema_field"] for value in result["methodology_values"]
    } == {"quantity_combusted", "quantity_unit"}


def test_record_key_prefers_source_reference_record_id() -> None:
    service = _service()
    approved = _approved_evidence(
        fields=[
            _field(
                "activity_quantity",
                28100,
                "MMBtu",
                source_reference={"record_id": "fuel-row-001"},
            )
        ]
    )

    result = service.project_approved_evidence(approved)

    assert result["methodology_values"][0]["record_key"] == "fuel-row-001"


def test_projection_replaces_existing_snapshot_for_approved_evidence() -> None:
    repository = InMemoryMethodologyValueRepository()
    service = _service(repository=repository)

    first = service.project_approved_evidence(
        _approved_evidence(fields=[_field("activity_quantity", 28100, "MMBtu")])
    )
    second = service.project_approved_evidence(
        _approved_evidence(fields=[_field("fuel_type", "Natural Gas", None)])
    )

    assert first["methodology_value_count"] == 1
    assert second["methodology_value_count"] == 1
    stored = repository.list_by_approved_evidence("approved-001")
    assert len(stored) == 1
    assert stored[0]["data_schema_field"] == "fuel_type"


def test_projection_can_run_without_persisting() -> None:
    repository = InMemoryMethodologyValueRepository()
    service = _service(repository=repository)

    result = service.project_approved_evidence(_approved_evidence(), persist=False)

    assert result["methodology_value_count"] == 3
    assert repository.list_all() == []


def test_invalid_approved_evidence_shape_fails() -> None:
    service = _service()

    with pytest.raises(ValueError, match="approved_evidence missing"):
        service.project_approved_evidence({"approved_evidence_id": "approved-001"})


def _service(
    *,
    mappings: tuple[ApprovedEvidenceFieldMapping, ...] | None = None,
    repository: InMemoryMethodologyValueRepository | None = None,
) -> MethodologyValueService:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    registry = MethodologyRegistryService(bundle)
    mapping_service = ApprovedEvidenceMappingService(
        mappings or load_default_approved_evidence_mappings(),
        registry,
    )
    return MethodologyValueService(
        mapping_service,
        registry,
        repository=repository,
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )


def _approved_evidence(
    *,
    fields: list[dict] | None = None,
    evidence_type: str = "CT-S1-FUELQTY",
) -> dict:
    default_fields = [
        _field("fuel_type", "Natural Gas", None, "review-fuel"),
        _field("activity_quantity", 28100, "MMBtu", "review-quantity"),
        _field("activity_unit", "MMBtu", None, "review-unit"),
    ]
    return {
        "approved_evidence_id": "approved-001",
        "evidence_id": "EV-1",
        "engagement_id": "ENG-1",
        "document_id": "DOC-1",
        "evidence_type": evidence_type,
        "review_status": "approved",
        "field_count": len(fields or default_fields),
        "approved_field_count": len(fields or default_fields),
        "fields": fields or default_fields,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_review_decision_ids": ["review-fuel", "review-quantity", "review-unit"],
    }


def _field(
    field_name: str,
    approved_value: str | float | int | bool | None,
    approved_unit: str | None,
    review_decision_id: str = "review-001",
    *,
    source_reference: dict | None = None,
) -> dict:
    return {
        "field_name": field_name,
        "display_label": field_name.replace("_", " ").title(),
        "extracted_value": approved_value,
        "approved_value": approved_value,
        "approved_unit": approved_unit,
        "decision": "accepted",
        "source_reference": source_reference
        or {
            "document_id": "DOC-1",
            "text_snippet": "Total Usage 28,100 MMBtu",
        },
        "review_decision_id": review_decision_id,
        "candidate_id": f"candidate-{review_decision_id}",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "confidence": 0.91,
        "validation_flags": [],
    }
