from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MethodologyLayer = Literal["GEN", "S1", "S2"]


@dataclass(frozen=True)
class MethodologySchemaRow:
    """One data-schema row from the GEN, Scope 1, or Scope 2 methodology workbooks."""

    field_id: str
    layer: MethodologyLayer
    scope_applicability: str | None
    block: str | None
    grain: str | None
    source_category: str | None
    calculation_method: str | None
    emission_source: str | None
    gas_applicability: str | None
    data_schema_fields: tuple[str, ...]
    calculation_role: str | None
    value_origin: str | None
    requirement_level: str | None
    condition: str | None
    anchor_type: str | None
    definition_purpose: str | None
    vocabulary_references: tuple[str, ...]
    source_citation: str | None
    derived_from: tuple[str, ...]
    node_id: str | None
    notes_flags: str | None
    source_workbook: str
    source_sheet: str
    source_row_number: int


@dataclass(frozen=True)
class MethodologyEdge:
    """One cross-layer dependency edge between GEN and Scope 1/Scope 2 rows."""

    edge_id: str
    layer: str
    scope_field_id: str | None
    scope_fields: tuple[str, ...]
    direction: str | None
    reference_type: str | None
    edge_type: str | None
    condition: str | None
    transformation: str | None
    gen_field_id: str | None
    gen_fields: tuple[str, ...]
    cardinality: str | None
    gen_version: str | None
    status: str | None
    notes: str | None
    source_workbook: str
    source_sheet: str
    source_row_number: int


@dataclass(frozen=True)
class VerificationRule:
    """One verification rule registry row."""

    rule_id: str
    layer: str
    rule_type: str | None
    assertion: str | None
    applies_to: tuple[str, ...]
    grain_key: str | None
    rule_expression: str | None
    source: str | None
    status: str | None
    notes: str | None
    source_workbook: str
    source_sheet: str
    source_row_number: int


@dataclass(frozen=True)
class MethodologySourceFile:
    """Resolved source file used to build a methodology bundle."""

    role: str
    path: Path
    sheet_name: str


@dataclass(frozen=True)
class MethodologyBundle:
    """Loaded S2 methodology package."""

    schema_rows: tuple[MethodologySchemaRow, ...]
    edges: tuple[MethodologyEdge, ...]
    rules: tuple[VerificationRule, ...]
    source_files: tuple[MethodologySourceFile, ...]

    @property
    def gen_schema_rows(self) -> tuple[MethodologySchemaRow, ...]:
        return tuple(row for row in self.schema_rows if row.layer == "GEN")

    @property
    def scope1_schema_rows(self) -> tuple[MethodologySchemaRow, ...]:
        return tuple(row for row in self.schema_rows if row.layer == "S1")

    @property
    def scope2_schema_rows(self) -> tuple[MethodologySchemaRow, ...]:
        return tuple(row for row in self.schema_rows if row.layer == "S2")

    @property
    def schema_by_field_id(self) -> dict[str, MethodologySchemaRow]:
        return {row.field_id: row for row in self.schema_rows}

    @property
    def edges_by_id(self) -> dict[str, MethodologyEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    @property
    def rules_by_id(self) -> dict[str, VerificationRule]:
        return {rule.rule_id: rule for rule in self.rules}
