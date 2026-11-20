"""Member directory at /api/v1/orgs/{org_id}/members: who is in this company, for the Setup team picker.

Any signed-in user of the org (another org's id -> 404; provider admins may read any org). Deliberately
small: id, name, email, status (active | invited), never roles, logins or other orgs' people.
Managing members stays in /users and /invites (org admin only).

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.db import get_db_session
from .deps import Principal, require_org_member

router = APIRouter(prefix="/orgs/{org_id}/members", tags=["org-members"])

Member = Annotated[Principal, Depends(require_org_member)]
Db = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


class MemberResponse(BaseModel):
    id: UUID
    email: str
    name: str
    status: str


class MemberListResponse(BaseModel):
    org_name: str
    items: list[MemberResponse]


@router.get("", response_model=MemberListResponse)
async def list_members(
    org_id: str, principal: Member, db: Db, q: Annotated[str, Query(max_length=100)] = ""
) -> MemberListResponse:
    try:
        oid = UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Organization not found") from None
    org_name = (await db.execute(text("SELECT name FROM organizations WHERE id = :id"), {"id": oid})).scalar()
    if org_name is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    pattern = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (await db.execute(
        text("SELECT id, email, status, TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS name "
             "FROM users WHERE org_id = :org_id AND status IN ('active', 'invited') "
             "AND (lower(email) LIKE :p OR lower(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) LIKE :p) "
             "ORDER BY lower(email) LIMIT 200"),
        {"org_id": oid, "p": pattern},
    )).mappings().all()
    return MemberListResponse(org_name=org_name, items=[MemberResponse(**dict(r)) for r in rows])
