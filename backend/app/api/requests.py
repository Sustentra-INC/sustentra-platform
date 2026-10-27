"""MVP-86 (DB-010): evidence requests change only through these actions, which check the
request's state, number sent requests and record who acted.

* POST  /v1/engagements/{id}/requests                    raise a request (201)
* PATCH /v1/engagements/{id}/requests/{ask_id}           change its text while not yet sent
* POST  /v1/engagements/{id}/requests/send               send asks together as one numbered request
* POST  /v1/engagements/{id}/requests/{ask_id}/resolve
* POST  /v1/engagements/{id}/requests/{ask_id}/withdraw

The rules are in ``request_service``; a move they refuse answers 409 with a sentence for
the user and writes nothing. Requests stay in ``workpaper_items`` (kind ``ask``) with the
frontend's payload shape, so GET .../workpaper-items, the Excel export and the assistant
read them unchanged. Request numbers are the engagement's highest number plus one, taken
under a per-engagement advisory lock, so two people sending at once get different
numbers. Each action writes one audit event carrying ids and the request number, never
the request's text, reason, link or note.

All routes are s1_writer: another org's engagement answers 404, a provider_admin 403 and
an archived engagement 409. Bodies forbid unknown fields, so a client cannot set the
state, the numbers, the history or who raised a request.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.engagements import require_open_engagement
from backend.app.api.s1_access import s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import request_service, workpaper_item_service
from backend.app.services.audit_log import write_audit_event
from backend.app.services.request_service import RequestConflict, RequestInvalid
from backend.app.services.workpaper_item_service import ITEM_KEY, MAX_PAYLOAD_BYTES

router = APIRouter(prefix="/v1", tags=["requests"])

KIND = "ask"
_NOT_FOUND = HTTPException(status_code=404, detail="Request not found.")


def _item_key(value: str) -> str:
    if not ITEM_KEY.match(value):
        raise ValueError("letters, digits and : . _ - only (max 200)")
    return value


AskId = Annotated[str, AfterValidator(_item_key)]
RequestType = Literal["missing_document", "replace_document", "missing_data", "clarify", "confirm_or_restate"]
AskOrigin = Literal["workspace_document", "review_value", "expected_item", "data_point"]
# Text a person writes: surrounding spaces removed; the required ones must not be blank.
WhatIsNeeded = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ItemLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Ref = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskSourceIn(_Body):
    origin: AskOrigin
    documentId: Ref | None = None
    fieldKey: Ref | None = None
    itemLabel: ItemLabel
    facilityName: Short | None = None
    period: Short | None = None
    sourcePage: Annotated[int, Field(ge=1)] | None = None
    arrival: Short | None = None


class RequestCreate(_Body):
    id: AskId
    type: RequestType
    whatIsNeeded: WhatIsNeeded
    source: AskSourceIn
    linkedFromAskId: AskId | None = None


class RequestEdit(_Body):
    whatIsNeeded: WhatIsNeeded


class RequestSend(_Body):
    askIds: list[AskId] = Field(min_length=1, max_length=200)
    lineNumbers: dict[str, StrictInt] | None = None

    @field_validator("askIds")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("each request may appear only once")
        return value


class RequestResolve(_Body):
    link: Long | None = None
    note: Long | None = None

    @field_validator("link", "note")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class RequestWithdraw(_Body):
    reason: Reason


class SentRequest(BaseModel):
    requestNumber: int
    sentAt: str
    askIds: list[str]
    asks: list[dict[str, Any]]


@contextmanager
def _rules() -> Iterator[None]:
    """Turn a refused move into 409 and malformed input into 422."""

    try:
        yield
    except RequestConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RequestInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _now() -> datetime:
    return datetime.now(UTC)


async def _locked(db: AsyncSession, engagement: dict[str, Any], ask_id: str) -> dict[str, Any]:
    """The request's payload, locked until the transaction ends (404 if there is none)."""

    if not ITEM_KEY.match(ask_id):
        raise _NOT_FOUND
    rows = await workpaper_item_service.get_items(db, engagement["id"], KIND, [ask_id], for_update=True)
    if not rows:
        raise _NOT_FOUND
    return rows[0]["payload"]


async def _save(
    db: AsyncSession, engagement: dict[str, Any], ask_id: str, ask: dict[str, Any], user: CurrentUser
) -> dict[str, Any]:
    if workpaper_item_service.payload_size(ask) > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=422,
            detail="This request's history is too long to record another change. "
                   "Withdraw it and add a new request instead.",
        )
    row = await workpaper_item_service.update_payload(db, engagement["id"], KIND, ask_id, ask, user.id)
    return row["payload"]


