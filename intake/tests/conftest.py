"""Shared fixtures for the intake test suite.

Every fixture wires the services with in-memory repositories and an in-memory
email sender, so tests touch no files and send nothing. The clock is injectable
so token and session expiry can be tested without sleeping.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.api.context import IntakeContext, configure_context  # noqa: E402
from intake.backend.config import load_settings  # noqa: E402
from intake.backend.repositories.magic_link_repository import (  # noqa: E402
    InMemoryMagicLinkTokenRepository,
)
from intake.backend.repositories.org_repository import InMemoryOrgRepository  # noqa: E402
from intake.backend.repositories.seed_profile_repository import (  # noqa: E402
    InMemorySeedProfileRepository,
)
from intake.backend.repositories.session_repository import InMemorySessionRepository  # noqa: E402
from intake.backend.repositories.site_repository import InMemorySiteRepository  # noqa: E402
from intake.backend.repositories.user_repository import InMemoryUserRepository  # noqa: E402
from intake.backend.repositories.audit_log_repository import (  # noqa: E402
    InMemoryAuditLogRepository,
)
from intake.backend.repositories.datapoint_state_repository import (  # noqa: E402
    InMemoryDatapointStateRepository,
)
from intake.backend.repositories.escalation_repository import (  # noqa: E402
    InMemoryEscalationRepository,
)
from intake.backend.adapters.llm import ScriptedLLMClient  # noqa: E402
from intake.backend.services.answer_parser import AnswerParser  # noqa: E402
from intake.backend.services.applicability_service import ApplicabilityService  # noqa: E402
from intake.backend.services.contradiction_service import ContradictionService  # noqa: E402
from intake.backend.services.explainer_service import ExplainerService  # noqa: E402
from intake.backend.services.notification_service import NotificationService  # noqa: E402
from intake.backend.services.review_service import ReviewService  # noqa: E402
from intake.backend.services.question_content import load_question_content  # noqa: E402
from intake.backend.services.auth_service import AuthService  # noqa: E402
from intake.backend.services.coverage_service import CoverageService  # noqa: E402
from intake.backend.services.interview_engine import InterviewEngine  # noqa: E402
from intake.backend.services.email_service import EmailService, InMemoryEmailSender  # noqa: E402
from intake.backend.services.escalation_service import EscalationService  # noqa: E402
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.profile_state_service import ProfileStateService  # noqa: E402
from intake.backend.services.seed_form_service import SeedFormService  # noqa: E402
from intake.backend.services.state_machine import StateMachine  # noqa: E402


class MutableClock:
    """A clock the tests can move forward."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


