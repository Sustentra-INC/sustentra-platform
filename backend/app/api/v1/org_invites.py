"""ORG-003 - invite management (org admin), at /api/v1/orgs/{org_id}/invites.

The public counterpart (validate/accept) lives in api/v1/auth.py. SCAFFOLD only:
the org-admin guard answers 501 until AUTH-004 and the service raises
NotImplementedError until ORG-003 is implemented. See invite_service for the
token model (auth_tokens type='invite', SHA-256, 24h TTL) and dependencies.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from ...services.invite_service import InviteService, get_invite_service
from .deps import Principal, require_org_admin

router = APIRouter(prefix="/orgs/{org_id}/invites", tags=["org-invites"])


class CreateInviteRequest(BaseModel):
    email: str
    role: Literal["org_admin", "org_member"]
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)


class InviteResponse(BaseModel):
    # The invited user's id (the seat is reserved up-front in 'invited' state).
    user_id: UUID
    org_id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    org_id: str,
    payload: CreateInviteRequest,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[InviteService, Depends(get_invite_service)],
) -> InviteResponse:
    row = await service.create_invite(
        org_id=org_id,
        email=payload.email,
        role=payload.role,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    return InviteResponse(**row)


@router.post("/{user_id}/resend", response_model=InviteResponse)
async def resend_invite(
    org_id: str,
    user_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[InviteService, Depends(get_invite_service)],
) -> InviteResponse:
    row = await service.resend_invite(org_id=org_id, user_id=user_id)
    return InviteResponse(**row)
