"""Reviewer decisions on calculation lines (Claire's calculation panels, F2).

* POST /v1/engagements/{id}/calculation-lines/{line_key}/choices/{choice_id}
      {action: accept | choose | reject | revert, option_id?, reason?}
* POST /v1/engagements/{id}/calculation-lines/{line_key}/inputs/{input_id}/{side}     side: company | recomputed
      {action: accept | edit | reject | revert, value?, unit?, reason?, document_id?}
      (an input's row is ``input_id = "<input>/<row id>"``)
* GET  /v1/engagements/{id}/calculation-lines/decisions     every current decision, and the orphaned ones (s1_reader)

The rules are ``services/review_field`` (the Methodology review's state machine) with ``services/calc_line_review``'s
checks; a move they refuse answers 409 (state, or an option that is not available) or 422 (input) with a sentence
and writes nothing. Each action inserts one add-only ``workpaper_items`` row (kind ``calc_line``, migration 0028) and
writes one ``calc_line_decision`` audit event (line key, target, side, action and status; never a value, unit, quote
or reason) in the same transaction. Who acted and when come from the session, never the body (bodies forbid unknown
fields). Writes are s1_writer on an open engagement: another org's engagement answers 404, a provider_admin 403 and
an archived engagement 409. A malformed line key is 422, a well-formed one the engagement does not have is 404.

A decision is recorded and shown (the trace endpoint carries it) but no total reads it yet: that is the next change.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import recalculation as recalculation_api
from backend.app.api.engagements import _visible, require_open_engagement
from backend.app.api.s1_access import s1_reader, s1_writer
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.services import calc_line_review as rules
from backend.app.services.audit_log import write_audit_event
from backend.app.services.calculation_lines import LINE_KEY
from backend.app.services.request_service import actor_of
from backend.app.services.review_field import ReviewConflict, ReviewInvalid, status_of

router = APIRouter(prefix="/v1", tags=["calculation-line-review"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoiceBody(_Body):
    action: Literal["accept", "choose", "reject", "revert"]
    option_id: str | None = Field(None, max_length=rules.MAX_TEXT)
    reason: str | None = Field(None, max_length=2000)


class InputBody(_Body):
    action: Literal["accept", "edit", "reject", "revert"]
    value: Any = None  # a number or text; the rules check it against the input
    unit: str | None = Field(None, max_length=rules.MAX_TEXT)
    reason: str | None = Field(None, max_length=2000)
    document_id: str | None = Field(None, max_length=rules.MAX_TEXT)


@contextmanager
def _rules() -> Iterator[None]:
    """Turn a refused move into 409 and malformed input into 422."""

    try:
        yield
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _line_key(value: str) -> str:
    if not LINE_KEY.fullmatch(value):
        raise HTTPException(status_code=422, detail="line_key: letters, digits and : . _ - only (max 200).")
    return value


async def _line_trace(db: AsyncSession, engagement: dict[str, Any], user: CurrentUser, line_key: str
                      ) -> dict[str, Any]:
    """The line's trace from one engine run: 404 when the engagement has no such line, 409 when it has no working."""

    result = await recalculation_api.traced_recalculation(db, engagement, user)
    line = next((ln for ln in result.get("calculation_lines", []) if ln.get("key") == line_key), None)
    if line is None:
        raise HTTPException(status_code=404, detail="No such calculation line. Reload the page to see the current "
                                                    "lines.")
    trace = line.get("trace")
    if not trace:
        raise HTTPException(status_code=409, detail="This line has no working to decide on yet.")
    return dict(trace)


async def _audit(db: AsyncSession, request: Request, user: CurrentUser, engagement: dict[str, Any], *,
                 line_key: str, target: str, target_id: str, side: str | None, action: str, status: str,
                 restored: str | None) -> None:
    await write_audit_event(
        db,
        "calc_line_decision",
        org_id=engagement["org_id"],
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="engagement",
        target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        # never a value, unit, quote or reason; a revert also says what it restored: previous, detected or empty
        metadata={"line_key": line_key, "target": target, "id": target_id, "side": side, "action": action,
                  "status": status, **({"restored": restored} if restored else {})},
    )


