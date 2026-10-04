"""Shared FastAPI dependencies for the /api/v1 admin surface (ORG-001..003).

Role guards are PLACEHOLDERS. The real implementation lands with AUTH-004, which
adds the session cookie -> user resolution and the RLS tenant context. Until then
every guard answers 501 so the routing, request validation, response models and
middleware can be exercised end to end exactly like the AUTH-001 auth stubs.

No `from __future__ import annotations`: these are used as FastAPI dependencies
and FastAPI must be able to resolve the annotations at runtime.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Shape is indicative; AUTH-004 owns the real one."""

    user_id: str
    role: str
    org_id: str | None = None


def _not_implemented(guard: str) -> HTTPException:
    return HTTPException(status_code=501, detail=f"Not implemented yet (AUTH-004): {guard}")


async def require_provider_admin(request: Request) -> Principal:
    """Allow only provider_admin callers.

    TODO(AUTH-004): resolve the session cookie -> user, verify role == 'provider_admin',
    set app.is_provider for the request's DB session, and return the Principal.
    403 for an authenticated non-provider caller; 401 when unauthenticated.
    """
    raise _not_implemented("require_provider_admin")


async def require_org_admin(request: Request, org_id: str) -> Principal:
    """Allow a provider_admin, or an org_admin acting on their OWN org.

    TODO(AUTH-004): resolve the session, verify role in ('provider_admin','org_admin'),
    set the RLS tenant context (app.tenant_id / app.is_provider) and return the Principal.
    Cross-org access by a non-provider caller must look like the org does not exist:
    return 404, never 403 (see ORG-002/ORG-003 acceptance notes).
    """
    raise _not_implemented("require_org_admin")
