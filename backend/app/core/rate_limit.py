"""Per-IP rate limiting (slowapi).

Every /api/v1/auth/* endpoint must be decorated with `@auth_rate_limit` and take
a `request: Request` parameter. All auth endpoints share ONE bucket per client
IP: 100 requests / 5 minutes by default (Settings.auth_rate_limit). Over the
limit -> 429 with Retry-After.

The client IP comes from request.client, which uvicorn fills from
X-Forwarded-For because it runs with --proxy-headers behind Caddy.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import get_settings

limiter = Limiter(key_func=get_remote_address, headers_enabled=True)

auth_rate_limit = limiter.shared_limit(lambda: get_settings().auth_rate_limit, scope="auth")
