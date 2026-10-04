"""ORG-001 - organizations (provider admin), mounted at /api/v1/provider/orgs.

SCAFFOLD: routes, schemas, status codes and the provider-admin guard are wired.
The guard (require_provider_admin) answers 501 until AUTH-004; the service bodies
raise NotImplementedError until ORG-001 is implemented. See organization_service
for the acceptance rules and the DB/EMAIL/audit dependencies.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from ...services.organization_service import OrganizationService, get_organization_service
from .deps import Principal, require_provider_admin
from .pagination import PageMeta, PageParams, page_params

router = APIRouter(prefix="/provider/orgs", tags=["provider-orgs"])

# API-level org status. NOTE: not yet a column on `organizations` (migration 0002);
# see organization_service TODO(DB) to add organizations.status + organizations.max_users.
ORG_STATUSES = ("active", "suspended")

SLUG_PATTERN = r"^[a-z0-9-]{3,63}$"


class InitialAdmin(BaseModel):
    """Optional first org_admin seeded when the org is created."""

    email: str
    first_name: str
    last_name: str


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=SLUG_PATTERN, description="3-63 lowercase alphanumeric + hyphen, unique")
    initial_admin: InitialAdmin | None = None


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    max_users: int | None = Field(default=None, ge=1)


class OrgResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    max_users: int | None = None
    user_count: int | None = None
    created_at: datetime
    updated_at: datetime


class OrgListResponse(BaseModel):
    items: list[OrgResponse]
    meta: PageMeta


@router.get("", response_model=OrgListResponse)
async def list_orgs(
    principal: Annotated[Principal, Depends(require_provider_admin)],
    params: Annotated[PageParams, Depends(page_params)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
    search: Annotated[str | None, Query(description="match on name or slug")] = None,
    org_status: Annotated[str | None, Query(alias="status")] = None,
) -> OrgListResponse:
    rows, total = await service.list_orgs(
        search=search, status=org_status, limit=params.page_size, offset=params.offset
    )
    return OrgListResponse(
        items=[OrgResponse(**row) for row in rows],
        meta=PageMeta(page=params.page, page_size=params.page_size, total=total),
    )


@router.post("", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: CreateOrgRequest,
    principal: Annotated[Principal, Depends(require_provider_admin)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrgResponse:
    initial_admin = payload.initial_admin.model_dump() if payload.initial_admin else None
    row = await service.create_org(name=payload.name, slug=payload.slug, initial_admin=initial_admin)
    return OrgResponse(**row)


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: UUID,
    principal: Annotated[Principal, Depends(require_provider_admin)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrgResponse:
    row = await service.get_org(org_id=str(org_id))
    return OrgResponse(**row)


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: UUID,
    payload: UpdateOrgRequest,
    principal: Annotated[Principal, Depends(require_provider_admin)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrgResponse:
    row = await service.update_org(org_id=str(org_id), name=payload.name, max_users=payload.max_users)
    return OrgResponse(**row)


@router.post("/{org_id}/suspend", response_model=OrgResponse)
async def suspend_org(
    org_id: UUID,
    principal: Annotated[Principal, Depends(require_provider_admin)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrgResponse:
    row = await service.suspend_org(org_id=str(org_id))
    return OrgResponse(**row)


@router.post("/{org_id}/activate", response_model=OrgResponse)
async def activate_org(
    org_id: UUID,
    principal: Annotated[Principal, Depends(require_provider_admin)],
    service: Annotated[OrganizationService, Depends(get_organization_service)],
) -> OrgResponse:
    row = await service.activate_org(org_id=str(org_id))
    return OrgResponse(**row)
