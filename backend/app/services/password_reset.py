"""Password reset (AUTH-006).

request_reset  - runs in a BACKGROUND TASK with its own DB session, so the HTTP
                 response is identical and takes the same time whether or not the
                 email exists. For an active user: earlier unused reset tokens are
                 marked used, a new token (15-min TTL, SHA-256 hash stored) is
                 created, and the link is emailed.
confirm_reset  - token valid (exists, unused, unexpired) -> password policy
                 (AUTH-003) -> set password_hash, mark token used, clear
                 failed_login_count / locked_until, revoke ALL sessions, audit
                 `password_reset`. Does NOT log the user in.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.config import get_settings
from ..core.db import set_provider, set_tenant
from ..core.security_primitives import hash_password, hash_token, new_token, validate_password
from .audit_log import write_audit_event
from .login import RequestMeta
from .sessions import revoke_user_sessions

logger = logging.getLogger("sustentra.auth")

RESET_TTL = timedelta(minutes=15)
REQUEST_ACCEPTED_MESSAGE = "If that email exists, a reset link has been sent"
INVALID_TOKEN_MESSAGE = "This reset link is invalid or has expired. Request a new one."

ResetSender = Any  # Callable[[str, str], None] - (to, link)


def utcnow() -> datetime:
    """Single clock for this module (tests monkeypatch it)."""
    return datetime.now(UTC)


@dataclass
class ResetOutcome:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


def reset_link(token: str, org_slug: str | None) -> str:
    base = get_settings().public_base_url.rstrip("/")
    path = f"/org/{quote(org_slug)}/reset-password" if org_slug else "/provider-admin/reset-password"
    return f"{base}{path}?token={quote(token)}"


# --- request (background) ------------------------------------------------------------

async def _create_reset_token(db: AsyncSession, email: str, org_slug: str | None,
                              meta: RequestMeta) -> tuple[str, str] | None:
    """Returns (to, link) when a link should be sent, else None. Same shape either way."""
    now = utcnow()
    email = email.strip().lower()
    slug = org_slug.strip().lower() if org_slug else None

    if slug:
        org = (await db.execute(text("SELECT id, status FROM organizations WHERE slug = :slug"),
                                {"slug": slug})).mappings().first()
        if org is None or org["status"] != "active":
            return None
        await set_tenant(db, org["id"])
        user = (await db.execute(text("SELECT id, org_id, email, role, status FROM users "
                                      "WHERE email = :email AND org_id = :org_id"),
                                 {"email": email, "org_id": org["id"]})).mappings().first()
    else:
        await set_provider(db)
        user = (await db.execute(text("SELECT id, org_id, email, role, status FROM users "
                                      "WHERE email = :email AND org_id IS NULL AND role = 'provider_admin'"),
                                 {"email": email})).mappings().first()

    if user is None or user["status"] != "active":
        return None

    await db.execute(
        text("UPDATE auth_tokens SET consumed_at = :now "
             "WHERE user_id = :uid AND type = 'password_reset' AND consumed_at IS NULL"),
        {"now": now, "uid": user["id"]},
    )
    token, token_hash = new_token()
    await db.execute(
        text("INSERT INTO auth_tokens (user_id, org_id, type, token_hash, created_at, expires_at) "
             "VALUES (:uid, :org_id, 'password_reset', :hash, :now, :expires)"),
        {"uid": user["id"], "org_id": user["org_id"], "hash": token_hash, "now": now, "expires": now + RESET_TTL},
    )
    await write_audit_event(
        db, "password_reset_requested", org_id=user["org_id"], actor_user_id=user["id"], actor_role=user["role"],
        target_type="user", target_id=str(user["id"]),
        request_id=meta.request_id, ip_address=meta.ip, user_agent=meta.user_agent,
    )
    return user["email"], reset_link(token, slug)


async def request_reset(sessionmaker: async_sessionmaker[AsyncSession], email: str, org_slug: str | None,
                        meta: RequestMeta, send_link: ResetSender) -> None:
    """Background task: never raises (the client already got its 200)."""
    try:
        async with sessionmaker() as db, db.begin():
            delivery = await _create_reset_token(db, email, org_slug, meta)
        if delivery is not None:  # send only after the token is committed
            send_link(*delivery)
    except Exception:  # noqa: BLE001
        logger.exception("password reset request failed")


# --- confirm ------------------------------------------------------------------------

async def confirm_reset(db: AsyncSession, token: str, new_password: str, meta: RequestMeta) -> ResetOutcome:
    invalid = ResetOutcome(400, {"detail": INVALID_TOKEN_MESSAGE})
    now = utcnow()

    row = (await db.execute(text("SELECT * FROM auth_resolve_reset_token(:hash)"),
                            {"hash": hash_token(token)})).mappings().first()
    if row is None or row["consumed_at"] is not None or row["expires_at"] <= now:
        return invalid

    if row["org_id"] is None:
        await set_provider(db)
    else:
        await set_tenant(db, row["org_id"])

    user = (await db.execute(
        text("SELECT u.id, u.org_id, u.email, u.role, u.status, o.status AS org_status "
             "FROM users u LEFT JOIN organizations o ON o.id = u.org_id WHERE u.id = :id"),
        {"id": row["user_id"]},
    )).mappings().first()
    if user is None or user["status"] != "active" or (user["org_id"] and user["org_status"] != "active"):
        return invalid

    violations = validate_password(new_password, user["email"])
    if violations:
        # Token stays usable so the user can try a stronger password.
        return ResetOutcome(422, {"detail": "Password does not meet the requirements", "violations": violations})

    user_id: uuid.UUID = user["id"]
    await db.execute(
        text("UPDATE users SET password_hash = :hash, failed_login_count = 0, locked_until = NULL, "
             "updated_at = :now WHERE id = :id"),
        {"hash": hash_password(new_password), "now": now, "id": user_id},
    )
    await db.execute(text("UPDATE auth_tokens SET consumed_at = :now WHERE id = :id"),
                     {"now": now, "id": row["token_id"]})
    revoked = await revoke_user_sessions(db, user_id)
    await write_audit_event(
        db, "password_reset", org_id=user["org_id"], actor_user_id=user_id, actor_role=user["role"],
        target_type="user", target_id=str(user_id),
        request_id=meta.request_id, ip_address=meta.ip, user_agent=meta.user_agent,
        metadata={"sessions_revoked": revoked},
    )
    # No session is created: the user signs in again with password + OTP.
    return ResetOutcome(200, {"message": "Password updated. Please sign in."})
