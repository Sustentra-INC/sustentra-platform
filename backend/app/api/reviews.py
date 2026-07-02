from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["reviews"])


class ReviewDecisionRequest(BaseModel):
    candidate_id: str
    decision: str
    approved_value: str | float | int | bool | None = None
    approved_unit: str | None = None
    reviewer_note: str | None = None
    reviewed_by: str


@router.put("/evidence/{evidence_id}/fields/{field_name}/review")
def review_field(
    evidence_id: str,
    field_name: str,
    payload: ReviewDecisionRequest
) -> dict[str, str | float | int | bool | None]:
    return {
        "review_decision_id": "rev_demo_001",
        "candidate_id": payload.candidate_id,
        "evidence_id": evidence_id,
        "field_name": field_name,
        "decision": payload.decision,
        "approved_value": payload.approved_value,
        "approved_unit": payload.approved_unit,
        "reviewer_note": payload.reviewer_note,
        "reviewed_by": payload.reviewed_by,
        "reviewed_at": datetime.now(timezone.utc).isoformat()
    }
