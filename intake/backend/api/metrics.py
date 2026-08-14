"""The two success metrics (intake Stage 6, Phase F).

Sustentra staff only. These numbers are about how well onboarding works, not
about any one client's inventory, and a client has no business reading another
client's completion time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser

router = APIRouter(prefix="/v1/intake/metrics", tags=["intake-metrics"])

REVIEWER_ROLE = "sustentra_reviewer"


def require_reviewer(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
    if user.role != REVIEWER_ROLE:
        raise HTTPException(status_code=403, detail="Metrics are for Sustentra staff.")
    return user


@router.get("")
def summary(user: AuthenticatedUser = Depends(require_reviewer)) -> dict:
    """Both success metrics, the sample size, and every client's journey."""
    return get_context().metrics_service.summary()


@router.get("/orgs/{org_id}")
def journey(org_id: str, user: AuthenticatedUser = Depends(require_reviewer)) -> dict:
    """One client's onboarding: when they started, where they are, what stuck."""
    found = get_context().metrics_service.journey(org_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such company.")
    return found