class Harness:
    """Everything a test needs, wired together."""

    def __init__(self) -> None:
        self.clock = MutableClock()
        # A private copy: load_settings() is cached, so a test that changes a
        # setting would otherwise leak into every test that ran after it.
        self.settings = load_settings().model_copy(deep=True)
        self.orgs = InMemoryOrgRepository()
        self.users = InMemoryUserRepository()
        self.sites = InMemorySiteRepository()
        self.tokens = InMemoryMagicLinkTokenRepository()
        self.sessions = InMemorySessionRepository()
        self.submissions = InMemorySeedProfileRepository()
        self.mailbox = InMemoryEmailSender()
        self.email_service = EmailService(sender=self.mailbox, settings=self.settings)

        self.auth_service = AuthService(
            token_repository=self.tokens,
            session_repository=self.sessions,
            user_repository=self.users,
            email_service=self.email_service,
            settings=self.settings,
            clock=self.clock,
        )
        self.org_service = OrgService(
            org_repository=self.orgs,
            user_repository=self.users,
            site_repository=self.sites,
            settings=self.settings,
            clock=self.clock,
        )
        self.seed_form_service = SeedFormService(
            org_repository=self.orgs,
            site_repository=self.sites,
            seed_profile_repository=self.submissions,
            email_service=self.email_service,
            settings=self.settings,
            clock=self.clock,
        )
        # Phase C1: state machine, applicability, escalations.
        self.states = InMemoryDatapointStateRepository()
        self.audit = InMemoryAuditLogRepository()
        self.escalations = InMemoryEscalationRepository()
        self.state_machine = StateMachine(self.states, self.audit, clock=self.clock)
        self.applicability = ApplicabilityService()
        # Phase D2: notifications and the reviewer queue. Wired in here so tests
        # exercise the same escalation -> email path the runtime uses.
        self.notification_service = NotificationService(
            escalation_repository=self.escalations,
            org_repository=self.orgs,
            site_repository=self.sites,
            email_service=self.email_service,
            settings=self.settings,
            clock=self.clock,
        )
        self.escalation_service = EscalationService(
            escalation_repository=self.escalations,
            state_repository=self.states,
            state_machine=self.state_machine,
            clock=self.clock,
            notifications=self.notification_service,
        )
        self.review_service = ReviewService(
            escalation_repository=self.escalations,
            state_repository=self.states,
            org_repository=self.orgs,
            site_repository=self.sites,
            audit_repository=self.audit,
            settings=self.settings,
            clock=self.clock,
        )
        self.profile_state_service = ProfileStateService(
            state_machine=self.state_machine,
            state_repository=self.states,
            org_repository=self.orgs,
            site_repository=self.sites,
            seed_profile_repository=self.submissions,
            clock=self.clock,
        )

        # Phase D: a scripted model, so tests never make a real call.
        self.llm = ScriptedLLMClient()
        self.question_content = load_question_content()
        self.contradictions = ContradictionService(self.applicability)
        self.explainer_service = ExplainerService(
            self.llm, self.orgs, self.sites, self.question_content
        )
        self.answer_parser = AnswerParser(
            llm_client=self.llm,
            state_repository=self.states,
            org_repository=self.orgs,
            site_repository=self.sites,
            state_machine=self.state_machine,
            escalations=self.escalation_service,
            question_content=self.question_content,
        )

        # Phase C2: the interview engine and coverage meter.
        self.interview_engine = InterviewEngine(
            state_repository=self.states,
            org_repository=self.orgs,
            site_repository=self.sites,
            state_machine=self.state_machine,
            applicability=self.applicability,
            escalations=self.escalation_service,
            profile_states=self.profile_state_service,
            settings=self.settings,
            clock=self.clock,
            contradictions=self.contradictions,
            explainers=self.explainer_service,
        )
        self.coverage_service = CoverageService(self.interview_engine)

        self.context = IntakeContext(
            auth_service=self.auth_service,
            org_service=self.org_service,
            seed_form_service=self.seed_form_service,
            email_service=self.email_service,
            profile_state_service=self.profile_state_service,
            interview_engine=self.interview_engine,
            coverage_service=self.coverage_service,
            escalation_service=self.escalation_service,
            state_repository=self.states,
            settings=self.settings,
            answer_parser=self.answer_parser,
            explainer_service=self.explainer_service,
            notification_service=self.notification_service,
            review_service=self.review_service,
        )

    # -- convenience --------------------------------------------------------

    def create_org(self, legal_name: str = "Northlight Studios", email: str = "owner@example.com"):
        return self.org_service.create_org(
            legal_name=legal_name,
            owner_name="Sam Owner",
            owner_email=email,
            created_by="internal@sustentra.com",
        )

    def seeded_org(self, sites: int = 1) -> dict:
        """Create an org, submit the seed form, and initialise its states."""
        created = self.create_org()
        org_id = created["org"]["org_id"]
        site_payloads = [
            site_payload(site_name=f"Stage {index + 1}") for index in range(sites)
        ]
        self.seed_form_service.submit(
            org_id=org_id,
            submitted_by=created["owner"]["user_id"],
            payload={"company": company_payload(), "sites": site_payloads},
        )
        summary = self.profile_state_service.initialise(org_id)
        return {"org_id": org_id, "summary": summary, "owner": created["owner"]}

    def state(self, org_id: str, datapoint_id: str, scope_ref: str | None = None) -> dict:
        found = self.states.find(org_id, datapoint_id, scope_ref)
        assert found is not None, f"no state for {datapoint_id} scope={scope_ref}"
        return found

    def profile_of(self, org_id: str) -> dict:
        return self.orgs.get(org_id) or {}

    def reviewer_token(
        self, org_id: str, email: str = "reviewer@sustentra.com"
    ) -> str:
        """A signed-in Sustentra reviewer.

        The reviewer is attached to an org because a user belongs to exactly one
        org in v1, but the role - not the org - is what the queue checks.
        """
        self.org_service.add_user(
            org_id=org_id, name="Rae Reviewer", email=email, role="sustentra_reviewer"
        )
        return self.sign_in(email)

    def sign_in(self, email: str = "owner@example.com") -> str:
        """Run the full magic-link flow and return a session token."""
        self.auth_service.request_magic_link(email)
        message = self.mailbox.last_to(email)
        assert message is not None, "no magic-link email was sent"
        raw_token = message.body.split("token=")[1].split()[0].strip()
        return self.auth_service.verify_magic_link(raw_token)["session_token"]


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def client(harness: Harness):
    """TestClient over the standalone intake app, wired to the harness."""
    from fastapi.testclient import TestClient

    from intake.backend.app import create_intake_app

    configure_context(harness.context)
    with TestClient(create_intake_app()) as test_client:
        test_client.harness = harness  # type: ignore[attr-defined]
        yield test_client
    configure_context(None)


def company_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Northlight Studios Ltd",
        "reporting_year": 2025,
        "responsible_party_name": "Ada Reyes",
        "responsible_party_role": "Facilities Director",
        "responsible_party_email": "ada@northlight.example",
        "industry": "film_production_facility",
        "reporting_period_start": "2025-01-01",
        "reporting_period_end": "2025-12-31",
        "fiscal_year_basis": "calendar year",
    }
    payload.update(overrides)
    return payload


def site_payload(**overrides) -> dict:
    payload = {
        "site_name": "Stage 4 Complex",
        "address_line": "12 Harbour Road",
        "city": "Wellington",
        "state_region": "Wellington",
        "postal_code": "6011",
        "country_region": "New Zealand",
        "operational_status": "operating all year",
        "site_type": "soundstage_complex",
        "ownership": "leased",
        "lease_type": "operating",
        "ownership_note": "Stage 4 sublet to productions.",
    }
    payload.update(overrides)
    return payload
