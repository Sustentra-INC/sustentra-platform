from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["processing-runs"])


class StartProcessingRunRequest(BaseModel):
    engagement_id: str
    pipeline_version: str = "pilot-v1"


@router.post("/documents/{document_id}/processing-runs")
def start_processing_run(document_id: str, payload: StartProcessingRunRequest) -> dict[str, str | None]:
    return {
        "run_id": "run_demo_001",
        "document_id": document_id,
        "engagement_id": payload.engagement_id,
        "status": "in_progress",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "pipeline_version": payload.pipeline_version,
        "error": None
    }


@router.get("/processing-runs/{run_id}")
def get_processing_run(run_id: str) -> dict[str, str | None]:
    return {
        "run_id": run_id,
        "document_id": "doc_demo_001",
        "engagement_id": "eng_demo_001",
        "status": "completed",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": "pilot-v1",
        "error": None
    }
