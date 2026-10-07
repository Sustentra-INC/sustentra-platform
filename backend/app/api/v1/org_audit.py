"""COMP-002 - an org's audit log, at /api/v1/orgs/{org_id}/audit-logs.

org_admin for their own org (another org's id -> 404), provider_admin for any org,
org_member -> 403. Cursor pagination; rules in services/audit_query.py.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from ...services import audit_query
from .deps import Principal, require_org_admin

router = APIRouter(prefix="/orgs/{org_id}/audit-logs", tags=["org-audit"])


class AuditEventResponse(BaseModel):
    id: UUID
    event_type: str
    created_at: datetime
    actor_user_id: UUID | None
    actor_role: str | None
    actor: str | None
    target_type: str | None
    target_id: str | None
    target: str | None
    metadata: dict[str, Any]


class AuditPageResponse(BaseModel):
    items: list[AuditEventResponse]
    # Pass back as ?cursor= (with the same filters) for the next page; null on the last page.
    next_cursor: str | None


@router.get("", response_model=AuditPageResponse)
async def list_audit_logs(
    org_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    event_type: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z][a-z0-9_]{1,63}$")] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    from_date: Annotated[date | None, Query(description="inclusive, UTC")] = None,
    to_date: Annotated[date | None, Query(description="inclusive, UTC")] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=audit_query.MAX_LIMIT)] = audit_query.DEFAULT_LIMIT,
) -> AuditPageResponse:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must not be after to_date")
    items, next_cursor = await audit_query.list_events(
        db, org_id, event_type=event_type, user_id=user_id, from_date=from_date, to_date=to_date,
        cursor=cursor, limit=limit,
    )
    return AuditPageResponse(items=[AuditEventResponse(**i) for i in items], next_cursor=next_cursor)
