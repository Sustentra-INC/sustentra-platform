from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.repositories.engagement_repository import JsonlEngagementRepository

router = APIRouter(prefix="/v1", tags=["engagements"])

_repository: Any = JsonlEngagementRepository()


def configure_repository(repository: Any) -> None:
    global _repository
    _repository = repository


DEFAULT_S1_ENGAGEMENT = {
    "engagement_id": "ENG-S1-2025",
    "engagement_name": "S1 Local Pipeline",
    "client_name": "SCE Manufacturing",
    "created_by": "system",
    "created_at": "2026-01-01T00:00:00+00:00",
    "status": "active",
    "reporting_period": {"start": "2025-01-01", "end": "2025-12-31"},
    "facilities": [
        {"facility_id": "facility-riverside", "name": "Riverside Plant"},
        {"facility_id": "facility-ontario", "name": "Ontario Plant"},
        {"facility_id": "facility-fresno", "name": "Fresno Plant"},
    ],
    "regulation": "NY Part 253",
    "conclusion_type": "GHG assurance",
    "assurance_level": "Limited assurance",
    "boundary_approach": "Operational control",
    "scope_boundary_statement": (
        "Electricity, stationary combustion, and supporting corporate inventory evidence "
        "for in-scope facilities."
    ),
}


class CreateEngagementRequest(BaseModel):
    engagement_name: str
    created_by: str
    client_name: str = "SCE Manufacturing"
    status: str = "draft"
    reporting_period: dict[str, str] | None = None
    facilities: list[dict[str, str]] | None = None
    regulation: str | None = None
    conclusion_type: str | None = None
    assurance_level: str | None = None
    boundary_approach: str | None = None
    scope_boundary_statement: str | None = None


@router.post("/engagements")
def create_engagement(payload: CreateEngagementRequest) -> dict:
    engagement_id = f"engagement::{payload.engagement_name.strip().lower().replace(' ', '-')}"
    record = {
        "engagement_id": engagement_id,
        "engagement_name": payload.engagement_name,
        "client_name": payload.client_name,
        "created_by": payload.created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": payload.status,
        "reporting_period": payload.reporting_period or {},
        "facilities": payload.facilities or [],
        "regulation": payload.regulation,
        "conclusion_type": payload.conclusion_type,
        "assurance_level": payload.assurance_level,
        "boundary_approach": payload.boundary_approach,
        "scope_boundary_statement": payload.scope_boundary_statement,
    }
    return _repository.save(record)


@router.get("/engagements/{engagement_id}")
def get_engagement(engagement_id: str) -> dict:
    record = _repository.get_by_id(engagement_id)
    if record is None and engagement_id == DEFAULT_S1_ENGAGEMENT["engagement_id"]:
        record = _repository.save(DEFAULT_S1_ENGAGEMENT)
    if record is None:
        raise HTTPException(status_code=404, detail="Engagement not found.")
    return record


@router.get("/engagements")
def list_engagements() -> dict:
    return {"items": _repository.list_all()}
