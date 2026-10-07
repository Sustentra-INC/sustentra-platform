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
- Status/role vocabulary (DB-004 decision): the users table stores exactly the API
  values - status invited|active|suspended|deleted, role org_admin|org_member|
  provider_admin (backend.app.domain.tenancy). No mapping in this layer: suspend ->
  status='suspended', reactivate -> status='active'. ('disabled' was retired by 0009.)
- Names: users has first_name and last_name columns (migration 0005); read/write
  those. full_name is legacy display text kept in sync on write.
- max_users (organizations.max_users, 0009): users in SEATED_USER_STATUSES count
  against it; reactivating or inviting when the org is full -> 422 (ORG-001).
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
