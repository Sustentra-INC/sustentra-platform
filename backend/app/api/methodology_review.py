"""Methodology review: the reviewer's decisions on the client's stated boundary, categories,
exclusions, factor sources, GWP and calculation methods (the page's fields).

* GET    /v1/engagements/{id}/methodology-review                  fields, catalog, AI status (s1_reader)
* POST   /v1/engagements/{id}/methodology-review/{field_id}/accept  take the suggestion, or the current value
* POST   /v1/engagements/{id}/methodology-review/{field_id}/edit    {value}
* POST   /v1/engagements/{id}/methodology-review/{field_id}/reject  {reason}
* POST   /v1/engagements/{id}/methodology-review/{field_id}/revert  back to pending
* POST   /v1/engagements/{id}/methodology-review/rows               {group}: add an entity or factor row (201)
* DELETE /v1/engagements/{id}/methodology-review/{field_id}         remove a row the reviewer added

The rules are in ``services/methodology_review``; a move they refuse answers 409 (state) or
422 (input) with a sentence for the user and writes nothing. Each field is a
``workpaper_items`` row (kind ``methodology``) created on its first action. Who acted and
when come from the session, never the body (bodies forbid unknown fields). Each action
writes one ``methodology_decision`` audit event with the field id, action and status only,
never a value, quote or reason. Writes are s1_writer on an open engagement: another org's
engagement answers 404, a provider_admin 403 and an archived engagement 409.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
import asyncio
from collections import Counter
import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.adapters.llm.claude import AiNotConfiguredError, ClaudeClient, get_claude
from backend.app.api import documents as documents_api
from backend.app.api.engagements import _visible, require_open_engagement
from backend.app.api.evidence_tree import document_decisions
from backend.app.api.s1_access import can_see, s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.config import Settings, get_settings
from backend.app.core.db import get_db_session, get_sessionmaker_dependency, set_tenant
from backend.app.services import ai_usage
from backend.app.services import methodology_prefill as prefill
from backend.app.services import methodology_review as rules
from backend.app.services import workpaper_item_service
from backend.app.services.audit_log import write_audit_event
from backend.app.services.methodology_review import KIND, MethodologyConflict, MethodologyInvalid
from backend.app.services.parser_service import ParserService
from backend.app.services.request_service import actor_of, stamp
from backend.app.services.workpaper_item_service import ITEM_KEY, MAX_PAYLOAD_BYTES

router = APIRouter(prefix="/v1", tags=["methodology-review"])

_NOT_FOUND = HTTPException(status_code=404, detail="That methodology field was not found. Reload the page to see the current fields.")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditBody(_Body):
    value: Any


class RejectBody(_Body):
    reason: str


class RowBody(_Body):
    group: Literal["entities", "factor:scope1", "factor:scope2"]


@contextmanager
def _rules() -> Iterator[None]:
    """Turn a refused move into 409 and malformed input into 422."""

    try:
        yield
    except MethodologyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MethodologyInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _now() -> datetime:
    return datetime.now(UTC)


def new_client(settings: Settings) -> ClaudeClient | None:
    """The Claude client, or None when this deployment has none set up (tests replace this)."""

    try:
        return get_claude(settings)
    except AiNotConfiguredError:
        return None


def _gate(settings: Settings, spent_microusd: int, candidates: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Why Claude cannot be asked now (code, sentence), or (None, None)."""

    if not settings.ai_suggestions_enabled:
        return "off", "Suggestions from the documents are switched off for this deployment."
    if new_client(settings) is None:
        return "not_configured", ("Suggestions from the documents are switched on, but Claude is not set up "
                                  "for this deployment. Contact support.")
    if ai_usage.cap_reached(spent_microusd, settings.ai_monthly_cap_usd):
        return "cap_reached", (f"This month's limit on suggestions (${settings.ai_monthly_cap_usd:,.2f}) has been "
                               "reached. They are available again next month, or the limit can be raised.")
    if not candidates:
        return "no_documents", prefill.NO_DOCUMENTS
    return None, None


