"""Baseline HTTP security middleware for the /api/v1 API.

- OriginCheckMiddleware: state-changing requests (POST/PUT/PATCH/DELETE) must
  come from an allowed Origin (or, if the browser sent no Origin, an allowed
  Referer). Anything else -> 403. This is the CSRF defence for cookie sessions.
- JSONContentTypeMiddleware: mutating requests that carry a body must be
  `application/json` -> otherwise 415. Blocks form-based CSRF and odd parsers.
- UploadSizeLimitMiddleware: document uploads larger than the configured limit
  get 413 before the multipart body is parsed (INFRA-007).

Both only apply under API_V1_PREFIX; the legacy /v1 routes are untouched.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import normalize_origin

API_V1_PREFIX = "/api/v1"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# The only endpoints allowed to take multipart/form-data (file uploads).
MULTIPART_PATHS = (re.compile(r"^/api/v1/engagements/[^/]+/documents/upload$"),)
# Upload routes whose body size is capped (the legacy dev-only /v1 mount included).
UPLOAD_PATHS = re.compile(r"^(?:/api)?/v1/engagements/[^/]+/documents/upload$")
# Room for the multipart envelope (boundaries, part headers, small form fields).
MULTIPART_OVERHEAD_BYTES = 1024 * 1024

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


def upload_too_large_detail(max_bytes: int) -> str:
    return f"File is too large. The maximum upload size is {max_bytes // (1024 * 1024)} MB."


class _BodyTooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    """413 for an upload whose request body exceeds ``max_bytes`` + the multipart
    envelope, before anything is parsed or spooled to disk. Uses the declared
    Content-Length when there is one and counts the streamed bytes otherwise
    (chunked uploads). The route still checks the exact file size."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.limit = max_bytes + MULTIPART_OVERHEAD_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or not UPLOAD_PATHS.match(scope["path"]):
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._reject(send)
            return

        received = 0
        too_large = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    too_large = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            # FastAPI turns a failed body read into its own 400; answer 413 instead.
            nonlocal started
            if too_large:
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        response = JSONResponse({"detail": upload_too_large_detail(self.max_bytes)}, status_code=413,
                                headers={"Connection": "close"})
        await response({"type": "http"}, _empty_receive, send)


async def _empty_receive() -> Message:  # pragma: no cover - JSONResponse never reads the body
    return {"type": "http.disconnect"}
