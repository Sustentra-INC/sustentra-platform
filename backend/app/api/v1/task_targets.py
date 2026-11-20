"""What a task is about, as the client names it, and the in-app link the server builds from it.

The client never sends a link. It names a target: an engagement plus a kind (document, line,
methodology_row, engagement) and the item's id. The server checks that the item exists in that
engagement of the caller's org, then builds the workpaper address (`/?view=...&e=...`, the same
addresses the workpaper itself uses) from the checked values. So a task link can only ever point at
a real screen of the caller's own organisation.

No `from __future__ import annotations`: imported by FastAPI route modules.
"""

from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.api import evidence_tree as evidence_tree_api
from backend.app.api.engagements import _visible
from backend.app.api.s1_access import can_see
from backend.app.core.auth import CurrentUser
from backend.app.services import calculation_lines as cl
from backend.app.services import methodology_review

TargetKind = Literal["document", "line", "methodology_row", "engagement"]

_NOT_FOUND = HTTPException(status_code=422, detail="That item does not exist in this engagement")


def _address(view: str, engagement_id: str, **extra: str) -> str:
    return "/?" + urlencode({"view": view, "e": engagement_id, **extra})


async def resolve_link(db: AsyncSession, user: CurrentUser, engagement_id: str, kind: TargetKind,
                       item_id: str | None) -> str:
    """The in-app path for a checked target, or 422 when the item is not in this engagement."""
    try:
        engagement: dict[str, Any] = await _visible(db, engagement_id, user)
    except HTTPException:
        raise _NOT_FOUND from None
    eid = str(engagement["id"])
    if kind == "engagement":
        return _address("dashboard", eid)
    if not item_id:
        raise _NOT_FOUND
    if kind == "document":
        record = documents_api.current_upload_service().get_document(item_id)
        if not can_see(record, user) or record is None or str(record.get("engagement_id")) != eid:
            raise _NOT_FOUND
        return _address("review", eid, doc=item_id)
    if kind == "line":
        def visible(record: dict[str, Any]) -> bool:
            return can_see(record, user)

        decisions = await evidence_tree_api.document_decisions(db, engagement)
        known = evidence_tree_api.system_line_keys(engagement, visible, decisions)
        known |= {line.key for line in cl.user_lines(engagement.get("settings"))}
        if item_id not in known:
            raise _NOT_FOUND
        return _address("schedule", eid, line=item_id)
    if methodology_review.catalog_field(item_id) is None and methodology_review.row_field(item_id) is None:
        raise _NOT_FOUND
    return _address("methodology", eid, row=item_id)
