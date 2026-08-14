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
from backend.app.services.edge_resolution_service import EdgeResolutionService
from backend.app.services.methodology_registry_service import MethodologyRegistryService


def test_fk_edge_is_join() -> None:
    service = _service(
        edges=[
            _edge("EDG-FK", reference_type="fk"),
        ]
    )

    edges = service.list_edges_for_field("S1-STC-010")

    assert len(edges) == 1
    assert edges[0].treatment == "foreign_key_join"
    assert edges[0].is_join is True


def test_rule_input_is_not_foreign_key_join() -> None:
    service = _service(
        edges=[
            _edge("EDG-RULE", reference_type="rule_input"),
        ]
    )

    edges = service.list_edges_for_field("S1-STC-010")

    assert len(edges) == 1
    assert edges[0].treatment == "rule_input"
    assert edges[0].is_join is False
    assert service.list_join_edges_for_field("S1-STC-010") == ()


def test_reference_type_treatments() -> None:
    service = _service(
        edges=[
            _edge("EDG-SCOPE", reference_type="scope"),
            _edge("EDG-WRITES", reference_type="writes_to"),
            _edge("EDG-DISCLOSED", reference_type="disclosed_via"),
        ]
    )

    treatments = {
        edge.edge.edge_id: edge.treatment
        for edge in service.list_edges_for_field("S1-STC-010")
    }

    assert treatments == {
        "EDG-SCOPE": "applicability_scope",
        "EDG-WRITES": "scope_writes_to_gen",
        "EDG-DISCLOSED": "scope_disclosed_via_gen",
    }


def test_unsupported_reference_type_is_reported_not_joined() -> None:
    service = _service(
        edges=[
            _edge("EDG-ODD", reference_type="odd_type"),
        ]
    )

    edge = service.list_edges_for_field("S1-STC-010")[0]

    assert edge.treatment == "unsupported_reference_type"
    assert edge.is_join is False
    assert "odd_type" in (edge.reason or "")


def test_wildcard_edge_from_registry_is_resolved() -> None:
    service = _service(
        schema_rows=[
            _schema("INV-010", "GEN"),
            _schema("S2-EFS-010", "S2"),
        ],
        edges=[
            _edge(
                "EDG-WILD",
                scope_field_id="S2-EFS-*",
                gen_field_id="INV-010",
                reference_type="disclosed_via",
            )
        ],
    )

    edges = service.list_edges_for_field("S2-EFS-010")

    assert len(edges) == 1
    assert edges[0].edge.edge_id == "EDG-WILD"
    assert edges[0].treatment == "scope_disclosed_via_gen"


def test_real_bundle_resolves_known_edges() -> None:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    service = EdgeResolutionService(MethodologyRegistryService(bundle))

    inv_edges = service.list_edges_for_field("INV-010")
    efs_edges = service.list_edges_for_field("S2-EFS-010")

    assert "EDG-S1-001" in {edge.edge.edge_id for edge in inv_edges}
    assert any(edge.is_join for edge in inv_edges)
    assert "EDG-S2-024" in {edge.edge.edge_id for edge in efs_edges}


def _service(
    *,
    schema_rows: list[MethodologySchemaRow] | None = None,
    edges: list[MethodologyEdge],
) -> EdgeResolutionService:
    return EdgeResolutionService(
        MethodologyRegistryService(
            _bundle(schema_rows=schema_rows, edges=edges)
        )
    )


def _bundle(
    *,
    schema_rows: list[MethodologySchemaRow] | None = None,
    edges: list[MethodologyEdge],
) -> MethodologyBundle:
    return MethodologyBundle(
        schema_rows=tuple(
            schema_rows
            or [
                _schema("INV-010", "GEN"),
                _schema("S1-STC-010", "S1"),
            ]
        ),
        edges=tuple(edges),
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


def _edge(
    edge_id: str,
    *,
    scope_field_id: str = "S1-STC-010",
    gen_field_id: str = "INV-010",
    reference_type: str,
) -> MethodologyEdge:
    return MethodologyEdge(
        edge_id=edge_id,
        layer="S1",
        scope_field_id=scope_field_id,
        scope_fields=(),
        direction="GEN_TO_SCOPE",
        reference_type=reference_type,
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
