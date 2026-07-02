from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["assistant"])


class AssistantRequest(BaseModel):
    engagement_id: str
    message: str


@router.post("/assistant/chat")
def assistant_chat(payload: AssistantRequest) -> dict[str, str]:
    return {
        "engagement_id": payload.engagement_id,
        "answer": "Assistant integration is a placeholder in this skeleton."
    }
