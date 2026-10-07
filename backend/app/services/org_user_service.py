"""ORG-002 - user management within an organization (org admin, or provider admin for any org).

Every function runs in the request's DB transaction. `get_current_user` has already
set the RLS scope: tenant scope for an org admin (they can only see their own org's
rows), provider scope for a provider admin. `require_org_admin` has already turned a
cross-org path into 404; RLS is the second layer, and every query also filters on
org_id explicitly.

Rules:
- Users with status 'deleted' (COMP-001) do not exist as far as this API is concerned.
- Roles: only org_admin <-> org_member. provider_admin is never assignable.
- An org admin cannot demote or suspend themselves (409).
- The org always keeps at least one ACTIVE org_admin: demoting or suspending the last
  one -> 409. The org's active admins are locked (SELECT ... FOR UPDATE, id order)
  before anything else, so two admins demoting each other at the same moment
  serialize: one succeeds, the other gets 409 - never zero admins, never a deadlock.
- suspend: status 'suspended', every session of the user deleted at once, and their
  outstanding tokens (OTP, password reset, invite) deleted. Idempotent.
- reactivate: back to 'active', or to 'invited' if they never set a password (an
  invited user who was suspended gets their invite flow back via ORG-003 resend).
  Seats: suspended users already hold a seat (SEATED_USER_STATUSES), so reactivating
  never exceeds max_users. Idempotent.
- Audit events (DB-003): user_role_changed (from/to), user_suspended
  (sessions_revoked), user_reactivated (status).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.tenancy import SEATED_USER_STATUSES
from .audit_log import write_audit_event
from .sessions import revoke_user_sessions

_ORG_NOT_FOUND = HTTPException(status_code=404, detail="Organization not found")
_USER_NOT_FOUND = HTTPException(status_code=404, detail="User not found")
_LAST_ADMIN = HTTPException(status_code=409, detail="The organization must keep at least one active admin")

_SEATED = ", ".join(f"'{s}'" for s in SEATED_USER_STATUSES)
_SELECT = """
    SELECT u.id, u.org_id, u.email, COALESCE(u.first_name, '') AS first_name,
           COALESCE(u.last_name, '') AS last_name, u.role, u.status, u.last_login_at,
           u.created_at, u.updated_at
      FROM users u
