"""ORG-002 - user management within an organization (org admin).

SKELETON ONLY. Every method raises NotImplementedError. Methods are async (MVP
runs SQLAlchemy async). Router guards (require_org_admin) currently 501 before
these run; the bodies pin down the contract + cross-ticket dependencies.

Acceptance rules to honour when implementing:
- All queries are tenant-scoped. A caller (non-provider) asking about another org's
  user must get 404, not 403 - rely on RLS (app.tenant_id) rather than a WHERE alone.
- Role changes are limited to org_admin <-> org_member. Never promote to provider_admin.
- Last-admin safety: the final remaining active org_admin cannot be demoted or
  suspended -> 409. Check inside the same transaction to avoid a race.
- `status` in the API is 'active'|'suspended'. The users table stores 'active'|'disabled'
  (migration 0002), so suspend -> status='disabled', reactivate -> status='active'.
  TODO(DB): decide whether to rename the DB enum or map in this layer (mapping now).
- The users table stores a single `full_name`; the API exposes first_name/last_name.
  TODO(DB): either split the column or map names here consistently with ORG-003.
- max_users: reactivating a user when the org is already at its limit -> 422 (ORG-001).
"""

from __future__ import annotations

from typing import Any


class OrgUserService:
    async def list_users(
        self,
        *,
        org_id: str,
        status: str | None,
        role: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (rows, total) for a paginated, filtered user list within one org."""
        # TODO(DB): tenant-scoped SELECT with status/role filters, LIMIT/OFFSET + COUNT(*).
        raise NotImplementedError("ORG-002: list_users")

    async def get_user(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        # TODO(DB): tenant-scoped SELECT by id; 404 when missing or cross-org.
        raise NotImplementedError("ORG-002: get_user")

    async def change_role(self, *, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        # TODO(DB): UPDATE role (org_admin|org_member only); 404 when missing/cross-org.
        # TODO(DB): enforce last-active-admin cannot be demoted -> 409.
        # TODO(DB-003): emit audit event 'user_role_changed'.
        raise NotImplementedError("ORG-002: change_role")

    async def suspend_user(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        # TODO(DB): set status='disabled'; 404 when missing/cross-org. Idempotent.
        # TODO(DB): enforce last-active-admin cannot be suspended -> 409.
        # TODO(AUTH-004): revoke the user's active sessions on suspend.
        # TODO(DB-003): emit audit event 'user_suspended'.
        raise NotImplementedError("ORG-002: suspend_user")

    async def reactivate_user(self, *, org_id: str, user_id: str) -> dict[str, Any]:
        # TODO(DB): set status='active'; 404 when missing/cross-org. Idempotent.
        # TODO(DB): reject when the org is at max_users -> 422.
        # TODO(DB-003): emit audit event 'user_reactivated'.
        raise NotImplementedError("ORG-002: reactivate_user")


def get_org_user_service() -> OrgUserService:
    """FastAPI dependency factory. TODO(AUTH-004/DB): inject the request's async session."""
    return OrgUserService()
