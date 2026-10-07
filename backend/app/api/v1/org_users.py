"""ORG-002 - user management within an org, at /api/v1/orgs/{org_id}/users (+ COMP-001 DELETE).

org_admin for their own org (another org's id -> 404), provider_admin for any org,
org_member -> 403, no session -> 401. Business rules live in org_user_service.

The list is flat - {items, total, page, page_size, max_users, seats_used} - which is what the
org-admin UI (frontend/features/admin/orgApi.ts) reads.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from ...domain.tenancy import ASSIGNABLE_ROLES as _ASSIGNABLE_ROLES
from ...domain.tenancy import LISTED_USER_STATUSES
from ...services import org_user_service as users
from .deps import Principal, require_org_admin
from .pagination import PageParams, page_params

router = APIRouter(prefix="/orgs/{org_id}/users", tags=["org-users"])

# Same values as the users table (DB-004, domain.tenancy): no mapping layer.
ASSIGNABLE_ROLES = _ASSIGNABLE_ROLES
USER_STATUSES = LISTED_USER_STATUSES


class UserResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    first_name: str
    last_name: str
    role: str
    status: str
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    max_users: int
    # Seats in use across the whole org (invited + active + suspended), independent of the filters.
    seats_used: int


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["org_admin", "org_member"]


OrgAdmin = Annotated[Principal, Depends(require_org_admin)]
Db = Annotated[AsyncSession, Depends(get_db_session)]


def _actor(principal: Principal, request: Request) -> users.Actor:
    return users.Actor(
        user_id=principal.id,
        role=principal.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    org_id: str,
    principal: OrgAdmin,
    db: Db,
    params: Annotated[PageParams, Depends(page_params)],
    user_status: Annotated[Literal["invited", "active", "suspended"] | None, Query(alias="status")] = None,
    role: Annotated[Literal["org_admin", "org_member"] | None, Query()] = None,
) -> UserListResponse:
    rows, total, seats = await users.list_users(db, org_id, status=user_status, role=role,
                                                    limit=params.page_size, offset=params.offset)
    return UserListResponse(items=[UserResponse(**row) for row in rows], total=total, page=params.page,
                            page_size=params.page_size, **seats)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(org_id: str, user_id: str, principal: OrgAdmin, db: Db) -> UserResponse:
    return UserResponse(**await users.get_user(db, org_id, user_id))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    org_id: str, user_id: str, payload: UpdateUserRequest, principal: OrgAdmin, db: Db, request: Request
) -> UserResponse:
    return UserResponse(**await users.change_role(db, _actor(principal, request), org_id, user_id, payload.role))


@router.post("/{user_id}/suspend", response_model=UserResponse)
async def suspend_user(org_id: str, user_id: str, principal: OrgAdmin, db: Db, request: Request) -> UserResponse:
    return UserResponse(**await users.suspend_user(db, _actor(principal, request), org_id, user_id))


@router.post("/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user(org_id: str, user_id: str, principal: OrgAdmin, db: Db, request: Request) -> UserResponse:
    return UserResponse(**await users.reactivate_user(db, _actor(principal, request), org_id, user_id))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_user(org_id: str, user_id: str, principal: OrgAdmin, db: Db, request: Request) -> Response:
    """COMP-001: erase a user (soft delete + anonymize). 204, then the user is 404 everywhere."""
    await users.delete_user(db, _actor(principal, request), org_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
