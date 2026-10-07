"""Shared FastAPI dependencies for the /api/v1 admin surface (ORG-001..003).

Role guards are now wired to the shipped AUTH-004 session/RBAC layer
(``core.auth.require_role`` + ``get_current_user``): 401 without a valid session,
403 for the wrong role, and — for an org_admin reaching into another org — 404.
The service bodies are still ``NotImplementedError`` pending ORG-001..003; the
columns they need now exist (DB-004: ``organizations.max_users``, one status vocabulary).

No ``from __future__ import annotations``: these are used as FastAPI dependencies
and FastAPI must be able to resolve the annotations at runtime.
"""

from fastapi import Depends, HTTPException

from ...core.auth import CurrentUser, require_role

# The authenticated caller, as resolved by AUTH-004.
Principal = CurrentUser

# Provider-admin only. 401 unauthenticated, 403 for any other role.
require_provider_admin = require_role("provider_admin")


async def require_org_admin(
    org_id: str,
    principal: CurrentUser = Depends(require_role("org_admin", "provider_admin")),
) -> CurrentUser:
    """Allow a provider_admin (any org), or an org_admin acting on their OWN org.

    Cross-org access by a non-provider caller must look like the org does not
    exist: return 404, never 403 (see ORG-002/ORG-003 acceptance notes). The RLS
    tenant context is already set by ``get_current_user`` for the request's DB
    session.
    """
    if not principal.is_provider and str(principal.org_id) != str(org_id):
        raise HTTPException(status_code=404, detail="Organization not found")
    return principal
