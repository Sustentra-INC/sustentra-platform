"""ORG-001 - organization management by provider admins.

Every function runs in the request's DB transaction, which `get_current_user`
has put in provider scope (`app.is_provider`), so RLS lets it see every org.

Rules:
- slug: ^[a-z0-9-]{3,63}$, unique (409 on a clash), immutable after create.
- create: optional initial_admin = {email, first_name, last_name}; the admin is an
  `org_admin` with status 'invited' (DB-004 vocabulary) and an invite token
  (auth_tokens type 'invite', 24h). Org, user and token are written in the same
  transaction; the email is sent by the route after the response (= after commit).
- max_users (organizations.max_users, 1..10000, default 25): may be lowered below
  the current seat count; that only blocks new seats (ORG-002 / ORG-003).
- suspend: status 'suspended' and every session of the org's users is deleted at
  once (login already refuses suspended orgs). activate: status 'active'; the
  revoked sessions stay revoked. Both are idempotent.
- Audit events (DB-003): org_created, user_invited, org_updated, org_suspended,
  org_activated - names of changed fields only, never values that could be secret.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.tenancy import DEFAULT_MAX_USERS, SEATED_USER_STATUSES
from .audit_log import write_audit_event
from .invite_service import PendingInvite, create_invited_user
from .org_user_service import Actor

__all__ = ["Actor", "PendingInvite", "activate_org", "create_org", "get_org", "list_orgs", "suspend_org",
           "update_org"]

_SEATED = ", ".join(f"'{s}'" for s in SEATED_USER_STATUSES)
_SELECT = f"""
    SELECT o.id, o.name, o.slug, o.status, o.max_users, o.created_at, o.updated_at,
           (SELECT count(*) FROM users u WHERE u.org_id = o.id AND u.status IN ({_SEATED})) AS user_count
      FROM organizations o
"""
_NOT_FOUND = HTTPException(status_code=404, detail="Organization not found")


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _audit(db: AsyncSession, actor: Actor, event: str, org_id: uuid.UUID, *,
                 target_type: str = "organization", target_id: str | None = None,
                 metadata: dict[str, Any] | None = None) -> None:
    await write_audit_event(
        db, event, org_id=org_id, actor_user_id=actor.user_id, actor_role=actor.role,
        target_type=target_type, target_id=target_id or str(org_id), request_id=actor.request_id,
        ip_address=actor.ip_address, user_agent=actor.user_agent, metadata=metadata or {},
    )


async def _get(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    row = (await db.execute(text(_SELECT + " WHERE o.id = :id"), {"id": org_id})).mappings().first()
    if row is None:
        raise _NOT_FOUND
    return dict(row)


async def list_orgs(db: AsyncSession, *, search: str | None, status: str | None, limit: int,
                    offset: int) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = ["TRUE"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if search and search.strip():
        where.append("(o.name ILIKE :q ESCAPE '\\' OR o.slug ILIKE :q ESCAPE '\\')")
        params["q"] = _like(search.strip())
    if status:
        where.append("o.status = :status")
        params["status"] = status
    clause = " AND ".join(where)
    total = (await db.execute(text(f"SELECT count(*) FROM organizations o WHERE {clause}"), params)).scalar_one()
    rows = await db.execute(
        text(_SELECT + f" WHERE {clause} ORDER BY o.created_at DESC, o.id LIMIT :limit OFFSET :offset"), params
    )
    return [dict(r) for r in rows.mappings()], int(total)


async def get_org(db: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    return await _get(db, org_id)


async def create_org(db: AsyncSession, actor: Actor, *, name: str, slug: str, max_users: int | None,
                     initial_admin: dict[str, str] | None) -> tuple[dict[str, Any], PendingInvite | None]:
    if (await db.execute(text("SELECT 1 FROM organizations WHERE slug = :slug"), {"slug": slug})).first():
        raise HTTPException(status_code=409, detail="An organization with this slug already exists")
    try:
        org_id = (await db.execute(
            text("INSERT INTO organizations (name, slug, max_users) VALUES (:name, :slug, :max_users) RETURNING id"),
            {"name": name, "slug": slug, "max_users": max_users or DEFAULT_MAX_USERS},
        )).scalar_one()
    except IntegrityError as exc:  # pragma: no cover - lost a race with another create
        raise HTTPException(status_code=409, detail="An organization with this slug already exists") from exc
    await _audit(db, actor, "org_created", org_id, metadata={"slug": slug, "initial_admin": initial_admin is not None})

    pending: PendingInvite | None = None
    if initial_admin:
        _, _, pending = await create_invited_user(
            db, actor, org_id, email=initial_admin["email"], role="org_admin", first_name=initial_admin["first_name"],
            last_name=initial_admin["last_name"], source="org_created",
        )
    return await _get(db, org_id), pending


async def update_org(db: AsyncSession, actor: Actor, org_id: uuid.UUID, *, name: str | None,
                     max_users: int | None) -> dict[str, Any]:
    await _get(db, org_id)
    changes = {k: v for k, v in (("name", name), ("max_users", max_users)) if v is not None}
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await db.execute(text(f"UPDATE organizations SET {sets}, updated_at = now() WHERE id = :id"),
                         {**changes, "id": org_id})
        await _audit(db, actor, "org_updated", org_id, metadata={"fields": sorted(changes)})
    return await _get(db, org_id)


async def suspend_org(db: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict[str, Any]:
    org = await _get(db, org_id)
    result = await db.execute(text("DELETE FROM sessions WHERE org_id = :id"), {"id": org_id})
    revoked = int(getattr(result, "rowcount", 0) or 0)
    if org["status"] != "suspended":
        await db.execute(text("UPDATE organizations SET status = 'suspended', updated_at = now() WHERE id = :id"),
                         {"id": org_id})
        await _audit(db, actor, "org_suspended", org_id, metadata={"sessions_revoked": revoked})
    return await _get(db, org_id)


async def activate_org(db: AsyncSession, actor: Actor, org_id: uuid.UUID) -> dict[str, Any]:
    org = await _get(db, org_id)
    if org["status"] != "active":
        await db.execute(text("UPDATE organizations SET status = 'active', updated_at = now() WHERE id = :id"),
                         {"id": org_id})
        await _audit(db, actor, "org_activated", org_id)
    return await _get(db, org_id)
