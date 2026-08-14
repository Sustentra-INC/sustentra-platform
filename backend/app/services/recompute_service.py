"""Recompute engine v0 for Subsystem 2 PR12."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RecomputeStatus = Literal[
    "matched",
    "mismatch",
    "missing_input",
    "unsupported",
]


@dataclass(frozen=True)
class RecomputeResult:
    calculation_path: str
    status: RecomputeStatus
    computed_value: float | None
    reported_value: float | None
    delta: float | None
    unit: str | None
    input_methodology_value_ids: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "calculation_path": self.calculation_path,
            "status": self.status,
            "computed_value": self.computed_value,
            "reported_value": self.reported_value,
            "delta": self.delta,
            "unit": self.unit,
            "input_methodology_value_ids": list(self.input_methodology_value_ids),
            "reason": self.reason,
        }


class RecomputeService:
    """Runs one narrow v0 recomputation path."""

    STATIONARY_FUEL_PATH = "scope1_stationary_combustion_fuel_based"

    def recompute_stationary_fuel_emissions(
        self,
        *,
        fuel_quantity: dict | None,
        emission_factor: dict | None,
        reported_emissions: dict | None,
    ) -> dict:
        missing = [
            name
            for name, value in (
                ("fuel_quantity", fuel_quantity),
                ("emission_factor", emission_factor),
                ("reported_emissions", reported_emissions),
            )
            if value is None
        ]
        if missing:
            return RecomputeResult(
                calculation_path=self.STATIONARY_FUEL_PATH,
                status="missing_input",
                computed_value=None,
                reported_value=None,
                delta=None,
                unit=None,
                input_methodology_value_ids=(),
                reason=f"missing input(s): {missing}",
            ).to_dict()

        quantity = _number(fuel_quantity.get("approved_value"))  # type: ignore[union-attr]
        factor = _number(emission_factor.get("approved_value"))  # type: ignore[union-attr]
        reported = _number(reported_emissions.get("approved_value"))  # type: ignore[union-attr]
        if quantity is None or factor is None or reported is None:
            return RecomputeResult(
                calculation_path=self.STATIONARY_FUEL_PATH,
                status="unsupported",
                computed_value=None,
                reported_value=reported,
                delta=None,
                unit=reported_emissions.get("approved_unit"),  # type: ignore[union-attr]
                input_methodology_value_ids=_ids(
                    fuel_quantity,
                    emission_factor,
                    reported_emissions,
                ),
                reason="v0 recompute requires numeric quantity, factor, and reported emissions",
            ).to_dict()

        computed = quantity * factor
        delta = reported - computed
        return RecomputeResult(
            calculation_path=self.STATIONARY_FUEL_PATH,
            status="matched" if delta == 0 else "mismatch",
            computed_value=computed,
            reported_value=reported,
            delta=delta,
            unit=reported_emissions.get("approved_unit"),  # type: ignore[union-attr]
            input_methodology_value_ids=_ids(
                fuel_quantity,
                emission_factor,
                reported_emissions,
            ),
            reason="fuel_quantity * emission_factor compared to reported emissions",
        ).to_dict()


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _ids(*values: dict | None) -> tuple[str, ...]:
    return tuple(
        str(value["methodology_value_id"])
        for value in values
        if value and value.get("methodology_value_id")
    )
