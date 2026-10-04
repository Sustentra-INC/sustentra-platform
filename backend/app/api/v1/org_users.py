"""ORG-002 - user management within an org (org admin), at /api/v1/orgs/{org_id}/users.

SCAFFOLD: routes, schemas, status codes and the org-admin guard are wired. The
guard (require_org_admin) answers 501 until AUTH-004; the service bodies raise
NotImplementedError until ORG-002 is implemented. See org_user_service for the
acceptance rules (tenant isolation -> cross-org 404, last-admin 409, status/name
mapping) and the DB/audit dependencies.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...services.org_user_service import OrgUserService, get_org_user_service
from .deps import Principal, require_org_admin
from .pagination import PageMeta, PageParams, page_params

router = APIRouter(prefix="/orgs/{org_id}/users", tags=["org-users"])

ASSIGNABLE_ROLES = ("org_admin", "org_member")
# API-level status. The users table stores 'active'|'disabled' (migration 0002);
# the service maps suspend -> 'disabled', reactivate -> 'active'.
USER_STATUSES = ("active", "suspended")


class UserResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    # The DB stores a single `full_name`; the service splits/maps to these (see ORG-003).
    first_name: str | None = None
    last_name: str | None = None
    role: str
    status: str
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    meta: PageMeta


class UpdateUserRequest(BaseModel):
    role: Literal["org_admin", "org_member"]


@router.get("", response_model=UserListResponse)
async def list_users(
    org_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    params: Annotated[PageParams, Depends(page_params)],
    service: Annotated[OrgUserService, Depends(get_org_user_service)],
    user_status: Annotated[str | None, Query(alias="status")] = None,
    role: Annotated[str | None, Query()] = None,
) -> UserListResponse:
    rows, total = await service.list_users(
        org_id=org_id, status=user_status, role=role, limit=params.page_size, offset=params.offset
    )
    return UserListResponse(
        items=[UserResponse(**row) for row in rows],
        meta=PageMeta(page=params.page, page_size=params.page_size, total=total),
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    org_id: str,
    user_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[OrgUserService, Depends(get_org_user_service)],
) -> UserResponse:
    row = await service.get_user(org_id=org_id, user_id=user_id)
    return UserResponse(**row)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    org_id: str,
    user_id: str,
    payload: UpdateUserRequest,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[OrgUserService, Depends(get_org_user_service)],
) -> UserResponse:
    row = await service.change_role(org_id=org_id, user_id=user_id, role=payload.role)
    return UserResponse(**row)


@router.post("/{user_id}/suspend", response_model=UserResponse)
async def suspend_user(
    org_id: str,
    user_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[OrgUserService, Depends(get_org_user_service)],
) -> UserResponse:
    row = await service.suspend_user(org_id=org_id, user_id=user_id)
    return UserResponse(**row)


@router.post("/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user(
    org_id: str,
    user_id: str,
    principal: Annotated[Principal, Depends(require_org_admin)],
    service: Annotated[OrgUserService, Depends(get_org_user_service)],
) -> UserResponse:
    row = await service.reactivate_user(org_id=org_id, user_id=user_id)
    return UserResponse(**row)
