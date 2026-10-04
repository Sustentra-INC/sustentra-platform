"""Server-side session lifecycle (AUTH-004).

Sessions live in the `sessions` table (DB-002). The browser only holds the
opaque token in the `__Host-session` cookie; the database only holds its
SHA-256 hash.

Lifetimes: absolute expiry 7 days after creation; idle timeout 8 hours since
`last_seen_at` (or creation). `last_seen_at` is refreshed at most once a minute.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security_primitives import hash_token, new_token

SESSION_COOKIE = "__Host-session"
ABSOLUTE_LIFETIME = timedelta(days=7)
IDLE_TIMEOUT = timedelta(hours=8)
LAST_SEEN_REFRESH = timedelta(minutes=1)


@dataclass(frozen=True)
class SessionUser:
    """The minimum needed to start a session for a user."""

    id: uuid.UUID
    org_id: uuid.UUID | None


@dataclass(frozen=True)
class ResolvedSession:
    session_id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    user_role: str
    user_status: str
    org_status: str | None

    def is_valid(self, now: datetime) -> bool:
        if self.revoked_at is not None or now >= self.expires_at:
            return False
        if now - (self.last_seen_at or self.created_at) > IDLE_TIMEOUT:
            return False
        if self.user_status != "active":
            return False
        # Provider admins have no org; everyone else needs an active org.
        return self.org_id is None or self.org_status == "active"


def utcnow() -> datetime:
    return datetime.now(UTC)


async def create_session(
    session: AsyncSession, user: SessionUser, ip: str | None, user_agent: str | None
) -> str:
    """Insert a session row and return the raw token for the cookie.

    The caller must already be in the user's tenant (or provider) context.
    """
    token, token_hash = new_token()
    now = utcnow()
    await session.execute(
        text(
            """
            INSERT INTO sessions (user_id, org_id, token_hash, created_at, expires_at, last_seen_at,
                                  ip_address, user_agent)
            VALUES (:user_id, :org_id, :token_hash, :created_at, :expires_at, :created_at,
                    CAST(:ip AS inet), :user_agent)
            """
        ),
        {
            "user_id": user.id,
            "org_id": user.org_id,
            "token_hash": token_hash,
            "created_at": now,
            "expires_at": now + ABSOLUTE_LIFETIME,
            "ip": ip,
            "user_agent": (user_agent or "")[:512] or None,
        },
    )
    return token


async def resolve_session(session: AsyncSession, token: str) -> ResolvedSession | None:
    row = (
        await session.execute(
            text("SELECT * FROM auth_resolve_session(:token_hash)"), {"token_hash": hash_token(token)}
        )
    ).mappings().first()
    return ResolvedSession(**row) if row else None


async def touch_session(session: AsyncSession, resolved: ResolvedSession, now: datetime) -> None:
    """Refresh last_seen_at at most once per minute (tenant context must be set)."""
    if resolved.last_seen_at is not None and now - resolved.last_seen_at < LAST_SEEN_REFRESH:
        return
    await session.execute(
        text("UPDATE sessions SET last_seen_at = :now WHERE id = :id"),
        {"now": now, "id": resolved.session_id},
    )


async def delete_session(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})


async def revoke_user_sessions(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Delete every session of a user (password reset, suspend, delete). Returns the count."""
    result = await session.execute(text("DELETE FROM sessions WHERE user_id = :user_id"), {"user_id": user_id})
    return int(getattr(result, "rowcount", 0) or 0)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ABSOLUTE_LIFETIME.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE, "", max_age=0, path="/", secure=True, httponly=True, samesite="strict"
    )
