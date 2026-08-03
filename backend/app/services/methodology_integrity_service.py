"""Methodology integrity validation for Subsystem 2 PR2."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from backend.app.domain.methodology import MethodologyBundle, MethodologySchemaRow

FindingSeverity = Literal["error", "warning", "info"]

FIELD_ID_PATTERN = re.compile(r"\b(?:S[12]-[A-Z0-9]+-\d+|[A-Z]{3}-\d+)\b")
FIELD_ID_PREFIX_PATTERN = re.compile(r"\b(S[12]-[A-Z0-9]+-)\*")


@dataclass(frozen=True)
class MethodologyIntegrityFinding:
    check_id: str
    severity: FindingSeverity
    message: str
    subject_id: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class MethodologyIntegrityReport:
    status: Literal["passed", "passed_with_warnings", "failed"]
    findings: tuple[MethodologyIntegrityFinding, ...]
    summary: dict[str, int | dict[str, int]]

    @property
    def error_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for finding in self.findings if finding.severity == "warning")


class MethodologyIntegrityService:
    """Runs static integrity checks over a loaded methodology bundle."""

    def validate(self, bundle: MethodologyBundle) -> MethodologyIntegrityReport:
        findings: list[MethodologyIntegrityFinding] = []
        schema_by_field_id = bundle.schema_by_field_id
        rows_by_layer = {
            "GEN": {row.field_id: row for row in bundle.gen_schema_rows},
            "S1": {row.field_id: row for row in bundle.scope1_schema_rows},
            "S2": {row.field_id: row for row in bundle.scope2_schema_rows},
        }

        findings.extend(self._check_unique_field_ids(bundle.schema_rows))
        findings.extend(self._check_edges(bundle, schema_by_field_id, rows_by_layer))
        findings.extend(self._check_rule_applies_to(bundle, schema_by_field_id))
        findings.extend(self._check_derived_from(bundle, schema_by_field_id, rows_by_layer))
        findings.extend(self._check_cx_guards(bundle))

        summary = self._summary(bundle, findings)
        error_count = sum(1 for finding in findings if finding.severity == "error")
        warning_count = sum(1 for finding in findings if finding.severity == "warning")
        if error_count:
            status = "failed"
        elif warning_count:
            status = "passed_with_warnings"
        else:
            status = "passed"
        return MethodologyIntegrityReport(
            status=status,
            findings=tuple(findings),
            summary=summary,
        )

    def _check_unique_field_ids(
        self,
        rows: tuple[MethodologySchemaRow, ...],
    ) -> list[MethodologyIntegrityFinding]:
        counts = Counter(row.field_id for row in rows)
        return [
            MethodologyIntegrityFinding(
                check_id="unique_field_id",
                severity="error",
                subject_id=field_id,
                message=f"Duplicate methodology Field_ID '{field_id}'.",
            )
            for field_id, count in sorted(counts.items())
            if count > 1
        ]

    def _check_edges(
        self,
        bundle: MethodologyBundle,
        schema_by_field_id: dict[str, MethodologySchemaRow],
        rows_by_layer: dict[str, dict[str, MethodologySchemaRow]],
    ) -> list[MethodologyIntegrityFinding]:
        findings: list[MethodologyIntegrityFinding] = []
        for edge in bundle.edges:
            scope_refs = list(self._field_refs(edge.scope_field_id, *edge.scope_fields))
            gen_refs = self._field_refs(edge.gen_field_id, *edge.gen_fields)
            wildcard_prefixes = self._wildcard_prefixes(
                edge.scope_field_id, *edge.scope_fields
            )

            for prefix in wildcard_prefixes:
                matched_refs = sorted(
                    field_id
                    for field_id in schema_by_field_id
                    if field_id.startswith(prefix)
                )
                if not matched_refs:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="edge_scope_field_wildcard_resolves",
                            severity="error",
                            subject_id=edge.edge_id,
                            source=edge.source_workbook,
                            message=(
                                "Edge scope wildcard reference "
                                f"'{prefix}*' does not match any schema rows."
                            ),
                        )
                    )
                    continue
                for ref in matched_refs:
                    if ref not in scope_refs:
                        scope_refs.append(ref)

            for ref in scope_refs:
                row = schema_by_field_id.get(ref)
                if row is None:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="edge_scope_field_resolves",
                            severity="error",
                            subject_id=edge.edge_id,
                            source=edge.source_workbook,
                            message=f"Edge scope Field_ID '{ref}' does not resolve.",
                        )
                    )
                    continue
                if row.layer not in {"S1", "S2"}:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="edge_scope_field_layer",
                            severity="error",
                            subject_id=edge.edge_id,
                            source=edge.source_workbook,
                            message=(
                                f"Edge scope Field_ID '{ref}' resolves to layer "
                                f"{row.layer}, expected S1 or S2."
                            ),
                        )
                    )

            for ref in gen_refs:
                row = rows_by_layer["GEN"].get(ref)
                if row is None:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="edge_gen_field_resolves",
                            severity="error",
                            subject_id=edge.edge_id,
                            source=edge.source_workbook,
                            message=f"Edge GEN Field_ID '{ref}' does not resolve to GEN.",
                        )
                    )

            layers = {
                schema_by_field_id[ref].layer
                for ref in (*scope_refs, *gen_refs)
                if ref in schema_by_field_id
            }
            if "S1" in layers and "S2" in layers:
                findings.append(
                    MethodologyIntegrityFinding(
                        check_id="no_direct_scope1_scope2_join",
                        severity="error",
                        subject_id=edge.edge_id,
                        source=edge.source_workbook,
                        message="Edge directly joins Scope 1 and Scope 2 rows.",
                    )
                )

        return findings

    def _check_rule_applies_to(
        self,
        bundle: MethodologyBundle,
        schema_by_field_id: dict[str, MethodologySchemaRow],
    ) -> list[MethodologyIntegrityFinding]:
        findings: list[MethodologyIntegrityFinding] = []
        for rule in bundle.rules:
            refs = self._field_refs(*rule.applies_to)
            if not refs and rule.applies_to:
                findings.append(
                    MethodologyIntegrityFinding(
                        check_id="rule_applies_to_prose",
                        severity="info",
                        subject_id=rule.rule_id,
                        source=rule.source_workbook,
                        message=(
                            "Rule Applies_To contains prose, registry names, or wildcard "
                            f"references not resolved in PR2: {'; '.join(rule.applies_to)}."
                        ),
                    )
                )
                continue
            for ref in refs:
                if ref not in schema_by_field_id:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="rule_applies_to_resolves",
                            severity="error",
                            subject_id=rule.rule_id,
                            source=rule.source_workbook,
                            message=f"Rule Applies_To Field_ID '{ref}' does not resolve.",
                        )
                    )
        return findings

    def _check_derived_from(
        self,
        bundle: MethodologyBundle,
        schema_by_field_id: dict[str, MethodologySchemaRow],
        rows_by_layer: dict[str, dict[str, MethodologySchemaRow]],
    ) -> list[MethodologyIntegrityFinding]:
        findings: list[MethodologyIntegrityFinding] = []
        for row in bundle.schema_rows:
            refs = self._field_refs(*row.derived_from)
            for ref in refs:
                if ref not in schema_by_field_id:
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="derived_from_resolves",
                            severity="error",
                            subject_id=row.field_id,
                            source=row.source_workbook,
                            message=f"Derived_From Field_ID '{ref}' does not resolve.",
                        )
                    )
                    continue
                if ref not in rows_by_layer[row.layer]:
                    ref_layer = schema_by_field_id[ref].layer
                    findings.append(
                        MethodologyIntegrityFinding(
                            check_id="derived_from_cross_layer",
                            severity="warning",
                            subject_id=row.field_id,
                            source=row.source_workbook,
                            message=(
                                f"Derived_From reference '{ref}' crosses from "
                                f"{row.layer} to {ref_layer}. PR2 records this for ESG "
                                "review; later edge resolution should own cross-layer joins."
                            ),
                        )
                    )
        return findings

    def _check_cx_guards(
        self,
        bundle: MethodologyBundle,
    ) -> list[MethodologyIntegrityFinding]:
        findings: list[MethodologyIntegrityFinding] = []
        if "CX-01" not in bundle.rules_by_id:
            findings.append(
                MethodologyIntegrityFinding(
                    check_id="cx01_exists",
                    severity="error",
                    subject_id="CX-01",
                    message="CX-01 completeness/document-request guard is missing.",
                )
            )
        if "CX-12" not in bundle.rules_by_id:
            findings.append(
                MethodologyIntegrityFinding(
                    check_id="cx12_exists",
                    severity="error",
                    subject_id="CX-12",
                    message="CX-12 conditional-applicability guard is missing.",
                )
            )
        return findings

    def _summary(
        self,
        bundle: MethodologyBundle,
        findings: list[MethodologyIntegrityFinding],
    ) -> dict[str, int | dict[str, int]]:
        value_origin_counts = Counter(
            (row.value_origin or "blank") for row in bundle.schema_rows
        )
        severity_counts = Counter(finding.severity for finding in findings)
        check_counts = Counter(finding.check_id for finding in findings)
        cx01_exposure_count = sum(
            1
            for row in bundle.schema_rows
            if (row.value_origin or "").casefold()
            in {"computed", "verifier_determined"}
        )
        assigned_count = sum(
            1
            for row in bundle.schema_rows
            if (row.value_origin or "").casefold() == "assigned"
        )
        conditional_row_count = sum(1 for row in bundle.schema_rows if row.condition)
        return {
            "schema_row_count": len(bundle.schema_rows),
            "gen_schema_row_count": len(bundle.gen_schema_rows),
            "scope1_schema_row_count": len(bundle.scope1_schema_rows),
            "scope2_schema_row_count": len(bundle.scope2_schema_rows),
            "edge_count": len(bundle.edges),
            "rule_count": len(bundle.rules),
            "cx01_non_requestable_value_origin_count": cx01_exposure_count,
            "assigned_value_origin_count": assigned_count,
            "cx12_conditional_row_count": conditional_row_count,
            "value_origin_counts": dict(sorted(value_origin_counts.items())),
            "severity_counts": dict(sorted(severity_counts.items())),
            "finding_counts_by_check": dict(sorted(check_counts.items())),
        }

    @staticmethod
    def _field_refs(*values: object) -> tuple[str, ...]:
        refs: list[str] = []
        for value in values:
            if value is None:
                continue
            for ref in FIELD_ID_PATTERN.findall(str(value)):
                if ref not in refs:
                    refs.append(ref)
        return tuple(refs)

    @staticmethod
    def _wildcard_prefixes(*values: object) -> tuple[str, ...]:
        prefixes: list[str] = []
        for value in values:
            if value is None:
                continue
            for prefix in FIELD_ID_PREFIX_PATTERN.findall(str(value)):
                if prefix not in prefixes:
                    prefixes.append(prefix)
        return tuple(prefixes)
