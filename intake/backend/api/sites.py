"""Site endpoints (intake Stage 1).

Read-only. Sites are created and updated through the seed-form endpoint so that
every write passes the same validation, provisional-value recording and
boundary-deferral logic. A second write path would be able to bypass all three.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.org_service import OrgError

router = APIRouter(prefix="/v1/intake", tags=["intake-sites"])


@router.get("/orgs/{org_id}/sites")
def list_sites(org_id: str, user: AuthenticatedUser = Depends(require_user)) -> list[dict]:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="Not authorised for this org.")
    try:
        return get_context().org_service.list_sites(org_id)
    except OrgError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sites/{site_id}")
def get_site(site_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict:
    sites = get_context().org_service.list_sites(user.org_id)
    site = next((item for item in sites if item["site_id"] == site_id), None)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found.")
    return site
