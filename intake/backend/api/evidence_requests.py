"""Expected documents (intake Stage 4, Phase E).

Data only: what should arrive, for which site, for which period, and whether S1
may start on it. There is no upload endpoint here and no file handling anywhere
in intake - documents belong to the existing S1 pipeline, which is untouched.

``/completeness-spec`` is the endpoint intake/SPEC.md Stage 4 asks for: the
expected-completeness spec derived from the client's profile, exposed for the
existing pipeline to adopt in place of hardcoded assumptions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser

router = APIRouter(prefix="/v1/intake/evidence-requests", tags=["intake-evidence-requests"])

REVIEWER_ROLE = "sustentra_reviewer"


def _resolve_org(user: AuthenticatedUser, org_id: str | None) -> str:
    if org_id is None or org_id == user.org_id:
        return user.org_id
    if user.role != REVIEWER_ROLE:
        raise HTTPException(status_code=403, detail="That list belongs to another client.")
    return org_id


@router.get("")
def list_requests(
    org_id: str | None = Query(default=None),
    refresh: bool = Query(
        default=True,
        description="Recompile from the client's current answers first. Safe to repeat.",
    ),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """The documents we expect from this client."""
    context = get_context()
    resolved = _resolve_org(user, org_id)
    service = context.evidence_request_service

    items = service.compile(resolved) if refresh else service.list_for_org(resolved)
    return {
        "org_id": resolved,
        "count": len(items),
        "safe_to_parse_now": sum(1 for item in items if item["safe_to_parse"]),
        "items": items,
    }


@router.get("/completeness-spec")
def completeness_spec(
    org_id: str | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    """Expected document counts per scope, for the S1 completeness gate.

    Recompiles first so the spec reflects the latest answers rather than
    whatever was last stored.
    """
    context = get_context()
    resolved = _resolve_org(user, org_id)
    context.evidence_request_service.compile(resolved)
    return context.evidence_request_service.completeness_spec(resolved)
