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
from intake.backend.services.auth_service import AuthService  # noqa: E402
from intake.backend.services.email_service import EmailService, InMemoryEmailSender  # noqa: E402
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.seed_form_service import SeedFormService  # noqa: E402


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
        self.settings = load_settings()
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
        self.context = IntakeContext(
            auth_service=self.auth_service,
            org_service=self.org_service,
            seed_form_service=self.seed_form_service,
            email_service=self.email_service,
        )

    # -- convenience --------------------------------------------------------

    def create_org(self, legal_name: str = "Northlight Studios", email: str = "owner@example.com"):
        return self.org_service.create_org(
            legal_name=legal_name,
            owner_name="Sam Owner",
            owner_email=email,
            created_by="internal@sustentra.com",
        )

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
