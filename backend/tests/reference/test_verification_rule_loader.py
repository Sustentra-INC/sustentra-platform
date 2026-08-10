from __future__ import annotations

from pathlib import Path

from backend.app.domain.methodology import (
    MethodologyBundle,
    MethodologyEdge,
    MethodologySchemaRow,
    MethodologySourceFile,
    VerificationRule,
)
from backend.app.reference.verification_rule_loader import (
    load_default_verification_rules,
    load_verification_rules,
)


def test_default_verification_rules_load_expected_count() -> None:
    rules = load_default_verification_rules(repo_root=Path(__file__).resolve().parents[3])

    assert len(rules) == 89


def test_default_verification_rules_identify_cross_rules() -> None:
    rules = load_default_verification_rules(repo_root=Path(__file__).resolve().parents[3])

    assert len([rule for rule in rules if rule.layer == "CROSS"]) == 15


def test_default_verification_rules_count_statuses() -> None:
    rules = load_default_verification_rules(repo_root=Path(__file__).resolve().parents[3])

    statuses = {}
    for rule in rules:
        statuses[rule.status] = statuses.get(rule.status, 0) + 1

    assert statuses["Active"] == 67
    assert statuses["CONFIRM"] == 15
    assert statuses["OPEN"] == 3


def test_confirm_rules_are_marked_provisional() -> None:
    rules = load_default_verification_rules(repo_root=Path(__file__).resolve().parents[3])

    confirm_rules = [rule for rule in rules if rule.status == "CONFIRM"]

    assert len(confirm_rules) == 15
    assert all(rule.is_provisional for rule in confirm_rules)


def test_applies_to_references_are_split_into_resolvable_and_unresolved() -> None:
    rules = load_verification_rules(
        _bundle(
            rules=[
                _rule(
                    "RULE-001",
                    applies_to=("S1-STC-010", "Any row with a non-null Condition"),
                )
            ]
        )
    )

    assert rules[0].resolvable_applies_to == ("S1-STC-010",)
    assert rules[0].unresolved_applies_to == ("Any row with a non-null Condition",)


def test_unknown_field_reference_is_unresolved() -> None:
    rules = load_verification_rules(
        _bundle(rules=[_rule("RULE-001", applies_to=("S1-NOPE-999",))])
    )

    assert rules[0].resolvable_applies_to == ()
    assert rules[0].unresolved_applies_to == ("S1-NOPE-999",)


def _bundle(rules: list[VerificationRule]) -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=(
            _schema("S1-STC-010", "S1"),
            _schema("INV-010", "GEN"),
        ),
        edges=(_edge(),),
        rules=tuple(rules),
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
        grain="fuel_record",
        source_category=None,
        calculation_method=None,
        emission_source=None,
        gas_applicability=None,
        data_schema_fields=("quantity_combusted",),
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
        gen_field_id="INV-010",
        gen_fields=(),
        cardinality="one_to_many",
        gen_version="GEN v1.1",
        status="Active",
        notes=None,
        source_workbook="edges.xlsx",
        source_sheet="Edge_Table",
        source_row_number=2,
    )


def _rule(rule_id: str, applies_to: tuple[str, ...]) -> VerificationRule:
    return VerificationRule(
        rule_id=rule_id,
        layer="CROSS",
        rule_type="guard",
        assertion="completeness",
        applies_to=applies_to,
        grain_key="-",
        rule_expression="Test expression",
        source="test",
        status="CONFIRM",
        notes=None,
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )
