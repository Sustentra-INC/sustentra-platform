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
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.services.derivation_service import DerivationService
from backend.app.services.methodology_registry_service import MethodologyRegistryService


def test_copy_derivation() -> None:
    service = _service(
        [
            _schema("S1-RAW-010", "S1"),
            _schema("S1-COPY-010", "S1", derived_from=("S1-RAW-010",)),
        ]
    )

    result = service.derive_field(
        "S1-COPY-010",
        [_value("mv-raw", "S1-RAW-010", 28100, "MMBtu")],
    )

    assert result["status"] == "derived"
    assert result["derived_value"] == 28100
    assert result["derived_unit"] == "MMBtu"
    assert result["source_methodology_value_ids"] == ["mv-raw"]
    assert result["reason"] == "copy derivation"


def test_sum_derivation() -> None:
    service = _service(
        [
            _schema("S1-A-010", "S1"),
            _schema("S1-B-010", "S1"),
            _schema("S1-TOTAL-010", "S1", derived_from=("S1-A-010", "S1-B-010")),
        ]
    )

    result = service.derive_field(
        "S1-TOTAL-010",
        [
            _value("mv-a", "S1-A-010", 10, "MMBtu"),
            _value("mv-b", "S1-B-010", "2.5", "MMBtu"),
        ],
    )

    assert result["status"] == "derived"
    assert result["derived_value"] == 12.5
    assert result["derived_unit"] == "MMBtu"
    assert result["reason"] == "sum derivation"


def test_missing_dependency_value() -> None:
    service = _service(
        [
            _schema("S1-A-010", "S1"),
            _schema("S1-B-010", "S1"),
            _schema("S1-TOTAL-010", "S1", derived_from=("S1-A-010", "S1-B-010")),
        ]
    )

    result = service.derive_field(
        "S1-TOTAL-010",
        [_value("mv-a", "S1-A-010", 10, "MMBtu")],
    )

    assert result["status"] == "missing_dependency"
    assert "S1-B-010" in (result["reason"] or "")


def test_cross_layer_derivation_is_unsupported() -> None:
    service = _service(
        [
            _schema("S1-OUT-020", "S1"),
            _schema("BIO-010", "GEN", derived_from=("S1-OUT-020",)),
        ]
    )

    result = service.derive_field(
        "BIO-010",
        [_value("mv-out", "S1-OUT-020", 10, "tCO2e")],
    )

    assert result["status"] == "cross_layer_unsupported"


def test_nonnumeric_multi_dependency_derivation_is_unsupported() -> None:
    service = _service(
        [
            _schema("S1-A-010", "S1"),
            _schema("S1-B-010", "S1"),
            _schema("S1-TOTAL-010", "S1", derived_from=("S1-A-010", "S1-B-010")),
        ]
    )

    result = service.derive_field(
        "S1-TOTAL-010",
        [
            _value("mv-a", "S1-A-010", "Natural Gas", None),
            _value("mv-b", "S1-B-010", "Diesel", None),
        ],
    )

    assert result["status"] == "unsupported_derivation"


def test_mixed_units_are_unsupported_for_sum() -> None:
    service = _service(
        [
            _schema("S1-A-010", "S1"),
            _schema("S1-B-010", "S1"),
            _schema("S1-TOTAL-010", "S1", derived_from=("S1-A-010", "S1-B-010")),
        ]
    )

    result = service.derive_field(
        "S1-TOTAL-010",
        [
            _value("mv-a", "S1-A-010", 10, "MMBtu"),
            _value("mv-b", "S1-B-010", 20, "gallons"),
        ],
    )

    assert result["status"] == "unsupported_derivation"


def test_unknown_field_fails() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        _service([_schema("S1-A-010", "S1")]).derive_field("S1-NOPE-010", [])


def test_real_bundle_derives_all_without_throwing() -> None:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    service = DerivationService(MethodologyRegistryService(bundle))

    results = service.derive_all([])

    assert len(results) == 186
    assert any(result["field_id"] == "BIO-010" for result in results)


def _service(rows: list[MethodologySchemaRow]) -> DerivationService:
    return DerivationService(MethodologyRegistryService(_bundle(rows)))


def _bundle(rows: list[MethodologySchemaRow]) -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=tuple(rows),
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


def _schema(
    field_id: str,
    layer: str,
    *,
    derived_from: tuple[str, ...] = (),
) -> MethodologySchemaRow:
    return MethodologySchemaRow(
        field_id=field_id,
        layer=layer,  # type: ignore[arg-type]
        scope_applicability=layer,
        block=field_id.split("-")[0],
        grain="fuel_record",
        source_category=None,
        calculation_method=None,
        emission_source=None,
        gas_applicability=None,
        data_schema_fields=("value",),
        calculation_role="parameter",
        value_origin="computed" if derived_from else "extracted",
        requirement_level="Core",
        condition=None,
        anchor_type="computed",
        definition_purpose="Test row",
        vocabulary_references=(),
        source_citation=None,
        derived_from=derived_from,
        node_id=None,
        notes_flags=None,
        source_workbook=f"{layer}.xlsx",
        source_sheet="Sheet1",
        source_row_number=2,
    )


def _value(
    methodology_value_id: str,
    field_id: str,
    value: str | float | int,
    unit: str | None,
) -> dict:
    return {
        "methodology_value_id": methodology_value_id,
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "methodology_field_id": field_id,
        "data_schema_field": "value",
        "grain": "fuel_record",
        "record_key": "record-1",
        "approved_value": value,
        "approved_unit": unit,
        "source_reference": {},
        "approved_evidence_id": "approved-001",
        "review_decision_id": "review-001",
        "value_origin": "approved_evidence",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _edge() -> MethodologyEdge:
    return MethodologyEdge(
        edge_id="EDG-001",
        layer="S1",
        scope_field_id="S1-A-010",
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
        applies_to=("S1-A-010",),
        grain_key="-",
        rule_expression="Test expression",
        source="test",
        status="Active",
        notes=None,
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )
