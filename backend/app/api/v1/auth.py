"""/api/v1/auth/* - every endpoint here MUST use @auth_rate_limit and take `request`.

AUTH-004: GET /me, POST /logout
AUTH-005: POST /login, POST /login/verify, POST /login/resend
AUTH-006: POST /password-reset/request, POST /password-reset/confirm

No `from __future__ import annotations` here: slowapi wraps the endpoints and
FastAPI must be able to resolve the annotations on the wrapper.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.auth import CurrentUser, get_current_user
from ...core.db import get_db_session, get_sessionmaker_dependency
from ...core.rate_limit import auth_rate_limit
from ...services import login as login_service
from ...services import password_reset as reset_service
from ...services.audit_log import write_audit_event
from ...services.otp_delivery import OtpSender, ResetSender, get_otp_sender, get_reset_sender
from ...services.sessions import clear_session_cookie, delete_session, set_session_cookie

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    # Omitted for provider admins.
    org_slug: str | None = Field(default=None, max_length=63)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=16)


class ResendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=1, max_length=64)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    org_slug: str | None = Field(default=None, max_length=63)


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


def _meta(request: Request) -> login_service.RequestMeta:
    return login_service.RequestMeta(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


def _respond(outcome: login_service.LoginOutcome) -> JSONResponse:
    return JSONResponse(outcome.body, status_code=outcome.status, headers=outcome.headers or None)


# --- AUTH-005: login ----------------------------------------------------------------

@router.post("/login")
@auth_rate_limit
async def login(
    request: Request,
    payload: LoginRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    send_otp: OtpSender = Depends(get_otp_sender),
) -> JSONResponse:
    outcome = await login_service.start_login(db, payload.email, payload.password, payload.org_slug, _meta(request))
    if outcome.otp_email and outcome.otp_code:
        # Runs after the response is sent (and after the transaction commits).
        background.add_task(send_otp, outcome.otp_email, outcome.otp_code)
    return _respond(outcome)


@router.post("/login/verify")
@auth_rate_limit
async def login_verify(
    request: Request,
    payload: VerifyRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    outcome = await login_service.verify_login(db, payload.challenge_id, payload.code, _meta(request))
    response = _respond(outcome)
    if outcome.session_token:
        set_session_cookie(response, outcome.session_token)
    return response


@router.post("/login/resend")
@auth_rate_limit
async def login_resend(
    request: Request,
    payload: ResendRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    send_otp: OtpSender = Depends(get_otp_sender),
) -> JSONResponse:
    outcome = await login_service.resend_code(db, payload.challenge_id, _meta(request))
    if outcome.otp_email and outcome.otp_code:
        background.add_task(send_otp, outcome.otp_email, outcome.otp_code)
    return _respond(outcome)


# --- AUTH-006: password reset ----------------------------------------------------------

@router.post("/password-reset/request")
@auth_rate_limit
async def password_reset_request(
    request: Request,
    payload: PasswordResetRequest,
    background: BackgroundTasks,
    sessionmaker=Depends(get_sessionmaker_dependency),  # noqa: B008
    send_link: ResetSender = Depends(get_reset_sender),
) -> JSONResponse:
    # All work (lookup, token, email) happens in the background: the response is
    # identical - and equally fast - whether or not the account exists.
    background.add_task(
        reset_service.request_reset, sessionmaker, payload.email, payload.org_slug, _meta(request), send_link
    )
    return JSONResponse({"message": reset_service.REQUEST_ACCEPTED_MESSAGE})


@router.post("/password-reset/confirm")
@auth_rate_limit
async def password_reset_confirm(
    request: Request,
    payload: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    outcome = await reset_service.confirm_reset(db, payload.token, payload.password, _meta(request))
    return JSONResponse(outcome.body, status_code=outcome.status)


# --- AUTH-004: session ----------------------------------------------------------------

@router.get("/me")
@auth_rate_limit
async def me(request: Request, user: CurrentUser = Depends(get_current_user)) -> JSONResponse:
    return JSONResponse(
        {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
            "role": user.role,
            "org_id": str(user.org_id) if user.org_id else None,
            "org_slug": user.org_slug,
        }
    )


@router.post("/logout")
@auth_rate_limit
async def logout(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    # Only THIS session ends; the user's other sessions stay valid.
    await delete_session(db, user.session_id)
    await write_audit_event(
        db,
        "logout",
        org_id=user.org_id,
        actor_user_id=user.id,
        actor_role=user.role,
        target_type="session",
        target_id=str(user.session_id),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    response = JSONResponse({"status": "logged_out"})
    clear_session_cookie(response)
    return response
