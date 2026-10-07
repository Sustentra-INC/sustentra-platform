"""ORG-001 - organization management (provider admin).

SKELETON ONLY. Every method raises NotImplementedError; the real async DB work
lands with the ORG-001 implementation ticket. Methods are async because the MVP
runs SQLAlchemy async (asyncpg, per MVP-7). The router guards (require_provider_admin)
currently short-circuit with 501, so these bodies are not reached at runtime yet -
they exist to pin down the contract and the cross-ticket dependencies for Jerome.

Acceptance rules to honour when implementing:
- slug: 3-63 chars, lowercase alphanumeric + hyphen (^[a-z0-9-]{3,63}$), unique.
  DB already enforces the format + uniqueness (migration 0002); return 409 on clash.
- create: optional initial_admin creates a seated org_admin user AND sends an invite.
- organizations.status ('active'|'suspended', migration 0005) and
  organizations.max_users (1..10000, default 25, migration 0009) are columns; the
  API uses the same values (backend.app.domain.tenancy, DB-004 decision).
- max_users: creating/activating a user at the limit must fail with 422 (ORG-002).
  Lowering max_users below the current seat count is allowed but blocks new seats.
- suspend: suspends the org and (per spec) blocks its users from logging in.
"""

from __future__ import annotations

from typing import Any


class OrganizationService:
    async def list_orgs(
        self,
        *,
        search: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (rows, total) for a paginated, optionally filtered org list."""
        # TODO(DB): SELECT with ILIKE on name/slug, status filter, LIMIT/OFFSET + COUNT(*).
        raise NotImplementedError("ORG-001: list_orgs")

    async def create_org(
        self,
        *,
        name: str,
        slug: str,
        initial_admin: dict[str, Any] | None,
    ) -> dict[str, Any]:
        # TODO(DB): INSERT organization; 409 on duplicate slug (uq_organizations_slug).
        # TODO(DB): if initial_admin, INSERT a seated org_admin user in the same tx.
        # TODO(EMAIL-001): if initial_admin, send the invite email with the signup token.
        # TODO(DB-003): emit audit event 'org_created' (+ 'user_invited' if seeded).
        raise NotImplementedError("ORG-001: create_org")

    async def get_org(self, *, org_id: str) -> dict[str, Any]:
        # TODO(DB): SELECT by id; 404 when missing.
        raise NotImplementedError("ORG-001: get_org")

    async def update_org(
        self,
        *,
        org_id: str,
        name: str | None,
        max_users: int | None,
    ) -> dict[str, Any]:
        # TODO(DB): partial UPDATE of name/max_users; 404 when missing.
        # TODO(DB-003): emit audit event 'org_updated' with the changed fields.
        raise NotImplementedError("ORG-001: update_org")

    async def suspend_org(self, *, org_id: str) -> dict[str, Any]:
        # TODO(DB): set status='suspended'; 404 when missing. Idempotent.
        # TODO(DB-003): emit audit event 'org_suspended'.
        raise NotImplementedError("ORG-001: suspend_org")

    async def activate_org(self, *, org_id: str) -> dict[str, Any]:
        # TODO(DB): set status='active'; 404 when missing. Idempotent.
        # TODO(DB-003): emit audit event 'org_activated'.
        raise NotImplementedError("ORG-001: activate_org")


def get_organization_service() -> OrganizationService:
    """FastAPI dependency factory. TODO(AUTH-004/DB): inject the request's async session."""
    return OrganizationService()
