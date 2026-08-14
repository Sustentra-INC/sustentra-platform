from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.domain.methodology import (
    MethodologyBundle,
    MethodologyEdge,
    MethodologySchemaRow,
    MethodologySourceFile,
    VerificationRule,
)
from backend.app.reference.approved_evidence_mapping_loader import (
    ApprovedEvidenceFieldMapping,
    load_default_approved_evidence_mappings,
)
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.services.approved_evidence_mapping_service import (
    ApprovedEvidenceMappingService,
    ApprovedEvidenceMappingValidationError,
)
from backend.app.services.methodology_registry_service import MethodologyRegistryService


def test_default_mapping_seed_validates_against_real_methodology_registry() -> None:
    service = _real_service()

    mappings = service.list_mappings()

    assert len(mappings) == 6
    assert all(mapping.mapping_status != "deprecated" for mapping in mappings)
    assert len(service.list_unconfirmed()) == 6


def test_mapping_service_lists_by_canonical_type_and_approved_field() -> None:
    service = _real_service()

    fuelqty_mappings = service.list_by_canonical_type("ct-s1-fuelqty")
    quantity_mappings = service.list_by_approved_field(
        "CT-S1-FUELQTY",
        "activity_quantity",
    )

    assert len(fuelqty_mappings) == 3
    assert [mapping.methodology_field_id for mapping in quantity_mappings] == [
        "S1-STC-010"
    ]
    assert quantity_mappings[0].data_schema_field == "quantity_combusted"


def test_mapping_service_gets_mapping_by_full_logical_key() -> None:
    service = _real_service()

    mapping = service.get_mapping(
        "CT-S1-MOBFUEL",
        "activity_unit",
        "S1-MOB-010",
        "quantity_unit",
    )

    assert mapping is not None
    assert mapping.mapping_status == "needs_domain_review"


def test_mapping_service_lists_by_methodology_field_and_status() -> None:
    service = _real_service()

    stc_mappings = service.list_by_methodology_field("S1-STC-010")
    review_mappings = service.list_by_status("needs_domain_review")

    assert len(stc_mappings) == 3
    assert {mapping.approved_field_name for mapping in stc_mappings} == {
        "fuel_type",
        "activity_quantity",
        "activity_unit",
    }
    assert len(review_mappings) == 2


def test_mapping_service_excludes_deprecated_by_default() -> None:
    service = ApprovedEvidenceMappingService(
        (
            _mapping(),
            _mapping(
                approved_field_name="old_quantity",
                data_schema_field="quantity_unit",
                mapping_status="deprecated",
            ),
        ),
        _registry(),
    )

    assert len(service.list_mappings()) == 1
    assert len(service.list_mappings(include_deprecated=True)) == 2
    assert service.list_by_status("deprecated")[0].approved_field_name == "old_quantity"


def test_mapping_service_supports_one_source_field_to_multiple_targets() -> None:
    service = ApprovedEvidenceMappingService(
        (
            _mapping(data_schema_field="quantity_combusted"),
            _mapping(data_schema_field="quantity_unit"),
        ),
        _registry(),
    )

    mappings = service.list_by_approved_field("CT-S1-FUELQTY", "activity_quantity")

    assert len(mappings) == 2
    assert {mapping.data_schema_field for mapping in mappings} == {
        "quantity_combusted",
        "quantity_unit",
    }


def test_mapping_service_rejects_unknown_methodology_field() -> None:
    with pytest.raises(ApprovedEvidenceMappingValidationError, match="unknown"):
        ApprovedEvidenceMappingService(
            (_mapping(methodology_field_id="S1-NOPE-999"),),
            _registry(),
        )


def test_mapping_service_rejects_data_schema_field_not_on_methodology_row() -> None:
    with pytest.raises(ApprovedEvidenceMappingValidationError, match="not present"):
        ApprovedEvidenceMappingService(
            (_mapping(data_schema_field="wrong_field"),),
            _registry(),
        )


def _real_service() -> ApprovedEvidenceMappingService:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    registry = MethodologyRegistryService(bundle)
    return ApprovedEvidenceMappingService(
        load_default_approved_evidence_mappings(),
        registry,
    )


def _registry() -> MethodologyRegistryService:
    return MethodologyRegistryService(_bundle())


def _bundle() -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=(
            _schema("S1-STC-010", "S1"),
            _schema("S1-MOB-010", "S1"),
        ),
        edges=(_edge(),),
        rules=(_rule("CX-01"), _rule("CX-12")),
        source_files=(
            MethodologySourceFile(
                role="test",
                path=Path("test.xlsx"),
                sheet_name="Sheet1",
            ),
        ),
    )


def _schema(field_id: str, layer: str) -> MethodologySchemaRow:
    return MethodologySchemaRow(
        field_id=field_id,
        layer=layer,  # type: ignore[arg-type]
        scope_applicability=layer,
        block=field_id.split("-")[0],
        grain="inventory",
        source_category=None,
        calculation_method=None,
        emission_source=None,
        gas_applicability=None,
        data_schema_fields=("fuel_type", "quantity_combusted", "quantity_unit"),
        calculation_role="parameter",
        value_origin="extracted",
        requirement_level="Core",
        condition=None,
        anchor_type="evidence-derived",
        definition_purpose="Test row",
        vocabulary_references=(),
        source_citation=None,
        derived_from=(),
        node_id=None,
        notes_flags=None,
        source_workbook=f"{layer}.xlsx",
        source_sheet="Sheet1",
        source_row_number=2,
    )


def _mapping(
    *,
    canonical_type_id: str = "CT-S1-FUELQTY",
    approved_field_name: str = "activity_quantity",
    methodology_field_id: str = "S1-STC-010",
    data_schema_field: str = "quantity_combusted",
    mapping_status: str = "provisional",
) -> ApprovedEvidenceFieldMapping:
    return ApprovedEvidenceFieldMapping(
        canonical_type_id=canonical_type_id,
        approved_field_name=approved_field_name,
        methodology_field_id=methodology_field_id,
        data_schema_field=data_schema_field,
        mapping_status=mapping_status,  # type: ignore[arg-type]
        notes="Test mapping",
    )


def _edge() -> MethodologyEdge:
    return MethodologyEdge(
        edge_id="EDG-001",
        layer="S1",
        scope_field_id="S1-STC-010",
        scope_fields=(),
        direction="GEN_TO_SCOPE",
        reference_type="fk",
        edge_type="inventory_fk",
        condition="direct",
        transformation=None,
        gen_field_id=None,
        gen_fields=(),
        cardinality="one_to_many",
        gen_version="GEN v1.1",
        status="Active",
        notes=None,
        source_workbook="edges.xlsx",
        source_sheet="Edge_Table",
        source_row_number=2,
    )


def _rule(rule_id: str) -> VerificationRule:
    return VerificationRule(
        rule_id=rule_id,
        layer="CROSS",
        rule_type="guard",
        assertion="completeness",
        applies_to=("S1-STC-010",),
        grain_key="-",
        rule_expression="Test expression",
        source="test",
        status="Active",
        notes=None,
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )
