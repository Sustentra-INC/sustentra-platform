"""Guided interview endpoints (intake Stage 2, Phase C2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.interview_engine import AnswerValidationError

router = APIRouter(prefix="/v1/intake/interview", tags=["intake-interview"])


class AnswerRequest(BaseModel):
    datapoint_id: str
    scope_ref: str | None = None
    answer: dict = Field(default_factory=dict)


class NotSureRequest(BaseModel):
    datapoint_id: str
    scope_ref: str | None = None


def _require_client(user: AuthenticatedUser) -> None:
    if not get_context().org_service.can_submit_seed_form(user.role):
        raise HTTPException(status_code=403, detail="Your role cannot answer the interview.")


@router.post("/start")
def start(user: AuthenticatedUser = Depends(require_user)) -> dict:
    """Instantiate states, back-fill the seed form, and return the first question."""
    context = get_context()
    summary = context.profile_state_service.initialise(user.org_id, actor_id=user.user_id)
    return {
        "summary": summary,
        "coverage": context.coverage_service.coverage(user.org_id),
        "next": context.interview_engine.next_question(user.org_id),
    }


@router.get("/next")
def next_question(user: AuthenticatedUser = Depends(require_user)) -> dict:
    context = get_context()
    return {
        "next": context.interview_engine.next_question(user.org_id),
        "coverage": context.coverage_service.coverage(user.org_id),
    }


@router.post("/answer")
def answer(
    payload: AnswerRequest, user: AuthenticatedUser = Depends(require_user)
) -> dict:
    _require_client(user)
    context = get_context()
    try:
        result = context.interview_engine.submit_answer(
            org_id=user.org_id,
            datapoint_id=payload.datapoint_id,
            scope_ref=payload.scope_ref,
            answer=payload.answer,
            actor_id=user.user_id,
        )
    except AnswerValidationError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors}) from exc

    return {
        "status": result["status"],
        "escalated": result["escalated"],
        "coverage": context.coverage_service.coverage(user.org_id),
        "next": context.interview_engine.next_question(user.org_id),
    }


@router.post("/not-sure")
def not_sure(
    payload: NotSureRequest, user: AuthenticatedUser = Depends(require_user)
) -> dict:
    """Show the explainer and hand the question to the team. Never a failure."""
    _require_client(user)
    context = get_context()
    try:
        result = context.interview_engine.not_sure(
            org_id=user.org_id,
            datapoint_id=payload.datapoint_id,
            scope_ref=payload.scope_ref,
            actor_id=user.user_id,
        )
    except AnswerValidationError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors}) from exc

    return {
        "explainer": result["explainer"],
        "message": result["message"],
        "coverage": context.coverage_service.coverage(user.org_id),
        "next": context.interview_engine.next_question(user.org_id),
    }


@router.get("/coverage")
def coverage(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return get_context().coverage_service.coverage(user.org_id)


@router.get("/states")
def states(user: AuthenticatedUser = Depends(require_user)) -> list[dict]:
    """Every recorded state for this org. Feeds the Phase E profile page."""
    return get_context().state_repository.list_by_org(user.org_id)
