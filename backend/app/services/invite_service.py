"""ORG-003 - invite and accept.

Invite tokens live in auth_tokens with type 'invite': the raw token is only ever in
the email link; the table stores its SHA-256 hash. TTL 24h.

create (org admin for their org, or provider admin):
- role org_admin | org_member; email lowercased; 409 if a (non-deleted) user with
  that email is already in the org; 422 if the org's seats are all taken
  (SEATED_USER_STATUSES >= organizations.max_users). The org row is locked
  (SELECT ... FOR UPDATE) first, so two invites cannot take the last seat together.
- the user is created up-front: status 'invited', no password, invited_by = actor.
- the email (link {PUBLIC_BASE_URL}/invite/accept?token=...) is sent by the route
  after the response, i.e. after the transaction has committed.
resend: only for a user still 'invited' (409 otherwise); every earlier unused
  invite token of the user is invalidated (consumed_at set) and a new one is sent.
validate / accept (public, rate limited): one generic 400 for a token that is
  unknown, expired, already used, or whose user / org is no longer invitable.
  accept checks the password policy (AUTH-003, 422 - the token stays usable),
  then sets password_hash, status 'active', and consumes the token (and any other
  invite tokens of the user) in one transaction. It does NOT create a session: the
  user signs in normally with password + email OTP.
Audit events (DB-003): user_invited, user_invite_resent, invite_accepted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.db import set_tenant
from ..core.security_primitives import hash_password, hash_token, new_token, validate_password
from ..domain.tenancy import SEATED_USER_STATUSES
from .audit_log import write_audit_event
from .org_user_service import Actor

INVITE_TTL = timedelta(hours=24)
INVITE_TTL_HOURS = 24
INVALID_INVITE_MESSAGE = "This invite link is invalid or has expired. Ask your administrator to send a new one."

_ORG_NOT_FOUND = HTTPException(status_code=404, detail="Organization not found")
_USER_NOT_FOUND = HTTPException(status_code=404, detail="User not found")
_SEATED = ", ".join(f"'{s}'" for s in SEATED_USER_STATUSES)

__all__ = ["Actor", "INVITE_TTL", "PendingInvite", "accept_invite", "create_invite", "create_invited_user",
           "invite_link", "resend_invite", "validate_invite"]


@dataclass(frozen=True)
class PendingInvite:
    """An invite email to send once the transaction has committed."""

    to: str
    link: str


@dataclass(frozen=True)
class InviteOutcome:
    """Status code + JSON body for the public endpoints (they never raise for bad tokens)."""

    status: int
    body: dict[str, Any]


def utcnow() -> datetime:
    """Single clock for this module (tests monkeypatch it)."""
    return datetime.now(UTC)


def invite_link(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/invite/accept?token={quote(token)}"


def _uuid(value: str, not_found: HTTPException) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise not_found from None


async def _audit(db: AsyncSession, actor: Actor, event: str, org_id: uuid.UUID, user_id: uuid.UUID,
                 metadata: dict[str, Any]) -> None:
    await write_audit_event(
        db, event, org_id=org_id, actor_user_id=actor.user_id, actor_role=actor.role, target_type="user",
        target_id=str(user_id), request_id=actor.request_id, ip_address=actor.ip_address,
        user_agent=actor.user_agent, metadata=metadata,
    )


async def _issue_token(db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, datetime]:
    """Invalidate the user's unused invite tokens and create a fresh one. Returns (raw token, expires_at)."""
    now = utcnow()
    await db.execute(
        text("UPDATE auth_tokens SET consumed_at = :now "
             "WHERE user_id = :uid AND type = 'invite' AND consumed_at IS NULL"),
        {"now": now, "uid": user_id},
    )
    token, token_hash = new_token()
    expires = now + INVITE_TTL
    await db.execute(
        text("INSERT INTO auth_tokens (user_id, org_id, type, token_hash, created_at, expires_at) "
             "VALUES (:uid, :org_id, 'invite', :hash, :now, :expires)"),
        {"uid": user_id, "org_id": org_id, "hash": token_hash, "now": now, "expires": expires},
    )
    return token, expires


