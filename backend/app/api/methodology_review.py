"""Methodology review: the reviewer's decisions on the client's stated boundary, categories,
exclusions, factor sources, GWP and calculation methods (the page's fields).

* GET    /v1/engagements/{id}/methodology-review                  fields, catalog, AI status (s1_reader)
* GET    /v1/engagements/{id}/methodology-review/auto-read        the automatic read of summary documents, if one is waiting or running (s1_reader)
* POST   /v1/engagements/{id}/methodology-review/{field_id}/accept  take the suggestion, or the current value
* POST   /v1/engagements/{id}/methodology-review/{field_id}/edit    {value}
* POST   /v1/engagements/{id}/methodology-review/{field_id}/reject  {reason}
* POST   /v1/engagements/{id}/methodology-review/{field_id}/revert  back to the previous value
* POST   /v1/engagements/{id}/methodology-review/rows               {group}: add an entity or factor row (201)
* DELETE /v1/engagements/{id}/methodology-review/{field_id}         remove a row the reviewer added
* GET    /v1/engagements/{id}/methodology-review/documents/{document_id}/locations  where each suggestion is printed on a PDF (s1_reader)

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
import contextlib
from contextlib import asynccontextmanager, contextmanager
import asyncio
import json
from collections import Counter
import logging
import re
import time
from datetime import UTC, datetime
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.adapters.llm.claude import (
    AiNotConfiguredError,
    ClaudeClient,
    StructuredReply,
    TokenUsage,
    get_claude,
)
from backend.app.api import documents as documents_api
from backend.app.api.engagements import _visible, require_open_engagement
from backend.app.api.evidence_tree import document_decisions
from backend.app.api.s1_access import can_see, s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.config import Settings, get_settings
from backend.app.core.db import get_db_session, get_sessionmaker_dependency, set_tenant
from backend.app.core.s1_scope import S1Scope, scoped
from backend.app.services import ai_usage, engagement_service
from backend.app.services import methodology_explanation as explanation
from backend.app.services import methodology_prefill as prefill
from backend.app.services import methodology_review as rules
from backend.app.services import quote_locator
from backend.app.services.methodology_gwp import EMBEDDED, use_of
from backend.app.services.document_file_types import served_type
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
    group: Literal["entities", "factor:scope1", "factor:scope2", "gwp"]


class _Declined(HTTPException):
    """The prefill did not start (busy, switched off, over the limit, nothing to read): 409 with a
    sentence, and ``code`` for the automatic read's record."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)
        self.code = code


class _HasId(Protocol):
    @property
    def id(self) -> uuid.UUID | None: ...


AUTOMATIC_ACTOR = "Sustentra's AI (automatic)"
# An automatic read's marker older than this is stale (the process that wrote it stopped): not shown.
AUTO_READ_FRESH_SECONDS = 600


@dataclass(frozen=True)
class _Caller:
    """Who a prefill is for when no signed-in user asked: Sustentra's AI itself (the automatic read).
    It has no user id (rows it writes carry none), sees its own organization's records, and is audited by name."""

    org_id: uuid.UUID
    id: uuid.UUID | None = None
    role: str | None = None

    def can_see(self, record: dict[str, Any]) -> bool:
        owner = record.get("org_id")
        return owner is not None and str(owner) == str(self.org_id)


def auto_read_view(marker: Any, claim: Any = None, now: datetime | None = None) -> dict[str, Any] | None:
    """What the page shows of an automatic read: ``{state, file_names, reason}`` while one is waiting or
    running, and a skip or failure with its sentence (all while recent), else nothing. A "reading" marker whose
    claim has not been renewed for CLAIM_TTL_SECONDS (or is gone) belongs to a process that stopped: it
    reads as a failure, "Reading was interrupted"."""

    if not isinstance(marker, dict) or marker.get("state") not in ("waiting", "reading", "skipped", "failed"):
        return None
    now = now or _now()
    state, reason = marker["state"], marker.get("reason")
    try:
        age = (now - datetime.fromisoformat(str(marker.get("at")).replace("Z", "+00:00"))).total_seconds()
        beat = datetime.fromisoformat(str((claim or {}).get("at")).replace("Z", "+00:00")) if isinstance(claim, dict) else None
    except ValueError:
        return None
    if age > AUTO_READ_FRESH_SECONDS:
        return None
    if state == "reading" and (beat is None or (now - beat).total_seconds() > CLAIM_TTL_SECONDS):
        state, reason = "failed", INTERRUPTED
    return {"state": state, "file_names": list(marker.get("file_names") or []), "reason": reason}


