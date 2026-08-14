from __future__ import annotations

from pathlib import Path

from backend.app.domain.methodology import (
    MethodologyBundle,
    MethodologyEdge,
    MethodologySchemaRow,
    MethodologySourceFile,
)
from backend.app.domain.verification_rule import RuntimeVerificationRule
from backend.app.reference.approved_evidence_mapping_loader import (
    ApprovedEvidenceFieldMapping,
)
from backend.app.services.approved_evidence_mapping_service import (
    ApprovedEvidenceMappingService,
)
from backend.app.services.completeness_tracker_service import CompletenessTrackerService
from backend.app.services.derivation_service import DerivationService
from backend.app.services.methodology_registry_service import MethodologyRegistryService
from backend.app.services.methodology_value_service import MethodologyValueService
from backend.app.services.s2_gap_record_service import S2GapRecordService
from backend.app.services.s2_orchestration_service import S2OrchestrationService
from backend.app.services.verification_engine_service import VerificationEngineService


def test_run_projects_values_and_returns_summary_artifacts() -> None:
    result = _service().run(_approved_evidence())

    summary = result["summary"]
    assert summary["methodology_run_id"].startswith("methodology-run::")
    assert summary["engagement_id"] == "ENG-1"
    assert summary["field_value_count"] == 3
    assert summary["missing_required_count"] == 2
    assert summary["not_applicable_count"] == 0
    assert summary["verification_result_count"] == 3
    assert summary["provisional_count"] == 1
    assert summary["gap_record_count"] == len(result["gap_records"])
    assert result["projection"]["methodology_value_count"] == 3
    assert result["derivations"][0]["status"] == "derived"


def test_runtime_condition_values_can_mark_required_row_not_applicable() -> None:
    result = _service().run(
        _approved_evidence(),
        runtime_condition_values={"S1-FUEL-010": "Diesel"},
    )

    conditional = _by_field(result["completeness"], "S1-CND-010")
    assert conditional["status"] == "not_applicable"
    assert result["summary"]["not_applicable_count"] == 1
    assert result["summary"]["missing_required_count"] == 1


def test_invalid_approved_evidence_fails_before_running_artifacts() -> None:
    service = _service()

    try:
        service.run({"approved_evidence_id": "approved-001"})
    except ValueError as exc:
        assert "approved_evidence missing" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected invalid approved evidence to fail.")


def _service() -> S2OrchestrationService:
    bundle = _bundle()
    registry = MethodologyRegistryService(bundle)
    mapping_service = ApprovedEvidenceMappingService(_mappings(), registry)
    return S2OrchestrationService(
        methodology_value_service=MethodologyValueService(
            mapping_service,
            registry,
            clock=lambda: "2026-01-01T00:00:00+00:00",
        ),
        completeness_tracker=CompletenessTrackerService(registry),
        derivation_service=DerivationService(registry),
        verification_engine=VerificationEngineService(),
        verification_rules=_rules(),
        gap_record_service=S2GapRecordService(
            clock=lambda: "2026-01-01T00:00:00+00:00"
        ),
        clock=lambda: "2026-01-01T00:00:00+00:00",
    )


def _approved_evidence() -> dict:
    fields = [
        _field("fuel_type", "Natural Gas", None, "review-fuel"),
        _field("activity_quantity", 28100, "MMBtu", "review-quantity"),
        _field("activity_unit", "MMBtu", None, "review-unit"),
    ]
    return {
        "approved_evidence_id": "approved-001",
        "evidence_id": "EV-1",
        "engagement_id": "ENG-1",
        "document_id": "DOC-1",
        "evidence_type": "CT-S1-FUELQTY",
        "review_status": "approved",
        "field_count": len(fields),
        "approved_field_count": len(fields),
        "fields": fields,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_review_decision_ids": ["review-fuel", "review-quantity", "review-unit"],
    }


