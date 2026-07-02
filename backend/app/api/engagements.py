from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["engagements"])


class CreateEngagementRequest(BaseModel):
    engagement_name: str
    created_by: str


@router.post("/engagements")
def create_engagement(payload: CreateEngagementRequest) -> dict[str, str]:
    return {
        "engagement_id": "eng_demo_001",
        "engagement_name": payload.engagement_name,
        "created_by": payload.created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft"
    }


@router.get("/engagements/{engagement_id}")
def get_engagement(engagement_id: str) -> dict[str, str]:
    return {
        "engagement_id": engagement_id,
        "engagement_name": "Pilot Engagement",
        "status": "active"
    }
