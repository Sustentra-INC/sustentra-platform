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
from intake.backend.repositories.evidence_request_repository import (
    JsonlEvidenceRequestRepository,
)
from intake.backend.adapters.llm import build_llm_client
from intake.backend.config import load_settings
from intake.backend.services.answer_parser import AnswerParser
from intake.backend.services.applicability_service import ApplicabilityService
from intake.backend.services.contradiction_service import ContradictionService
from intake.backend.services.explainer_service import ExplainerService
from intake.backend.services.evidence_request_service import EvidenceRequestService
from intake.backend.services.notification_service import NotificationService
from intake.backend.services.profile_audit_service import ProfileAuditService
from intake.backend.services.profile_service import ProfileService
from intake.backend.services.review_service import ReviewService
from intake.backend.services.question_content import load_question_content
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
    settings: object
    answer_parser: AnswerParser | None = None
    explainer_service: ExplainerService | None = None
    notification_service: NotificationService | None = None
    review_service: ReviewService | None = None
    profile_service: ProfileService | None = None
    evidence_request_service: EvidenceRequestService | None = None


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
    evidence_requests = JsonlEvidenceRequestRepository()
    profile_audit = ProfileAuditService(audit)

    settings = load_settings()
    machine = StateMachine(states, audit)

    # Phase D2: notifications. The email adapter defaults to the local outbox,
    # so nothing here can reach a real person until it is configured.
    notification_service = NotificationService(
        escalation_repository=escalation_records,
        org_repository=orgs,
        site_repository=sites,
        email_service=email_service,
        settings=settings,
    )
    escalation_service = EscalationService(
        escalation_records, states, machine, notifications=notification_service
    )
    review_service = ReviewService(
        escalation_repository=escalation_records,
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        audit_repository=audit,
        settings=settings,
    )
    profile_state_service = ProfileStateService(machine, states, orgs, sites, submissions)

    # Phase D. The LLM adapter defaults to 'disabled', so nothing here makes a
    # paid call unless it is explicitly switched on.
    applicability = ApplicabilityService()
    content = load_question_content()
    llm_client = build_llm_client()
    contradictions = ContradictionService(applicability)
    explainer_service = ExplainerService(llm_client, orgs, sites, content)
    answer_parser = AnswerParser(
        llm_client=llm_client,
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        escalations=escalation_service,
        question_content=content,
    )

    # Phase E: the profile page and the expected-document list.
    evidence_request_service = EvidenceRequestService(
        evidence_request_repository=evidence_requests,
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        escalation_repository=escalation_records,
        settings=settings,
    )

    interview_engine = InterviewEngine(
        state_repository=states,
        org_repository=orgs,
        site_repository=sites,
        state_machine=machine,
        applicability=applicability,
        escalations=escalation_service,
        profile_states=profile_state_service,
        contradictions=contradictions,
        explainers=explainer_service,
    )
    coverage_service = CoverageService(interview_engine)
    profile_service = ProfileService(
        org_repository=orgs,
        site_repository=sites,
        state_repository=states,
        escalation_repository=escalation_records,
        audit_repository=audit,
        coverage_service=coverage_service,
        settings=settings,
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
            profile_audit=profile_audit,
            profile_states=profile_state_service,
        ),
        email_service=email_service,
        profile_state_service=profile_state_service,
        interview_engine=interview_engine,
        coverage_service=coverage_service,
        escalation_service=escalation_service,
        state_repository=states,
        settings=settings,
        answer_parser=answer_parser,
        explainer_service=explainer_service,
        notification_service=notification_service,
        review_service=review_service,
        profile_service=profile_service,
        evidence_request_service=evidence_request_service,
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
