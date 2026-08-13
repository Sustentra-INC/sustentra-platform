"""Internal review queue (intake Stage 3, Phase D2).

The screen the Sustentra team works. Everything here is restricted to the
``sustentra_reviewer`` role.

Reviewers see across clients, unlike everyone else. A user belongs to one org in
v1 and client roles are scoped to it, but the queue only works if an internal
reviewer can see every client's open questions - that is the point of the role.
The check is explicit on every route rather than inherited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.escalation_service import EscalationError

router = APIRouter(prefix="/v1/intake/review", tags=["intake-review"])


class ResolveRequest(BaseModel):
    """The answer the reviewer is writing into the client's profile."""

    value: dict = Field(default_factory=dict)
    resolution_note: str | None = None


def require_reviewer(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
    if user.role != "sustentra_reviewer":
        raise HTTPException(status_code=403, detail="The review queue is for Sustentra staff.")
    return user


@router.get("/queue")
def queue(user: AuthenticatedUser = Depends(require_reviewer)) -> dict:
    """Everything waiting on the team, oldest first."""
    context = get_context()
    items = sorted(
        context.escalation_service.list_open(), key=lambda item: item["created_at"]
    )
    return {
        "count": len(items),
        "sla_hours": context.settings.escalation.sla_hours,
        "items": [context.review_service.summarise(item) for item in items],
    }


@router.get("/escalations/{escalation_id}")
def escalation_detail(
    escalation_id: str, user: AuthenticatedUser = Depends(require_reviewer)
) -> dict:
    detail = get_context().review_service.detail(escalation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such escalation.")
    return detail


@router.post("/escalations/{escalation_id}/resolve")
def resolve(
    escalation_id: str,
    payload: ResolveRequest,
    user: AuthenticatedUser = Depends(require_reviewer),
) -> dict:
    """Write the answer into the client's profile and tell them it is done."""
    context = get_context()
    if not payload.value:
        raise HTTPException(
            status_code=400, detail="An answer is required to resolve an escalation."
        )
    try:
        record = context.escalation_service.resolve(
            escalation_id,
            value=payload.value,
            actor_id=user.email,
            resolution_note=payload.resolution_note,
        )
    except EscalationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"escalation": record, "queue_count": len(context.escalation_service.list_open())}
