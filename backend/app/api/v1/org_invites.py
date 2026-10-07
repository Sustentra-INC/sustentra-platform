"""ORG-003 - invites (org admin), at /api/v1/orgs/{org_id}/invites.

org_admin for their own org (another org's id -> 404), provider_admin for any org,
org_member -> 403. The public counterpart (validate / accept) lives in
api/v1/auth.py. Rules: services/invite_service.py.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from ...services import invite_service as invites
from ...services.otp_delivery import InviteSender, get_invite_sender
from .deps import Principal, require_org_admin

router = APIRouter(prefix="/orgs/{org_id}/invites", tags=["org-invites"])

# Deliberately simple (no email-validator dependency): one @, no spaces, a dot in the domain.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    role: Literal["org_admin", "org_member"]
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL.match(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class InviteResponse(BaseModel):
    # `id` and `user_id` are the same: the invited user (their seat is reserved up-front).
    id: UUID
    user_id: UUID
    org_id: UUID
    email: str
    first_name: str
    last_name: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


OrgAdmin = Annotated[Principal, Depends(require_org_admin)]
Db = Annotated[AsyncSession, Depends(get_db_session)]
Sender = Annotated[InviteSender, Depends(get_invite_sender)]


def _actor(principal: Principal, request: Request) -> invites.Actor:
    return invites.Actor(
        user_id=principal.id,
        role=principal.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    org_id: str,
    payload: CreateInviteRequest,
    principal: OrgAdmin,
    db: Db,
    request: Request,
    background: BackgroundTasks,
    send_invite: Sender,
) -> InviteResponse:
    row, pending = await invites.create_invite(
        db, _actor(principal, request), org_id, email=payload.email, role=payload.role,
        first_name=payload.first_name, last_name=payload.last_name,
    )
    background.add_task(send_invite, pending.to, pending.link)  # after the response = after commit
    return InviteResponse(**row)


@router.post("/{user_id}/resend", response_model=InviteResponse)
async def resend_invite(
    org_id: str,
    user_id: str,
    principal: OrgAdmin,
    db: Db,
    request: Request,
    background: BackgroundTasks,
    send_invite: Sender,
) -> InviteResponse:
    row, pending = await invites.resend_invite(db, _actor(principal, request), org_id, user_id)
    background.add_task(send_invite, pending.to, pending.link)
    return InviteResponse(**row)
