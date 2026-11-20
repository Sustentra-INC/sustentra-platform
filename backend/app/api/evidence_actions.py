"""Evidence page changes as server actions, each with an audit event (MVP-139).

* POST   /v1/engagements/{id}/evidence-lines                       add a line
* PATCH  /v1/engagements/{id}/evidence-lines/{line_key}            rename a line
* DELETE /v1/engagements/{id}/evidence-lines/{line_key}            delete a line
* POST   /v1/engagements/{id}/documents/{document_id}/placements   move a document ({from, to})
* POST   /v1/engagements/{id}/documents/{document_id}/facility     place a document on a Setup facility ({facility_id})
* GET    /v1/engagements/{id}/evidence-activity                     what was changed, newest first

Writers only (archived engagement: 409, another org: 404). Every write takes the engagement's
row lock first and reads the engagement again, so two writers run one after the other and neither
loses the other's change. The actor comes from the session. Audit rows hold ids and labels, never
document text. No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import evidence_tree as tree_api
from backend.app.api.engagements import _check_line_anchors, _reject_system_lines, _visible, require_open_engagement
from backend.app.api.s1_access import can_see, s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import audit_query, engagement_service, workpaper_item_service
from backend.app.services import calculation_lines as cl
from backend.app.services.audit_log import write_audit_event
from backend.app.services.ai_facility import FACILITY_TYPES
from backend.app.services.evidence_tree_service import DocState, EvidenceTreeService, Loaded

router = APIRouter(prefix="/v1", tags=["evidence-actions"])

LINE_CREATED = "evidence_line_created"
LINE_RENAMED = "evidence_line_renamed"
LINE_DELETED = "evidence_line_deleted"
DOCUMENT_MOVED = "evidence_document_moved"
FACILITY_SET = "evidence_document_facility_set"
EVENT_TYPES = (LINE_CREATED, LINE_RENAMED, LINE_DELETED, DOCUMENT_MOVED, FACILITY_SET)

BLOCK_NAMES = {
    cl.BLOCK_SUMMARY: "Summary documents and workbook",
    cl.BLOCK_UNASSIGNED: "Unassigned documents",
    cl.SUPPORTING_UNASSIGNED: "Unassigned supporting evidence",
}
STALE_MOVE = "This document was already moved from there. Reload Evidence to see where it is now."


# --- request bodies ---------------------------------------------------------------------
class LineCreate(BaseModel):
    """A new line. The server builds the key and records who added it; a client cannot send either."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=40)
    level2_label: str = Field(max_length=cl.MAX_LABEL)
    anchor_kind: str = Field(max_length=20)
    anchor_id: str | None = Field(default=None, max_length=200)
    label: str = Field(max_length=cl.MAX_LABEL)
    scope: str | None = Field(default=None, max_length=20)


class LineRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=cl.MAX_LABEL)


