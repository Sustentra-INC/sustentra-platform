"""Service wiring for the intake API.

The existing S1 routers each hold a module-level service plus a
``configure_service`` hook for tests. Intake services share repositories, so they
are built once here instead of five times. ``configure_context`` is the same
test hook, applied to the whole set.

The context is built lazily on first use so importing a router never touches the
filesystem or config.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.repositories.magic_link_repository import JsonlMagicLinkTokenRepository
from intake.backend.repositories.org_repository import JsonlOrgRepository
from intake.backend.repositories.seed_profile_repository import JsonlSeedProfileRepository
from intake.backend.repositories.session_repository import JsonlSessionRepository
from intake.backend.repositories.site_repository import JsonlSiteRepository
from intake.backend.repositories.user_repository import JsonlUserRepository
from intake.backend.services.auth_service import AuthError, AuthService
from intake.backend.services.email_service import EmailService
from intake.backend.services.org_service import OrgService
from intake.backend.services.seed_form_service import SeedFormService


@dataclass
class IntakeContext:
    auth_service: AuthService
    org_service: OrgService
    seed_form_service: SeedFormService
    email_service: EmailService


def build_default_context() -> IntakeContext:
    """Wire the JSONL-backed services used at runtime."""
    orgs = JsonlOrgRepository()
    users = JsonlUserRepository()
    sites = JsonlSiteRepository()
    tokens = JsonlMagicLinkTokenRepository()
    sessions = JsonlSessionRepository()
    submissions = JsonlSeedProfileRepository()
    email_service = EmailService()

    return IntakeContext(
        auth_service=AuthService(
            token_repository=tokens,
            session_repository=sessions,
            user_repository=users,
            email_service=email_service,
        ),
        org_service=OrgService(
            org_repository=orgs,
            user_repository=users,
            site_repository=sites,
        ),
        seed_form_service=SeedFormService(
            org_repository=orgs,
            site_repository=sites,
            seed_profile_repository=submissions,
            email_service=email_service,
        ),
        email_service=email_service,
    )


_context: IntakeContext | None = None


def get_context() -> IntakeContext:
    global _context
    if _context is None:
        _context = build_default_context()
    return _context


def configure_context(context: IntakeContext | None) -> None:
    """Swap the shared context (tests inject temp repositories); None resets it."""
    global _context
    _context = context


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign-in required.")
    return token.strip()


def require_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    """FastAPI dependency resolving the caller's session."""
    token = _bearer_token(authorization)
    try:
        return get_context().auth_service.resolve_session(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
