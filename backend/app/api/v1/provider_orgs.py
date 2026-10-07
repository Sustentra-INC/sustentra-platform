"""ORG-001 - organizations (provider admin), mounted at /api/v1/provider/orgs.

Provider admins only (401 without a session, 403 for org_admin/org_member).
Business rules, audit events and the invite flow live in organization_service.

List responses are flat - {items, total, page, page_size} - which is the shape the
provider-admin UI (frontend/features/admin/providerApi.ts) reads.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from ...domain.tenancy import DEFAULT_MAX_USERS, MAX_MAX_USERS
from ...domain.tenancy import ORG_STATUSES as _ORG_STATUSES
from ...services import organization_service as orgs
from ...services.otp_delivery import InviteSender, get_invite_sender
from .deps import Principal, require_provider_admin
from .pagination import PageParams, page_params

router = APIRouter(prefix="/provider/orgs", tags=["provider-orgs"])

# organizations.status (0005) and organizations.max_users (0009); see domain.tenancy.
ORG_STATUSES = _ORG_STATUSES

SLUG_PATTERN = r"^[a-z0-9-]{3,63}$"
# Deliberately simple (no email-validator dependency): one @, no spaces, a dot in the domain.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _trimmed(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class InitialAdmin(BaseModel):
    """Optional first org_admin, invited when the org is created."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL.match(value):
            raise ValueError("must be a valid email address")
        return value

    _names = field_validator("first_name", "last_name")(_trimmed)


class CreateOrgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=SLUG_PATTERN, description="3-63 lowercase alphanumeric + hyphen, unique, immutable")
    max_users: int | None = Field(default=None, ge=1, le=MAX_MAX_USERS,
                                  description=f"seat limit, default {DEFAULT_MAX_USERS}")
    initial_admin: InitialAdmin | None = None

    _name = field_validator("name")(_trimmed)


class UpdateOrgRequest(BaseModel):
    # extra="forbid": the slug (and status) cannot be changed here.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    max_users: int | None = Field(default=None, ge=1, le=MAX_MAX_USERS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value)


class OrgResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    max_users: int = DEFAULT_MAX_USERS
    user_count: int
    created_at: datetime
    updated_at: datetime


class OrgListResponse(BaseModel):
    items: list[OrgResponse]
    total: int
    page: int
    page_size: int


ProviderAdmin = Annotated[Principal, Depends(require_provider_admin)]
Db = Annotated[AsyncSession, Depends(get_db_session)]


def _actor(principal: Principal, request: Request) -> orgs.Actor:
    return orgs.Actor(
        user_id=principal.id,
        role=principal.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get("", response_model=OrgListResponse)
async def list_orgs(
    principal: ProviderAdmin,
    db: Db,
    params: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=255, description="match on name or slug")] = None,
    org_status: Annotated[Literal["active", "suspended"] | None, Query(alias="status")] = None,
) -> OrgListResponse:
    rows, total = await orgs.list_orgs(db, search=search, status=org_status, limit=params.page_size,
                                       offset=params.offset)
    return OrgListResponse(items=[OrgResponse(**row) for row in rows], total=total, page=params.page,
                           page_size=params.page_size)


@router.post("", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: CreateOrgRequest,
    principal: ProviderAdmin,
    db: Db,
    request: Request,
    background: BackgroundTasks,
    send_invite: Annotated[InviteSender, Depends(get_invite_sender)],
) -> OrgResponse:
    row, pending = await orgs.create_org(
        db, _actor(principal, request), name=payload.name, slug=payload.slug, max_users=payload.max_users,
        initial_admin=payload.initial_admin.model_dump() if payload.initial_admin else None,
    )
    if pending is not None:
        # Runs after the response is sent, i.e. after get_db_session has committed.
        background.add_task(send_invite, pending.to, pending.link)
    return OrgResponse(**row)


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(org_id: UUID, principal: ProviderAdmin, db: Db) -> OrgResponse:
    return OrgResponse(**await orgs.get_org(db, org_id))


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: UUID, payload: UpdateOrgRequest, principal: ProviderAdmin, db: Db, request: Request
) -> OrgResponse:
    row = await orgs.update_org(db, _actor(principal, request), org_id, name=payload.name,
                                max_users=payload.max_users)
    return OrgResponse(**row)


@router.post("/{org_id}/suspend", response_model=OrgResponse)
async def suspend_org(org_id: UUID, principal: ProviderAdmin, db: Db, request: Request) -> OrgResponse:
    return OrgResponse(**await orgs.suspend_org(db, _actor(principal, request), org_id))


@router.post("/{org_id}/activate", response_model=OrgResponse)
async def activate_org(org_id: UUID, principal: ProviderAdmin, db: Db, request: Request) -> OrgResponse:
    return OrgResponse(**await orgs.activate_org(db, _actor(principal, request), org_id))
