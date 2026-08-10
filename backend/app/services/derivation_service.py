"""Derived methodology field engine v0 for Subsystem 2 PR9."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.app.domain.methodology import MethodologySchemaRow
from backend.app.services.methodology_registry_service import MethodologyRegistryService

DerivationStatus = Literal[
    "derived",
    "missing_dependency",
    "cross_layer_unsupported",
    "unsupported_derivation",
]


@dataclass(frozen=True)
class DerivedValueResult:
    field_id: str
    status: DerivationStatus
    derived_value: str | float | int | bool | None
    derived_unit: str | None
    dependency_field_ids: tuple[str, ...]
    source_methodology_value_ids: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "status": self.status,
            "derived_value": self.derived_value,
            "derived_unit": self.derived_unit,
            "dependency_field_ids": list(self.dependency_field_ids),
            "source_methodology_value_ids": list(self.source_methodology_value_ids),
            "reason": self.reason,
        }


class DerivationService:
    """Computes a safe v0 subset of methodology Derived_From relationships."""

    def __init__(self, methodology_registry: MethodologyRegistryService) -> None:
        self._registry = methodology_registry

    def derive_field(
        self,
        field_id: str,
        methodology_values: list[dict],
    ) -> dict:
        row = self._registry.get_row(field_id)
        if row is None:
            raise ValueError(f"Unknown methodology Field_ID: {field_id}")
        return self._derive_row(row, methodology_values).to_dict()

    def derive_all(
        self,
        methodology_values: list[dict],
    ) -> list[dict]:
        return [
            self._derive_row(row, methodology_values).to_dict()
            for row in self._registry.list_derived_rows()
        ]

    def _derive_row(
        self,
        row: MethodologySchemaRow,
        methodology_values: list[dict],
    ) -> DerivedValueResult:
        dependency_field_ids = row.derived_from
        if not dependency_field_ids:
            return DerivedValueResult(
                field_id=row.field_id,
                status="unsupported_derivation",
                derived_value=None,
                derived_unit=None,
                dependency_field_ids=(),
                source_methodology_value_ids=(),
                reason="row has no Derived_From dependencies",
            )
        dependency_rows = [self._registry.get_row(field_id) for field_id in dependency_field_ids]
        if any(dependency is None for dependency in dependency_rows):
            return DerivedValueResult(
                field_id=row.field_id,
                status="missing_dependency",
                derived_value=None,
                derived_unit=None,
                dependency_field_ids=dependency_field_ids,
                source_methodology_value_ids=(),
                reason="one or more Derived_From references do not resolve",
            )
        if any(dependency.layer != row.layer for dependency in dependency_rows if dependency):
            return DerivedValueResult(
                field_id=row.field_id,
                status="cross_layer_unsupported",
                derived_value=None,
                derived_unit=None,
                dependency_field_ids=dependency_field_ids,
                source_methodology_value_ids=(),
                reason="cross-layer Derived_From must be resolved through EDGES",
            )

        dependency_values = _values_for_dependencies(
            methodology_values,
            dependency_field_ids,
        )
        missing = [
            field_id
            for field_id in dependency_field_ids
            if field_id not in dependency_values
        ]
        if missing:
            return DerivedValueResult(
                field_id=row.field_id,
                status="missing_dependency",
                derived_value=None,
                derived_unit=None,
                dependency_field_ids=dependency_field_ids,
                source_methodology_value_ids=tuple(
                    str(value["methodology_value_id"])
                    for values in dependency_values.values()
                    for value in values
                ),
                reason=f"missing dependency value(s): {missing}",
            )

        source_values = [
            value
            for field_id in dependency_field_ids
            for value in dependency_values[field_id]
        ]
        source_ids = tuple(str(value["methodology_value_id"]) for value in source_values)

        if len(source_values) == 1:
            value = source_values[0]
            return DerivedValueResult(
                field_id=row.field_id,
                status="derived",
                derived_value=value.get("approved_value"),
                derived_unit=value.get("approved_unit"),
                dependency_field_ids=dependency_field_ids,
                source_methodology_value_ids=source_ids,
                reason="copy derivation",
            )

        numeric_values = [_as_number(value.get("approved_value")) for value in source_values]
        if all(value is not None for value in numeric_values):
            units = {
                value.get("approved_unit")
                for value in source_values
                if value.get("approved_unit") is not None
            }
            if len(units) <= 1:
                total = sum(value for value in numeric_values if value is not None)
                return DerivedValueResult(
                    field_id=row.field_id,
                    status="derived",
                    derived_value=total,
                    derived_unit=next(iter(units)) if units else None,
                    dependency_field_ids=dependency_field_ids,
                    source_methodology_value_ids=source_ids,
                    reason="sum derivation",
                )

        return DerivedValueResult(
            field_id=row.field_id,
            status="unsupported_derivation",
            derived_value=None,
            derived_unit=None,
            dependency_field_ids=dependency_field_ids,
            source_methodology_value_ids=source_ids,
            reason="derivation is not a supported v0 copy or sum",
        )


def _values_for_dependencies(
    methodology_values: list[dict],
    dependency_field_ids: tuple[str, ...],
) -> dict[str, list[dict]]:
    dependency_set = set(dependency_field_ids)
    values: dict[str, list[dict]] = {}
    for value in methodology_values:
        field_id = value.get("methodology_field_id")
        if field_id in dependency_set:
            values.setdefault(str(field_id), []).append(value)
    return values


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            number = float(value.replace(",", ""))
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None