@contextmanager
def _rules() -> Iterator[None]:
    """Turn a refused move into 409 and malformed input into 422."""

    try:
        yield
    except MethodologyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MethodologyInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _public(record: dict[str, Any]) -> dict[str, Any]:
    """The record as the API returns it, with the explanation of its suggestion (why Sustentra's AI suggested it)."""

    out = rules.public(record)
    field = rules.catalog_field(str(record["field_id"])) or rules.row_field(str(record["field_id"]))
    if field is not None and isinstance(out.get("suggestion"), dict):
        out["explanation"] = explanation.explain(field, out["suggestion"])
    return out


def _now() -> datetime:
    return datetime.now(UTC)


def new_client(settings: Settings) -> ClaudeClient | None:
    """The Claude client, or None when this deployment has none set up (tests replace this)."""

    try:
        return get_claude(settings, timeout_s=prefill.REQUEST_TIMEOUT_S)
    except AiNotConfiguredError:
        return None


_CONFIG = "Sustentra's AI couldn't process this request (configuration)."


def _is_request_rejected(exc: BaseException) -> bool:
    """True when the provider answered 400 or 422: the request itself is wrong, so retrying cannot help."""

    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in (400, 401, 403, 404, 422)


def _reason(exc: BaseException) -> str:
    """A short, safe reason for the response: provider error type and the first 120 characters of its
    message (which describes the request, never the documents), with anything key-shaped removed."""

    if not isinstance(exc, anthropic.APIStatusError):
        return type(exc).__name__
    body: dict[str, Any] = exc.body if isinstance(exc.body, dict) else {}
    inner = body.get("error")
    error: dict[str, Any] = inner if isinstance(inner, dict) else body
    message = re.sub(r"sk-[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]{32,}", "[removed]", str(error.get("message", "")))
    kind = "billing" if "credit balance" in message.lower() else str(error.get("type") or exc.status_code)
    return f"{kind}: {message[:120]}".strip()


def _log_call_failure(exc: BaseException, part: str = "") -> None:
    """Exception type, and for a provider answer its status, error type, message and request id.

    The provider's message describes the request's shape (for example a schema limit), not the
    document; the prompt and the documents are never logged.
    """

    if isinstance(exc, anthropic.APIStatusError):
        body: dict[str, Any] = exc.body if isinstance(exc.body, dict) else {}
        inner = body.get("error")
        error: dict[str, Any] = inner if isinstance(inner, dict) else body
        logger.warning("methodology prefill: Claude call failed part=" + part + " (%s) status=%s error_type=%s request_id=%s message=%s",
                       type(exc).__name__, exc.status_code, error.get("type"), exc.request_id,
                       str(error.get("message", ""))[:500])
    else:
        logger.warning("methodology prefill: Claude call failed part=%s (%s)", part, type(exc).__name__)


def _combine(results: list[prefill.PartResult]) -> tuple[StructuredReply[prefill.PrefillOutput] | None, list[dict[str, str]]]:
    """The three calls as one reply (for the ledger and ``verify``), and the sections that gave nothing.

    The reply is "ok" when at least one part is; otherwise it carries the first part's outcome. None
    when every call raised. Usage and cost are the sum of the calls that were answered.
    """

    failed: list[dict[str, str]] = []
    replies: list[StructuredReply[Any]] = []
    for result in results:
        label = prefill.PART_LABELS[result.part]
        if result.reply is None:
            failed.append({"section": label, "reason": _reason(result.error) if result.error else "no answer"})
        elif result.reply.outcome == "ok" and result.reply.output is not None:
            replies.append(result.reply)
        else:
            failed.append({"section": label, "reason": result.reply.outcome})
            replies.append(result.reply)
    if not replies:
        return None, failed
    good = {r.part: r.reply.output for r in results if r.reply and r.reply.outcome == "ok" and r.reply.output is not None}
    first = next((r for r in replies if r.outcome == "ok"), replies[0])
    costs = [r.cost_microusd for r in replies]
    usage = sum((r.usage for r in replies), TokenUsage())
    combined = StructuredReply(
        outcome=first.outcome, output=prefill.merge_parts(good) if good else None, model=first.model, usage=usage,
        cost_microusd=None if any(c is None for c in costs) else sum(c for c in costs if c is not None),
        request_id=first.request_id, stop_reason=first.stop_reason, refusal_category=first.refusal_category)
    return combined, failed


