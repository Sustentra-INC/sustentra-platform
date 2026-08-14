"""Runtime methodology registry for Subsystem 2 PR3."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from backend.app.domain.methodology import (
    MethodologyBundle,
    MethodologyEdge,
    MethodologyLayer,
    MethodologySchemaRow,
    VerificationRule,
)

FIELD_ID_PATTERN = re.compile(r"\b(?:S[12]-[A-Z0-9]+-\d+|[A-Z]{3}-\d+)\b")
FIELD_ID_PREFIX_PATTERN = re.compile(r"\b(S[12]-[A-Z0-9]+-)\*")


class MethodologyRegistryService:
    """Queryable runtime index over an already-loaded methodology bundle.

    The registry owns lookup/index behavior only. Workbook parsing stays in the
    PR1 loader, and rule execution/completeness evaluation stay in later S2 PRs.
    """

    def __init__(self, bundle: MethodologyBundle) -> None:
        self._bundle = bundle
        self._rows_by_field_id = bundle.schema_by_field_id
        self._rows_by_layer = self._index_rows_by_attr("layer")
        self._rows_by_value_origin = self._index_rows_by_normalized_attr("value_origin")
        self._rows_by_requirement_level = self._index_rows_by_normalized_attr(
            "requirement_level"
        )
        self._rows_by_vocabulary_reference = self._index_rows_by_vocabulary_reference()
        self._rules_by_field_id = self._index_rules_by_field_id()
        self._edges_by_field_id = self._index_edges_by_field_id()

    def get_row(self, field_id: str) -> MethodologySchemaRow | None:
        """Return a schema row by Field_ID, or None when it is not loaded."""

        return self._rows_by_field_id.get(field_id)

    def list_rows(
        self,
        *,
        layer: MethodologyLayer | None = None,
    ) -> tuple[MethodologySchemaRow, ...]:
        """List schema rows, optionally restricted to GEN, S1, or S2."""

        if layer is None:
            return self._bundle.schema_rows
        return tuple(self._rows_by_layer.get(layer, ()))

    def list_by_value_origin(self, value_origin: str) -> tuple[MethodologySchemaRow, ...]:
        """List rows by Value_Origin using case-insensitive matching."""

        return tuple(self._rows_by_value_origin.get(_normalize_key(value_origin), ()))

    def list_required_rows(
        self,
        requirement_level: str = "Core",
    ) -> tuple[MethodologySchemaRow, ...]:
        """List rows by requirement level, defaulting to Core rows."""

        return tuple(
            self._rows_by_requirement_level.get(_normalize_key(requirement_level), ())
        )

    def list_rows_by_vocabulary_reference(
        self,
        canonical_type_id: str,
    ) -> tuple[MethodologySchemaRow, ...]:
        """List rows that reference a canonical vocabulary/document type ID."""

        return tuple(
            self._rows_by_vocabulary_reference.get(_normalize_key(canonical_type_id), ())
        )

    def list_conditions(self) -> tuple[MethodologySchemaRow, ...]:
        """List rows with a non-empty Condition."""

        return tuple(row for row in self._bundle.schema_rows if row.condition)

    def list_derived_rows(self) -> tuple[MethodologySchemaRow, ...]:
        """List rows with non-empty Derived_From references."""

        return tuple(row for row in self._bundle.schema_rows if row.derived_from)

    def list_rules_for_field(self, field_id: str) -> tuple[VerificationRule, ...]:
        """List rules with concrete Applies_To references to a field.

        PR3 intentionally does not attach prose targets such as "Any row with a
        non-null Condition" to every possible row.
        """

        return tuple(self._rules_by_field_id.get(field_id, ()))

    def list_edges_for_field(self, field_id: str) -> tuple[MethodologyEdge, ...]:
        """List edges that reference a field directly or through a wildcard."""

        return tuple(self._edges_by_field_id.get(field_id, ()))

    def _index_rows_by_attr(
        self,
        attr_name: str,
    ) -> dict[str, tuple[MethodologySchemaRow, ...]]:
        indexed: defaultdict[str, list[MethodologySchemaRow]] = defaultdict(list)
        for row in self._bundle.schema_rows:
            value = getattr(row, attr_name)
            if value:
                indexed[value].append(row)
        return {key: tuple(rows) for key, rows in indexed.items()}

    def _index_rows_by_normalized_attr(
        self,
        attr_name: str,
    ) -> dict[str, tuple[MethodologySchemaRow, ...]]:
        indexed: defaultdict[str, list[MethodologySchemaRow]] = defaultdict(list)
        for row in self._bundle.schema_rows:
            value = getattr(row, attr_name)
            if value:
                indexed[_normalize_key(value)].append(row)
        return {key: tuple(rows) for key, rows in indexed.items()}

    def _index_rows_by_vocabulary_reference(
        self,
    ) -> dict[str, tuple[MethodologySchemaRow, ...]]:
        indexed: defaultdict[str, list[MethodologySchemaRow]] = defaultdict(list)
        for row in self._bundle.schema_rows:
            for vocabulary_reference in row.vocabulary_references:
                indexed[_normalize_key(vocabulary_reference)].append(row)
        return {key: tuple(rows) for key, rows in indexed.items()}

    def _index_rules_by_field_id(self) -> dict[str, tuple[VerificationRule, ...]]:
        indexed: defaultdict[str, list[VerificationRule]] = defaultdict(list)
        for rule in self._bundle.rules:
            for field_id in _field_refs(rule.applies_to):
                if field_id in self._rows_by_field_id:
                    indexed[field_id].append(rule)
        return {key: tuple(rules) for key, rules in indexed.items()}

    def _index_edges_by_field_id(self) -> dict[str, tuple[MethodologyEdge, ...]]:
        indexed: defaultdict[str, list[MethodologyEdge]] = defaultdict(list)
        for edge in self._bundle.edges:
            field_ids = set(
                _field_refs(
                    (
                        edge.scope_field_id,
                        *edge.scope_fields,
                        edge.gen_field_id,
                        *edge.gen_fields,
                    )
                )
            )
            field_ids.update(
                self._expand_wildcards(
                    edge.scope_field_id,
                    *edge.scope_fields,
                    edge.gen_field_id,
                    *edge.gen_fields,
                )
            )
            for field_id in sorted(field_ids):
                if field_id in self._rows_by_field_id:
                    indexed[field_id].append(edge)
        return {key: tuple(edges) for key, edges in indexed.items()}

    def _expand_wildcards(self, *values: object) -> tuple[str, ...]:
        matched: list[str] = []
        for prefix in _wildcard_prefixes(values):
            for field_id in sorted(self._rows_by_field_id):
                if field_id.startswith(prefix) and field_id not in matched:
                    matched.append(field_id)
        return tuple(matched)


def _normalize_key(value: str) -> str:
    return value.strip().casefold()


def _field_refs(values: Iterable[object]) -> tuple[str, ...]:
    refs: list[str] = []
    for value in values:
        if value is None:
            continue
        for ref in FIELD_ID_PATTERN.findall(str(value)):
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _wildcard_prefixes(values: Iterable[object]) -> tuple[str, ...]:
    prefixes: list[str] = []
    for value in values:
        if value is None:
            continue
        for prefix in FIELD_ID_PREFIX_PATTERN.findall(str(value)):
            if prefix not in prefixes:
                prefixes.append(prefix)
    return tuple(prefixes)
