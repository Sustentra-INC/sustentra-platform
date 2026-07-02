from pydantic import BaseModel


class ApprovedEvidenceField(BaseModel):
    """Approved field payload retained for downstream consumers."""

    field_name: str
    extracted_value: str | float | int | bool | None = None
    approved_value: str | float | int | bool | None = None
    unit: str | None = None
    decision: str
    source_reference: dict


class ApprovedEvidence(BaseModel):
    """Approved evidence aggregate for an engagement/document pair."""

    evidence_id: str
    engagement_id: str
    document_id: str
    evidence_type: str
    review_status: str
    fields: list[ApprovedEvidenceField]
