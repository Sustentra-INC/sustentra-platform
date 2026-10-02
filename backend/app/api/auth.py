from __future__ import annotations

from fastapi import APIRouter, Header

from backend.app.api.identity_deps import (
    CurrentActor,
    OptionalActor,
    get_identity_service,
    map_identity_error,
)
from backend.app.services.identity_service import IdentityError
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class MfaLoginRequest(BaseModel):
    mfa_token: str
    code: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str


class MfaConfirmRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    password: str
    code: str


class LogoutRequest(BaseModel):
    token: str | None = None


@router.get("/status")
def auth_status() -> dict:
    return get_identity_service().status()


@router.post("/login")
def login(payload: LoginRequest) -> dict:
    try:
        return get_identity_service().login(payload.username, payload.password)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/login/mfa")
def login_mfa(payload: MfaLoginRequest) -> dict:
    try:
        return get_identity_service().complete_mfa_login(payload.mfa_token, payload.code)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/logout")
def logout(
    payload: LogoutRequest | None = None,
    authorization: str | None = Header(default=None),
    actor: dict | None = OptionalActor,
) -> dict:
    token = (payload.token if payload else None) or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    return get_identity_service().logout(token, actor)


@router.get("/me")
def me(actor: dict = CurrentActor) -> dict:
    return actor


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest) -> dict:
    try:
        return get_identity_service().request_password_reset(payload.email)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirmRequest) -> dict:
    try:
        return get_identity_service().confirm_password_reset(payload.token, payload.new_password)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/mfa/setup")
def setup_mfa(actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().setup_mfa(actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/mfa/confirm")
def confirm_mfa(payload: MfaConfirmRequest, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().confirm_mfa(actor, payload.code)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/mfa/disable")
def disable_mfa(payload: MfaDisableRequest, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().disable_mfa(actor, payload.password, payload.code)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc
