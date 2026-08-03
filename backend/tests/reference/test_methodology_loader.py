from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from backend.app.domain.methodology import MethodologySourceFile
from backend.app.reference.methodology_loader import (
    CORE_METHODOLOGY_FILES,
    MethodologyColumnError,
    MethodologyDataError,
    MethodologySheetError,
    MethodologySourceNotFoundError,
    find_default_methodology_sources,
    load_default_methodology_bundle,
    load_methodology_bundle,
)


def test_default_methodology_sources_resolve_to_five_workbooks() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    sources = find_default_methodology_sources(repo_root=repo_root)

    assert len(sources) == 5
    assert {source.role for source in sources} == set(CORE_METHODOLOGY_FILES)
    assert all(source.path.exists() for source in sources)


def test_real_methodology_bundle_loads_expected_row_counts() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    bundle = load_default_methodology_bundle(repo_root=repo_root)

    assert len(bundle.gen_schema_rows) == 51
    assert len(bundle.scope1_schema_rows) == 139
    assert len(bundle.scope2_schema_rows) == 89
    assert len(bundle.edges) == 114
    assert len(bundle.rules) == 89
    assert len(bundle.source_files) == 5


def test_real_methodology_bundle_exposes_runtime_indexes() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    bundle = load_default_methodology_bundle(repo_root=repo_root)

    assert bundle.schema_by_field_id["S1-STC-010"].layer == "S1"
    assert bundle.schema_by_field_id["S1-STC-010"].data_schema_fields == (
        "fuel_type",
        "quantity_combusted",
        "quantity_unit",
    )
    assert bundle.schema_by_field_id["INV-010"].layer == "GEN"
    assert bundle.edges_by_id["EDG-S1-001"].direction == "GEN_TO_SCOPE"
    assert bundle.rules_by_id["CX-01"].rule_type == "guard"


def test_scope2_scope_column_normalizes_to_scope_applicability() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    bundle = load_default_methodology_bundle(repo_root=repo_root)

    row = bundle.schema_by_field_id["S2-MTR-010"]
    assert row.layer == "S2"
    assert row.scope_applicability == "2"


def test_missing_source_role_fails(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path,
        role="gen_schema",
        sheet="1_Schema",
        headers=_schema_headers(),
        rows=[["INV-010"]],
    )

    with pytest.raises(MethodologySourceNotFoundError):
        load_methodology_bundle((source,))


def test_missing_expected_sheet_fails(tmp_path: Path) -> None:
    sources = _minimal_sources(tmp_path)
    bad = _workbook(
        tmp_path,
        role="gen_schema",
        sheet="WrongSheet",
        headers=_schema_headers(),
        rows=[["INV-010"]],
    )
    sources["gen_schema"] = MethodologySourceFile(
        role="gen_schema",
        path=bad.path,
        sheet_name="1_Schema",
    )

    with pytest.raises(MethodologySheetError):
        load_methodology_bundle(tuple(sources.values()))


def test_missing_required_column_fails(tmp_path: Path) -> None:
    sources = _minimal_sources(tmp_path)
    bad = _workbook(
        tmp_path,
        role="rules",
        sheet="Verification_Rules",
        headers=["Rule_ID", "Layer", "Type"],
        rows=[["CX-01", "CROSS", "guard"]],
    )
    sources["rules"] = bad

    with pytest.raises(MethodologyColumnError):
        load_methodology_bundle(tuple(sources.values()))


def test_blank_required_id_fails(tmp_path: Path) -> None:
    sources = _minimal_sources(tmp_path)
    bad = _workbook(
        tmp_path,
        role="edges",
        sheet="Edge_Table",
        headers=_edge_headers(),
        rows=[[None]],
    )
    sources["edges"] = bad

    with pytest.raises(MethodologyDataError):
        load_methodology_bundle(tuple(sources.values()))


