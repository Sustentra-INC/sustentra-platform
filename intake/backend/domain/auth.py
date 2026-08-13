"""Magic-link and session models (intake Stage 0).

Magic-link email login, no passwords (SPEC section 3). The link token IS the
credential, so only a SHA-256 hash of a token is ever persisted - never the raw
value. Tokens are single-use and expire; sessions expire and can be revoked.

This is pilot-grade auth. Rate limiting, HTTPS-only cookie handling and a
hardened session store are explicitly out of scope for Phase B.
"""

from __future__ import annotations

from pydantic import BaseModel


class MagicLinkToken(BaseModel):
    """A single-use, expiring login token addressed to an email.

    ``token_hash`` is the SHA-256 hex digest of the raw token. The raw token
    exists only in the email that was sent.
    """

    token_id: str
    email: str
    token_hash: str
    created_at: str
    expires_at: str
    consumed_at: str | None = None


class Session(BaseModel):
    """An authenticated session produced by consuming a magic-link token."""

    session_id: str
    session_token_hash: str
    user_id: str
    org_id: str
    created_at: str
    expires_at: str
    revoked_at: str | None = None


class AuthenticatedUser(BaseModel):
    """Resolved identity returned by the auth service and the /me endpoint."""

    user_id: str
    org_id: str
    email: str
    name: str
    role: str
    session_expires_at: str
