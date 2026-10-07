from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.api.s1_access import s1_reader
from backend.app.core.auth import CurrentUser

router = APIRouter(prefix="/v1", tags=["assistant"])


class AssistantRequest(BaseModel):
    engagement_id: str
    message: str


@router.post("/assistant/chat")
def assistant_chat(payload: AssistantRequest, user: CurrentUser = Depends(s1_reader)) -> dict[str, str]:
    return {
        "engagement_id": payload.engagement_id,
        "answer": "Assistant integration is a placeholder in this skeleton."
    }
