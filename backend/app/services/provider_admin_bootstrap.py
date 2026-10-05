"""ORG-000 - bootstrap a provider_admin (backs `cli create-provider-admin`).

There is no sign-up for provider admins, so the very first one is created from the
API container over SSM. Everything runs on the API's own engine (app_user) under the
provider RLS scope (`set_provider`), in one transaction:

  * INSERT users (role='provider_admin', org_id NULL, status='active').
    Idempotent on the email: `uq_users_email_org_id` is UNIQUE NULLS NOT DISTINCT,
    so ON CONFLICT DO NOTHING turns a second run (or a race) into a no-op.
  * Password: either a bcrypt hash computed by the caller from an interactive
    prompt (same hasher as login), or no password plus a one-time password_reset
    token whose link is returned for the operator to open (until EMAIL-001 sends it).
  * Audit `provider_admin_created` (DB-003). Never includes the password or token.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import set_provider
from ..core.security_primitives import new_token
from .audit_log import write_audit_event
from .password_reset import reset_link

EVENT_TYPE = "provider_admin_created"
# Longer than the self-service reset TTL: the operator may need a moment to hand it over.
BOOTSTRAP_RESET_TTL = timedelta(hours=1)
NAME_MAX_LENGTH = 100

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SELECT_EXISTING = text(
    "SELECT id, status FROM users WHERE email = :email AND org_id IS NULL"
)
_INSERT_ADMIN = text(
    """
    INSERT INTO users (org_id, email, first_name, last_name, full_name, role, status, password_hash)
    VALUES (NULL, :email, :first_name, :last_name, :full_name, 'provider_admin', 'active', :password_hash)
    ON CONFLICT ON CONSTRAINT uq_users_email_org_id DO NOTHING
    RETURNING id
    """
)
_INSERT_RESET_TOKEN = text(
    "INSERT INTO auth_tokens (user_id, org_id, type, token_hash, created_at, expires_at) "
    "VALUES (:uid, NULL, 'password_reset', :hash, :now, :expires)"
)


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    user_id: uuid.UUID
    status: str
    reset_link: str | None = None
    reset_expires_at: datetime | None = None


# --- input -----------------------------------------------------------------------

def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL_RE.fullmatch(value):
        raise ValueError(f"not a valid email address: {email!r}")
    return value


def normalize_name(value: str, label: str) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        raise ValueError(f"{label} must not be empty")
    if len(cleaned) > NAME_MAX_LENGTH:
        raise ValueError(f"{label} must be at most {NAME_MAX_LENGTH} characters")
    return cleaned


# --- db --------------------------------------------------------------------------

async def find_provider_admin(db: AsyncSession, email: str) -> RowMapping | None:
    await set_provider(db)
    return (await db.execute(_SELECT_EXISTING, {"email": email})).mappings().first()


async def create_provider_admin(
    db: AsyncSession,
    *,
    email: str,
    first_name: str,
    last_name: str,
    password_hash: str | None,
    issue_reset_link: bool = False,
) -> BootstrapResult:
    """Create the provider_admin unless one with this email exists (then: no-op).

    Inputs must already be normalized. Pass a bcrypt `password_hash`, or
    `issue_reset_link=True` (password stays NULL until the link is used).
    The caller owns the transaction.
    """
    if password_hash is None and not issue_reset_link:
        raise ValueError("either password_hash or issue_reset_link is required")

    await set_provider(db)
    user_id = (await db.execute(_INSERT_ADMIN, {
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{first_name} {last_name}",
        "password_hash": password_hash,
    })).scalar_one_or_none()

    if user_id is None:  # already there (earlier run or a concurrent one)
        existing = await find_provider_admin(db, email)
        if existing is None:  # pragma: no cover - conflict row vanished mid-transaction
            raise RuntimeError(f"provider_admin {email!r} conflicted but could not be read back")
        return BootstrapResult(created=False, user_id=existing["id"], status=existing["status"])

    link: str | None = None
    expires: datetime | None = None
    if issue_reset_link:
        now = utcnow()
        expires = now + BOOTSTRAP_RESET_TTL
        token, token_hash = new_token()
        await db.execute(_INSERT_RESET_TOKEN,
                         {"uid": user_id, "hash": token_hash, "now": now, "expires": expires})
        link = reset_link(token, None)

    await write_audit_event(
        db, EVENT_TYPE, org_id=None, actor_user_id=None, actor_role="system",
        target_type="user", target_id=str(user_id),
        metadata={
            "source": "cli",
            "password_set": password_hash is not None,
            "reset_link_issued": link is not None,
        },
    )
    return BootstrapResult(created=True, user_id=user_id, status="active",
                           reset_link=link, reset_expires_at=expires)