async def _candidates(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser) -> list[dict[str, Any]]:
    """The documents Claude would read: summary documents the reviewer has not set aside."""

    return prefill.candidate_documents(
        documents_api.current_upload_service(), documents_api.current_pipeline_service(),
        str(engagement["id"]), lambda record: can_see(record, user), await document_decisions(db, engagement))


async def ai_status(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser,
                    settings: Settings | None = None) -> dict[str, Any]:
    """Whether Claude suggestions can be asked for now, and the numbers behind it."""

    settings = settings or get_settings()
    spent = await ai_usage.month_spend_microusd(db, engagement["org_id"])
    candidates = await _candidates(db, engagement, user) if settings.ai_suggestions_enabled else []
    code, reason = _gate(settings, spent, candidates)
    return {"enabled": code is None, "reason_code": code, "reason": reason, "provider": settings.ai_provider,
            "model": settings.ai_model, "month_spend_usd": round(spent / ai_usage.MICRO, 2),
            "cap_usd": settings.ai_monthly_cap_usd}


def _definition(field_id: str) -> dict[str, Any] | None:
    return rules.catalog_field(field_id) or rules.row_field(field_id)


async def _locked(db: AsyncSession, engagement: dict[str, Any], field_id: str, user: CurrentUser
                  ) -> tuple[dict[str, Any], dict[str, Any]]:
    """The field's definition and stored record, locked until the transaction ends. A fixed
    field gets its row on first use; a row that was never added, or was removed, is a 404."""

    field = _definition(field_id) if ITEM_KEY.match(field_id) else None
    if field is None:
        raise _NOT_FOUND
    if not field.get("user_added"):
        await workpaper_item_service.insert_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=field_id,
            payload=rules.new_record(field_id), user_id=user.id)
    found = await workpaper_item_service.get_items(db, engagement["id"], KIND, [field_id], for_update=True)
    if not found or found[0]["payload"].get("removed"):
        raise _NOT_FOUND
    return field, found[0]["payload"]


async def _save(db: AsyncSession, engagement: dict[str, Any], field_id: str, record: dict[str, Any],
                user: CurrentUser) -> dict[str, Any]:
    if workpaper_item_service.payload_size(record) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=422,
            detail="This field's history is too long to record another change. Contact support if you need more.")
    row = await workpaper_item_service.update_payload(db, engagement["id"], KIND, field_id, record, user.id)
    return row["payload"]


