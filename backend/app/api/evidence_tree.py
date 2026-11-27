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
from backend.app.services import calc_line_review, evidence_cache, methodology_gwp  # noqa: F401 - the modules the recalculation reads the decisions and the GWP choice from
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


async def creator_names(db: AsyncSession, org_id: uuid.UUID) -> dict[str, str]:
    """Display name by user id, for "Added by ..." on a reviewer's line: full name, else first and last
    name, else the login. A deleted user keeps their row, so they are still named (by login when they
    have no name)."""

    rows = await db.execute(
        text("""
            SELECT id::text AS user_id,
                   COALESCE(NULLIF(trim(COALESCE(full_name, concat_ws(' ', first_name, last_name))), ''), email)
                       AS name
              FROM users WHERE org_id = :org_id
        """),
        {"org_id": org_id},
    )
    return {r["user_id"]: r["name"] for r in rows.mappings() if r["name"]}


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


async def loaded_for(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser, service: EvidenceTreeService,
                     stamp: str | None) -> tuple[Any, dict[str, dict[str, Any]]]:
    """The engagement's loaded documents and lines with the reviewers' document decisions: kept per organization
    and engagement while nothing they are built from has changed (``services/evidence_cache.py``), else read in
    bulk and worked out again."""

    key = (evidence_cache.scope_of(user), str(engagement["id"]))
    found = evidence_cache.LOADED.get(key, stamp)
    if found is not None:
        return found
    decisions = await document_decisions(db, engagement)
    loaded = service.load(engagement, lambda record: can_see(record, user), decisions)
    # Kept only when nothing changed while it was read: the stamp taken again must be the one taken before.
    if stamp is not None and await service.cache_stamp(db, engagement, fresh=True) == stamp:
        size = 600 * sum(len(r.fields) for d in loaded.docs for r in d.records)  # a rough size of the records
        evidence_cache.LOADED.put(key, stamp, (loaded, decisions), size)
    return loaded, decisions


async def recalculation_for(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
    """The engagement's recalculation: the very one Results answers (``run_recalculation``, kept while nothing it is
    built from has changed), so the schedule, Results and the Excel workpaper agree."""

    from backend.app.api import recalculation as recalculation_api

    return await recalculation_api.run_recalculation(db, engagement, user)


@router.get("/engagements/{engagement_id}/evidence-tree")
async def get_evidence_tree(
    engagement_id: str,
    facility_id: str | None = Query(None, max_length=200, description="show only this Setup facility"),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    service = _service()
    stamp = await service.cache_stamp(db, engagement)  # before any read: a change in between is caught next time
    loaded, decisions = await loaded_for(db, engagement, user, service, stamp)
    names = await creator_names(db, engagement["org_id"])
    return service.tree(engagement, lambda record: can_see(record, user), decisions, facility_id, names,
                        loaded=loaded)


@router.get("/engagements/{engagement_id}/calculation-lines/{line_key}/schedule")
async def get_line_schedule(
    engagement_id: str,
    line_key: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    service = _service()
    stamp = await service.cache_stamp(db, engagement)
    loaded, decisions = await loaded_for(db, engagement, user, service, stamp)
    names = await reviewer_names(db, engagement["org_id"])
    # the schedule runs the recalculation: kept, not run again for every line and every visit
    recalculation = await recalculation_for(db, engagement, user)
    schedule = service.schedule(
        engagement, lambda record: can_see(record, user), line_key, decisions,
        name_of=lambda login: names.get(str(login).lower(), str(login)), loaded=loaded, recalculation=recalculation,
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="This calculation line does not exist in this engagement.")
    return schedule
