from __future__ import annotations

from pathlib import Path

from backend.app.domain.methodology import (
    MethodologyBundle,
    MethodologyEdge,
    MethodologySchemaRow,
    MethodologySourceFile,
    VerificationRule,
)
from backend.app.reference.methodology_loader import load_default_methodology_bundle
from backend.app.services.methodology_registry_service import MethodologyRegistryService


def test_real_methodology_registry_indexes_loaded_bundle() -> None:
    registry = _real_registry()

    assert registry.get_row("INV-010") is not None
    assert registry.get_row("INV-010").layer == "GEN"  # type: ignore[union-attr]
    assert registry.get_row("NOPE-999") is None
    assert len(registry.list_rows()) == 279
    assert len(registry.list_rows(layer="GEN")) == 51
    assert len(registry.list_rows(layer="S1")) == 139
    assert len(registry.list_rows(layer="S2")) == 89


def test_real_methodology_registry_lists_rows_by_value_origin() -> None:
    registry = _real_registry()

    assert len(registry.list_by_value_origin("extracted")) == 183
    assert len(registry.list_by_value_origin("ASSIGNED")) == 42
    assert len(registry.list_by_value_origin("computed")) == 39
    assert len(registry.list_by_value_origin("verifier_determined")) == 15


def test_real_methodology_registry_lists_required_condition_and_derived_rows() -> None:
    registry = _real_registry()

    core_rows = registry.list_required_rows()
    assert len(core_rows) == 235
    assert all(row.requirement_level == "Core" for row in core_rows)
    assert registry.list_required_rows("core") == core_rows

    conditional_rows = registry.list_conditions()
    assert len(conditional_rows) == 132
    assert all(row.condition for row in conditional_rows)

    derived_rows = registry.list_derived_rows()
    assert len(derived_rows) == 186
    assert all(row.derived_from for row in derived_rows)
    assert "BIO-010" in {row.field_id for row in derived_rows}
    assert "RUP-010" in {row.field_id for row in derived_rows}


def test_real_methodology_registry_lists_rows_by_vocabulary_reference() -> None:
    registry = _real_registry()

    rows = registry.list_rows_by_vocabulary_reference("ct-s2-eac")

    assert len(rows) == 9
    assert all("CT-S2-EAC" in row.vocabulary_references for row in rows)


def test_real_methodology_registry_lists_rules_for_exact_field_references_only() -> None:
    registry = _real_registry()

    org_rules = registry.list_rules_for_field("ORG-030")
    condition_rules = registry.list_rules_for_field("S2-MTR-010")

    assert {rule.rule_id for rule in org_rules} == {"G-01"}
    assert "CX-12" not in {rule.rule_id for rule in condition_rules}


def test_real_methodology_registry_lists_edges_for_exact_and_wildcard_refs() -> None:
    registry = _real_registry()

    inv_edges = registry.list_edges_for_field("INV-010")
    efs_edges = registry.list_edges_for_field("S2-EFS-010")

    assert "EDG-S1-001" in {edge.edge_id for edge in inv_edges}
    assert "EDG-S2-024" in {edge.edge_id for edge in efs_edges}


def test_registry_with_synthetic_bundle_indexes_wildcard_edges() -> None:
    registry = MethodologyRegistryService(
        _bundle(
            schema_rows=[
                _schema("INV-010", "GEN"),
                _schema("S2-EFS-010", "S2"),
                _schema("S2-EFS-020", "S2"),
                _schema("S2-MTR-010", "S2"),
            ],
            edges=[
                _edge(
                    edge_id="EDG-WILD",
                    scope_field_id="S2-EFS-*",
                    gen_field_id="INV-010",
                )
            ],
        )
    )

    assert {edge.edge_id for edge in registry.list_edges_for_field("S2-EFS-010")} == {
        "EDG-WILD"
    }
    assert {edge.edge_id for edge in registry.list_edges_for_field("S2-EFS-020")} == {
        "EDG-WILD"
    }
    assert registry.list_edges_for_field("S2-MTR-010") == ()


def test_registry_with_synthetic_bundle_does_not_expand_prose_rules() -> None:
    registry = MethodologyRegistryService(
        _bundle(
            rules=[
                _rule("RULE-EXACT", applies_to=("S1-STC-010",)),
                _rule("RULE-PROSE", applies_to=("Any row with a non-null Condition",)),
            ]
        )
    )

    assert {rule.rule_id for rule in registry.list_rules_for_field("S1-STC-010")} == {
        "RULE-EXACT"
    }


def _real_registry() -> MethodologyRegistryService:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    return MethodologyRegistryService(bundle)


def _bundle(
    *,
    schema_rows: list[MethodologySchemaRow] | None = None,
    edges: list[MethodologyEdge] | None = None,
    rules: list[VerificationRule] | None = None,
) -> MethodologyBundle:
    rows = schema_rows or [
        _schema("INV-010", "GEN"),
        _schema("S1-STC-010", "S1"),
        _schema("S2-MTR-010", "S2"),
    ]
    return MethodologyBundle(
        schema_rows=tuple(rows),
        edges=tuple([_edge()] if edges is None else edges),
        rules=tuple([_rule("CX-01"), _rule("CX-12")] if rules is None else rules),
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
    value_origin: str = "extracted",
    requirement_level: str = "Core",
    condition: str | None = None,
    vocabulary_references: tuple[str, ...] = (),
    derived_from: tuple[str, ...] = (),
) -> MethodologySchemaRow:
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
        data_schema_fields=("value",),
        calculation_role="parameter",
        value_origin=value_origin,
        requirement_level=requirement_level,
        condition=condition,
        anchor_type="evidence-derived",
        definition_purpose="Test row",
        vocabulary_references=vocabulary_references,
        source_citation=None,
        derived_from=derived_from,
        node_id=None,
        notes_flags=None,
        source_workbook=f"{layer}.xlsx",
        source_sheet="Sheet1",
        source_row_number=2,
    )


def _edge(
    *,
    edge_id: str = "EDG-001",
    scope_field_id: str = "S1-STC-010",
    gen_field_id: str = "INV-010",
) -> MethodologyEdge:
    return MethodologyEdge(
        edge_id=edge_id,
        layer="S1",
        scope_field_id=scope_field_id,
        scope_fields=(),
        direction="GEN_TO_SCOPE",
        reference_type="fk",
        edge_type="inventory_fk",
        condition="direct",
        transformation=None,
        gen_field_id=gen_field_id,
        gen_fields=(),
        cardinality="one_to_many",
        gen_version="GEN v1.1",
        status="Active",
        notes=None,
        source_workbook="edges.xlsx",
        source_sheet="Edge_Table",
        source_row_number=2,
    )


def _rule(
    rule_id: str,
    *,
    applies_to: tuple[str, ...] = ("INV-010",),
) -> VerificationRule:
    return VerificationRule(
        rule_id=rule_id,
        layer="CROSS",
        rule_type="guard",
        assertion="completeness",
        applies_to=applies_to,
        grain_key="-",
        rule_expression="Test expression",
        source="test",
        status="Active",
        notes=None,
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )
