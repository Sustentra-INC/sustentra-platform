"""/api/v1/auth/* - every endpoint here MUST use @auth_rate_limit and take `request`.

Endpoint bodies arrive with AUTH-004 (me/logout), AUTH-005 (login/OTP) and
AUTH-006 (password reset). Until then they answer 501 so the routing, rate
limiting and middleware can already be exercised end to end.

No `from __future__ import annotations` here: slowapi wraps the endpoints and
FastAPI must be able to resolve the `Request` annotation on the wrapper.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...core.rate_limit import auth_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _not_implemented(ticket: str) -> JSONResponse:
    return JSONResponse({"detail": f"Not implemented yet ({ticket})"}, status_code=501)


@router.post("/login")
@auth_rate_limit
async def login(request: Request) -> JSONResponse:
    return _not_implemented("AUTH-005")


# --- ORG-003: public invite validate / accept ---------------------------------
# Rate limited like every other /api/v1/auth/* endpoint. Implementation delegates to
# invite_service (validate_token / accept_invite); until then these answer 501, so the
# response_model values below document the intended contract for the frontend.


class InviteValidateResponse(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    org_name: str


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=1)
    # TODO(AUTH-006): enforce the shared password policy (length/complexity).
    password: str = Field(min_length=8)


class AcceptInviteResponse(BaseModel):
    # NOTE: accept does NOT create a session; the user logs in via /auth/login afterwards.
    user_id: UUID
    org_id: UUID
    email: str
    accepted_at: datetime


@router.get("/invite/validate", response_model=InviteValidateResponse)
@auth_rate_limit
async def validate_invite(request: Request, token: str = Query(min_length=1)) -> JSONResponse:
    # TODO(ORG-003): return await invite_service.validate_token(token=token)
    #                reject expired/consumed tokens; do not leak registration status.
    return _not_implemented("ORG-003")


@router.post("/invite/accept", response_model=AcceptInviteResponse)
@auth_rate_limit
async def accept_invite(request: Request, payload: AcceptInviteRequest) -> JSONResponse:
    # TODO(ORG-003): return await invite_service.accept_invite(token=payload.token,
    #                password=payload.password). Set password_hash + consumed_at in one tx.
    return _not_implemented("ORG-003")