async def _audit(db: AsyncSession, request: Request, user: CurrentUser, engagement: dict[str, Any],
                 field_id: str, action: str, status: str | None) -> None:
    await write_audit_event(
        db,
        "methodology_decision",
        org_id=engagement["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata={"field_id": field_id, "action": action, "status": status},  # never a value or reason
    )


@router.get("/engagements/{engagement_id}/methodology-review", response_model=dict[str, Any])
async def get_methodology_review(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    engagement = await _visible(db, engagement_id, user)
    stored = {row["item_key"]: row["payload"]
              for row in await workpaper_item_service.list_items(db, engagement["id"], KIND)}
    fields = [rules.public(stored.get(f["field_id"]) or rules.new_record(f["field_id"])) for f in rules.CATALOG]
    catalog = [dict(f) for f in rules.CATALOG]
    for key, record in stored.items():  # rows the reviewer added, oldest first
        definition = rules.row_field(key)
        if definition is not None and not record.get("removed"):
            definition["user_added"] = bool(record.get("user_added"))  # the record's flag is the truth
            fields.append(rules.public(record))
            catalog.append(definition)
    return {
        "fields": fields,
        "catalog": catalog,
        "groups": [{"group": g, "label": label} for g, label in rules.GROUPS],
        "row_groups": list(rules.ROW_GROUPS),
        "ai": await ai_status(db, engagement, user),
    }


async def _act(action: str, field_id: str, request: Request, user: CurrentUser, engagement: dict[str, Any],
               db: AsyncSession, **inputs: Any) -> dict[str, Any]:
    field, record = await _locked(db, engagement, field_id, user)
    now, actor = _now(), actor_of(user)
    with _rules():
        if action == "accept":
            updated = rules.accept(record, field, actor, now)
        elif action == "edit":
            updated = rules.edit(record, field, inputs["value"], actor, now)
        elif action == "reject":
            updated = rules.reject(record, field, inputs["reason"], actor, now)
        else:
            updated = rules.revert(record, field, actor, now)
    saved = await _save(db, engagement, field_id, updated, user)
    await _audit(db, request, user, engagement, field_id, action, rules.status_of(saved))
    return rules.public(saved)


@router.post("/engagements/{engagement_id}/methodology-review/rows", status_code=201, response_model=dict[str, Any])
async def add_row(
    body: RowBody,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    field_id = rules.new_row_id(body.group)
    # Removed rows count on purpose: it bounds the rows an engagement can ever hold.
    added = [r for r in await workpaper_item_service.list_items(db, engagement["id"], KIND)
             if r["payload"].get("user_added")]
    if len(added) >= rules.MAX_ADDED_ROWS:
        raise HTTPException(
            status_code=409,
            detail=f"This engagement already has the most rows a reviewer can add ({rules.MAX_ADDED_ROWS}). "
                   "Edit an existing row instead.")
    record = rules.new_row(field_id, actor_of(user), _now())
    row = await workpaper_item_service.insert_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=field_id,
        payload=record, user_id=user.id)
    if row is None:  # a random id colliding: not expected
        raise HTTPException(status_code=409, detail="The row could not be added. Try again.")
    await _audit(db, request, user, engagement, field_id, "add_row", rules.PENDING)
    return {**rules.public(row["payload"]), "field": {**(rules.row_field(field_id) or {}), "user_added": True}}


@router.post("/engagements/{engagement_id}/methodology-review/{field_id}/accept", response_model=dict[str, Any])
async def accept_field(
    field_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act("accept", field_id, request, user, engagement, db)


@router.post("/engagements/{engagement_id}/methodology-review/{field_id}/edit", response_model=dict[str, Any])
async def edit_field(
    field_id: str,
    body: EditBody,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act("edit", field_id, request, user, engagement, db, value=body.value)


@router.post("/engagements/{engagement_id}/methodology-review/{field_id}/reject", response_model=dict[str, Any])
async def reject_field(
    field_id: str,
    body: RejectBody,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act("reject", field_id, request, user, engagement, db, reason=body.reason)


@router.post("/engagements/{engagement_id}/methodology-review/{field_id}/revert", response_model=dict[str, Any])
async def revert_field(
    field_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act("revert", field_id, request, user, engagement, db)


@router.delete("/engagements/{engagement_id}/methodology-review/{field_id}", response_model=dict[str, Any])
async def remove_row(
    field_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    field, record = await _locked(db, engagement, field_id, user)
    with _rules():
        removed = rules.remove(record, field, actor_of(user), _now())
    saved = await _save(db, engagement, field_id, removed, user)
    await _audit(db, request, user, engagement, field_id, "remove_row", None)
    return {**rules.public(saved), "removed": True}


# --- Claude's suggestions ---------------------------------------------------------------------

logger = logging.getLogger(__name__)

_FAILED = {
    "refused": "Claude declined to read these documents. Nothing was changed.",
    "incomplete": "Claude's answer was cut short, so none of it was kept. Try again.",
    "invalid": "Claude's answer could not be read, so none of it was kept. Try again.",
}


async def _store(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser,
                 verified: list[prefill.Verified], dropped: Counter[str]) -> tuple[int, int]:
    """Put each verified suggestion on its field's record: (suggested, kept_reviewer_decision).
    A field the reviewer has decided is left alone. An entity or factor source already on the
    page (suggested or decided), or already added by an earlier suggestion of this same reply, is
    not added again; a new one becomes a new row. A value the store refuses (too long for the
    record) is counted in ``dropped`` as invalid_value."""

    suggested = kept = 0
    fixed = {v.field_id: v for v in verified if v.field_id}
    for field_id in fixed:  # a record for each, so it can be locked and its state read
        await workpaper_item_service.insert_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=field_id,
            payload=rules.new_record(field_id), user_id=user.id)
    locked = {row["item_key"]: row["payload"] for row in await workpaper_item_service.get_items(
        db, engagement["id"], KIND, list(fixed), for_update=True)}
    for field_id, item in fixed.items():
        if rules.status_of(locked[field_id]) != rules.PENDING:
            kept += 1
            continue
        try:
            saved = await rules.save_suggestion(db, org_id=engagement["org_id"], engagement_id=engagement["id"],
                                                field_id=field_id, suggestion=item.suggestion, user_id=user.id)
        except MethodologyInvalid:
            dropped["invalid_value"] += 1
            continue
        suggested += 1 if saved is not None else 0
    existing = [row for row in await workpaper_item_service.list_items(db, engagement["id"], KIND)
                if rules.row_field(row["item_key"]) is not None and not row["payload"].get("removed")]
    for item in (v for v in verified if v.row_group):
        group = str(item.row_group)
        value = item.suggestion["value"]
        if any(row["item_key"].startswith(rules.ROW_GROUPS[group][0] + ":") and any(
                prefill.same_row_value(group, mine, value)
                for mine in ((row["payload"].get("suggestion") or {}).get("value"),
                             (row["payload"].get("decision") or {}).get("value"))) for row in existing):
            continue
        field_id = rules.new_row_id(group)
        field = rules.row_field(field_id)
        assert field is not None
        try:  # a row Claude found: user_added stays false, so only a reviewer-made row can be removed
            record = rules.with_suggestion(rules.new_record(field_id), field, item.suggestion)
            if workpaper_item_service.payload_size(record) > MAX_PAYLOAD_BYTES:
                raise MethodologyInvalid("too long")
        except MethodologyInvalid:
            dropped["invalid_value"] += 1
            continue
        row = await workpaper_item_service.insert_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=field_id,
            payload=record, user_id=user.id)
        if row is not None:  # None: the random id collided; not expected
            existing.append({"item_key": field_id, "payload": record})  # so a repeat in this reply is skipped
            suggested += 1
    return suggested, kept


async def _audit_prefill(db: AsyncSession, request: Request, user: CurrentUser, engagement: dict[str, Any],
                         metadata: dict[str, Any]) -> None:
    await write_audit_event(
        db, "methodology_prefill", org_id=engagement["org_id"], actor_user_id=user.id, actor_role=user.role,
        target_type="engagement", target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"), metadata=metadata)  # counts and cost only


@asynccontextmanager
async def _short_transaction(sessions: async_sessionmaker[AsyncSession], org_id: Any) -> AsyncIterator[AsyncSession]:
    """Its own short transaction in the organization's RLS scope, committed on exit."""

    async with sessions() as session, session.begin():
        await set_tenant(session, org_id)
        yield session


# Organizations with a prefill running in this process. One call per organization at a time:
# a double click answers 409 instead of a second billed call, and the cap check below always
# sees the spend of the call before it.
_RUNNING: set[str] = set()
_BUSY = "Suggestions are already being prepared for this organization. Try again in a minute."
_NOT_SAVED = ("Claude answered, but its suggestions could not be saved, so none were kept. "
              "The call was recorded. Try again.")


@router.post("/engagements/{engagement_id}/methodology-review/prefill", response_model=dict[str, Any])
async def prefill_methodology(
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker_dependency),
) -> Any:
    """Ask Claude to propose values from the client's summary documents (one call, synchronous).

    Three short steps, never holding a database connection while documents are parsed or Claude
    answers (up to 90 s):

    1. Gate, in the request's transaction (committed before the slow part): the organization's
       advisory lock is only *tried* (``pg_try_advisory_xact_lock``; held means another prefill is
       deciding right now: 409), then the switch, the client, this month's spend against the cap and
       the documents are checked.
    2. Read the documents and make the one Claude call, with no transaction open.
    3. Record the call in the ledger in its own committed transaction (a call that was made is
       always recorded, whatever happens next), then verify and store the suggestions and write the
       audit event in a second one; if that fails, nothing is kept and the answer is a 502 sentence.

    Cap, race safety: this process runs one prefill per organization at a time (``_RUNNING``) and
    re-reads the spend after the previous call's ledger row, so the cap is exact within a process.
    Across several app processes two calls could be in flight together, so the cap can be passed by
    at most one call per process, never more. Answers 409 with a sentence when it is switched off,
    over the monthly limit, has no documents, is already running, or Claude declines.
    """

    settings, org_id = get_settings(), engagement["org_id"]
    if str(org_id) in _RUNNING:
        raise HTTPException(status_code=409, detail=_BUSY)
    _RUNNING.add(str(org_id))
    try:
        return await _prefill(request, user, engagement, db, sessions, settings)
    finally:
        _RUNNING.discard(str(org_id))


async def _prefill(request: Request, user: CurrentUser, engagement: dict[str, Any], db: AsyncSession,
                   sessions: async_sessionmaker[AsyncSession], settings: Settings) -> Any:
    org_id = engagement["org_id"]
    if not await ai_usage.try_lock_org(db, org_id):
        raise HTTPException(status_code=409, detail=_BUSY)
    candidates = await _candidates(db, engagement, user)
    code, reason = _gate(settings, await ai_usage.month_spend_microusd(db, org_id), candidates)
    if code is not None:
        raise HTTPException(status_code=409, detail=reason)
    client = new_client(settings)
    assert client is not None
    await db.commit()  # releases the connection and the lock before the slow part

    documents = await asyncio.to_thread(
        prefill.read_documents, candidates, storage=documents_api.current_upload_service().storage_service,
        parser=ParserService())
    if not any(d.lines for d in documents):
        raise HTTPException(status_code=409, detail="The company's summary documents could not be read. "
                                                    "Upload a readable copy of the report or methodology document.")
    started = time.monotonic()
    try:
        reply = await asyncio.to_thread(
            client.structured, system=prefill.SYSTEM_PROMPT, content=prefill.render_documents(documents),
            output_type=prefill.PrefillOutput, max_tokens=prefill.MAX_OUTPUT_TOKENS)
    except Exception as exc:  # network, auth, rate limit: no usage to record; the type only is logged
        logger.warning("methodology prefill: Claude call failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Claude could not be reached. Try again in a moment.") from exc
    cost_usd = round((reply.cost_microusd or 0) / ai_usage.MICRO, 6)
    ok = reply.outcome == "ok" and reply.output is not None
    async with _short_transaction(sessions, org_id) as ledger:  # committed whatever happens next
        await ai_usage.record(ledger, org_id=org_id, engagement_id=engagement["id"], feature=prefill.FEATURE,
                              provider=client.provider, reply=reply, user_id=user.id)
        if not ok:
            await _audit_prefill(ledger, request, user, engagement, {
                "outcome": reply.outcome, "documents": len(documents), "cost_usd": cost_usd})
    logger.info("methodology prefill: outcome=%s documents=%d cost_microusd=%s duration_ms=%d", reply.outcome,
                len(documents), reply.cost_microusd, int((time.monotonic() - started) * 1000))
    if not ok or reply.output is None:
        return JSONResponse(status_code=409, content={"detail": _FAILED.get(reply.outcome, _FAILED["invalid"])})
    try:
        verified, dropped = prefill.verify(reply.output, documents, model=reply.model, request_id=reply.request_id,
                                           now_iso=stamp(_now()))
        async with _short_transaction(sessions, org_id) as work:
            suggested, kept = await _store(work, engagement, user, verified, dropped)
            await _audit_prefill(work, request, user, engagement, {
                "outcome": "ok", "documents": len(documents), "suggested": suggested,
                "dropped": sum(dropped.values()), "kept_reviewer_decision": kept, "cost_usd": cost_usd})
    except Exception as exc:  # the call is already recorded; keep nothing and say so
        logger.error("methodology prefill: suggestions not saved (%s)", type(exc).__name__)
        try:
            async with _short_transaction(sessions, org_id) as failed:
                await _audit_prefill(failed, request, user, engagement, {
                    "outcome": "not_saved", "documents": len(documents), "cost_usd": cost_usd})
        except Exception as audit_exc:  # best effort
            logger.error("methodology prefill: audit not written (%s)", type(audit_exc).__name__)
        return JSONResponse(status_code=502, content={"detail": _NOT_SAVED})
    read = [{"document_id": d.document_id, "file_name": d.file_name, "truncated": d.truncated} for d in documents]
    return {"suggested": suggested, "dropped": dict(dropped), "kept_reviewer_decision": kept,
            "documents_read": read, "cost_usd": cost_usd, "model": reply.model}