def _gate(settings: Settings, spent_microusd: int, candidates: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Why Claude cannot be asked now (code, sentence), or (None, None)."""

    if not settings.ai_suggestions_enabled:
        return "off", "Suggestions from the documents are switched off for this deployment."
    if new_client(settings) is None:
        return "not_configured", ("Suggestions from the documents are switched on, but Sustentra's AI is not set up "
                                  "for this deployment. Contact support.")
    if ai_usage.cap_reached(spent_microusd, settings.ai_monthly_cap_usd):
        return "cap_reached", (f"This month's limit on suggestions (${settings.ai_monthly_cap_usd:,.2f}) has been "
                               "reached. They are available again next month, or the limit can be raised.")
    if not candidates:
        return "no_documents", prefill.NO_DOCUMENTS
    return None, None


async def _candidates(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser | _Caller
                      ) -> list[dict[str, Any]]:
    """The documents Claude would read: summary documents the reviewer has not set aside."""

    sees = user.can_see if isinstance(user, _Caller) else (lambda record: can_see(record, user))
    return prefill.candidate_documents(
        documents_api.current_upload_service(), documents_api.current_pipeline_service(),
        str(engagement["id"]), sees, await document_decisions(db, engagement))


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


async def _update_meta(db: AsyncSession, engagement: dict[str, Any], user: _HasId, *,
                       prefill_ran_at: str | None = None, covered: list[str] | None = None,
                       reveal: str | None = None, auto_read: dict[str, Any] | None = None) -> None:
    """The page-state item (prefill marker, revealed rows), created on first use and locked while
    it is changed."""

    await workpaper_item_service.insert_item(
        db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=rules.META_KEY,
        payload=rules.new_meta(), user_id=user.id)
    [row] = await workpaper_item_service.get_items(db, engagement["id"], KIND, [rules.META_KEY], for_update=True)
    meta = {**rules.new_meta(), **row["payload"]}
    if prefill_ran_at:
        meta["prefill_ran_at"] = prefill_ran_at
        meta["prefill_covered"] = covered or []
    if reveal and reveal not in meta["revealed"]:
        meta["revealed"] = [*meta["revealed"], reveal]
    if auto_read is not None:
        meta["auto_read"] = auto_read
    await workpaper_item_service.update_payload(db, engagement["id"], KIND, rules.META_KEY, meta, user.id)


async def _save(db: AsyncSession, engagement: dict[str, Any], field_id: str, record: dict[str, Any],
                user: CurrentUser) -> dict[str, Any]:
    if workpaper_item_service.payload_size(record) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=422,
            detail="This field's history is too long to record another change. Contact support if you need more.")
    row = await workpaper_item_service.update_payload(db, engagement["id"], KIND, field_id, record, user.id)
    return row["payload"]


async def _audit(db: AsyncSession, request: Request, user: CurrentUser, engagement: dict[str, Any],
                 field_id: str, action: str, status: str | None, restored: str | None = None) -> None:
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
        # never a value or reason; a revert also says what it restored: previous, detected or empty
        metadata={"field_id": field_id, "action": action, "status": status, **({"restored": restored} if restored else {})},
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
    meta = {**rules.new_meta(), **stored.get(rules.META_KEY, {})}
    fields = []
    for f in rules.CATALOG:
        record = stored.get(f["field_id"]) or rules.new_record(f["field_id"])
        item = {**_public(record), "display_state": rules.display_state(record, meta),
                "shown": rules.is_shown(f, record, meta, stored)}
        note = rules.shown_note(f, record, meta, stored)
        if note:
            item["shown_note"] = note
        fields.append(item)
    catalog = [dict(f) for f in rules.CATALOG]
    for key, record in stored.items():  # rows the reviewer added, oldest first
        definition = rules.row_field(key)
        if definition is not None and not record.get("removed"):
            definition["user_added"] = bool(record.get("user_added"))  # the record's flag is the truth
            fields.append({**_public(record), "display_state": rules.HAS_VALUE, "shown": True})
            catalog.append(definition)
    return {
        "prefill_ran_at": meta.get("prefill_ran_at"),
        "auto_read": auto_read_view(meta.get("auto_read"), meta.get("claim")),
        "fields": fields,
        "catalog": catalog,
        "groups": [{"group": g, "label": label} for g, label in rules.GROUPS],
        "row_groups": list(rules.ROW_GROUPS),
        "ai": await ai_status(db, engagement, user),
    }


@router.get("/engagements/{engagement_id}/methodology-review/auto-read", response_model=dict[str, Any])
async def get_auto_read(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Whether Sustentra's AI is about to read, or reading, this engagement's summary documents by itself
    (``{state: waiting | reading | skipped, file_names, reason}``), else ``null``. Small: the Evidence page polls it."""

    engagement = await _visible(db, engagement_id, user)
    found = await workpaper_item_service.get_items(db, engagement["id"], KIND, [rules.META_KEY])
    payload = found[0]["payload"] if found else {}
    return {"auto_read": auto_read_view(payload.get("auto_read"), payload.get("claim"))}


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
    restored = (saved.get("history") or [{}])[-1].get("restored") if action == "revert" else None
    await _audit(db, request, user, engagement, field_id, action, rules.status_of(saved), restored=restored)
    return _public(saved)


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
    return {**_public(row["payload"]), "field": {**(rules.row_field(field_id) or {}), "user_added": True}}


@router.post("/engagements/{engagement_id}/methodology-review/{field_id}/reveal", response_model=dict[str, Any])
async def reveal_field(
    field_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """"Add an item": show a hidden optional row, ready for a value. Remembered per engagement."""

    field = rules.catalog_field(field_id) if ITEM_KEY.match(field_id) else None
    if field is None:
        raise _NOT_FOUND
    if field.get("required", True):
        raise HTTPException(status_code=422, detail=f"'{field['label']}' is always shown, so there is nothing to add.")
    await _update_meta(db, engagement, user, reveal=field_id)
    await _audit(db, request, user, engagement, field_id, "reveal", None)
    return {"field_id": field_id, "shown": True}


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
    return {**_public(saved), "removed": True}


@router.get("/engagements/{engagement_id}/methodology-review/documents/{document_id}/locations",
            response_model=dict[str, Any])
async def document_locations(
    engagement_id: str,
    document_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Where each methodology suggestion read from this document is printed on it, so the viewer can
    highlight it. Located from the PDF's own text layer (``quote_locator``): a quote that is not printed
    on its page comes back ``located: false``, never placed approximately. Reads the stored suggestions only."""

    engagement = await _visible(db, engagement_id, user)
    upload = documents_api.current_upload_service()
    document = next((d for d in upload.list_documents(str(engagement["id"]))
                     if str(d.get("document_id")) == document_id and can_see(d, user)), None)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    path = None
    storage_uri = str(document.get("storage_uri") or "")
    owner = document.get("org_id")
    try:
        if owner is None or upload.storage_service.is_owned_by(storage_uri, str(owner)):
            candidate = upload.storage_service.resolve_storage_uri(storage_uri)
            path = candidate if candidate.is_file() else None
    except ValueError:
        path = None
    is_pdf = path is not None and served_type(path, document.get("file_name")).media_type == "application/pdf"
    items: list[dict[str, Any]] = []
    for row in await workpaper_item_service.list_items(db, engagement["id"], KIND):
        if row["payload"].get("removed"):
            continue
        for source in quote_locator.sources_on_document(row["payload"], document_id):
            placed = quote_locator.locate_on_pdf(path, source["quote"], source["page"]) if is_pdf and path else None
            items.append({"field_id": row["item_key"], "entry": source["entry"], "page": placed.page if placed else source["page"],
                          "located": placed is not None, "rects": placed.rects if placed else []})
    return {"document_id": document_id, "items": items}


# --- Claude's suggestions ---------------------------------------------------------------------

logger = logging.getLogger(__name__)

_FAILED = {
    "refused": "Sustentra's AI declined to read these documents. Nothing was changed.",
    "incomplete": "The AI's answer was cut short, so none of it was kept. Try again.",
    "invalid": "The AI's answer could not be read, so none of it was kept. Try again.",
}


async def _store(db: AsyncSession, engagement: dict[str, Any], user: _HasId,
                 verified: list[prefill.Verified], dropped: Counter[str]) -> tuple[int, int]:
    """Put each verified suggestion on its field's record: (suggested, kept_reviewer_decision).
    A field the reviewer has decided is left alone. An entity or factor source already on the
    page (suggested or decided), or already added by an earlier suggestion of this same reply, is
    not added again; a new one becomes a new row. A value the store refuses (too long for the
    record) is counted in ``dropped`` as invalid_value."""

    suggested = kept = 0
    fixed = {v.field_id: v for v in verified if v.field_id}
    # GWP: the report may name several sets. The fixed field takes one and every other is a row, whatever
    # the order of this reply: a pending suggestion keeps its set if this run still found it, and a set that
    # is already on a row never goes into the fixed field as well.
    gwp_all = [fixed.pop("gwp")] if "gwp" in fixed else []
    gwp_all += [v for v in verified if v.row_group == "gwp"]
    # A set the document only mentions inside other factors, or as the exception to its method, is information: it
    # is a row, whatever slot the reply (or the verifier) put it in, and never the fixed field.
    info_only = lambda g: use_of(g.suggestion["value"].get("applies_to")) == EMBEDDED  # noqa: E731
    gwp_items = [g for g in gwp_all if not info_only(g)]
    if gwp_all:
        fixed["gwp"] = gwp_items[0] if gwp_items else gwp_all[0]  # a record for the fixed field, so it can be locked and read
    for field_id in fixed:
        await workpaper_item_service.insert_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=field_id,
            payload=rules.new_record(field_id), user_id=user.id)
    locked = {row["item_key"]: row["payload"] for row in await workpaper_item_service.get_items(
        db, engagement["id"], KIND, list(fixed), for_update=True)}
    stored_rows = [row for row in await workpaper_item_service.list_items(db, engagement["id"], KIND)
                   if row["item_key"].startswith("gwp:") and not row["payload"].get("removed")]
    row_values = [v for row in stored_rows for v in ((row["payload"].get("suggestion") or {}).get("value"),
                                                      (row["payload"].get("decision") or {}).get("value"))]
    same = lambda a, b: prefill.same_row_value("gwp", a, b)  # noqa: E731
    moved: list[prefill.Verified] = []  # the GWP sets that are not the fixed field's
    gwp_fixed_values: list[Any] = []
    if gwp_all:
        record = locked["gwp"]
        if rules.status_of(record) != rules.PENDING:
            # The decision's value, and the set that was suggested when it was decided: a rejected field has
            # no value, but the set it rejected must never come back as a row.
            decided = (record.get("decision") or {}).get("value")
            suggested_then = (record.get("suggestion") or {}).get("value")
            gwp_fixed_values += [decided, suggested_then]
            held = lambda g: same(decided, g.suggestion["value"]) or same(suggested_then, g.suggestion["value"])  # noqa: E731
            if any(held(g) for g in gwp_items):
                kept += 1
            moved = [prefill.Verified(None, "gwp", g.suggestion) for g in gwp_all if not held(g)]
            fixed.pop("gwp")
        else:
            current = (record.get("suggestion") or {}).get("value")
            chosen = next((g for g in gwp_items if current and same(current, g.suggestion["value"])), None) or next(
                (g for g in gwp_items if not any(same(v, g.suggestion["value"]) for v in row_values)), None)
            if chosen is None:
                fixed.pop("gwp")
                stale = (record.get("suggestion") or {}).get("value")
                if isinstance(stale, dict) and use_of(stale.get("applies_to")) == EMBEDDED:
                    # An earlier read put an information-only set in the fixed field: with no default found now,
                    # the field is empty again (the set stays as a row below).
                    await workpaper_item_service.update_payload(
                        db, engagement["id"], KIND, "gwp", {k: v for k, v in record.items() if k != "suggestion"}, user.id)
            else:
                fixed["gwp"] = chosen
                gwp_fixed_values.append(chosen.suggestion["value"])
            moved = [prefill.Verified(None, "gwp", g.suggestion) for g in gwp_all if g is not chosen]
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
    for item in [*(v for v in verified if v.row_group and v.row_group != "gwp"), *moved]:
        group = str(item.row_group)
        value = item.suggestion["value"]
        if group == "gwp" and any(prefill.same_row_value(group, mine, value) for mine in gwp_fixed_values):
            continue  # the fixed GWP field already holds this set
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


async def _audit_prefill(db: AsyncSession, request: Request | None, user: CurrentUser | _Caller,
                         engagement: dict[str, Any], metadata: dict[str, Any]) -> None:
    if request is None:  # the automatic read: no request, no person; the event names its actor
        metadata = {**metadata, "actor": AUTOMATIC_ACTOR, "automatic": True}
    await write_audit_event(
        db, "methodology_prefill", org_id=engagement["org_id"], actor_user_id=user.id, actor_role=user.role,
        target_type="engagement", target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None) if request else None,
        ip_address=(request.client.host if request.client else None) if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata=metadata)  # counts and cost only


@asynccontextmanager
async def _short_transaction(sessions: async_sessionmaker[AsyncSession], org_id: Any) -> AsyncIterator[AsyncSession]:
    """Its own short transaction in the organization's RLS scope, committed on exit."""

    async with sessions() as session, session.begin():
        await set_tenant(session, org_id)
        yield session


# Engagements with a prefill running in this process: a double click answers 409 instead of a second
# billed call. Across processes the claim below (``_claim``, in the database) does the same.
_RUNNING: set[str] = set()
_BUSY = "Suggestions are already being prepared for this engagement. Try again in a minute."
# A read renews its claim every HEARTBEAT_SECONDS; a claim not renewed for CLAIM_TTL_SECONDS belongs to a
# process that stopped, and is free (so is the "reading" marker it left: it reads as interrupted).
HEARTBEAT_SECONDS = 15.0
CLAIM_TTL_SECONDS = 60
# The automatic read finding the engagement busy waits for the current read to end (looking every
# BUSY_POLL_SECONDS, at most BUSY_WAIT_SECONDS) and tries once more.
BUSY_POLL_SECONDS = 2.0
BUSY_WAIT_SECONDS = 300.0
INTERRUPTED = "Reading was interrupted. Try again."

_CLAIM = text("""
    UPDATE workpaper_items
       SET payload = jsonb_set(payload, '{claim}', jsonb_build_object('by', CAST(:by AS text), 'at', to_jsonb(now()))),
           updated_at = now()
     WHERE engagement_id = :eid AND kind = :kind AND item_key = :key
       AND (payload->'claim' IS NULL OR jsonb_typeof(payload->'claim') = 'null'
            OR (payload->'claim'->>'at')::timestamptz < now() - make_interval(secs => :ttl))
 RETURNING 1""")
_BEAT = text("""
    UPDATE workpaper_items SET payload = jsonb_set(payload, '{claim,at}', to_jsonb(now()))
     WHERE engagement_id = :eid AND kind = :kind AND item_key = :key AND payload->'claim'->>'by' = :by""")
_RELEASE = text("""
    UPDATE workpaper_items SET payload = payload - 'claim'
     WHERE engagement_id = :eid AND kind = :kind AND item_key = :key AND payload->'claim'->>'by' = :by""")
_FREE = text("""
    SELECT NOT EXISTS (SELECT 1 FROM workpaper_items
     WHERE engagement_id = :eid AND kind = :kind AND item_key = :key AND payload->'claim' IS NOT NULL
       AND jsonb_typeof(payload->'claim') <> 'null'
       AND (payload->'claim'->>'at')::timestamptz >= now() - make_interval(secs => :ttl))""")


def _claim_params(engagement: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"eid": engagement["id"], "kind": KIND, "key": rules.META_KEY, **extra}


async def _claim(sessions: async_sessionmaker[AsyncSession], engagement: dict[str, Any], token: str) -> bool:
    """Take the engagement's read claim (compare-and-set on the page-state item, committed at once, so
    every process sees it): true when it was free or expired. Only one caller can hold it."""

    async with _short_transaction(sessions, engagement["org_id"]) as db:
        await workpaper_item_service.insert_item(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], kind=KIND, item_key=rules.META_KEY,
            payload=rules.new_meta(), user_id=None)
        got = (await db.execute(_CLAIM, _claim_params(engagement, by=token, ttl=CLAIM_TTL_SECONDS))).first()
    return got is not None


async def _claim_free(sessions: async_sessionmaker[AsyncSession], engagement: dict[str, Any]) -> bool:
    async with _short_transaction(sessions, engagement["org_id"]) as db:
        return bool((await db.execute(_FREE, _claim_params(engagement, ttl=CLAIM_TTL_SECONDS))).scalar())


async def _heartbeat(sessions: async_sessionmaker[AsyncSession], engagement: dict[str, Any], token: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            async with _short_transaction(sessions, engagement["org_id"]) as db:
                await db.execute(_BEAT, _claim_params(engagement, by=token))
        except Exception as exc:  # the read goes on; the claim just may expire
            logger.error("methodology prefill: heartbeat failed (%s)", type(exc).__name__)


@asynccontextmanager
async def _claimed(sessions: async_sessionmaker[AsyncSession], engagement: dict[str, Any]) -> AsyncIterator[None]:
    """One read of the engagement at a time, in this process (``_RUNNING``) and across processes (the claim,
    renewed while the read lasts, released at the end). Another read in flight: ``_Declined("busy")``."""

    key = str(engagement["id"])
    if key in _RUNNING:
        raise _Declined("busy", _BUSY)
    _RUNNING.add(key)
    try:
        token = uuid.uuid4().hex
        if not await _claim(sessions, engagement, token):
            raise _Declined("busy", _BUSY)
        beat = asyncio.ensure_future(_heartbeat(sessions, engagement, token))
        try:
            yield
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
            try:
                async with _short_transaction(sessions, engagement["org_id"]) as db:
                    await db.execute(_RELEASE, _claim_params(engagement, by=token))
            except Exception as exc:  # it expires on its own
                logger.error("methodology prefill: claim not released (%s)", type(exc).__name__)
    finally:
        _RUNNING.discard(key)


_NOT_SAVED = ("Sustentra's AI answered, but its suggestions could not be saved, so none were kept. "
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

    Race safety: one read per engagement at a time, in this process and across processes (the claim in
    the database, ``_claimed``): a second caller answers 409 and makes no call. The cap is read after
    the previous call's ledger row, under the organization's advisory lock; reads of different
    engagements of one organization may overlap, so the cap can be passed by at most one call per
    engagement in flight. Answers 409 with a sentence when it is switched off, over the monthly limit,
    has no documents, is already running, or Claude declines.
    """

    async with _claimed(sessions, engagement):
        return await _prefill(request, user, engagement, db, sessions, get_settings())


async def _prefill(request: Request | None, user: CurrentUser | _Caller, engagement: dict[str, Any],
                   db: AsyncSession, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> Any:
    org_id = engagement["org_id"]
    if not await ai_usage.try_lock_org(db, org_id):
        raise _Declined("busy", _BUSY)
    candidates = await _candidates(db, engagement, user)
    code, reason = _gate(settings, await ai_usage.month_spend_microusd(db, org_id), candidates)
    if code is not None:
        raise _Declined(code, str(reason))
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
    results = await asyncio.to_thread(prefill.run_parts, client, documents)
    for result in results:
        if result.error is not None:  # no usage to record; type, status and provider message are logged, never content
            _log_call_failure(result.error, result.part)
    reply, failed_sections = _combine(results)
    if reply is None:  # every call raised: nothing was billed
        errors = [r.error for r in results if r.error is not None]
        rejected = next((e for e in errors if _is_request_rejected(e)), None)
        if rejected is not None:
            raise HTTPException(status_code=500, detail=f"{_CONFIG[:-1]} (provider: {_reason(rejected)}).") from rejected
        raise HTTPException(
            status_code=502, detail=f"Sustentra's AI could not be reached. Try again in a moment. ({_reason(errors[0])})"
        ) from errors[0]
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
        for entry in dropped.detail:  # codes and locations only, never the document's words
            logger.info("methodology prefill: set aside field=%s reason=%s line=%s", entry["field"], entry["reason"],
                        entry["line"])
        async with _short_transaction(sessions, org_id) as work:
            suggested, kept = await _store(work, engagement, user, verified, dropped)
            await _update_meta(work, engagement, user, prefill_ran_at=stamp(_now()),
                               covered=[f["field_id"] for f in rules.CATALOG],
                               auto_read={"state": "done", "file_names": [], "reason": None, "at": stamp(_now())})
            await _audit_prefill(work, request, user, engagement, {
                "outcome": "ok", "documents": len(documents), "suggested": suggested,
                "dropped": sum(dropped.values()), "kept_reviewer_decision": kept, "cost_usd": cost_usd,
                **({"failed_sections": [f["section"] for f in failed_sections]} if failed_sections else {})})
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
    return {"suggested": suggested, "dropped": dict(dropped), "dropped_detail": dropped.detail,
            "kept_reviewer_decision": kept,
            "documents_read": read, "cost_usd": cost_usd, "model": reply.model, "failed_sections": failed_sections}


# --- the automatic read ---------------------------------------------------------------------------
# Started by services/auto_read.py after a summary document finishes reading and the engagement has
# had no new one for the debounce time. It is the button's own code path (``_prefill``) with Sustentra's
# AI as the caller: the same busy lock, the same switch, client and monthly cap check (``_gate``), the
# same usage ledger, and ``_store`` never overwrites a reviewer's decision (``kept_reviewer_decision``).

@dataclass(frozen=True)
class AutoReadResult:
    state: Literal["done", "skipped", "failed"]
    reason_code: str | None = None
    reason: str | None = None


async def _mark_auto_read(sessions: async_sessionmaker[AsyncSession], caller: _Caller, engagement: dict[str, Any],
                          state: str, file_names: list[str], reason: str | None = None) -> None:
    """The page's "Sustentra's AI is reading ..." marker (engagement page state), in its own transaction."""

    async with _short_transaction(sessions, engagement["org_id"]) as db:
        await _update_meta(db, engagement, caller, auto_read={
            "state": state, "file_names": file_names, "reason": reason, "at": stamp(_now())})


async def _auto_read_context(sessions: async_sessionmaker[AsyncSession], caller: _Caller, engagement_id: str
                            ) -> tuple[dict[str, Any] | None, bool | None]:
    """The engagement (None when it is gone or closed) and the organization's switch."""

    async with _short_transaction(sessions, caller.org_id) as db:
        engagement = await engagement_service.get_engagement(db, engagement_id)
        enabled = (await db.execute(text("SELECT auto_read_summaries FROM organizations WHERE id = :id"),
                                    {"id": caller.org_id})).scalar()
    if engagement is None or engagement["status"] != "active":
        return None, enabled
    return engagement, enabled


async def prepare_automatic_prefill(org_id: str, engagement_id: str, file_names: list[str],
                                    sessions: async_sessionmaker[AsyncSession]) -> bool:
    """Before the debounce wait: false (and nothing shown) when the organization switched the automatic
    read off or the engagement is closed; else the page says Sustentra's AI will read the documents shortly."""

    caller = _Caller(org_id=uuid.UUID(str(org_id)))
    engagement, enabled = await _auto_read_context(sessions, caller, engagement_id)
    if engagement is None or enabled is False:
        return False
    await _mark_auto_read(sessions, caller, engagement, "waiting", file_names)
    return True


async def run_automatic_prefill(org_id: str, engagement_id: str, file_names: list[str],
                                sessions: async_sessionmaker[AsyncSession],
                                settings: Settings | None = None) -> AutoReadResult:
    """Read the engagement's summary documents as Sustentra's AI. Skips, and records why (the page
    marker and an audit event), when the organization switched it off, the engagement is closed, a
    prefill is already running, or the gate says no (switch, client, monthly limit, no documents)."""

    settings = settings or get_settings()
    caller = _Caller(org_id=uuid.UUID(str(org_id)))
    with scoped(S1Scope.tenant(caller.org_id)):
        engagement, enabled = await _auto_read_context(sessions, caller, engagement_id)
        if engagement is None:
            return AutoReadResult("skipped", "engagement_unavailable", "The engagement is closed or gone.")
        if enabled is False:
            await _mark_auto_read(sessions, caller, engagement, "skipped", file_names, None)
            return AutoReadResult("skipped", "setting_off", "Reading summary documents automatically is off.")
        outcome = await _read_when_free(sessions, caller, engagement, file_names, settings)
        return outcome


async def _read_when_free(sessions: async_sessionmaker[AsyncSession], caller: _Caller, engagement: dict[str, Any],
                          file_names: list[str], settings: Settings) -> AutoReadResult:
    """Claim the engagement and read. Busy (the button, or a read in another process): wait for that read to
    end and try once more, so a document that arrived meanwhile is not lost; busy again: skip, and say so."""

    for attempt in (1, 2):
        try:
            async with _claimed(sessions, engagement):
                await _mark_auto_read(sessions, caller, engagement, "reading", file_names)
                async with sessions() as db, db.begin():
                    await set_tenant(db, caller.org_id)
                    answer = await _prefill(None, caller, engagement, db, sessions, settings)
                if isinstance(answer, JSONResponse):  # the call was made but gave nothing, or nothing was saved
                    detail = json.loads(bytes(answer.body)).get("detail")
                    await _mark_auto_read(sessions, caller, engagement, "failed", file_names, str(detail))
                    return AutoReadResult("failed", "not_saved", str(detail))
                await _mark_auto_read(sessions, caller, engagement, "done", file_names)
                return AutoReadResult("done")
        except _Declined as exc:
            if exc.code == "busy" and attempt == 1 and await _wait_until_free(sessions, engagement):
                await _mark_auto_read(sessions, caller, engagement, "waiting", file_names)
                continue
            await _record_auto_read_skip(sessions, caller, engagement, file_names, exc.code, str(exc.detail), "skipped")
            return AutoReadResult("skipped", exc.code, str(exc.detail))
        except HTTPException as exc:
            state = "skipped" if exc.status_code == 409 else "failed"
            code = "not_read" if exc.status_code == 409 else "error"
            await _record_auto_read_skip(sessions, caller, engagement, file_names, code, str(exc.detail), state)
            return AutoReadResult(state, code, str(exc.detail))  # type: ignore[arg-type]
        except Exception as exc:  # never raises into the scheduler; the type only is logged
            logger.error("methodology auto read: failed (%s)", type(exc).__name__)
            reason = "Sustentra's AI could not read the documents automatically."
            await _record_auto_read_skip(sessions, caller, engagement, file_names, "error", reason, "failed")
            return AutoReadResult("failed", "error", reason)
    raise AssertionError("unreachable")


async def _wait_until_free(sessions: async_sessionmaker[AsyncSession], engagement: dict[str, Any]) -> bool:
    """Wait for the read in flight to end: true when the engagement is free, false after BUSY_WAIT_SECONDS."""

    waited = 0.0
    while waited <= BUSY_WAIT_SECONDS:
        if str(engagement["id"]) not in _RUNNING and await _claim_free(sessions, engagement):
            return True
        await asyncio.sleep(BUSY_POLL_SECONDS)
        waited += BUSY_POLL_SECONDS
    return False


async def _record_auto_read_skip(sessions: async_sessionmaker[AsyncSession], caller: _Caller,
                                 engagement: dict[str, Any], file_names: list[str], code: str, reason: str,
                                 state: str) -> None:
    try:
        async with _short_transaction(sessions, caller.org_id) as db:
            await _audit_prefill(db, None, caller, engagement, {
                "outcome": state, "reason_code": code, "documents": len(file_names)})
        await _mark_auto_read(sessions, caller, engagement, state, file_names, reason)
    except Exception as exc:  # best effort: the read itself is already decided
        logger.error("methodology auto read: skip not recorded (%s)", type(exc).__name__)
