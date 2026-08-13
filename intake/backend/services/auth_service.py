"""Magic-link authentication (intake Stage 0).

Flow: request a link by email -> a single-use, expiring token is emailed ->
the token is exchanged for a session -> the session authenticates later calls.

Security properties implemented here:

* Raw tokens are never persisted. Only SHA-256 hashes are stored, and hashes are
  compared with ``hmac.compare_digest``.
* Tokens are single-use and expire (``auth.magic_link_ttl_minutes``).
* Sessions expire (``auth.session_ttl_hours``) and can be revoked.
* ``request_magic_link`` returns an identical response whether or not the email
  belongs to a user, so the endpoint cannot be used to discover who has an
  account.

Explicitly NOT implemented in Phase B: rate limiting, lockout, cookie handling,
CSRF protection. This is pilot-grade auth for a guided onboarding flow.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_settings
from intake.backend.domain.auth import AuthenticatedUser, MagicLinkToken, Session
from intake.backend.repositories.magic_link_repository import MagicLinkTokenRepository
from intake.backend.repositories.session_repository import SessionRepository
from intake.backend.repositories.user_repository import UserRepository, normalise_email

INVALID_LINK_MESSAGE = "This sign-in link is invalid or has expired. Please request a new one."
INVALID_SESSION_MESSAGE = "Your session has expired. Please sign in again."


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a raw token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AuthError(Exception):
    """Raised when a link or session cannot be accepted."""


class AuthService:
    def __init__(
        self,
        token_repository: MagicLinkTokenRepository,
        session_repository: SessionRepository,
        user_repository: UserRepository,
        email_service: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
        token_factory: Callable[[int], str] | None = None,
    ) -> None:
        self._tokens = token_repository
        self._sessions = session_repository
        self._users = user_repository
        self._email = email_service
        self._settings = settings or load_settings()
        self._clock = clock
        self._token_factory = token_factory or secrets.token_urlsafe

    # -- magic link ---------------------------------------------------------

    def request_magic_link(self, email: str) -> dict[str, Any]:
        """Email a sign-in link if the address belongs to a user.

        The response never reveals whether the address exists.
        """
        address = normalise_email(email)
        user = self._users.get_by_email(address)
        if user is None or user.get("status") != "active":
            return {"status": "sent"}

        raw_token = self._token_factory(self._settings.auth.token_bytes)
        now = self._clock()
        token = MagicLinkToken(
            token_id=f"mlt_{uuid.uuid4().hex}",
            email=address,
            token_hash=hash_token(raw_token),
            created_at=now.isoformat(),
            expires_at=(
                now + timedelta(minutes=self._settings.auth.magic_link_ttl_minutes)
            ).isoformat(),
        )
        self._tokens.save(token)

        self._email.send_template(
            "magic_link",
            to=address,
            context={
                "name": user.get("name") or address,
                "verify_url": self._settings.auth.verify_url_template.format(token=raw_token),
                "ttl_minutes": self._settings.auth.magic_link_ttl_minutes,
            },
        )
        return {"status": "sent"}

    def verify_magic_link(self, raw_token: str) -> dict[str, Any]:
        """Exchange a magic-link token for a session. Single-use."""
        if not raw_token:
            raise AuthError(INVALID_LINK_MESSAGE)

        candidate = hash_token(raw_token)
        record = self._tokens.get_by_token_hash(candidate)
        if record is None or not hmac.compare_digest(str(record.get("token_hash", "")), candidate):
            raise AuthError(INVALID_LINK_MESSAGE)
        if record.get("consumed_at"):
            raise AuthError(INVALID_LINK_MESSAGE)

        now = self._clock()
        if now >= _parse(record["expires_at"]):
            raise AuthError(INVALID_LINK_MESSAGE)

        user = self._users.get_by_email(record["email"])
        if user is None or user.get("status") != "active":
            raise AuthError(INVALID_LINK_MESSAGE)

        # Burn the token before issuing the session.
        consumed = dict(record)
        consumed["consumed_at"] = now.isoformat()
        self._tokens.save(consumed)

        raw_session_token = self._token_factory(self._settings.auth.token_bytes)
        session = Session(
            session_id=f"ses_{uuid.uuid4().hex}",
            session_token_hash=hash_token(raw_session_token),
            user_id=user["user_id"],
            org_id=user["org_id"],
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=self._settings.auth.session_ttl_hours)).isoformat(),
        )
        self._sessions.save(session)

        refreshed = dict(user)
        refreshed["last_login_at"] = now.isoformat()
        self._users.save(refreshed)

        return {
            "session_token": raw_session_token,
            "expires_at": session.expires_at,
            "user": self._public_user(refreshed, session.expires_at).model_dump(),
        }

    # -- sessions -----------------------------------------------------------

    def resolve_session(self, session_token: str) -> AuthenticatedUser:
        if not session_token:
            raise AuthError(INVALID_SESSION_MESSAGE)

        candidate = hash_token(session_token)
        record = self._sessions.get_by_token_hash(candidate)
        if record is None or not hmac.compare_digest(
            str(record.get("session_token_hash", "")), candidate
        ):
            raise AuthError(INVALID_SESSION_MESSAGE)
        if record.get("revoked_at"):
            raise AuthError(INVALID_SESSION_MESSAGE)
        if self._clock() >= _parse(record["expires_at"]):
            raise AuthError(INVALID_SESSION_MESSAGE)

        user = self._users.get(record["user_id"])
        if user is None or user.get("status") != "active":
            raise AuthError(INVALID_SESSION_MESSAGE)
        return self._public_user(user, record["expires_at"])

    def revoke_session(self, session_token: str) -> dict[str, Any]:
        record = self._sessions.get_by_token_hash(hash_token(session_token))
        if record is None:
            return {"status": "signed_out"}
        revoked = dict(record)
        revoked["revoked_at"] = self._clock().isoformat()
        self._sessions.save(revoked)
        return {"status": "signed_out"}

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _public_user(user: dict[str, Any], session_expires_at: str) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=user["user_id"],
            org_id=user["org_id"],
            email=user["email"],
            name=user["name"],
            role=user["role"],
            session_expires_at=session_expires_at,
        )
