"""/api/v1/auth/* - every endpoint here MUST use @auth_rate_limit and take `request`.

AUTH-004: GET /me, POST /logout (this file).
AUTH-005 fills in POST /login (+ /login/verify, /login/resend); AUTH-006 adds
password reset. Until then /login answers 501.

No `from __future__ import annotations` here: slowapi wraps the endpoints and
FastAPI must be able to resolve the annotations on the wrapper.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.auth import CurrentUser, get_current_user
from ...core.db import get_db_session
from ...core.rate_limit import auth_rate_limit
from ...services.audit_log import write_audit_event
from ...services.sessions import clear_session_cookie, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _not_implemented(ticket: str) -> JSONResponse:
    return JSONResponse({"detail": f"Not implemented yet ({ticket})"}, status_code=501)


@router.post("/login")
@auth_rate_limit
async def login(request: Request) -> JSONResponse:
    return _not_implemented("AUTH-005")


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
