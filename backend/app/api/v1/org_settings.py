"""Organization settings at /api/v1/orgs/{org_id}/settings (org_admin for their own org, provider_admin for any).

``read_summary_documents_automatically`` (default on): whether Sustentra's AI reads a company summary
document (Block 1) by itself when it finishes reading. Another org's id -> 404.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from ...services.audit_log import write_audit_event
from .deps import Principal, require_org_admin

router = APIRouter(prefix="/orgs/{org_id}/settings", tags=["org-settings"])

Admin = Annotated[Principal, Depends(require_org_admin)]
Db = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


class OrgSettings(BaseModel):
    read_summary_documents_automatically: bool


class UpdateOrgSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_summary_documents_automatically: bool


def _oid(org_id: str) -> UUID:
    try:
        return UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Organization not found") from None


@router.get("", response_model=OrgSettings)
async def get_org_settings(org_id: str, principal: Admin, db: Db) -> OrgSettings:
    value = (await db.execute(text("SELECT auto_read_summaries FROM organizations WHERE id = :id"),
                              {"id": _oid(org_id)})).scalar()
    if value is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrgSettings(read_summary_documents_automatically=bool(value))


@router.patch("", response_model=OrgSettings)
async def update_org_settings(org_id: str, body: UpdateOrgSettings, request: Request, principal: Admin,
                              db: Db) -> OrgSettings:
    oid = _oid(org_id)
    result = await db.execute(
        text("UPDATE organizations SET auto_read_summaries = :v, updated_at = now() WHERE id = :id"),
        {"v": body.read_summary_documents_automatically, "id": oid})
    if not getattr(result, "rowcount", 0):
        raise HTTPException(status_code=404, detail="Organization not found")
    await write_audit_event(
        db, "org_settings_updated", org_id=oid, actor_user_id=principal.id, actor_role=principal.role,
        target_type="organization", target_id=str(oid), request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"),
        metadata={"read_summary_documents_automatically": body.read_summary_documents_automatically})
    return OrgSettings(read_summary_documents_automatically=body.read_summary_documents_automatically)
