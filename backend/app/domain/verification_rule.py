from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeVerificationRule:
    """Typed runtime verification rule loaded from methodology workbooks."""

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
    is_provisional: bool
    resolvable_applies_to: tuple[str, ...]
    unresolved_applies_to: tuple[str, ...]
    source_workbook: str
    source_sheet: str
    source_row_number: int
