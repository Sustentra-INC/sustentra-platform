"""The in-app assistant's read-only view of the Methodology review (GET only).

Same access as the review page: a signed-in reader of the engagement's own organization (a request for another
organization's engagement is a 404, like every cross-org S1 lookup). Nothing is written, no model is called and the
model id is never returned: the answers are the stored records' explanations (services/methodology_assistant.py).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.engagements import _visible
from backend.app.api.s1_access import s1_reader
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import methodology_assistant as assistant
from backend.app.services import workpaper_item_service
from backend.app.services.methodology_review import KIND

router = APIRouter(prefix="/v1", tags=["methodology-assistant"])


async def _records(db: AsyncSession, engagement_id: str, user: CurrentUser) -> dict[str, dict[str, Any]]:
    engagement = await _visible(db, engagement_id, user)
    return {row["item_key"]: row["payload"] for row in await workpaper_item_service.list_items(db, engagement["id"], KIND)}


@router.get("/engagements/{engagement_id}/methodology-assistant/explain", response_model=dict[str, Any])
async def explain_suggestion(
    engagement_id: str,
    q: str = Query("", max_length=300),
    field_id: str = Query("", max_length=100),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Why Sustentra's AI suggested what the question names (a field id, or words from its name or value)."""

    return assistant.explain_matches(await _records(db, engagement_id, user), q, field_id)


@router.get("/engagements/{engagement_id}/methodology-assistant/summary", response_model=dict[str, Any])
async def suggestions_summary(
    engagement_id: str,
    document: str = Query("", max_length=200),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """What Sustentra's AI found on the Methodology page, optionally only from documents named like ``document``."""

    return assistant.summary(await _records(db, engagement_id, user), document)
