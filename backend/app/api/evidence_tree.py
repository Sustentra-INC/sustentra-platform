"""The Evidence page's read routes: the tree of documents filed into calculation lines, and
one line's schedule.

* GET /v1/engagements/{id}/evidence-tree                         (s1_reader)
* GET /v1/engagements/{id}/calculation-lines/{line_key}/schedule (s1_reader)

Where a document is filed is its workpaper item (kind "document") payload: a ``placements``
list of ``{"from", "to"}`` moves applied, in order, to the document's default placement. The
payload is saved whole by PUT /workpaper-items/document/{id}, so a client must merge
``placements`` into the payload it read and keep every other key. Reviewers' own lines live in
the engagement's ``settings.evidenceLines`` (PATCH /engagements/{id}).

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.api import reviews as reviews_api
from backend.app.api.engagements import _visible
from backend.app.api.s1_access import can_see, s1_reader
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import workpaper_item_service
from backend.app.services.evidence_tree_service import EvidenceTreeService

router = APIRouter(prefix="/v1", tags=["evidence-tree"])


def _service() -> EvidenceTreeService:
    return EvidenceTreeService(
        upload_service=documents_api.current_upload_service(),
        pipeline_service=documents_api.current_pipeline_service(),
        review_service=reviews_api.current_service(),
    )


async def document_decisions(db: AsyncSession, engagement: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The reviewer's per-document decisions (facility, disposition, relationships, placements)."""

    return {
        str(item["payload"].get("documentId") or item["item_key"]): item["payload"]
        for item in await workpaper_item_service.list_items(db, engagement["id"], "document")
    }


async def reviewer_names(db: AsyncSession, org_id: uuid.UUID) -> dict[str, str]:
    """Display names of the org's users by login (email, lower case): full name, else first
    and last name. A login with no name here is shown as it is."""

    rows = await db.execute(
        text("""
            SELECT lower(email) AS login,
                   NULLIF(trim(COALESCE(full_name, concat_ws(' ', first_name, last_name))), '') AS name
              FROM users WHERE org_id = :org_id AND status <> 'deleted'
        """),
        {"org_id": org_id},
    )
    return {r["login"]: r["name"] for r in rows.mappings() if r["name"]}


def system_line_keys(engagement: dict[str, Any], visible: Callable[[dict], bool],
                     decisions: dict[str, dict[str, Any]]) -> set[str]:
    """The keys of the lines the system creates for the engagement (never reviewer-made)."""

    return _service().system_line_keys(engagement, visible, decisions)


@router.get("/engagements/{engagement_id}/evidence-tree")
async def get_evidence_tree(
    engagement_id: str,
    facility_id: str | None = Query(None, max_length=200, description="show only this Setup facility"),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    decisions = await document_decisions(db, engagement)
    return _service().tree(engagement, lambda record: can_see(record, user), decisions, facility_id)


@router.get("/engagements/{engagement_id}/calculation-lines/{line_key}/schedule")
async def get_line_schedule(
    engagement_id: str,
    line_key: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    decisions = await document_decisions(db, engagement)
    names = await reviewer_names(db, engagement["org_id"])
    schedule = _service().schedule(
        engagement, lambda record: can_see(record, user), line_key, decisions,
        name_of=lambda login: names.get(str(login).lower(), str(login)),
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="This calculation line does not exist in this engagement.")
    return schedule
