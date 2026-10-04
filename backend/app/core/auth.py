"""Authentication + RBAC dependencies for /api/v1 (AUTH-004).

    current = Depends(get_current_user)            # 401 unless a valid session
    admin   = Depends(require_role("org_admin"))     # 403 for other roles

get_current_user also sets the RLS tenant context for the request's
transaction (AUTH-002): the org from the session, or provider scope for
provider admins. This is the ONLY place request data turns into a tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.sessions import SESSION_COOKIE, resolve_session, touch_session, utcnow
from .db import get_db_session, set_provider, set_tenant

Role = Literal["provider_admin", "org_admin", "org_member"]
ROLES: tuple[Role, ...] = ("provider_admin", "org_admin", "org_member")

_UNAUTHENTICATED = HTTPException(status_code=401, detail="Not authenticated")
_FORBIDDEN = HTTPException(status_code=403, detail="Forbidden")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    first_name: str | None
    last_name: str | None
    full_name: str | None
    role: str
    org_id: uuid.UUID | None
    org_slug: str | None
    session_id: uuid.UUID

    @property
    def is_provider(self) -> bool:
        return self.role == "provider_admin"


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db_session)) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _UNAUTHENTICATED

    resolved = await resolve_session(db, token)
    now = utcnow()
    if resolved is None or not resolved.is_valid(now):
        raise _UNAUTHENTICATED

    # Tenant context comes from the session - never from the request.
    if resolved.org_id is None:
        await set_provider(db)
    else:
        await set_tenant(db, resolved.org_id)

    row = (
        await db.execute(
            text(
                """
                SELECT u.id, u.email, u.first_name, u.last_name, u.full_name, u.role, u.org_id, o.slug
                  FROM users u
                  LEFT JOIN organizations o ON o.id = u.org_id
                 WHERE u.id = :user_id
                """
            ),
            {"user_id": resolved.user_id},
        )
    ).mappings().first()
    if row is None:
        raise _UNAUTHENTICATED

    await touch_session(db, resolved, now)

    user = CurrentUser(
        id=row["id"],
        email=row["email"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        full_name=row["full_name"],
        role=row["role"],
        org_id=row["org_id"],
        org_slug=row["slug"],
        session_id=resolved.session_id,
    )
    request.state.user_id = str(user.id)
    request.state.org_id = str(user.org_id) if user.org_id else None
    return user


def role_allowed(role: str, allowed: tuple[str, ...]) -> bool:
    return role in allowed


def require_role(*roles: Role) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependency factory: 401 without a valid session, 403 for any other role."""
    unknown = set(roles) - set(ROLES)
    if unknown or not roles:
        raise ValueError(f"require_role needs known roles, got {roles!r}")

    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not role_allowed(user.role, roles):
            raise _FORBIDDEN
        return user

    return dependency