class PlacementMove(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from", min_length=1, max_length=200)
    to: str = Field(min_length=1, max_length=200)


class FacilityChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: str = Field(min_length=1, max_length=200)
    # The facility the page believes the document is on now (null: none). When sent and it is not what is saved, another
    # reviewer decided meanwhile and nothing is written (409).
    expected_facility_id: str | None = Field(default=None, max_length=200)


# --- shared steps -------------------------------------------------------------------------
async def _locked(db: AsyncSession, engagement_id: str) -> dict[str, Any]:
    """The engagement under its row lock, as it stands now."""

    row = await engagement_service.lock_engagement(db, engagement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Engagement not found.")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail="Engagement is archived.")
    return row


def _stored_lines(engagement: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (engagement.get("settings") or {}).get("evidenceLines")
    return [entry for entry in raw if isinstance(entry, dict)] if isinstance(raw, list) else []


async def _save_lines(db: AsyncSession, engagement: dict[str, Any], lines: list[dict[str, Any]]) -> None:
    settings = {**(engagement.get("settings") or {}), "evidenceLines": lines}
    await engagement_service.update_engagement(db, engagement["id"], {"settings": settings})


async def _audit(db: AsyncSession, request: Request, user: CurrentUser, event: str, engagement: dict[str, Any],
                 metadata: dict[str, Any]) -> None:
    await write_audit_event(
        db, event,
        org_id=engagement["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,  # ids and labels only: never a document's text
    )


async def _load(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser) -> tuple[Loaded, dict[str, dict[str, Any]]]:
    decisions = await tree_api.document_decisions(db, engagement)
    return tree_api._service().load(engagement, lambda record: can_see(record, user), decisions), decisions


def _next_chain(chain: list[Any], move: dict[str, str], doc: DocState, known: set[str]) -> list[Any]:
    """The document's saved moves once ``move`` is added, derived from where the document is filed
    then (``cl.derive_placements``): at most one move per default slot, whatever its history. The
    full chain is kept only when the derived one does not file the document in exactly the same
    places now (a move out of "supporting:unassigned" also matches a placement on a line that is gone,
    and the derived order can't see that) or when no safe order exists."""

    full = [*chain, move]
    filing = cl.apply_placements(doc.default_slots, full, known)
    derived = cl.derive_placements(doc.default_slots, filing)
    if derived is not None and cl.raw_filing(cl.apply_placements(doc.default_slots, derived, known)) == cl.raw_filing(filing):
        full = derived
    if len(full) > cl.MAX_PLACEMENT_MOVES:
        name = doc.document.get("file_name") or doc.document_id
        raise HTTPException(status_code=409, detail=f"{name} has been moved too many times to save another move. "
                                                     "Ask Sustentra support to tidy its history.")
    return full


async def _save_chain(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser, document_id: str,
                      existing: dict[str, Any], chain: list[Any]) -> dict[str, Any]:
    payload = {**existing, "documentId": document_id, "placements": chain}
    if workpaper_item_service.payload_size(payload) > workpaper_item_service.MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=409, detail="This document has too many saved changes to save another move.")
    await workpaper_item_service.save_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind="document", item_key=document_id,
        payload=payload, user_id=user.id)
    return payload


def _place_label(loaded: Loaded, key: str) -> str:
    if key in BLOCK_NAMES:
        return BLOCK_NAMES[key]
    line = next((ln for ln in loaded.lines if ln.key == key), None)
    if line is None:
        return key
    # the same rule as the page's lineTitle: the fuel in front unless the label already names it
    return line.label if line.level2_label.lower() in line.label.lower() else f"{line.level2_label} · {line.label}"


def _answer(lines: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {**extra, "evidenceLines": lines}


# --- lines ----------------------------------------------------------------------------------
@router.post("/engagements/{engagement_id}/evidence-lines", status_code=201)
async def create_line(
    engagement_id: str,
    body: LineCreate,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    engagement = await _locked(db, engagement_id)
    stored = _stored_lines(engagement)
    try:
        entry = cl.normalize_line(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if entry["key"] in {line.get("key") for line in stored}:
        raise HTTPException(status_code=409, detail="That line already exists. Use the existing line.")
    if len(stored) >= cl.MAX_EVIDENCE_LINES:
        raise HTTPException(status_code=422, detail=f"An engagement can have at most {cl.MAX_EVIDENCE_LINES} added lines.")
    line = cl.stamp_new_lines([entry], stored, user_id=str(user.id),
                              now=datetime.now(timezone.utc).isoformat(timespec="seconds"))[0]
    lines = [*stored, line]
    settings = {**(engagement.get("settings") or {}), "evidenceLines": lines}
    _check_line_anchors(settings, engagement)
    await _reject_system_lines(db, engagement, settings, user)
    await _save_lines(db, engagement, lines)
    await _audit(db, request, user, LINE_CREATED, engagement,
                 {"line_key": line["key"], "label": line["label"], "level2_label": line["level2_label"],
                  "category": line["category"]})
    return _answer(lines, line=line)


async def _own_line(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser, line_key: str,
                    system_keys: set[str] | None = None) -> dict[str, Any]:
    """The reviewer's own line with this key, or the sentence that says why it can't be changed:
    another tab already deleted it, the system creates it, or it now holds documents the system filed."""

    stored = _stored_lines(engagement)
    found = next((line for line in stored if line.get("key") == line_key), None)
    if system_keys is None:
        decisions = await tree_api.document_decisions(db, engagement)
        system_keys = tree_api.system_line_keys(engagement, lambda record: can_see(record, user), decisions)
    if found is None:
        if line_key in system_keys:
            raise HTTPException(status_code=422, detail="The system creates this line, so it can't be renamed or deleted.")
        raise HTTPException(status_code=404, detail="This line was already deleted. Reload to see the current lines.")
    if line_key in system_keys:
        raise HTTPException(status_code=409, detail="This line now holds documents the system filed, so it can't be "
                                                    "renamed or deleted.")
    return found


@router.patch("/engagements/{engagement_id}/evidence-lines/{line_key}")
async def rename_line(
    engagement_id: str,
    line_key: str,
    body: LineRename,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    engagement = await _locked(db, engagement_id)
    stored = _stored_lines(engagement)
    found = await _own_line(db, engagement, user, line_key)
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Give the line a name.")
    if label == found.get("label"):
        return _answer(stored, line=found)
    renamed = {**found, "label": label}
    lines = [renamed if line is found else line for line in stored]
    await _save_lines(db, engagement, lines)
    await _audit(db, request, user, LINE_RENAMED, engagement,
                 {"line_key": line_key, "old_label": str(found.get("label")), "new_label": label})
    return _answer(lines, line=renamed)


@router.delete("/engagements/{engagement_id}/evidence-lines/{line_key}")
async def delete_line(
    engagement_id: str,
    line_key: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Delete a line the reviewers added. Each document filed on it is moved to Unassigned supporting
    evidence by an explicit move saved now, so adding the line again later does not pull them back.
    One transaction: the documents move and the line goes, or nothing changes."""

    engagement = await _locked(db, engagement_id)
    stored = _stored_lines(engagement)
    loaded, decisions = await _load(db, engagement, user)
    found = await _own_line(db, engagement, user, line_key, {line.key for line in loaded.system})
    known_before = {line.key for line in loaded.lines}
    known_after = known_before - {line_key}
    move = {"from": line_key, "to": cl.SUPPORTING_UNASSIGNED}
    shown = {d.document_id for d in loaded.docs}
    changed: dict[str, dict[str, Any]] = {}
    moved = 0
    # Every document with a placement on the line (set-aside ones too: if one comes back it stays where
    # its owner left it). A document that cannot take the move fails the whole delete, by name.
    for doc in [*loaded.docs, *loaded.aside]:
        existing = decisions.get(doc.document_id) or {}
        chain = _chain(existing)
        if not any(s.target == line_key for s in cl.apply_placements(doc.default_slots, chain, known_before)):
            continue
        changed[doc.document_id] = await _save_chain(db, engagement, user, doc.document_id, existing,
                                                     _next_chain(chain, move, doc, known_after))
        moved += doc.document_id in shown
    lines = [line for line in stored if line is not found]
    await _save_lines(db, engagement, lines)
    await _audit(db, request, user, LINE_DELETED, engagement,
                 {"line_key": line_key, "label": str(found.get("label")), "documents_moved": moved})
    return _answer(lines, documents_moved=moved, documents=changed)


def _chain(existing: dict[str, Any]) -> list[Any]:
    chain = existing.get("placements")
    return list(chain) if isinstance(chain, list) else []


# --- a document's placement -------------------------------------------------------------------
@router.post("/engagements/{engagement_id}/documents/{document_id}/placements")
async def move_document(
    engagement_id: str,
    document_id: str,
    body: PlacementMove,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Move one of a document's placements. ``from`` must be a place the document is in now, or the
    answer is 409 and nothing is saved (another tab moved it first). Answers with the saved payload."""

    if not workpaper_item_service.ITEM_KEY.match(document_id):
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    engagement = await _locked(db, engagement_id)
    loaded, decisions = await _load(db, engagement, user)
    doc = next((d for d in loaded.docs if d.document_id == document_id), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    source, target = body.from_, body.to
    if source not in {s.target for s in doc.slots}:
        raise HTTPException(status_code=409, detail=STALE_MOVE)
    known = {line.key for line in loaded.lines}
    if target not in known and target not in cl.FIXED_TARGETS:
        raise HTTPException(status_code=422, detail="That line no longer exists. Reload Evidence and pick another place.")
    if source == target:
        raise HTTPException(status_code=422, detail="The document is already there.")
    existing = decisions.get(document_id) or {}
    move = {"from": source, "to": target}
    payload = await _save_chain(db, engagement, user, document_id, existing,
                                _next_chain(_chain(existing), move, doc, known))
    await _audit(db, request, user, DOCUMENT_MOVED, engagement,
                 {"document_id": document_id, "from": source, "to": target,
                  "from_label": _place_label(loaded, source), "to_label": _place_label(loaded, target)})
    return {"document_id": document_id, "payload": payload}


# --- a document's facility --------------------------------------------------------------------
@router.post("/engagements/{engagement_id}/documents/{document_id}/facility")
async def set_document_facility(
    engagement_id: str,
    document_id: str,
    body: FacilityChoice,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """The reviewer places a document on a Setup facility: saved as the document's own facility decision (it wins over
    every rule) and audited. ``suggested`` in the audit row says it was Claude's suggestion the reviewer took. The
    actor is the session's. 422 when the facility is not in Setup; 404 for a document that is not on the page."""

    if not workpaper_item_service.ITEM_KEY.match(document_id):
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    engagement = await _locked(db, engagement_id)
    loaded, decisions = await _load(db, engagement, user)
    doc = next((d for d in loaded.docs if d.document_id == document_id), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    if doc.canonical_type_id not in FACILITY_TYPES:
        raise HTTPException(status_code=422, detail="That kind of document is not placed on a facility.")
    facility = next((f for f in loaded.facilities if str(f.get("facilityId")) == body.facility_id), None)
    if facility is None:
        raise HTTPException(status_code=422, detail="That facility is not in Setup. Reload Evidence and pick another.")
    existing = decisions.get(document_id) or {}
    # Claude's suggestion as the page shows it (the same rule as the Evidence tree row), judged before this decision
    shown = EvidenceTreeService._suggestion(
        doc, {str(f.get("facilityId")): str(f.get("name")) for f in loaded.facilities}, decisions)
    suggested = shown is not None and shown["facility_id"] == body.facility_id
    if existing.get("facilityId") == body.facility_id:  # already there: nothing to write, nothing to log
        return {"document_id": document_id, "payload": existing}
    if "expected_facility_id" in body.model_fields_set and (existing.get("facilityId") or None) != (
            body.expected_facility_id or None):
        raise HTTPException(status_code=409, detail="Another reviewer already chose a facility for this document. "
                                                     "Reload Evidence to see it.")
    if existing.get("placements"):
        raise HTTPException(status_code=409, detail="This document was moved by hand. Move it back to Unassigned first, "
                                                     "or place it from the Evidence tree.")
    payload = {**existing, "documentId": document_id, "facilityId": body.facility_id}
    if workpaper_item_service.payload_size(payload) > workpaper_item_service.MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=409, detail="This document has too many saved changes to save another.")
    await workpaper_item_service.save_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind="document", item_key=document_id,
        payload=payload, user_id=user.id)
    await _audit(db, request, user, FACILITY_SET, engagement,
                 {"document_id": document_id, "facility_id": body.facility_id, "facility_name": str(facility.get("name")),
                  "suggested": suggested})
    return {"document_id": document_id, "payload": payload}


# --- reading the log --------------------------------------------------------------------------
@router.get("/engagements/{engagement_id}/evidence-activity")
async def evidence_activity(
    engagement_id: str,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=audit_query.MAX_LIMIT)] = audit_query.DEFAULT_LIMIT,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Line and placement changes on this engagement, newest first, with who made each. Any reader of
    the engagement; another org's engagement answers 404."""

    engagement = await _visible(db, engagement_id, user)
    scope = audit_query._scope(engagement["org_id"], {"engagement": str(engagement["id"]), "kind": "evidence"})
    where = ["a.org_id = :org_id", "a.target_type = 'engagement'", "a.target_id = :target",
             "a.event_type = ANY(:events)"]
    params: dict[str, Any] = {"org_id": engagement["org_id"], "target": str(engagement["id"]),
                              "events": list(EVENT_TYPES), "limit": limit + 1}
    if cursor:
        params["c_at"], params["c_id"] = audit_query.decode_cursor(cursor, scope)
        where.append("(a.created_at, a.id) < (:c_at, :c_id)")
    rows = (await db.execute(text(f"""
        SELECT a.id, a.event_type, a.created_at, a.actor_user_id, a.metadata,
               COALESCE(NULLIF(trim(COALESCE(u.full_name, concat_ws(' ', u.first_name, u.last_name))), ''), u.email)
                   AS actor_name
          FROM audit_logs a LEFT JOIN users u ON u.id = a.actor_user_id
         WHERE {' AND '.join(where)}
         ORDER BY a.created_at DESC, a.id DESC
         LIMIT :limit
    """).bindparams(bindparam("events", type_=ARRAY(Text()))), params)).mappings().all()
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for r in rows:
        meta = r["metadata"]
        meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
        items.append({
            "id": str(r["id"]), "event_type": r["event_type"], "at": r["created_at"].isoformat(),
            "actor_name": r["actor_name"] or ("Unknown user" if r["actor_user_id"] else None),
            **{k: meta.get(k) for k in ("line_key", "label", "level2_label", "old_label", "new_label",
                                        "documents_moved", "document_id", "from", "to", "from_label", "to_label",
                                        "facility_id", "facility_name", "suggested")
               if k in meta},
        })
    next_cursor = audit_query.encode_cursor(rows[-1]["created_at"], rows[-1]["id"], scope) if more and rows else None
    return {"items": items, "next_cursor": next_cursor}

