"""Org and user management (intake Stage 0).

v1 onboarding is Sustentra-initiated: an internal user creates the org and its
first ``client_owner``, who can then sign in with a magic link and complete the
seed form. There is no public self-signup in v1.

SPEC section 8 scope cut: a user belongs to exactly one org. Attempting to add
an existing user to a second org is rejected rather than silently re-homing them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_settings
from intake.backend.domain.org import Org
from intake.backend.domain.user import User
from intake.backend.repositories.org_repository import OrgRepository
from intake.backend.repositories.site_repository import SiteRepository
from intake.backend.repositories.user_repository import UserRepository, normalise_email


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrgError(Exception):
    """Raised when an org or user operation is not allowed."""


class OrgService:
    def __init__(
        self,
        org_repository: OrgRepository,
        user_repository: UserRepository,
        site_repository: SiteRepository,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._orgs = org_repository
        self._users = user_repository
        self._sites = site_repository
        self._settings = settings or load_settings()
        self._clock = clock

    def create_org(
        self,
        legal_name: str,
        owner_name: str,
        owner_email: str,
        created_by: str,
    ) -> dict[str, Any]:
        """Create a company and its first client_owner."""
        legal_name = legal_name.strip()
        if not legal_name:
            raise OrgError("legal_name is required.")

        email = normalise_email(owner_email)
        if not email or "@" not in email:
            raise OrgError("A valid owner email is required.")

        existing_user = self._users.get_by_email(email)
        if existing_user is not None:
            raise OrgError(
                f"{email} already belongs to org {existing_user['org_id']}. "
                "A user belongs to exactly one org in v1."
            )

        now = self._clock().isoformat()
        org = Org(
            org_id=f"org_{uuid.uuid4().hex[:12]}",
            legal_name=legal_name,
            created_at=now,
            created_by=created_by,
            updated_at=now,
        )
        self._orgs.save(org)

        owner = User(
            user_id=f"usr_{uuid.uuid4().hex[:12]}",
            org_id=org.org_id,
            email=email,
            name=owner_name.strip() or email,
            role="client_owner",
            created_at=now,
        )
        self._users.save(owner)
        return {"org": org.model_dump(), "owner": owner.model_dump()}

    def can_manage_users(self, role: str) -> bool:
        return bool(self._settings.roles.get(role, {}).get("can_manage_users"))

    def can_submit_seed_form(self, role: str) -> bool:
        return bool(self._settings.roles.get(role, {}).get("can_submit_seed_form"))

    def is_internal_role(self, role: str) -> bool:
        """Is this one of ours rather than a client's?

        The distinction is already in the roles config. It matters from Phase D2
        onwards, when ``sustentra_reviewer`` gained the power to read across
        clients: without this, a client owner could grant that role to an email
        they control and read every other client's profile.
        """
        return bool(self._settings.roles.get(role, {}).get("internal"))

    def get_org(self, org_id: str) -> dict[str, Any]:
        org = self._orgs.get(org_id)
        if org is None:
            raise OrgError(f"Unknown org {org_id}.")
        return org

    def add_user(
        self,
        org_id: str,
        name: str,
        email: str,
        role: str,
        actor_role: str | None = None,
    ) -> dict[str, Any]:
        self.get_org(org_id)
        if role not in self._settings.role_names():
            raise OrgError(f"Unknown role {role!r}. Known roles: {self._settings.role_names()}")

        # Only Sustentra staff may create Sustentra staff. A client owner can
        # manage their own team; granting an internal role would hand them the
        # cross-client review queue and every other client's profile.
        #
        # Fails closed: an unstated actor is refused rather than trusted, so a
        # future caller that forgets to pass one cannot open this back up.
        if self.is_internal_role(role) and not self.is_internal_role(actor_role or ""):
            raise OrgError(f"Only Sustentra staff can grant the {role!r} role.")

        address = normalise_email(email)
        existing = self._users.get_by_email(address)
        if existing is not None:
            if existing["org_id"] != org_id:
                raise OrgError(
                    f"{address} already belongs to org {existing['org_id']}. "
                    "A user belongs to exactly one org in v1."
                )
            return existing

        user = User(
            user_id=f"usr_{uuid.uuid4().hex[:12]}",
            org_id=org_id,
            email=address,
            name=name.strip() or address,
            role=role,  # type: ignore[arg-type]
            created_at=self._clock().isoformat(),
        )
        self._users.save(user)
        return user.model_dump()

    def list_users(self, org_id: str) -> list[dict[str, Any]]:
        self.get_org(org_id)
        return self._users.list_by_org(org_id)

    def list_sites(self, org_id: str) -> list[dict[str, Any]]:
        self.get_org(org_id)
        return self._sites.list_by_org(org_id)
