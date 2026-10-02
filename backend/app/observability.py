"""Structured (JSON) logging and per-request access logs for the API.

Every request produces exactly one JSON log line with:
    request_id, method, path, status, duration_ms, user_id, org_id

Never logged: request/response bodies, headers, query strings, passwords,
OTP codes or tokens. Handlers must not pass secrets to the logger either.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

REQUEST_ID_HEADER = "X-Request-ID"
_MAX_REQUEST_ID_LEN = 128

# Attribute names a standard LogRecord always has; anything else came from `extra=`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
# Defense in depth: drop these keys even if someone passes them in `extra=`.
_REDACTED_KEYS = {"password", "otp", "otp_code", "code", "token", "authorization", "secret", "totp"}

access_logger = logging.getLogger("sustentra.access")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if key.lower() in _REDACTED_KEYS:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Send all logs to stdout as JSON (Docker -> awslogs -> CloudWatch)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Our middleware writes the access log; uvicorn's would duplicate it (and include query strings).
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def _request_id(request: Request) -> str:
    incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if incoming and len(incoming) <= _MAX_REQUEST_ID_LEN and incoming.replace("-", "").isalnum():
        return incoming
    return uuid.uuid4().hex


def set_request_actor(request: Request, actor: dict[str, Any] | None) -> None:
    """Called by the auth dependencies so the access log can include user/org IDs."""
    if not actor:
        return
    request.state.user_id = actor.get("actor_id") or actor.get("user_id")
    request.state.org_id = actor.get("client_id") or actor.get("organization_id") or actor.get("org_id")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            access_logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,  # no query string: it may carry tokens
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "user_id": getattr(request.state, "user_id", None),
                    "org_id": getattr(request.state, "org_id", None),
                },
            )


def install(app: FastAPI) -> None:
    configure_logging()
    app.add_middleware(RequestLoggingMiddleware)
