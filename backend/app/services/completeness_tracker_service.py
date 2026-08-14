"""Completeness tracker and S1-to-S2 gate for Subsystem 2 PR7."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from backend.app.domain.methodology import MethodologySchemaRow
from backend.app.services.condition_evaluator import ConditionEvaluator
from backend.app.services.methodology_registry_service import MethodologyRegistryService

CompletenessStatus = Literal[
    "complete",
    "missing_required",
    "not_applicable",
    "provisional_condition_unknown",
    "not_requestable_value_origin",
]

REQUESTABLE_VALUE_ORIGINS = {"extracted"}
NON_REQUESTABLE_VALUE_ORIGINS = {"computed", "verifier_determined", "assigned"}


@dataclass(frozen=True)
class CompletenessRowResult:
    field_id: str
    layer: str
    value_origin: str | None
    requirement_level: str | None
    condition: str | None
    condition_status: str | None
    status: CompletenessStatus
    methodology_value_ids: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "layer": self.layer,
            "value_origin": self.value_origin,
            "requirement_level": self.requirement_level,
            "condition": self.condition,
            "condition_status": self.condition_status,
            "status": self.status,
            "methodology_value_ids": list(self.methodology_value_ids),
            "reason": self.reason,
        }


class CompletenessTrackerService:
    """Evaluates methodology rows for requestable missing values."""

    def __init__(
        self,
        methodology_registry: MethodologyRegistryService,
        condition_evaluator: ConditionEvaluator | None = None,
    ) -> None:
        self._registry = methodology_registry
        self._condition_evaluator = condition_evaluator or ConditionEvaluator()

    def evaluate(
        self,
        *,
        engagement_id: str,
        methodology_values: list[dict],
        runtime_condition_values: dict[str, object] | None = None,
        requirement_level: str = "Core",
    ) -> dict:
        if not engagement_id or not engagement_id.strip():
            raise ValueError("engagement_id is required.")
        values_by_field = self._index_values(methodology_values)
        condition_values = runtime_condition_values or {}
        results = [
            self._evaluate_row(row, values_by_field, condition_values)
            for row in self._registry.list_required_rows(requirement_level)
        ]
        status_counts = Counter(result.status for result in results)
        return {
            "engagement_id": engagement_id,
            "status_counts": dict(sorted(status_counts.items())),
            "results": [result.to_dict() for result in results],
        }

    def _evaluate_row(
        self,
        row: MethodologySchemaRow,
        values_by_field: dict[str, list[dict]],
        condition_values: dict[str, object],
    ) -> CompletenessRowResult:
        condition_status = None
        if row.condition:
            condition_result = self._condition_evaluator.evaluate(
                row.condition,
                condition_values,
            )
            condition_status = condition_result.status
            if condition_result.status == "not_applicable":
                return _row_result(
                    row,
                    status="not_applicable",
                    condition_status=condition_status,
                    reason="condition evaluated false",
                )
            if condition_result.status in {"unknown", "unsupported_condition"}:
                return _row_result(
                    row,
                    status="provisional_condition_unknown",
                    condition_status=condition_status,
                    reason=condition_result.reason,
                )

        value_origin = (row.value_origin or "").casefold()
        matching_values = values_by_field.get(row.field_id, [])
        if matching_values:
            return _row_result(
                row,
                status="complete",
                condition_status=condition_status,
                methodology_value_ids=tuple(
                    str(value["methodology_value_id"]) for value in matching_values
                ),
            )
        if value_origin in REQUESTABLE_VALUE_ORIGINS:
            return _row_result(
                row,
                status="missing_required",
                condition_status=condition_status,
                reason="required extracted methodology value is missing",
            )
        return _row_result(
            row,
            status="not_requestable_value_origin",
            condition_status=condition_status,
            reason=f"value_origin '{row.value_origin}' is not requestable evidence",
        )

    @staticmethod
    def _index_values(methodology_values: list[dict]) -> dict[str, list[dict]]:
        indexed: defaultdict[str, list[dict]] = defaultdict(list)
        for value in methodology_values:
            field_id = value.get("methodology_field_id")
            value_id = value.get("methodology_value_id")
            if field_id and value_id and _has_populated_value(value.get("approved_value")):
                indexed[str(field_id)].append(value)
        return indexed


def _row_result(
    row: MethodologySchemaRow,
    *,
    status: CompletenessStatus,
    condition_status: str | None,
    methodology_value_ids: tuple[str, ...] = (),
    reason: str | None = None,
) -> CompletenessRowResult:
    return CompletenessRowResult(
        field_id=row.field_id,
        layer=row.layer,
        value_origin=row.value_origin,
        requirement_level=row.requirement_level,
        condition=row.condition,
        condition_status=condition_status,
        status=status,
        methodology_value_ids=methodology_value_ids,
        reason=reason,
    )


def _has_populated_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True
