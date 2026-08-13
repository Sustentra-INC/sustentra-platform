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
from intake.backend.repositories.audit_log_repository import JsonlAuditLogRepository
from intake.backend.repositories.datapoint_state_repository import (
    DatapointStateRepository,
    JsonlDatapointStateRepository,
)
from intake.backend.repositories.escalation_repository import JsonlEscalationRepository
from intake.backend.services.applicability_service import ApplicabilityService
from intake.backend.services.auth_service import AuthError, AuthService
from intake.backend.services.coverage_service import CoverageService
from intake.backend.services.email_service import EmailService
from intake.backend.services.escalation_service import EscalationService
from intake.backend.services.interview_engine import InterviewEngine
from intake.backend.services.org_service import OrgService
from intake.backend.services.profile_state_service import ProfileStateService
from intake.backend.services.seed_form_service import SeedFormService
from intake.backend.services.state_machine import StateMachine


@dataclass
class IntakeContext:
    auth_service: AuthService
    org_service: OrgService
    seed_form_service: SeedFormService
    email_service: EmailService
    profile_state_service: ProfileStateService
    interview_engine: InterviewEngine
    coverage_service: CoverageService
    escalation_service: EscalationService
    state_repository: DatapointStateRepository


def build_default_context() -> IntakeContext:
    """Wire the JSONL-backed services used at runtime."""
    orgs = JsonlOrgRepository()
    users = JsonlUserRepository()
    sites = JsonlSiteRepository()
    tokens = JsonlMagicLinkTokenRepository()
    sessions = JsonlSessionRepository()
    submissions = JsonlSeedProfileRepository()
    email_service = EmailService()

    states = JsonlDatapointStateRepository()
    audit = JsonlAuditLogRepository()
    escalation_records = JsonlEscalationRepository()

    machine = StateMachine(states, audit)
    escalation_service = EscalationService(escalation_records, states, machine)
    profile_state_service = ProfileStateService(machine, states, orgs, sites, submissions)
    interview_engine = InterviewEngine(
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        applicability=ApplicabilityService(),
        escalations=escalation_service,
        profile_states=profile_state_service,
    )

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
        profile_state_service=profile_state_service,
        interview_engine=interview_engine,
        coverage_service=CoverageService(interview_engine),
        escalation_service=escalation_service,
        state_repository=states,
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