def _minimal_sources(tmp_path: Path) -> dict[str, MethodologySourceFile]:
    return {
        "gen_schema": _workbook(
            tmp_path,
            role="gen_schema",
            sheet="1_Schema",
            headers=_schema_headers(),
            rows=[_schema_row(f"GEN-{i:03}") for i in range(51)],
        ),
        "scope1_schema": _workbook(
            tmp_path,
            role="scope1_schema",
            sheet="1_Schema",
            headers=_schema_headers(),
            rows=[_schema_row(f"S1-{i:03}") for i in range(139)],
        ),
        "scope2_schema": _workbook(
            tmp_path,
            role="scope2_schema",
            sheet="S2_Schema",
            headers=["Field_ID", "Scope", *_schema_headers()[2:]],
            rows=[_schema_row(f"S2-{i:03}") for i in range(89)],
        ),
        "edges": _workbook(
            tmp_path,
            role="edges",
            sheet="Edge_Table",
            headers=_edge_headers(),
            rows=[_edge_row(f"EDG-{i:03}") for i in range(114)],
        ),
        "rules": _workbook(
            tmp_path,
            role="rules",
            sheet="Verification_Rules",
            headers=_rule_headers(),
            rows=[_rule_row(f"CX-{i:03}") for i in range(89)],
        ),
    }


def _workbook(
    tmp_path: Path,
    *,
    role: str,
    sheet: str,
    headers: list[str],
    rows: list[list[str | None]],
) -> MethodologySourceFile:
    path = tmp_path / f"{role}.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    worksheet.append(headers)
    for row in rows:
        padded = row + [None] * (len(headers) - len(row))
        worksheet.append(padded)
    workbook.save(path)
    return MethodologySourceFile(role=role, path=path, sheet_name=sheet)


def _schema_headers() -> list[str]:
    return [
        "Field_ID",
        "Scope_Applicability",
        "Block",
        "Grain",
        "Source_Category",
        "Calculation_Method",
        "Emission_Source",
        "Gas_Applicability",
        "Data_Schema_Field(s)",
        "Calculation_Role",
        "Value_Origin",
        "Requirement_Level",
        "Condition",
        "Anchor_Type",
        "Definition_Purpose",
        "Vocabulary_Reference",
        "Source_Citation",
        "Derived_From",
        "Node_ID",
        "Notes_Flags",
    ]


def _schema_row(field_id: str) -> list[str]:
    return [
        field_id,
        "General",
        "INV",
        "inventory",
        "N/A",
        "N/A",
        "N/A",
        "N/A",
        "inventory_id; reporting_year",
        "parameter",
        "extracted",
        "Core",
        "",
        "evidence-derived",
        "Definition",
        "inventory_id",
        "",
        "",
        "",
        "",
    ]


def _edge_headers() -> list[str]:
    return [
        "Edge_ID",
        "Layer",
        "Scope_Field_ID",
        "Scope_Field(s)",
        "Direction",
        "Reference_Type",
        "Edge_Type",
        "Condition",
        "Transformation",
        "GEN_Field_ID",
        "GEN_Field(s)",
        "Cardinality",
        "GEN_Version",
        "Status",
        "Notes",
    ]


def _edge_row(edge_id: str | None) -> list[str | None]:
    return [
        edge_id,
        "S1",
        "S1-STC-100",
        "inventory_id",
        "GEN_TO_SCOPE",
        "fk",
        "inventory_fk",
        "direct",
        "",
        "INV-010",
        "inventory_id",
        "one_to_many",
        "GEN v1.1",
        "Active",
        "",
    ]


def _rule_headers() -> list[str]:
    return [
        "Rule_ID",
        "Layer",
        "Type",
        "Assertion",
        "Applies_To",
        "Grain_Key",
        "Rule_Expression",
        "Source",
        "Status",
        "Notes",
    ]


def _rule_row(rule_id: str) -> list[str]:
    return [
        rule_id,
        "CROSS",
        "guard",
        "completeness",
        "ALL — every row with Value_Origin",
        "-",
        "No document request for computed fields.",
        "Sustentra architecture",
        "Active",
        "",
    ]
