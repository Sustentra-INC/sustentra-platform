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
from backend.app.services.completeness_tracker_service import CompletenessTrackerService
from backend.app.services.methodology_registry_service import MethodologyRegistryService


def test_complete_when_required_extracted_value_exists() -> None:
    result = _tracker().evaluate(
        engagement_id="ENG-1",
        methodology_values=[_value("mv-001", "S1-STC-010")],
    )

    row = _by_field(result, "S1-STC-010")
    assert row["status"] == "complete"
    assert row["methodology_value_ids"] == ["mv-001"]


def test_missing_required_for_requestable_extracted_row_without_value() -> None:
    result = _tracker().evaluate(engagement_id="ENG-1", methodology_values=[])

    row = _by_field(result, "S1-STC-010")
    assert row["status"] == "missing_required"


def test_non_extracted_value_origins_are_not_requestable() -> None:
    result = _tracker().evaluate(engagement_id="ENG-1", methodology_values=[])

    assert _by_field(result, "S1-CMP-010")["status"] == "not_requestable_value_origin"
    assert _by_field(result, "S1-VER-010")["status"] == "not_requestable_value_origin"
    assert _by_field(result, "S1-ASN-010")["status"] == "not_requestable_value_origin"


def test_false_condition_is_not_applicable_not_missing() -> None:
    result = _tracker().evaluate(
        engagement_id="ENG-1",
        methodology_values=[],
        runtime_condition_values={"S1-STC-010": "no"},
    )

    row = _by_field(result, "S1-CND-010")
    assert row["status"] == "not_applicable"
    assert row["condition_status"] == "not_applicable"


def test_unknown_condition_is_provisional_not_missing() -> None:
    result = _tracker().evaluate(
        engagement_id="ENG-1",
        methodology_values=[],
        runtime_condition_values={},
    )

    row = _by_field(result, "S1-CND-010")
    assert row["status"] == "provisional_condition_unknown"
    assert row["condition_status"] == "unknown"


def test_true_condition_allows_missing_requestable_result() -> None:
    result = _tracker().evaluate(
        engagement_id="ENG-1",
        methodology_values=[],
        runtime_condition_values={"S1-STC-010": "yes"},
    )

    row = _by_field(result, "S1-CND-010")
    assert row["status"] == "missing_required"
    assert row["condition_status"] == "applicable"


def test_status_counts_are_reported() -> None:
    result = _tracker().evaluate(
        engagement_id="ENG-1",
        methodology_values=[_value("mv-001", "S1-STC-010")],
        runtime_condition_values={"S1-STC-010": "no"},
    )

    assert result["status_counts"] == {
        "complete": 1,
        "missing_required": 1,
        "not_applicable": 1,
        "not_requestable_value_origin": 3,
    }


def test_real_methodology_bundle_can_be_evaluated_without_values() -> None:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    tracker = CompletenessTrackerService(MethodologyRegistryService(bundle))

    result = tracker.evaluate(engagement_id="ENG-1", methodology_values=[])

    assert len(result["results"]) == 235
    assert "missing_required" in result["status_counts"]
    assert "not_requestable_value_origin" in result["status_counts"]


def test_missing_engagement_id_fails() -> None:
    with pytest.raises(ValueError, match="engagement_id"):
        _tracker().evaluate(engagement_id="", methodology_values=[])


def _tracker() -> CompletenessTrackerService:
    return CompletenessTrackerService(MethodologyRegistryService(_bundle()))


def _by_field(result: dict, field_id: str) -> dict:
    return next(row for row in result["results"] if row["field_id"] == field_id)


def _value(methodology_value_id: str, field_id: str) -> dict:
    return {
        "methodology_value_id": methodology_value_id,
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "methodology_field_id": field_id,
        "data_schema_field": "quantity_combusted",
        "grain": "fuel_record",
        "record_key": "record-1",
        "approved_value": 28100,
        "approved_unit": "MMBtu",
        "source_reference": {},
        "approved_evidence_id": "approved-001",
        "review_decision_id": "review-001",
        "value_origin": "approved_evidence",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _bundle() -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=(
            _schema("S1-STC-010", "S1", value_origin="extracted"),
            _schema("S1-MOB-010", "S1", value_origin="extracted"),
            _schema("S1-CMP-010", "S1", value_origin="computed"),
            _schema("S1-VER-010", "S1", value_origin="verifier_determined"),
            _schema("S1-ASN-010", "S1", value_origin="assigned"),
            _schema(
                "S1-CND-010",
                "S1",
                value_origin="extracted",
                condition="S1-STC-010 = yes",
            ),
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


def _schema(
    field_id: str,
    layer: str,
    *,
    value_origin: str,
    condition: str | None = None,
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
        data_schema_fields=("quantity_combusted",),
        calculation_role="parameter",
        value_origin=value_origin,
        requirement_level="Core",
        condition=condition,
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
