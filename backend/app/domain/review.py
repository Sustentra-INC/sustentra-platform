from pydantic import BaseModel


class ReviewDecision(BaseModel):
    """Reviewer decision record for one evidence field candidate."""

    review_decision_id: str
    candidate_id: str
    evidence_id: str
    field_name: str
    decision: str
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None
    reviewer_note: str | None = None
    reviewed_by: str
    reviewed_at: str
