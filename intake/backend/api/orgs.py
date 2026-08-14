"""Org and user endpoints (intake Stage 0).

v1 onboarding is Sustentra-initiated, so org creation is an internal operation
guarded by an admin key read from the environment (never from a config file -
secrets are not committed). The guard fails closed: if ``INTAKE_ADMIN_API_KEY``
is unset the endpoint refuses rather than standing open.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.org_service import OrgError

router = APIRouter(prefix="/v1/intake", tags=["intake-orgs"])

ADMIN_KEY_ENV = "INTAKE_ADMIN_API_KEY"


class CreateOrgRequest(BaseModel):
    legal_name: str
    owner_name: str
    owner_email: str
    created_by: str


class AddUserRequest(BaseModel):
    name: str
    email: str
    role: str


def require_admin_key(x_intake_admin_key: str | None = Header(default=None)) -> None:
    """Guard internal-only endpoints. Fails closed when no key is configured."""
    expected = os.environ.get(ADMIN_KEY_ENV)
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Org creation is not configured. Set {ADMIN_KEY_ENV} to enable this "
                "internal endpoint."
            ),
        )
    if not x_intake_admin_key or not hmac.compare_digest(x_intake_admin_key, expected):
        raise HTTPException(status_code=403, detail="Not authorised.")


def _assert_same_org(user: AuthenticatedUser, org_id: str) -> None:
    if user.org_id != org_id:
        raise HTTPException(status_code=403, detail="Not authorised for this org.")


@router.post("/orgs", dependencies=[Depends(require_admin_key)])
def create_org(payload: CreateOrgRequest) -> dict:
    try:
        return get_context().org_service.create_org(
            legal_name=payload.legal_name,
            owner_name=payload.owner_name,
            owner_email=payload.owner_email,
            created_by=payload.created_by,
        )
    except OrgError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orgs/{org_id}")
def get_org(org_id: str, user: AuthenticatedUser = Depends(require_user)) -> dict:
    _assert_same_org(user, org_id)
    try:
        return get_context().org_service.get_org(org_id)
    except OrgError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orgs/{org_id}/users")
def list_users(org_id: str, user: AuthenticatedUser = Depends(require_user)) -> list[dict]:
    _assert_same_org(user, org_id)
    return get_context().org_service.list_users(org_id)


@router.post("/orgs/{org_id}/users")
def add_user(
    org_id: str, payload: AddUserRequest, user: AuthenticatedUser = Depends(require_user)
) -> dict:
    _assert_same_org(user, org_id)
    service = get_context().org_service
    if not service.can_manage_users(user.role):
        raise HTTPException(status_code=403, detail="Your role cannot manage users.")
    try:
        return service.add_user(
            org_id=org_id,
            name=payload.name,
            email=payload.email,
            role=payload.role,
            actor_role=user.role,
        )
    except OrgError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