async def _audit(
    db: AsyncSession,
    request: Request,
    user: CurrentUser,
    engagement: dict[str, Any],
    event_type: str,
    metadata: dict[str, Any],
) -> None:
    await write_audit_event(
        db,
        event_type,
        org_id=engagement["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata=metadata,  # ids and numbers only, never the request's text
    )


@router.post("/engagements/{engagement_id}/requests", status_code=201, response_model=dict[str, Any])
async def create_request(
    body: RequestCreate,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    if body.linkedFromAskId is not None:
        rows = await workpaper_item_service.get_items(db, engagement["id"], KIND, [body.linkedFromAskId])
        with _rules():
            request_service.check_follow_up(rows[0]["payload"] if rows else None)
    ask = request_service.new_ask(body.id, body.model_dump(), request_service.actor_of(user), _now())
    row = await workpaper_item_service.insert_item(
        db,
        org_id=engagement["org_id"],
        engagement_id=engagement["id"],
        kind=KIND,
        item_key=body.id,
        payload=ask,
        user_id=user.id,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="A request with this id already exists.")
    await _audit(db, request, user, engagement, "request_created", {
        "ask_id": body.id,
        "type": body.type,
        "origin": body.source.origin,
        "follow_up_of": body.linkedFromAskId,
    })
    return row["payload"]


@router.post("/engagements/{engagement_id}/requests/send", response_model=SentRequest)
async def send_requests(
    body: RequestSend,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> SentRequest:
    # The numbering lock first, then the rows in key order: see lock_request_numbers.
    await workpaper_item_service.lock_request_numbers(db, engagement["id"])
    rows = await workpaper_item_service.get_items(db, engagement["id"], KIND, body.askIds, for_update=True)
    found = {row["item_key"]: row["payload"] for row in rows}
    missing = [ask_id for ask_id in body.askIds if ask_id not in found]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"There is no request '{missing[0]}' in this engagement, so nothing was sent. "
                   "Reload the page to see the current requests.",
        )
    number = await workpaper_item_service.next_request_number(db, engagement["id"])
    now = _now()
    with _rules():
        sent = request_service.send(
            {ask_id: found[ask_id] for ask_id in body.askIds},
            number,
            body.lineNumbers,
            request_service.actor_of(user),
            now,
        )
    asks = [await _save(db, engagement, ask_id, ask, user) for ask_id, ask in sent.items()]
    await _audit(db, request, user, engagement, "request_sent", {
        "request_number": number,
        "ask_ids": body.askIds,
        "count": len(body.askIds),
    })
    return SentRequest(requestNumber=number, sentAt=request_service.stamp(now), askIds=body.askIds, asks=asks)


@router.patch("/engagements/{engagement_id}/requests/{ask_id}", response_model=dict[str, Any])
async def edit_request(
    ask_id: str,
    body: RequestEdit,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    ask = await _locked(db, engagement, ask_id)
    with _rules():
        edited = request_service.edit(ask, body.whatIsNeeded, request_service.actor_of(user), _now())
    if edited is None:  # the same text: nothing to record
        return ask
    saved = await _save(db, engagement, ask_id, edited, user)
    await _audit(db, request, user, engagement, "request_edited", {"ask_id": ask_id})
    return saved


@router.post("/engagements/{engagement_id}/requests/{ask_id}/resolve", response_model=dict[str, Any])
async def resolve_request(
    ask_id: str,
    request: Request,
    body: RequestResolve | None = Body(None),
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    body = body or RequestResolve()
    ask = await _locked(db, engagement, ask_id)
    with _rules():
        resolved = request_service.resolve(ask, body.link, body.note, request_service.actor_of(user), _now())
    saved = await _save(db, engagement, ask_id, resolved, user)
    await _audit(db, request, user, engagement, "request_resolved", {
        "ask_id": ask_id,
        "request_number": request_service.request_number(resolved),
    })
    return saved


@router.post("/engagements/{engagement_id}/requests/{ask_id}/withdraw", response_model=dict[str, Any])
async def withdraw_request(
    ask_id: str,
    body: RequestWithdraw,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    ask = await _locked(db, engagement, ask_id)
    with _rules():
        withdrawn = request_service.withdraw(ask, body.reason, request_service.actor_of(user), _now())
    saved = await _save(db, engagement, ask_id, withdrawn, user)
    await _audit(db, request, user, engagement, "request_withdrawn", {
        "ask_id": ask_id,
        "request_number": request_service.request_number(withdrawn),  # None if it was never sent
    })
    return saved