"""


@dataclass(frozen=True)
class Actor:
    """Who did it, for the audit trail and the self-checks."""

    user_id: uuid.UUID
    role: str
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


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


async def _org(db: AsyncSession, org_id: str) -> dict[str, Any]:
    oid = _uuid(org_id, _ORG_NOT_FOUND)
    row = (await db.execute(
        text(f"""
            SELECT o.id, o.max_users,
                   (SELECT count(*) FROM users u WHERE u.org_id = o.id AND u.status IN ({_SEATED})) AS seats_used
              FROM organizations o WHERE o.id = :id
        """),
        {"id": oid},
    )).mappings().first()
    if row is None:
        raise _ORG_NOT_FOUND
    return dict(row)


async def _user(db: AsyncSession, org_id: uuid.UUID, user_id: str, *, lock: bool = False) -> dict[str, Any]:
    uid = _uuid(user_id, _USER_NOT_FOUND)
    sql = _SELECT + " WHERE u.id = :uid AND u.org_id = :org_id AND u.status <> 'deleted'"
    if lock:
        sql += " FOR UPDATE OF u"
    row = (await db.execute(text(sql), {"uid": uid, "org_id": org_id})).mappings().first()
    if row is None:
        raise _USER_NOT_FOUND
    return dict(row)


async def _lock_active_admins(db: AsyncSession, org_id: uuid.UUID) -> list[uuid.UUID]:
    """Lock the org's active admins (always first, always in id order, so concurrent
    role changes / suspensions serialize without deadlocking) and return their ids."""
    return list((await db.execute(
        text("SELECT id FROM users WHERE org_id = :org_id AND role = 'org_admin' AND status = 'active' "
             "ORDER BY id FOR UPDATE"),
        {"org_id": org_id},
    )).scalars().all())


def _ensure_another_active_admin(active_admins: list[uuid.UUID], user_id: uuid.UUID) -> None:
    if not [a for a in active_admins if a != user_id]:
        raise _LAST_ADMIN


def _refuse_self(actor: Actor, user_id: uuid.UUID, action: str) -> None:
    if actor.user_id == user_id:
        raise HTTPException(status_code=409, detail=f"You cannot {action} yourself")


async def list_users(db: AsyncSession, org_id: str, *, status: str | None, role: str | None, limit: int,
                     offset: int) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """(rows, total matching the filters, {max_users, seats_used}) for one org, newest first."""
    org = await _org(db, org_id)
    where = ["u.org_id = :org_id", "u.status <> 'deleted'"]
    params: dict[str, Any] = {"org_id": org["id"], "limit": limit, "offset": offset}
    if status:
        where.append("u.status = :status")
        params["status"] = status
    if role:
        where.append("u.role = :role")
        params["role"] = role
    clause = " AND ".join(where)
    total = (await db.execute(text(f"SELECT count(*) FROM users u WHERE {clause}"), params)).scalar_one()
    rows = await db.execute(
        text(_SELECT + f" WHERE {clause} ORDER BY u.created_at DESC, u.id LIMIT :limit OFFSET :offset"), params
    )
    seats = {"max_users": int(org["max_users"]), "seats_used": int(org["seats_used"])}
    return [dict(r) for r in rows.mappings()], int(total), seats


async def get_user(db: AsyncSession, org_id: str, user_id: str) -> dict[str, Any]:
    org = await _org(db, org_id)
    return await _user(db, org["id"], user_id)


async def change_role(db: AsyncSession, actor: Actor, org_id: str, user_id: str, role: str) -> dict[str, Any]:
    org = await _org(db, org_id)
    admins = await _lock_active_admins(db, org["id"])
    user = await _user(db, org["id"], user_id, lock=True)
    if user["role"] == role:
        return user
    if user["role"] == "org_admin":  # a demotion
        _refuse_self(actor, user["id"], "demote")
        if user["status"] == "active":
            _ensure_another_active_admin(admins, user["id"])
    await db.execute(text("UPDATE users SET role = :role, updated_at = now() WHERE id = :id"),
                     {"role": role, "id": user["id"]})
    await _audit(db, actor, "user_role_changed", org["id"], user["id"], {"from": user["role"], "to": role})
    return await _user(db, org["id"], user_id)


async def suspend_user(db: AsyncSession, actor: Actor, org_id: str, user_id: str) -> dict[str, Any]:
    org = await _org(db, org_id)
    admins = await _lock_active_admins(db, org["id"])
    user = await _user(db, org["id"], user_id, lock=True)
    _refuse_self(actor, user["id"], "suspend")
    if user["status"] == "suspended":
        return user
    if user["role"] == "org_admin" and user["status"] == "active":
        _ensure_another_active_admin(admins, user["id"])
    await db.execute(text("UPDATE users SET status = 'suspended', updated_at = now() WHERE id = :id"),
                     {"id": user["id"]})
    revoked = await revoke_user_sessions(db, user["id"])
    await db.execute(text("DELETE FROM auth_tokens WHERE user_id = :id AND consumed_at IS NULL"), {"id": user["id"]})
    await _audit(db, actor, "user_suspended", org["id"], user["id"],
                 {"previous_status": user["status"], "sessions_revoked": revoked})
    return await _user(db, org["id"], user_id)


async def reactivate_user(db: AsyncSession, actor: Actor, org_id: str, user_id: str) -> dict[str, Any]:
    org = await _org(db, org_id)
    user = await _user(db, org["id"], user_id, lock=True)
    if user["status"] != "suspended":
        return user
    has_password = (await db.execute(text("SELECT password_hash IS NOT NULL FROM users WHERE id = :id"),
                                     {"id": user["id"]})).scalar_one()
    new_status = "active" if has_password else "invited"
    await db.execute(text("UPDATE users SET status = :status, updated_at = now() WHERE id = :id"),
                     {"status": new_status, "id": user["id"]})
    await _audit(db, actor, "user_reactivated", org["id"], user["id"], {"status": new_status})
    return await _user(db, org["id"], user_id)