async def create_invited_user(db: AsyncSession, actor: Actor, org_id: uuid.UUID, *, email: str, role: str,
                              first_name: str, last_name: str,
                              source: str) -> tuple[uuid.UUID, datetime, PendingInvite]:
    """Insert the invited user + token and audit it. No seat/duplicate checks: callers do those."""
    user_id = (await db.execute(
        text("""
            INSERT INTO users (org_id, email, first_name, last_name, full_name, role, status, invited_by)
            VALUES (:org_id, :email, :first, :last, :full, :role, 'invited', :invited_by) RETURNING id
        """),
        {"org_id": org_id, "email": email, "first": first_name, "last": last_name,
         "full": f"{first_name} {last_name}".strip(), "role": role, "invited_by": actor.user_id},
    )).scalar_one()
    token, expires = await _issue_token(db, user_id, org_id)
    await _audit(db, actor, "user_invited", org_id, user_id, {"role": role, "source": source})
    return user_id, expires, PendingInvite(to=email, link=invite_link(token))


async def _invite_row(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, expires: datetime) -> dict[str, Any]:
    row = (await db.execute(
        text("SELECT id, org_id, email, COALESCE(first_name, '') AS first_name, COALESCE(last_name, '') AS last_name, "
             "role, status, created_at FROM users WHERE id = :id AND org_id = :org_id"),
        {"id": user_id, "org_id": org_id},
    )).mappings().one()
    return {**dict(row), "user_id": row["id"], "expires_at": expires}


async def create_invite(db: AsyncSession, actor: Actor, org_id: str, *, email: str, role: str, first_name: str,
                        last_name: str) -> tuple[dict[str, Any], PendingInvite]:
    oid = _uuid(org_id, _ORG_NOT_FOUND)
    # Lock the org: serializes seat checks against other invites and max_users edits.
    org = (await db.execute(text("SELECT id, max_users FROM organizations WHERE id = :id FOR UPDATE"),
                            {"id": oid})).mappings().first()
    if org is None:
        raise _ORG_NOT_FOUND
    taken = (await db.execute(
        text("SELECT 1 FROM users WHERE org_id = :org_id AND email = :email AND status <> 'deleted'"),
        {"org_id": oid, "email": email},
    )).first()
    if taken:
        raise HTTPException(status_code=409, detail="A user with this email already exists in this organization")
    used = (await db.execute(text(f"SELECT count(*) FROM users WHERE org_id = :org_id AND status IN ({_SEATED})"),
                             {"org_id": oid})).scalar_one()
    if used >= org["max_users"]:
        raise HTTPException(
            status_code=422,
            detail=f"All {org['max_users']} seats are in use. Remove a user or ask your provider for more seats.",
        )
    user_id, expires, pending = await create_invited_user(
        db, actor, oid, email=email, role=role, first_name=first_name, last_name=last_name, source="invite"
    )
    return await _invite_row(db, oid, user_id, expires), pending


async def resend_invite(db: AsyncSession, actor: Actor, org_id: str, user_id: str) -> tuple[dict[str, Any],
                                                                                              PendingInvite]:
    oid = _uuid(org_id, _ORG_NOT_FOUND)
    uid = _uuid(user_id, _USER_NOT_FOUND)
    if (await db.execute(text("SELECT 1 FROM organizations WHERE id = :id"), {"id": oid})).first() is None:
        raise _ORG_NOT_FOUND
    user = (await db.execute(
        text("SELECT id, email, status FROM users WHERE id = :id AND org_id = :org_id AND status <> 'deleted' "
             "FOR UPDATE"),
        {"id": uid, "org_id": oid},
    )).mappings().first()
    if user is None:
        raise _USER_NOT_FOUND
    if user["status"] != "invited":
        raise HTTPException(status_code=409, detail="This user is not waiting for an invite")
    token, expires = await _issue_token(db, uid, oid)
    await _audit(db, actor, "user_invite_resent", oid, uid, {})
    return await _invite_row(db, oid, uid, expires), PendingInvite(to=user["email"], link=invite_link(token))


