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

A decision is checked against the line's automatic working (``with_line_decisions=False``). Accepted and edited values
on the recomputed side, and chosen options, are then read into the line's working (F3b, ``calc_trace/decisions``); a
pending suggestion never is.

No ``from __future__ import annotations``: FastAPI resolves these at runtime.
"""

from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
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


# Why the working would not take a decision -> the code a refusal answers with (409).
CODES = {"set_elsewhere": "not_decidable", "line_mixes_runs": "mixed_line", "stale": "stale",
         "line_has_no_working": "no_working", "unit_mismatch": "unit_mismatch", "invalid_value": "invalid_value",
         "no_route_for_option": "no_route", "option_not_available": "no_route", "total_decided": "total_decided"}
# Anything else the totals refuse (the category does not add up, no single category line, market-based not
# recalculated, could not count) is "not_counted"; a stream changed between the check and the write, "state_changed".


class _Refused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@contextmanager
def _rules() -> Iterator[None]:
    """Turn a refused move into 409 and malformed input into 422. A move the working cannot take is a 409 with a
    ``code`` (``rules.Refused``)."""

    try:
        yield
    except rules.Refused as exc:
        raise _Refused(exc.code, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _line_key(value: str) -> str:
    if not LINE_KEY.fullmatch(value):
        raise HTTPException(status_code=422, detail="line_key: letters, digits and : . _ - only (max 200).")
    return value


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
    """One engine run per POST, off the event loop and with no lock held: the run offers the line's automatic trace,
    the move is made on it (``rules.Proposal``) and worked in by the rules the totals use; a move the working would
    not take is refused with a code. Only then the line's lock, a cheap check that the stream has not moved since
    (409 ``state_changed``), and the add-only write."""

    line_key = _line_key(line_key)
    with _rules():
        target_id = rules.clean_id(target_id, "choice id" if target == rules.CHOICE else "input id")
    stream = rules.stream_of(target, target_id, side)
    events = await rules.current(db, engagement["id"])
    stored = next((e for e in events if e.get("line_key") == line_key and e.get("stream") == stream), None)
    record = stored["record"] if stored else rules.new_record(stream)
    now, actor = datetime.now(UTC), actor_of(user)

    def make(trace: dict[str, Any], record: dict[str, Any] = record) -> dict[str, Any]:
        if target == rules.CHOICE:
            choice = rules.find_choice(trace, target_id)
            if choice is None:
                raise HTTPException(status_code=404, detail="That choice is not on this line. Reload the page.")
            return rules.decide_choice(record, choice, action, option_id=inputs.get("option_id"),
                                       reason=inputs.get("reason"), actor=actor, now=now,
                                       basis=rules.basis_of(trace, choice=choice))
        found = rules.find_input(trace, target_id)
        if found is None:
            raise HTTPException(status_code=404, detail="That input is not on this line. Reload the page.")
        assert side is not None
        item, row = found
        return rules.decide_input(record, item, row, side, action, value=inputs.get("value"),
                                  unit=inputs.get("unit"), reason=inputs.get("reason"),
                                  document_id=inputs.get("document_id"), actor=actor, now=now,
                                  basis=rules.basis_of(trace, row if row is not None else item))

    proposal = rules.Proposal(line_key, stream, make)
    others = [e for e in events if not (e.get("line_key") == line_key and e.get("stream") == stream)]
    result = await recalculation_api.run_recalculation(db, engagement, user, line_decisions=others,
                                                       proposal=proposal)
    if not proposal.seen:
        raise HTTPException(status_code=404, detail="No such calculation line. Reload the page to see the current "
                                                    "lines.")
    if not proposal.trace:
        raise HTTPException(status_code=409, detail="This line has no working to decide on yet.")
    if proposal.error is not None:
        with _rules():
            raise proposal.error
    updated = proposal.record
    assert updated is not None
    if action in ("accept", "edit", "choose") and side != "company":
        line = next((ln for ln in result.get("calculation_lines", []) if ln.get("key") == line_key), None)
        refused = next((n for n in ((line or {}).get("decisions") or {}).get("not_applied", [])
                        if n.get("target") == target and n.get("id") == target_id and n.get("side") == side), None)
        if refused is not None:
            raise _Refused(CODES.get(str(refused.get("reason")), "not_counted"), str(refused.get("message")))
    await rules.lock(db, engagement["id"], line_key)
    now_stored = next((e for e in await rules.current(db, engagement["id"], line_key) if e["stream"] == stream), None)
    if (now_stored or {}).get("seq") != (stored or {}).get("seq"):
        # Another request wrote this stream while this one was checking (a double click). The move is made again on
        # the stream's new state and the same automatic working: what the engine checked (this move's value, unit
        # and basis, against the line and its category) is unchanged, so only the state machine can refuse it now.
        assert now_stored is not None and proposal.trace is not None
        try:
            updated = make(proposal.trace, now_stored["record"])
        except (ReviewConflict, ReviewInvalid) as exc:
            raise _Refused("state_changed", "This decision was changed by someone else a moment ago, and this "
                                            f"change no longer fits: {exc} Reload to see the current state.") from exc
        stored = now_stored
    with _rules():
        event = await rules.append(
            db, org_id=engagement["org_id"], engagement_id=engagement["id"], line_key=line_key, stream=stream,
            target=target, target_id=target_id, side=side, previous_seq=int(stored["seq"]) if stored else 0,
            record=updated, user_id=user.id)
    restored = (updated.get("history") or [{}])[-1].get("restored") if action == "revert" else None
    await _audit(db, request, user, engagement, line_key=line_key, target=target, target_id=target_id, side=side,
                 action=action, status=status_of(updated), restored=restored)
    return {"line_key": line_key, "target": target, "id": target_id, "side": side, "seq": event["seq"],
            **rules.public_record(updated)}


async def _answer(acting: Awaitable[dict[str, Any]]) -> dict[str, Any] | JSONResponse:
    """The decision, or 409 ``{detail, code}`` when the line's working would not take it (nothing is written)."""

    try:
        return await acting
    except _Refused as exc:
        return JSONResponse(status_code=409, content={"detail": exc.detail, "code": exc.code})


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
) -> dict[str, Any] | JSONResponse:
    return await _answer(_act(request, user, engagement, db, line_key=line_key, target=rules.CHOICE,
                              target_id=choice_id, side=None, action=body.action, option_id=body.option_id,
                              reason=body.reason))


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
) -> dict[str, Any] | JSONResponse:
    return await _answer(_act(request, user, engagement, db, line_key=line_key, target=rules.INPUT,
                              target_id=input_id, side=side, action=body.action, value=body.value, unit=body.unit,
                              reason=body.reason, document_id=body.document_id))


@router.get("/engagements/{engagement_id}/calculation-lines/decisions", response_model=dict[str, Any])
async def list_decisions(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict[str, Any]:
    """Every current decision, split into those on lines the engagement still has and the orphaned ones (the line
    was deleted or renamed): kept and reported here, never applied to another line."""

    engagement = await _visible(db, engagement_id, user)
    result = await recalculation_api.traced_recalculation(db, engagement, user, with_line_decisions=False)
    keys = [str(ln["key"]) for ln in result.get("calculation_lines", []) if ln.get("key") is not None]
    placed, orphaned = rules.split_orphans(await rules.current(db, engagement["id"]), keys)
    return {"decisions": placed, "orphaned_decisions": orphaned}
