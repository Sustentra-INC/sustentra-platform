"""Baseline HTTP security middleware for the /api/v1 API.

- OriginCheckMiddleware: state-changing requests (POST/PUT/PATCH/DELETE) must
  come from an allowed Origin (or, if the browser sent no Origin, an allowed
  Referer). Anything else -> 403. This is the CSRF defence for cookie sessions.
- JSONContentTypeMiddleware: mutating requests that carry a body must be
  `application/json` -> otherwise 415. Blocks form-based CSRF and odd parsers.

Both only apply under API_V1_PREFIX; the legacy /v1 routes are untouched.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import normalize_origin

API_V1_PREFIX = "/api/v1"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# The only endpoints allowed to take multipart/form-data (file uploads).
MULTIPART_PATHS = (re.compile(r"^/api/v1/engagements/[^/]+/documents/upload$"),)

CallNext = Callable[[Request], Awaitable[Response]]


def _applies(request: Request, methods: frozenset[str]) -> bool:
    return request.method in methods and request.url.path.startswith(API_V1_PREFIX)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        super().__init__(app)
        self._allowed = allowed_origins

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if _applies(request, STATE_CHANGING_METHODS) and not self._is_allowed(request):
            return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        return await call_next(request)

    def _is_allowed(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin and origin != "null":
            return normalize_origin(origin) in self._allowed
        referer = request.headers.get("referer")
        if referer:
            return normalize_origin(referer) in self._allowed
        # Neither header: not a browser we can verify -> reject.
        return False


class JSONContentTypeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if _applies(request, BODY_METHODS) and _has_body(request):
            content_type = request.headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            is_upload = media_type == "multipart/form-data" and any(
                pattern.match(request.url.path) for pattern in MULTIPART_PATHS
            )
            if media_type != "application/json" and not is_upload:
                return JSONResponse(
                    {"detail": "Content-Type must be application/json"}, status_code=415
                )
        return await call_next(request)


def _has_body(request: Request) -> bool:
    if request.headers.get("transfer-encoding", "").lower() == "chunked":
        return True
    length = request.headers.get("content-length")
    return bool(length and length.strip() not in ("", "0"))
