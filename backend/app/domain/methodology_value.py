from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

MethodologyValueOrigin = Literal["approved_evidence"]


class MethodologyValue(BaseModel):
    """Engagement-specific methodology field value projected from approved evidence."""

    methodology_value_id: str
    engagement_id: str
    evidence_id: str
    document_id: str
    methodology_field_id: str
    data_schema_field: str
    grain: str | None = None
    record_key: str
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None
    source_reference: dict[str, Any]
    approved_evidence_id: str
    review_decision_id: str
    value_origin: MethodologyValueOrigin = "approved_evidence"
    created_at: str


class MethodologyValueProjectionResult(BaseModel):
    """Projection result for one approved evidence aggregate."""

    approved_evidence_id: str
    engagement_id: str
    evidence_id: str
    document_id: str
    methodology_value_count: int
    unmapped_fields: list[str]
    methodology_values: list[MethodologyValue]