def _field(
    field_name: str,
    approved_value: str | float | int | None,
    approved_unit: str | None,
    review_decision_id: str,
) -> dict:
    return {
        "field_name": field_name,
        "display_label": field_name.replace("_", " ").title(),
        "extracted_value": approved_value,
        "approved_value": approved_value,
        "approved_unit": approved_unit,
        "decision": "accepted",
        "source_reference": {
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


def _mappings() -> tuple[ApprovedEvidenceFieldMapping, ...]:
    return (
        _mapping("fuel_type", "S1-FUEL-010", "fuel_type"),
        _mapping("activity_quantity", "S1-QTY-010", "quantity_combusted"),
        _mapping("activity_unit", "S1-UNIT-010", "quantity_unit"),
    )


def _mapping(
    approved_field_name: str,
    methodology_field_id: str,
    data_schema_field: str,
) -> ApprovedEvidenceFieldMapping:
    return ApprovedEvidenceFieldMapping(
        canonical_type_id="CT-S1-FUELQTY",
        approved_field_name=approved_field_name,
        methodology_field_id=methodology_field_id,
        data_schema_field=data_schema_field,
        mapping_status="confirmed",
        notes=None,
    )


def _rules() -> tuple[RuntimeVerificationRule, ...]:
    return (
        _rule("RULE-PASS", "guard", ("S1-FUEL-010",)),
        _rule("RULE-FAIL", "gate", ("S1-MISS-010",)),
        _rule("RULE-CONFIRM", "guard", ("S1-FUEL-010",), is_provisional=True),
    )


def _rule(
    rule_id: str,
    rule_type: str,
    applies_to: tuple[str, ...],
    *,
    is_provisional: bool = False,
) -> RuntimeVerificationRule:
    return RuntimeVerificationRule(
        rule_id=rule_id,
        layer="S1",
        rule_type=rule_type,
        assertion="completeness",
        applies_to=applies_to,
        grain_key="-",
        rule_expression="Synthetic rule expression",
        source="test",
        status="CONFIRM" if is_provisional else "Active",
        notes=None,
        is_provisional=is_provisional,
        resolvable_applies_to=applies_to,
        unresolved_applies_to=(),
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )


def _bundle() -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=(
            _schema("S1-FUEL-010", data_schema_fields=("fuel_type",)),
            _schema("S1-QTY-010", data_schema_fields=("quantity_combusted",)),
            _schema("S1-UNIT-010", data_schema_fields=("quantity_unit",)),
            _schema("S1-MISS-010"),
            _schema("S1-CND-010", condition="S1-FUEL-010 = 'Natural Gas'"),
            _schema(
                "S1-COPY-010",
                value_origin="computed",
                derived_from=("S1-QTY-010",),
            ),
        ),
        edges=(_edge(),),
        rules=(),
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
    *,
    data_schema_fields: tuple[str, ...] = ("value",),
    value_origin: str = "extracted",
    condition: str | None = None,
    derived_from: tuple[str, ...] = (),
) -> MethodologySchemaRow:
    return MethodologySchemaRow(
        field_id=field_id,
        layer="S1",
        scope_applicability="S1",
        block="S1",
        grain="fuel_record",
        source_category=None,
        calculation_method=None,
        emission_source=None,
        gas_applicability=None,
        data_schema_fields=data_schema_fields,
        calculation_role="parameter",
        value_origin=value_origin,
        requirement_level="Core",
        condition=condition,
        anchor_type="evidence-derived",
        definition_purpose="Test row",
        vocabulary_references=(),
        source_citation=None,
        derived_from=derived_from,
        node_id=None,
        notes_flags=None,
        source_workbook="test.xlsx",
        source_sheet="Sheet1",
        source_row_number=2,
    )


def _edge() -> MethodologyEdge:
    return MethodologyEdge(
        edge_id="EDG-001",
        layer="S1",
        scope_field_id="S1-FUEL-010",
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


def _by_field(result: dict, field_id: str) -> dict:
    return next(row for row in result["results"] if row["field_id"] == field_id)
