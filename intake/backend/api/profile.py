"""The profile page (intake Stage 6, Phase E).

The client's living record and its edit history. Scoped to the caller's own org
- a client sees their profile and nobody else's - with Sustentra reviewers able
to read any client's, which is what the review role is for.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser

router = APIRouter(prefix="/v1/intake/profile", tags=["intake-profile"])

REVIEWER_ROLE = "sustentra_reviewer"


def _resolve_org(user: AuthenticatedUser, org_id: str | None) -> str:
    """Whose profile is being asked for, and may this caller see it?"""
    if org_id is None or org_id == user.org_id:
        return user.org_id
    if user.role != REVIEWER_ROLE:
        raise HTTPException(status_code=403, detail="That profile belongs to another client.")
    return org_id


@router.get("")
def get_profile(
    org_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Everything on the record for one client."""
    profile = get_context().profile_service.profile(_resolve_org(user, org_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="No such company.")
    return profile


@router.get("/history")
def get_history(
    org_id: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=1000),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Every recorded change, oldest first."""
    return get_context().profile_service.history(_resolve_org(user, org_id), limit=limit)
