"""Per-IP rate limiting (slowapi).

Every /api/v1/auth/* endpoint must be decorated with `@auth_rate_limit` and take
a `request: Request` parameter. All auth endpoints share ONE bucket per client
IP: 100 requests / 5 minutes by default (Settings.auth_rate_limit). Over the
limit -> 429 with Retry-After.

The client IP comes from request.client, which uvicorn fills from
X-Forwarded-For because it runs with --proxy-headers behind Caddy.

Exception (AUTH-007): GET /api/v1/auth/me is not part of that bucket. It is
called on every protected page render - and server-side by the Next app, whose
requests all come from the web container's IP - so sharing the brute-force
bucket logged people out during normal navigation and could lock everyone out
of login. It has its own, much higher limit per session
(Settings.session_rate_limit, default 600 / minute), keyed by the session
cookie's hash (or the IP when there is no cookie).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from ..services.sessions import SESSION_COOKIE
from .config import get_settings
from .security_primitives import hash_token

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)

auth_rate_limit = limiter.shared_limit(lambda: get_settings().auth_rate_limit, scope="auth")


def session_key(request: Request) -> str:
    """Rate-limit key for session-authenticated reads: the session, not the IP."""

    token = request.cookies.get(SESSION_COOKIE)
    return f"session:{hash_token(token)}" if token else f"ip:{get_remote_address(request)}"


session_rate_limit = limiter.limit(lambda: get_settings().session_rate_limit, key_func=session_key)
