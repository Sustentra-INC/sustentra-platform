"""The verifier's work on an engagement, saved: evidence requests, findings and
examination states (migration 0012). Before this they lived only in the browser.

* GET  /v1/engagements/{id}/workpaper-items[?kind=ask]      list (s1_reader)
* PUT  /v1/engagements/{id}/workpaper-items/{kind}/{key}    create or replace (s1_writer)

The payload is the frontend's own object (an Ask, a Finding, an Examination); the API
checks its shape and size, not its fields, so the screens can evolve without a
migration. Another org's engagement answers 404, like every S1 route.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.engagements import _visible, require_open_engagement
from backend.app.api.s1_access import s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import workpaper_item_service
from backend.app.services.audit_log import write_audit_event

router = APIRouter(prefix="/v1", tags=["workpaper"])

Kind = Literal["ask", "finding", "examination", "document"]
MAX_PAYLOAD_BYTES = 32 * 1024
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._\-]{0,199}$")


class WorkpaperItemSave(BaseModel):
    payload: dict[str, Any]

    @field_validator("payload")
    @classmethod
    def _small_enough(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"must be at most {MAX_PAYLOAD_BYTES // 1024} KB")
        return value


class WorkpaperItem(BaseModel):
    kind: str
    item_key: str
    payload: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime
    updated_by: uuid.UUID | None
    updated_at: datetime


class WorkpaperItemList(BaseModel):
    items: list[WorkpaperItem]


@router.get("/engagements/{engagement_id}/workpaper-items", response_model=WorkpaperItemList)
async def list_workpaper_items(
    engagement_id: str,
    kind: Kind | None = Query(None),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> WorkpaperItemList:
    engagement = await _visible(db, engagement_id, user)
    rows = await workpaper_item_service.list_items(db, engagement["id"], kind)
    return WorkpaperItemList(items=[WorkpaperItem(**row) for row in rows])


@router.put("/engagements/{engagement_id}/workpaper-items/{kind}/{item_key}", response_model=WorkpaperItem)
async def save_workpaper_item(
    kind: Kind,
    item_key: str,
    body: WorkpaperItemSave,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> WorkpaperItem:
    if not _KEY.match(item_key):
        raise HTTPException(status_code=422, detail="item_key: letters, digits and : . _ - only (max 200).")
    assert user.org_id is not None  # s1_writer excludes provider_admin
    row = await workpaper_item_service.save_item(
        db,
        org_id=engagement["org_id"],
        engagement_id=engagement["id"],
        kind=kind,
        item_key=item_key,
        payload=body.payload,
        user_id=user.id,
    )
    await write_audit_event(
        db,
        "workpaper_item_saved",
        org_id=engagement["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"kind": kind, "item_key": item_key},  # never the payload
    )
    return WorkpaperItem(**row)
