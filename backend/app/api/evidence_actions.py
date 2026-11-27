"""Evidence page changes as server actions, each with an audit event (MVP-139).

* POST   /v1/engagements/{id}/evidence-lines                       add a line
* PATCH  /v1/engagements/{id}/evidence-lines/{line_key}            rename a line
* DELETE /v1/engagements/{id}/evidence-lines/{line_key}            delete a line
* PATCH  /v1/engagements/{id}/evidence-fuels/{category}/{level2}   rename a Level 2 (fuel); its id never changes
* DELETE /v1/engagements/{id}/evidence-fuels/{category}/{level2}   delete a Level 2 the reviewers made, with its lines
* POST   /v1/engagements/{id}/documents/{document_id}/placements   move a document ({from, to})
* POST   /v1/engagements/{id}/documents/{document_id}/facility     place a document on a Setup facility ({facility_id})
* POST   /v1/engagements/{id}/evidence-folders                      add a folder to Block 1
* PATCH  /v1/engagements/{id}/evidence-folders/{folder_id}          rename a folder
* DELETE /v1/engagements/{id}/evidence-folders/{folder_id}          delete a folder (its documents go to the top of Block 1)
* POST   /v1/engagements/{id}/documents/{document_id}/folder       put a Block 1 document in a folder, or out ({folder_id} or null)
* GET    /v1/engagements/{id}/evidence-activity                     what was changed, newest first

Writers only (archived engagement: 409, another org: 404). Every write takes the engagement's
row lock first and reads the engagement again, so two writers run one after the other and neither
loses the other's change. The actor comes from the session. Audit rows hold ids and labels, never
document text. No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

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
LEVEL2_RENAMED = "evidence_level2_renamed"
LEVEL2_DELETED = "evidence_level2_deleted"
FACILITY_SET = "evidence_document_facility_set"
FOLDER_CREATED = "evidence_folder_created"
FOLDER_RENAMED = "evidence_folder_renamed"
FOLDER_DELETED = "evidence_folder_deleted"
DOCUMENT_FOLDERED = "evidence_document_folder_set"
EVENT_TYPES = (LINE_CREATED, LINE_RENAMED, LINE_DELETED, LEVEL2_RENAMED, LEVEL2_DELETED, DOCUMENT_MOVED, FACILITY_SET,
               FOLDER_CREATED, FOLDER_RENAMED, FOLDER_DELETED, DOCUMENT_FOLDERED)

BLOCK_NAMES = {
    cl.BLOCK_SUMMARY: "Summary documents and workbook",
    cl.BLOCK_UNASSIGNED: "Unassigned documents",
    cl.SUPPORTING_UNASSIGNED: "Unassigned supporting evidence",
}
# A document in one of these states is already being read: moving it asks for no new read.
NO_REREAD_STATES = frozenset({"queued", "in_progress"})
STALE_MOVE = "This document was already moved from there. Reload Evidence to see where it is now."


# --- request bodies ---------------------------------------------------------------------
class LineCreate(BaseModel):
    """A new line. The server builds the key and records who added it; a client cannot send either."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(max_length=40)
    level2_label: str = Field(max_length=cl.MAX_LABEL)
    # The id of the fuel the line goes under, when the client knows it (a fuel already on the page): a renamed fuel
    # keeps its id, so a line added under its new name must not start a second fuel.
    level2: str | None = Field(default=None, max_length=60)
    anchor_kind: str = Field(max_length=20)
    anchor_id: str | None = Field(default=None, max_length=200)
    label: str = Field(max_length=cl.MAX_LABEL)
    scope: str | None = Field(default=None, max_length=20)


class LineRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=cl.MAX_LABEL)


class Level2Name(BaseModel):
    """A fuel's new name. No length limit here: ``clean_level2_name`` answers with a sentence."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=2000)


class FolderName(BaseModel):
    """A folder's name. No length limit here: ``clean_folder_name`` answers with a sentence."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=2000)


class FolderChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder_id: str | None = Field(default=None, max_length=200)  # null: out of any folder, to the top of Block 1


class PlacementMove(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from", min_length=1, max_length=200)
    to: str = Field(min_length=1, max_length=200)
    # A document that sits in other places too, moved onto a line of another type: "reread" reads it again as that
    # type, which takes it off those places; "move_only" moves just this placement and leaves its type alone.
    reread: Literal["reread", "move_only"] | None = None


class RereadState(BaseModel):
    """What became of a read a move asked for: ``pending`` (asked again), ``failed`` (with the reason), ``done``."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["pending", "failed", "done"]
    error: str | None = Field(default=None, max_length=500)


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


def _reread_for(loaded: Loaded, doc: DocState, target: str) -> dict[str, str] | None:
    """The read a move onto ``target`` asks for: the document read again as the line's type, when that type is
    not the one it was read as (a summary document, an unidentified one, a bill of another kind). None for a
    block, a line no extractor feeds, a document of the line's type already, or one being read right now."""

    line = next((ln for ln in loaded.lines if ln.key == target), None)
    type_id = cl.line_type_id(line) if line is not None else None
    if type_id is None or doc.canonical_type_id == type_id:
        return None
    if str(doc.document.get("processing_status") or "").lower() in NO_REREAD_STATES:
        return None
    return {"canonical_type_id": type_id, "type_name": str(cl.type_name(type_id))}


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
    wanted = body.model_dump(exclude_none=True)
    if "level2" not in wanted:  # a name a reviewer gave a fuel is that fuel, whatever it was called before
        for found_id, renamed in cl.stored_level2_names(engagement.get("settings")).items():
            found_category, _, found_level2 = found_id.partition(":")
            if found_category == body.category and cl.folder_name_key(renamed["label"]) == cl.folder_name_key(body.level2_label):
                wanted["level2"] = found_level2
    try:
        entry = cl.normalize_line(wanted)
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
    changed, moved = await _move_to_unassigned(db, engagement, user, loaded, decisions, {line_key})
    lines = [line for line in stored if line is not found]
    await _save_lines(db, engagement, lines)
    await _audit(db, request, user, LINE_DELETED, engagement,
                 {"line_key": line_key, "label": str(found.get("label")), "documents_moved": moved})
    return _answer(lines, documents_moved=moved, documents=changed)


async def _move_to_unassigned(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser, loaded: Loaded,
                              decisions: dict[str, dict[str, Any]], gone: set[str]) -> tuple[dict[str, dict[str, Any]], int]:
    """Every document filed on one of the lines ``gone`` moves to Unassigned supporting evidence, by explicit moves
    saved now. Returns the saved decisions by document and how many of the documents the page shows moved."""

    known_before = {line.key for line in loaded.lines}
    known_after = known_before - gone
    shown = {d.document_id for d in loaded.docs}
    changed: dict[str, dict[str, Any]] = {}
    moved = 0
    # Every document with a placement on a line (set-aside ones too: if one comes back it stays where
    # its owner left it). A document that cannot take the move fails the whole delete, by name.
    for doc in [*loaded.docs, *loaded.aside]:
        existing = decisions.get(doc.document_id) or {}
        chain = _chain(existing)
        touched = False
        for line_key in sorted(gone):
            if not any(s.target == line_key for s in cl.apply_placements(doc.default_slots, chain, known_before)):
                continue
            chain = _next_chain(chain, {"from": line_key, "to": cl.SUPPORTING_UNASSIGNED}, doc, known_after)
            touched = True
        if not touched:
            continue
        changed[doc.document_id] = await _save_chain(db, engagement, user, doc.document_id, existing, chain)
        moved += doc.document_id in shown
    return changed, moved


def _chain(existing: dict[str, Any]) -> list[Any]:
    chain = existing.get("placements")
    return list(chain) if isinstance(chain, list) else []


# --- Level 2 (fuel) -----------------------------------------------------------------------------
def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _fuel(loaded: Loaded, category: str, level2: str) -> list[cl.CalculationLine]:
    """The lines of one fuel, or 404 (another tab deleted it, or it never was here)."""

    group = [ln for ln in loaded.lines if ln.category == category and ln.level2 == level2]
    if category not in cl.CATEGORY_SCOPE or not group:
        raise HTTPException(status_code=404, detail="This fuel was already deleted. Reload Evidence to see the current fuels.")
    return group


@router.patch("/engagements/{engagement_id}/evidence-fuels/{category}/{level2}")
async def rename_fuel(
    engagement_id: str,
    category: str,
    level2: str,
    body: Level2Name,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Rename a fuel (Level 2), the system's or the reviewers' own. Only the name shown changes: the fuel's id (its
    slug, in every line key) stays, so the documents, the lines and the decisions on them stay where they are.
    422 for an empty, too long or control-character name; 409 (``level2_name_taken``) when another fuel of the
    category has the name; 404 for a fuel that is not there."""

    engagement = await _locked(db, engagement_id)
    loaded, _ = await _load(db, engagement, user)
    group = _fuel(loaded, category, level2)
    try:
        name = cl.clean_level2_name(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    old = group[0].level2_label
    names = cl.stored_level2_names(engagement.get("settings"))
    if name == old:  # nothing to write, nothing to log
        return {"level2": {"category": category, "level2": level2, "label": old}, "evidenceLevel2Names": names}
    if any(ln.category == category and ln.level2 != level2 and cl.folder_name_key(ln.level2_label) == cl.folder_name_key(name)
           for ln in loaded.lines):
        raise _refuse(409, "level2_name_taken", f"{name} already exists in this category. Use another name.")
    fuel_id = cl.level2_id(category, level2)
    if fuel_id not in names and len(names) >= cl.MAX_LEVEL2_NAMES:
        raise HTTPException(status_code=422, detail=f"An engagement can have at most {cl.MAX_LEVEL2_NAMES} renamed fuels.")
    names = {**names, fuel_id: {"label": name, "renamed_by": str(user.id), "renamed_at": _now()}}
    settings = {**(engagement.get("settings") or {}), cl.LEVEL2_NAMES_KEY: names}
    await engagement_service.update_engagement(db, engagement["id"], {"settings": settings})
    await _audit(db, request, user, LEVEL2_RENAMED, engagement,
                 {"category": category, "level2": level2, "old_label": old, "new_label": name})
    return {"level2": {"category": category, "level2": level2, "label": name}, "evidenceLevel2Names": names}


@router.delete("/engagements/{engagement_id}/evidence-fuels/{category}/{level2}")
async def delete_fuel(
    engagement_id: str,
    category: str,
    level2: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Delete a fuel the reviewers made, with the lines under it. Each document filed on them moves to Unassigned
    supporting evidence by an explicit move saved now (a line made again later does not pull them back), and the
    audit trail keeps the event. A fuel the system creates, or one that now holds a line the system makes, answers
    409 (``level2_system_created``). One transaction: the documents move and the fuel goes, or nothing changes."""

    engagement = await _locked(db, engagement_id)
    loaded, decisions = await _load(db, engagement, user)
    group = _fuel(loaded, category, level2)
    system_keys = {line.key for line in loaded.system}
    if any(ln.key in system_keys or not ln.created_by_user for ln in group):
        raise _refuse(409, "level2_system_created", "Created by the system from your Setup; can't be deleted.")
    gone = {ln.key for ln in group}
    changed, moved = await _move_to_unassigned(db, engagement, user, loaded, decisions, gone)
    lines = [line for line in _stored_lines(engagement) if line.get("key") not in gone]
    names = {k: v for k, v in cl.stored_level2_names(engagement.get("settings")).items() if k != cl.level2_id(category, level2)}
    settings = {**(engagement.get("settings") or {}), "evidenceLines": lines, cl.LEVEL2_NAMES_KEY: names}
    await engagement_service.update_engagement(db, engagement["id"], {"settings": settings})
    await _audit(db, request, user, LEVEL2_DELETED, engagement,
                 {"category": category, "level2": level2, "label": group[0].level2_label,
                  "lines_deleted": len(gone), "documents_moved": moved})
    return _answer(lines, documents_moved=moved, documents=changed, evidenceLevel2Names=names)


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
    answer is 409 and nothing is saved (another tab moved it first). Answers with the saved payload.

    A document moved onto a line of another type also answers ``reread``: ``{canonical_type_id, type_name}``,
    the type the client asks the extraction queue to read it as (POST /documents/{id}/processing-runs with
    ``canonical_type_id_override``). The earlier extraction stays in the record, and nothing decided on
    it applies to the new values, which start unreviewed. The saved move then covers every place the
    document is in (``from`` "*"), since its records will be filed again by the new read, and the decision
    holds ``rereadPending`` until a read of that type arrives: its old-type records count on no line meanwhile.
    A re-read takes the document off its other places, so a document that has any must say which it wants
    (``reread``: "reread" or "move_only"): 409 without it. "move_only" moves just this placement."""

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
    hint = _reread_for(loaded, doc, target)
    others = sorted({s.target for s in doc.slots} - {source})
    if hint and others and body.reread is None:
        name = doc.document.get("file_name") or document_id
        raise HTTPException(status_code=409, detail=(
            f"{name} is also on {' and '.join(_place_label(loaded, k) for k in others)}. Re-reading it as "
            f"{hint['type_name']} takes it off those places. Choose to re-read it or to move it without re-reading."))
    reread = hint if hint and body.reread != "move_only" else None
    if reread:
        chain = [{"from": cl.ALL_PLACES, "to": target}]
        existing = {**existing, "rereadPending": {"canonical_type_id": reread["canonical_type_id"],
                                                  "type_name": reread["type_name"], "requested_at": _now(),
                                                  "error": None}}
    else:
        chain = _next_chain(_chain(existing), move, doc, known)
    if "folderId" in existing and not cl.in_summary_block(
            cl.apply_placements(doc.default_slots, chain, known)):
        existing = {k: v for k, v in existing.items() if k != "folderId"}  # it leaves Block 1, so it leaves its folder
    payload = await _save_chain(db, engagement, user, document_id, existing, chain)
    await _audit(db, request, user, DOCUMENT_MOVED, engagement,
                 {"document_id": document_id, "from": source, "to": target,
                  "from_label": _place_label(loaded, source), "to_label": _place_label(loaded, target),
                  **({"reread_as": hint["canonical_type_id"], "reread_as_label": hint["type_name"],
                      "reread_choice": "reread" if reread else "move_only"} if hint else {})})
    return {"document_id": document_id, "payload": payload, "reread": reread}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.post("/engagements/{engagement_id}/documents/{document_id}/reread-state")
async def set_reread_state(
    engagement_id: str,
    document_id: str,
    body: RereadState,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """What became of the read a move asked for, kept on the server so it survives a reload: ``failed`` stores the
    reason (the document stays out of the calculation), ``pending`` clears it for another try, ``done`` ends the wait.
    409 when no re-read is waiting on the document (``done`` is always fine)."""

    if not workpaper_item_service.ITEM_KEY.match(document_id):
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    engagement = await _locked(db, engagement_id)
    decisions = await tree_api.document_decisions(db, engagement)
    existing = decisions.get(document_id) or {}
    pending = existing.get("rereadPending")
    if not isinstance(pending, dict):
        if body.state == "done":
            return {"document_id": document_id, "payload": existing}
        raise HTTPException(status_code=409, detail="No re-read is waiting for this document.")
    if body.state == "done":
        payload = {k: v for k, v in existing.items() if k != "rereadPending"}
    else:
        error = " ".join((body.error or "").split())[:500] or None if body.state == "failed" else None
        payload = {**existing, "rereadPending": {**pending, "error": error or ("The read failed." if body.state == "failed" else None),
                                                 **({"requested_at": _now()} if body.state == "pending" else {})}}
    payload["documentId"] = document_id
    await workpaper_item_service.save_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind="document", item_key=document_id,
        payload=payload, user_id=user.id)
    return {"document_id": document_id, "payload": payload}


# --- Block 1 folders --------------------------------------------------------------------------
def _stored_folders(engagement: dict[str, Any]) -> list[dict[str, Any]]:
    return cl.stored_folders(engagement.get("settings"))


async def _save_folders(db: AsyncSession, engagement: dict[str, Any], folders: list[dict[str, Any]]) -> None:
    settings = {**(engagement.get("settings") or {}), "evidenceFolders": folders}
    await engagement_service.update_engagement(db, engagement["id"], {"settings": settings})


def _folder_answer(folders: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {**extra, "evidenceFolders": folders}


def _folder_name_or_422(raw: str, folders: list[dict[str, Any]], except_id: str | None = None) -> str:
    try:
        name = cl.clean_folder_name(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    taken = {cl.folder_name_key(f["name"]) for f in folders if f["id"] != except_id}
    if cl.folder_name_key(name) in taken:
        raise HTTPException(status_code=409, detail="A folder with that name already exists. Use another name.")
    return name


def _folder_or_404(folders: list[dict[str, Any]], folder_id: str) -> dict[str, Any]:
    found = next((f for f in folders if f["id"] == folder_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="This folder was already deleted. Reload Evidence to see the "
                                                    "current folders.")
    return found


@router.post("/engagements/{engagement_id}/evidence-folders", status_code=201)
async def create_folder(
    engagement_id: str,
    body: FolderName,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Add a folder to Block 1 (one level: a folder never holds a folder)."""

    engagement = await _locked(db, engagement_id)
    folders = _stored_folders(engagement)
    if len(folders) >= cl.MAX_FOLDERS:
        raise HTTPException(status_code=422, detail=f"An engagement can have at most {cl.MAX_FOLDERS} folders.")
    name = _folder_name_or_422(body.name, folders)
    folder = {"id": f"fld-{uuid.uuid4().hex[:12]}", "name": name, "created_by": str(user.id),
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    folders = [*folders, folder]
    await _save_folders(db, engagement, folders)
    await _audit(db, request, user, FOLDER_CREATED, engagement, {"folder_id": folder["id"], "folder_name": name})
    return _folder_answer(folders, folder=folder)


@router.patch("/engagements/{engagement_id}/evidence-folders/{folder_id}")
async def rename_folder(
    engagement_id: str,
    folder_id: str,
    body: FolderName,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    engagement = await _locked(db, engagement_id)
    folders = _stored_folders(engagement)
    found = _folder_or_404(folders, folder_id)
    name = _folder_name_or_422(body.name, folders, except_id=folder_id)
    if name == found["name"]:
        return _folder_answer(folders, folder=found)
    renamed = {**found, "name": name}
    folders = [renamed if f is found else f for f in folders]
    await _save_folders(db, engagement, folders)
    await _audit(db, request, user, FOLDER_RENAMED, engagement,
                 {"folder_id": folder_id, "old_label": found["name"], "new_label": name})
    return _folder_answer(folders, folder=renamed)


@router.delete("/engagements/{engagement_id}/evidence-folders/{folder_id}")
async def delete_folder(
    engagement_id: str,
    folder_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Delete a folder. Its documents are not deleted: each goes to the top of Block 1, by clearing the
    folder from its saved decision now. One transaction: the documents come out and the folder goes, or
    nothing changes."""

    engagement = await _locked(db, engagement_id)
    folders = _stored_folders(engagement)
    found = _folder_or_404(folders, folder_id)
    loaded, decisions = await _load(db, engagement, user)
    shown = {d.document_id for d in loaded.docs if cl.in_summary_block(d.slots)}
    changed: dict[str, dict[str, Any]] = {}
    moved = 0
    for document_id, existing in decisions.items():  # every saved decision that names the folder, shown or not
        if existing.get("folderId") != folder_id:
            continue
        payload = {k: v for k, v in existing.items() if k != "folderId"}
        await workpaper_item_service.save_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind="document", item_key=document_id,
            payload={**payload, "documentId": document_id}, user_id=user.id)
        changed[document_id] = {**payload, "documentId": document_id}
        moved += document_id in shown
    folders = [f for f in folders if f is not found]
    await _save_folders(db, engagement, folders)
    await _audit(db, request, user, FOLDER_DELETED, engagement,
                 {"folder_id": folder_id, "folder_name": found["name"], "documents_moved": moved})
    return _folder_answer(folders, documents_moved=moved, documents=changed)


@router.post("/engagements/{engagement_id}/documents/{document_id}/folder")
async def set_document_folder(
    engagement_id: str,
    document_id: str,
    body: FolderChoice,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    _open: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Put a document that is in Block 1 into a folder, or take it out (``folder_id`` null: the top of
    Block 1). 422 for a document that is not in Block 1; 404 for a folder that is gone or a document that
    is not on the page. Answers with the saved payload."""

    if not workpaper_item_service.ITEM_KEY.match(document_id):
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    engagement = await _locked(db, engagement_id)
    loaded, decisions = await _load(db, engagement, user)
    doc = next((d for d in loaded.docs if d.document_id == document_id), None)
    if doc is None:
        raise HTTPException(status_code=404, detail="That document isn't on the Evidence page for this engagement.")
    if not cl.in_summary_block(doc.slots):
        raise HTTPException(status_code=422, detail="Only documents in Summary documents and workbook can go in a folder.")
    folders = _stored_folders(engagement)
    target = _folder_or_404(folders, body.folder_id) if body.folder_id is not None else None
    existing = decisions.get(document_id) or {}
    folder_ids = {f["id"] for f in folders}
    current = cl.document_folder(existing, folder_ids)
    if current == (target["id"] if target else None):  # already there: nothing to write, nothing to log
        return {"document_id": document_id, "payload": existing}
    payload = {k: v for k, v in existing.items() if k != "folderId"}
    payload["documentId"] = document_id
    if target is not None:
        payload["folderId"] = target["id"]
    if workpaper_item_service.payload_size(payload) > workpaper_item_service.MAX_PAYLOAD_BYTES:
        raise HTTPException(status_code=409, detail="This document has too many saved changes to save another.")
    await workpaper_item_service.save_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind="document", item_key=document_id,
        payload=payload, user_id=user.id)
    names = {f["id"]: f["name"] for f in folders}
    await _audit(db, request, user, DOCUMENT_FOLDERED, engagement,
                 {"document_id": document_id, "folder_id": target["id"] if target else None,
                  "from_label": names.get(current) if current else BLOCK_NAMES[cl.BLOCK_SUMMARY],
                  "to_label": target["name"] if target else BLOCK_NAMES[cl.BLOCK_SUMMARY]})
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
            **{k: meta.get(k) for k in ("line_key", "label", "level2_label", "category", "level2", "lines_deleted", "old_label", "new_label",
                                        "documents_moved", "document_id", "from", "to", "from_label", "to_label",
                                        "facility_id", "facility_name", "suggested", "folder_id", "folder_name",
                                        "reread_as", "reread_as_label", "reread_choice")
               if k in meta},
        })
    next_cursor = audit_query.encode_cursor(rows[-1]["created_at"], rows[-1]["id"], scope) if more and rows else None
    return {"items": items, "next_cursor": next_cursor}