# --- public: validate / accept --------------------------------------------------------

async def _resolve(db: AsyncSession, token: str, *, lock: bool) -> dict[str, Any] | None:
    """The invite + invitee + org for a usable token, or None (-> the generic 400)."""
    found = (await db.execute(text("SELECT * FROM auth_resolve_invite_token(:hash)"),
                              {"hash": hash_token(token)})).mappings().first()
    if found is None or found["consumed_at"] is not None or found["expires_at"] <= utcnow():
        return None
    if found["org_id"] is None:  # invites are for org users only
        return None
    await set_tenant(db, found["org_id"])
    row = (await db.execute(
        text("SELECT u.id AS user_id, u.org_id, u.email, u.role, u.status, COALESCE(u.first_name, '') AS first_name, "
             "COALESCE(u.last_name, '') AS last_name, o.name AS org_name, o.slug AS org_slug, o.status AS org_status "
             "FROM users u JOIN organizations o ON o.id = u.org_id WHERE u.id = :id"
             + (" FOR UPDATE OF u" if lock else "")),
        {"id": found["user_id"]},
    )).mappings().first()
    if row is None or row["status"] != "invited" or row["org_status"] != "active":
        return None
    return {**dict(row), "token_id": found["token_id"]}


async def validate_invite(db: AsyncSession, token: str) -> InviteOutcome:
    invite = await _resolve(db, token, lock=False)
    if invite is None:
        return InviteOutcome(400, {"detail": INVALID_INVITE_MESSAGE})
    return InviteOutcome(200, {k: invite[k] for k in ("email", "first_name", "last_name", "org_name", "org_slug")})


async def accept_invite(db: AsyncSession, token: str, password: str, *, request_id: str | None,
                        ip_address: str | None, user_agent: str | None) -> InviteOutcome:
    invite = await _resolve(db, token, lock=True)
    if invite is None:
        return InviteOutcome(400, {"detail": INVALID_INVITE_MESSAGE})
    violations = validate_password(password, invite["email"])
    if violations:
        # The token stays usable so the user can pick a stronger password.
        return InviteOutcome(422, {"detail": "Password does not meet the requirements", "violations": violations})

    now = utcnow()
    # Single use: whichever request flips consumed_at first wins (the user row lock
    # above already serializes two accepts of the same invite).
    consumed = (await db.execute(
        text("UPDATE auth_tokens SET consumed_at = :now WHERE id = :id AND consumed_at IS NULL RETURNING id"),
        {"now": now, "id": invite["token_id"]},
    )).first()
    if consumed is None:  # pragma: no cover - only reachable in a race the row lock prevents
        return InviteOutcome(400, {"detail": INVALID_INVITE_MESSAGE})
    await db.execute(
        text("UPDATE auth_tokens SET consumed_at = :now WHERE user_id = :uid AND type = 'invite' "
             "AND consumed_at IS NULL"),
        {"now": now, "uid": invite["user_id"]},
    )
    await db.execute(
        text("UPDATE users SET password_hash = :hash, status = 'active', failed_login_count = 0, "
             "locked_until = NULL, updated_at = :now WHERE id = :id"),
        {"hash": hash_password(password), "now": now, "id": invite["user_id"]},
    )
    await write_audit_event(
        db, "invite_accepted", org_id=invite["org_id"], actor_user_id=invite["user_id"], actor_role=invite["role"],
        target_type="user", target_id=str(invite["user_id"]), request_id=request_id, ip_address=ip_address,
        user_agent=user_agent,
    )
    # No session: the user signs in with password + OTP (AUTH-005).
    return InviteOutcome(200, {
        "user_id": str(invite["user_id"]), "org_id": str(invite["org_id"]), "email": invite["email"],
        "org_slug": invite["org_slug"], "accepted_at": now.isoformat(),
    })
