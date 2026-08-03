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
from backend.app.services.methodology_integrity_service import (
    MethodologyIntegrityService,
)


def test_real_methodology_bundle_passes_with_documented_warnings() -> None:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "passed_with_warnings"
    assert report.error_count == 0
    assert report.summary["schema_row_count"] == 279
    assert report.summary["edge_count"] == 114
    assert report.summary["rule_count"] == 89
    assert report.summary["cx01_non_requestable_value_origin_count"] == 54
    assert report.summary["assigned_value_origin_count"] == 42
    assert report.summary["cx12_conditional_row_count"] == 132


def test_real_methodology_bundle_reports_expected_warning_categories() -> None:
    bundle = load_default_methodology_bundle(repo_root=Path(__file__).resolve().parents[3])
    report = MethodologyIntegrityService().validate(bundle)
    warning_checks = {
        finding.check_id for finding in report.findings if finding.severity == "warning"
    }
    all_checks = {finding.check_id for finding in report.findings}
    info_checks = {
        finding.check_id for finding in report.findings if finding.severity == "info"
    }

    assert "derived_from_cross_layer" in warning_checks
    assert "edge_scope_field_wildcard_resolves" not in all_checks
    assert "rule_applies_to_prose" in info_checks


def test_duplicate_field_id_fails() -> None:
    bundle = _bundle(
        schema_rows=[
            _schema("INV-010", "GEN"),
            _schema("INV-010", "GEN"),
            _schema("S1-STC-010", "S1"),
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "unique_field_id" for f in report.findings)


def test_edge_with_missing_gen_field_fails() -> None:
    bundle = _bundle(
        edges=[
            _edge(
                edge_id="EDG-BAD",
                scope_field_id="S1-STC-010",
                gen_field_id="INV-999",
            )
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "edge_gen_field_resolves" for f in report.findings)


def test_edge_with_missing_scope_field_fails() -> None:
    bundle = _bundle(
        edges=[
            _edge(
                edge_id="EDG-BAD",
                scope_field_id="S1-STC-999",
                gen_field_id="INV-010",
            )
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "edge_scope_field_resolves" for f in report.findings)


def test_direct_scope1_scope2_edge_fails() -> None:
    bundle = _bundle(
        schema_rows=[
            _schema("INV-010", "GEN"),
            _schema("S1-STC-010", "S1"),
            _schema("S2-MTR-010", "S2"),
        ],
        edges=[
            _edge(
                edge_id="EDG-BAD",
                scope_field_id="S1-STC-010",
                gen_field_id="S2-MTR-010",
            )
        ],
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "no_direct_scope1_scope2_join" for f in report.findings)


def test_edge_scope_wildcard_expands_to_matching_scope_rows() -> None:
    bundle = _bundle(
        schema_rows=[
            _schema("INV-010", "GEN"),
            _schema("S2-EFS-010", "S2"),
            _schema("S2-EFS-020", "S2"),
        ],
        edges=[
            _edge(
                edge_id="EDG-WILDCARD",
                scope_field_id="S2-EFS-*",
                gen_field_id="INV-010",
            )
        ],
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "passed"
    assert not any(
        f.check_id == "edge_scope_field_wildcard_resolves" for f in report.findings
    )


def test_edge_scope_wildcard_without_matches_fails() -> None:
    bundle = _bundle(
        edges=[
            _edge(
                edge_id="EDG-WILDCARD",
                scope_field_id="S2-NOPE-*",
                gen_field_id="INV-010",
            )
        ],
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(
        f.check_id == "edge_scope_field_wildcard_resolves" for f in report.findings
    )


def test_rule_missing_applies_to_field_fails() -> None:
    bundle = _bundle(
        rules=[
            _rule("CX-01"),
            _rule("CX-12"),
            _rule("BAD-RULE", applies_to=("S1-STC-999",)),
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "rule_applies_to_resolves" for f in report.findings)


def test_missing_cx_guards_fail() -> None:
    bundle = _bundle(rules=[])

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "cx01_exists" for f in report.findings)
    assert any(f.check_id == "cx12_exists" for f in report.findings)


def test_derived_from_missing_reference_fails() -> None:
    bundle = _bundle(
        schema_rows=[
            _schema("INV-010", "GEN", derived_from=("INV-999",)),
            _schema("S1-STC-010", "S1"),
            _schema("S2-MTR-010", "S2"),
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "failed"
    assert any(f.check_id == "derived_from_resolves" for f in report.findings)


def test_derived_from_cross_layer_is_warning_for_current_workbook_compatibility() -> None:
    bundle = _bundle(
        schema_rows=[
            _schema("INV-010", "GEN", derived_from=("S1-STC-010",)),
            _schema("S1-STC-010", "S1"),
            _schema("S2-MTR-010", "S2"),
        ]
    )

    report = MethodologyIntegrityService().validate(bundle)

    assert report.status == "passed_with_warnings"
    assert any(f.check_id == "derived_from_cross_layer" for f in report.findings)


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
    condition: str | None = None,
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
        requirement_level="Core",
        condition=condition,
        anchor_type="evidence-derived",
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


def _rule(rule_id: str, *, applies_to: tuple[str, ...] = ("INV-010",)) -> VerificationRule:
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
