from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ApprovedEvidenceReviewStatus = Literal[
    "in_review",
    "partially_approved",
    "approved",
    "no_approved_fields",
]

ApprovedEvidenceFieldDecision = Literal["accepted", "edited"]


class ApprovedEvidenceField(BaseModel):
    """Downstream source-of-truth field derived from review decisions."""

    field_name: str
    display_label: str
    extracted_value: str | float | int | bool | None = None
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None
    decision: ApprovedEvidenceFieldDecision
    source_reference: dict[str, Any]
    review_decision_id: str
    candidate_id: str
    reviewer_id: str
    reviewed_at: str
    confidence: float | None = None
    validation_flags: list[str] = Field(default_factory=list)


class ApprovedEvidence(BaseModel):
    """Approved evidence aggregate projected from latest review decisions."""

    approved_evidence_id: str
    evidence_id: str
    engagement_id: str
    document_id: str
    evidence_type: str
    review_status: ApprovedEvidenceReviewStatus
    field_count: int = Field(ge=0)
    approved_field_count: int = Field(ge=0)
    fields: list[ApprovedEvidenceField]
    created_at: str
    source_review_decision_ids: list[str]
