"""Magic-link auth endpoints (intake Stage 0)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from intake.backend.api.context import _bearer_token, get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.auth_service import AuthError

router = APIRouter(prefix="/v1/intake/auth", tags=["intake-auth"])


class MagicLinkRequest(BaseModel):
    email: str


class VerifyRequest(BaseModel):
    token: str


@router.post("/magic-link")
def request_magic_link(payload: MagicLinkRequest) -> dict:
    """Send a sign-in link.

    Always reports success so the endpoint cannot be used to discover which
    email addresses have accounts.
    """
    return get_context().auth_service.request_magic_link(payload.email)


@router.post("/verify")
def verify_magic_link(payload: VerifyRequest) -> dict:
    try:
        return get_context().auth_service.verify_magic_link(payload.token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
def current_user(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return user.model_dump()


@router.post("/sign-out")
def sign_out(authorization: str | None = Header(default=None)) -> dict:
    return get_context().auth_service.revoke_session(_bearer_token(authorization))
