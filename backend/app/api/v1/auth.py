"""/api/v1/auth/* - every endpoint here MUST use @auth_rate_limit and take `request`.

Endpoint bodies arrive with AUTH-004 (me/logout), AUTH-005 (login/OTP) and
AUTH-006 (password reset). Until then they answer 501 so the routing, rate
limiting and middleware can already be exercised end to end.

No `from __future__ import annotations` here: slowapi wraps the endpoints and
FastAPI must be able to resolve the `Request` annotation on the wrapper.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...core.rate_limit import auth_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _not_implemented(ticket: str) -> JSONResponse:
    return JSONResponse({"detail": f"Not implemented yet ({ticket})"}, status_code=501)


@router.post("/login")
@auth_rate_limit
async def login(request: Request) -> JSONResponse:
    return _not_implemented("AUTH-005")