async def _act(request: Request, user: CurrentUser, engagement: dict[str, Any], db: AsyncSession, *, line_key: str,
               target: str, target_id: str, side: str | None, action: str, **inputs: Any) -> dict[str, Any]:
    line_key = _line_key(line_key)
    with _rules():
        target_id = rules.clean_id(target_id, "choice id" if target == rules.CHOICE else "input id")
    trace = await _line_trace(db, engagement, user, line_key)
    choice = rules.find_choice(trace, target_id) if target == rules.CHOICE else None
    found = rules.find_input(trace, target_id) if target == rules.INPUT else None
    if target == rules.CHOICE and choice is None:
        raise HTTPException(status_code=404, detail="That choice is not on this line. Reload the page.")
    if target == rules.INPUT and found is None:
        raise HTTPException(status_code=404, detail="That input is not on this line. Reload the page.")
    stream = rules.stream_of(target, target_id, side)
    await rules.lock(db, engagement["id"], line_key)
    events = await rules.current(db, engagement["id"], line_key)
    stored = next((e for e in events if e["stream"] == stream), None)
    record = stored["record"] if stored else rules.new_record(stream)
    now, actor = datetime.now(UTC), actor_of(user)
    with _rules():
        if choice is not None:
            updated = rules.decide_choice(record, choice, action, option_id=inputs.get("option_id"),
                                          reason=inputs.get("reason"), actor=actor, now=now)
        else:
            assert found is not None and side is not None
            item, row = found
            updated = rules.decide_input(record, item, row, side, action, value=inputs.get("value"),
                                         unit=inputs.get("unit"), reason=inputs.get("reason"),
                                         document_id=inputs.get("document_id"), actor=actor, now=now)
        event = await rules.append(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], line_key=line_key, stream=stream,
            target=target, target_id=target_id, side=side, previous_seq=int(stored["seq"]) if stored else 0,
            record=updated, user_id=user.id)
    restored = (updated.get("history") or [{}])[-1].get("restored") if action == "revert" else None
    await _audit(db, request, user, engagement, line_key=line_key, target=target, target_id=target_id, side=side,
                 action=action, status=status_of(updated), restored=restored)
    return {"line_key": line_key, "target": target, "id": target_id, "side": side, "seq": event["seq"],
            **rules.public_record(updated)}


@router.post("/engagements/{engagement_id}/calculation-lines/{line_key}/choices/{choice_id}",
             response_model=dict[str, Any])
async def decide_choice(
    line_key: str,
    choice_id: str,
    body: ChoiceBody,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act(request, user, engagement, db, line_key=line_key, target=rules.CHOICE, target_id=choice_id,
                      side=None, action=body.action, option_id=body.option_id, reason=body.reason)


@router.post("/engagements/{engagement_id}/calculation-lines/{line_key}/inputs/{input_id:path}/{side}",
             response_model=dict[str, Any])
async def decide_input(
    line_key: str,
    input_id: str,
    side: Literal["company", "recomputed"],
    body: InputBody,
    request: Request,
    user: CurrentUser = Depends(s1_writer),
    engagement: dict[str, Any] = Depends(require_open_engagement),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    return await _act(request, user, engagement, db, line_key=line_key, target=rules.INPUT, target_id=input_id,
                      side=side, action=body.action, value=body.value, unit=body.unit, reason=body.reason,
                      document_id=body.document_id)


@router.get("/engagements/{engagement_id}/calculation-lines/decisions", response_model=dict[str, Any])
async def list_decisions(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Every current decision, split into those on lines the engagement still has and the orphaned ones (the line
    was deleted or renamed): kept and reported here, never applied to another line."""

    engagement = await _visible(db, engagement_id, user)
    result = await recalculation_api.traced_recalculation(db, engagement, user)
    keys = [str(ln["key"]) for ln in result.get("calculation_lines", []) if ln.get("key") is not None]
    placed, orphaned = rules.split_orphans(await rules.current(db, engagement["id"]), keys)
    return {"decisions": placed, "orphaned_decisions": orphaned}
