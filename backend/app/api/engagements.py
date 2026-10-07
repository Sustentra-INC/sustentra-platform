"""S1-BE-002 - workpaper engagements, stored in Postgres (migration 0008, RLS).

* org_admin / org_member: list, create, read and update their own org's engagements;
* provider_admin: reads every org's (support) and gets 403 on writes;
* another org's engagement answers 404, like the other S1 routes (SEC-001).

``settings`` carries the rest of the Setup screen (facilities, regulation,
assurance, contacts ...) using the frontend's field names; only known keys are
accepted. Engagements are archived (``status``), never deleted.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

import json
import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.s1_access import s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import engagement_service
from backend.app.services.audit_log import write_audit_event

router = APIRouter(prefix="/v1", tags=["engagements"])

# Setup-screen fields kept in `settings` (frontend EngagementConfig names).
SETTINGS_KEYS = frozenset(
    {
        "facilities",
        "regulation",
        "regulationJurisdiction",
        "conclusionType",
        "assuranceLevel",
        "boundaryApproach",
        "scopeBoundaryStatement",
        "methodology",
        "clientContact",
        "engagementTeam",
        "verifierEmail",
        "dataScope",
        "assuranceStandard",
        "materialityThreshold",
    }
)
MAX_SETTINGS_BYTES = 64 * 1024
_NOT_FOUND = HTTPException(status_code=404, detail="Engagement not found.")


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _check_settings(value: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(value) - SETTINGS_KEYS)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(unknown)}")
    if len(json.dumps(value)) > MAX_SETTINGS_BYTES:
        raise ValueError("settings are too large")
    return value


def _check_period(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValueError("reporting_period_end must not be before reporting_period_start")


class EngagementCreate(BaseModel):
    name: str = Field(max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    settings: dict[str, Any] = Field(default_factory=dict)

    _name = field_validator("name")(_clean_name)
    _settings = field_validator("settings")(_check_settings)

    @model_validator(mode="after")
    def _period(self) -> "EngagementCreate":
        _check_period(self.reporting_period_start, self.reporting_period_end)
        return self


class EngagementUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    client_name: str | None = Field(default=None, max_length=200)
    reporting_period_start: date | None = None
    reporting_period_end: date | None = None
    status: Literal["active", "archived"] | None = None
    settings: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must not be null")
        return _clean_name(value)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must not be null")
        return value

    @field_validator("settings")
    @classmethod
    def _settings(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            raise ValueError("must not be null")
        return _check_settings(value)


class EngagementResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    client_name: str | None
    reporting_period_start: date | None
    reporting_period_end: date | None
    status: str
    settings: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class EngagementListResponse(BaseModel):
    items: list[EngagementResponse]


async def _audit(db: AsyncSession, request: Request, user: CurrentUser, event: str, row: dict, fields: list[str]) -> None:
    await write_audit_event(
        db,
        event,
        org_id=row["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(row["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"fields": fields},  # names only, never values
    )


async def _visible(db: AsyncSession, engagement_id: str, user: CurrentUser) -> dict[str, Any]:
    row = await engagement_service.get_engagement(db, engagement_id)
    # RLS already hides other orgs' rows; the check below is the belt to its braces.
    if row is None or (not user.is_provider and str(row["org_id"]) != str(user.org_id)):
        raise _NOT_FOUND
    return row


async def require_open_engagement(
    engagement_id: str,
    user: CurrentUser = Depends(s1_writer),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Dependency for routes that add documents to an engagement: it must exist in the
    caller's org (404 otherwise, like every cross-org S1 lookup) and be active (409)."""

    row = await _visible(db, engagement_id, user)
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail="Engagement is archived.")
    return row


@router.get("/engagements", response_model=EngagementListResponse)
async def list_engagements(
    include_archived: bool = Query(False),
    org_id: uuid.UUID | None = Query(None, description="provider_admin only: one org's engagements"),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session),
) -> EngagementListResponse:
    scope = org_id if user.is_provider else user.org_id
    rows = await engagement_service.list_engagements(db, include_archived=include_archived, org_id=scope)
    return EngagementListResponse(items=[EngagementResponse(**row) for row in rows])


@router.post("/engagements", response_model=EngagementResponse, status_code=201)
async def create_engagement(
    payload: EngagementCreate,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    db: AsyncSession = Depends(get_db_session),
) -> EngagementResponse:
    assert user.org_id is not None  # s1_writer excludes provider_admin
    row = await engagement_service.create_engagement(
        db,
        org_id=user.org_id,
        created_by=user.id,
        name=payload.name,
        client_name=payload.client_name,
        reporting_period_start=payload.reporting_period_start,
        reporting_period_end=payload.reporting_period_end,
        settings=payload.settings,
    )
    await _audit(db, request, user, "engagement_created", row, sorted(payload.model_fields_set))
    return EngagementResponse(**row)


@router.get("/engagements/{engagement_id}", response_model=EngagementResponse)
async def get_engagement(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session),
) -> EngagementResponse:
    return EngagementResponse(**await _visible(db, engagement_id, user))


@router.patch("/engagements/{engagement_id}", response_model=EngagementResponse)
async def update_engagement(
    engagement_id: str,
    payload: EngagementUpdate,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    db: AsyncSession = Depends(get_db_session),
) -> EngagementResponse:
    current = await _visible(db, engagement_id, user)
    changes = payload.model_dump(exclude_unset=True)
    start = changes.get("reporting_period_start", current["reporting_period_start"])
    end = changes.get("reporting_period_end", current["reporting_period_end"])
    try:
        _check_period(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not changes:
        return EngagementResponse(**current)
    row = await engagement_service.update_engagement(db, current["id"], changes)
    event = "engagement_archived" if changes.get("status") == "archived" else "engagement_updated"
    await _audit(db, request, user, event, row, sorted(changes))
    return EngagementResponse(**row)
