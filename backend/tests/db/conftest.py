from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core import db as core_db
from backend.app.core.config import Settings, get_settings
from backend.app.core.rate_limit import limiter
from backend.app.core.security_primitives import hash_password
from backend.app.main import create_app
from backend.app.services import login as login_service
from backend.app.services import otp_delivery
from backend.app.services import password_reset as reset_service
from backend.app.services import invite_service
from backend.app.services import sessions as session_service
from backend.app.services.otp_delivery import get_invite_sender, get_otp_sender, get_reset_sender
from backend.app.services.sessions import SESSION_COOKIE
from backend.tests.db._db_contract import (
    DatabaseContractError,
    TestDatabaseUrls,
    ValidatedTestDatabase,
    required_database_mode_from_env,
    validate_required_database_setup,
)

asyncpg = pytest.importorskip("asyncpg")
httpx = pytest.importorskip("httpx")

TEST_ORIGIN = "https://app.sustentra.test"
TEST_PASSWORD = "violet tractor sings at dawn"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@dataclass(frozen=True)
class SeedIdentities:
    org_a_id: uuid.UUID
    org_b_id: uuid.UUID
    org_a_admin_id: uuid.UUID
    org_a_member_id: uuid.UUID
    org_b_admin_id: uuid.UUID
    org_b_member_id: uuid.UUID
    provider_admin_id: uuid.UUID
    password: str = TEST_PASSWORD


@dataclass
class EmailCapture:
    otp_codes: list[tuple[str, str]]
    reset_links: list[tuple[str, str]]
    invite_links: list[tuple[str, str]] = field(default_factory=list)

    def capture_otp(self, to: str, code: str) -> None:
        self.otp_codes.append((to, code))

    def capture_reset(self, to: str, link: str) -> None:
        self.reset_links.append((to, link))

    def capture_invite(self, to: str, link: str) -> None:
        self.invite_links.append((to, link))

    def latest_invite_link(self, email: str) -> str:
        match = email.strip().lower()
        for recipient, link in reversed(self.invite_links):
            if recipient.strip().lower() == match:
                return link
        raise AssertionError(f"No invite email captured for {email!r}.")

    def latest_otp_code(self, email: str) -> str:
        match = email.strip().lower()
        for recipient, code in reversed(self.otp_codes):
            if recipient.strip().lower() == match:
                return code
        raise AssertionError(f"No OTP email captured for {email!r}.")

    def clear(self) -> None:
        self.otp_codes.clear()
        self.reset_links.clear()
        self.invite_links.clear()


@dataclass
class TransportGuard:
    smtp_calls: int = 0
    ses_calls: int = 0


@dataclass
class ControlledClock:
    now_value: datetime

    def utcnow(self) -> datetime:
        return self.now_value

    def advance(self, delta: timedelta) -> None:
        self.now_value += delta


@dataclass
class DbTestClient:
    client: Any
    email_capture: EmailCapture

    @property
    def headers(self) -> dict[str, str]:
        return {"Origin": TEST_ORIGIN}

    async def login_with_otp(
        self,
        *,
        email: str,
        password: str,
        org_slug: str | None,
    ) -> str:
        body: dict[str, Any] = {"email": email, "password": password}
        if org_slug is not None:
            body["org_slug"] = org_slug

        login_response = await self.client.post("/api/v1/auth/login", json=body, headers=self.headers)
        assert login_response.status_code == 200
        challenge_id = login_response.json()["challenge_id"]
        code = self.email_capture.latest_otp_code(email)

        verify_response = await self.client.post(
            "/api/v1/auth/login/verify",
            json={"challenge_id": challenge_id, "code": code},
            headers=self.headers,
        )
        assert verify_response.status_code == 200

        cookie = self.client.cookies.get(SESSION_COOKIE)
        if not cookie:
            raise AssertionError("Expected login helper to return a valid session cookie.")
        return str(cookie)


def _is_required_database_mode(pytestconfig: pytest.Config) -> bool:
    return bool(pytestconfig.getoption("--require-test-db")) or required_database_mode_from_env()


@pytest.fixture(scope="session", autouse=True)
def _validated_db_contract(pytestconfig: pytest.Config) -> ValidatedTestDatabase:
    required = _is_required_database_mode(pytestconfig)
    try:
        return validate_required_database_setup(required=required)
    except DatabaseContractError as exc:
        if required:
            pytest.fail(f"Required test-database setup is invalid: {exc}", pytrace=False)
        pytest.skip(f"Database integration tests skipped: {exc}")


@pytest.fixture(scope="session")
def db_contract(_validated_db_contract: ValidatedTestDatabase) -> ValidatedTestDatabase:
    return _validated_db_contract


@pytest.fixture(scope="session")
def db_urls(db_contract: ValidatedTestDatabase) -> TestDatabaseUrls:
    return db_contract.urls


@pytest.fixture(scope="session")
def seeded_identity_template() -> SeedIdentities:
    return SeedIdentities(
        org_a_id=uuid.UUID("aaaaaaaa-0000-0000-0000-00000000f1a1"),
        org_b_id=uuid.UUID("bbbbbbbb-0000-0000-0000-00000000f1b2"),
        org_a_admin_id=uuid.UUID("aaaaaaaa-1111-0000-0000-00000000f1a1"),
        org_a_member_id=uuid.UUID("aaaaaaaa-2222-0000-0000-00000000f1a1"),
        org_b_admin_id=uuid.UUID("bbbbbbbb-1111-0000-0000-00000000f1b2"),
        org_b_member_id=uuid.UUID("bbbbbbbb-2222-0000-0000-00000000f1b2"),
        provider_admin_id=uuid.UUID("cccccccc-3333-0000-0000-00000000f1ff"),
    )


@pytest.fixture(autouse=True)
def reset_test_state(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter.reset()
    monkeypatch.setenv("OTP_HMAC_SECRET", "test-only-otp-hmac-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", TEST_ORIGIN)
    get_settings.cache_clear()
    yield
    limiter.reset()
    get_settings.cache_clear()


@pytest.fixture
def email_capture() -> EmailCapture:
    return EmailCapture(otp_codes=[], reset_links=[])


@pytest.fixture
def controlled_clock(monkeypatch: pytest.MonkeyPatch) -> ControlledClock:
    clock = ControlledClock(now_value=datetime(2026, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(login_service, "utcnow", clock.utcnow)
    monkeypatch.setattr(reset_service, "utcnow", clock.utcnow)
    monkeypatch.setattr(session_service, "utcnow", clock.utcnow)
    monkeypatch.setattr(invite_service, "utcnow", clock.utcnow)
    return clock


@pytest.fixture
def transport_guard(monkeypatch: pytest.MonkeyPatch) -> TransportGuard:
    guard = TransportGuard()

    def _blocked_smtp(*_args: Any, **_kwargs: Any) -> None:
        guard.smtp_calls += 1
        raise AssertionError("Unexpected SMTP transport call in DB integration test.")

    def _blocked_ses(*_args: Any, **_kwargs: Any) -> None:
        guard.ses_calls += 1
        raise AssertionError("Unexpected SES transport call in DB integration test.")

    monkeypatch.setattr(otp_delivery, "_send_smtp", _blocked_smtp)
    monkeypatch.setattr(otp_delivery, "_send_ses", _blocked_ses)
    return guard


@pytest_asyncio.fixture
async def admin_connection(db_urls: TestDatabaseUrls) -> Any:
    conn = await asyncpg.connect(db_urls.admin_url)
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def seeded_identities(
    admin_connection: Any,
    seeded_identity_template: SeedIdentities,
) -> SeedIdentities:
    identities = seeded_identity_template

    await admin_connection.execute("TRUNCATE sessions, auth_tokens, users, organizations CASCADE")
    await admin_connection.execute("TRUNCATE audit_logs")
    await admin_connection.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Org A', 'org-a'), ($2, 'Org B', 'org-b')",
        identities.org_a_id,
        identities.org_b_id,
    )
    await admin_connection.execute(
        """
        INSERT INTO users (
            id, org_id, email, role, status, password_hash, first_name, last_name, full_name
        ) VALUES
          ($1, $2, 'admin.a@org-a.test', 'org_admin', 'active', $8, 'Ada', 'Admin', 'Ada Admin'),
          ($3, $2, 'member.a@org-a.test', 'org_member', 'active', $8, 'Mia', 'Member', 'Mia Member'),
          ($4, $5, 'admin.b@org-b.test', 'org_admin', 'active', $8, 'Ben', 'Boss', 'Ben Boss'),
          ($6, $5, 'member.b@org-b.test', 'org_member', 'active', $8, 'Bo', 'Builder', 'Bo Builder'),
          ($7, NULL, 'provider@sustentra.test', 'provider_admin', 'active', $8, 'Pri', 'Provider', 'Pri Provider')
        """,
        identities.org_a_admin_id,
        identities.org_a_id,
        identities.org_a_member_id,
        identities.org_b_admin_id,
        identities.org_b_id,
        identities.org_b_member_id,
        identities.provider_admin_id,
        _TEST_PASSWORD_HASH,
    )

    return identities


@pytest_asyncio.fixture
async def db_test_client(db_urls: TestDatabaseUrls, email_capture: EmailCapture) -> DbTestClient:
    engine = core_db.create_engine(db_urls.app_url, pool_size=2, max_overflow=0)
    app = create_app(Settings(environment="test", git_sha="test", ALLOWED_ORIGINS=TEST_ORIGIN))  # type: ignore[call-arg]
    sessionmaker = core_db.build_sessionmaker(engine)

    async def session_dep() -> Any:
        async with sessionmaker() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[core_db.get_db_session] = session_dep
    app.dependency_overrides[core_db.get_sessionmaker_dependency] = lambda: sessionmaker
    app.dependency_overrides[get_otp_sender] = lambda: email_capture.capture_otp
    app.dependency_overrides[get_reset_sender] = lambda: email_capture.capture_reset
    app.dependency_overrides[get_invite_sender] = lambda: email_capture.capture_invite

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            yield DbTestClient(client=client, email_capture=email_capture)
    finally:
        app.dependency_overrides.clear()
        email_capture.clear()
        await engine.dispose()


@pytest_asyncio.fixture
async def single_pool_sessionmaker(db_urls: TestDatabaseUrls) -> async_sessionmaker[AsyncSession]:
    engine = core_db.create_engine(db_urls.app_url, pool_size=1, max_overflow=0)
    try:
        yield core_db.build_sessionmaker(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def as_app_user(db_urls: TestDatabaseUrls) -> Callable[..., Awaitable[Any]]:
    async def _run(
        work: Callable[[Any], Awaitable[Any]],
        *,
        tenant_id: uuid.UUID | None = None,
        provider: bool = False,
    ) -> Any:
        conn = await asyncpg.connect(db_urls.app_url)
        try:
            async with conn.transaction():
                if tenant_id is not None:
                    await conn.execute(
                        "SELECT set_config('app.tenant_id', $1, true), set_config('app.is_provider', 'false', true)",
                        str(tenant_id),
                    )
                elif provider:
                    await conn.execute(
                        "SELECT set_config('app.is_provider', 'true', true), set_config('app.tenant_id', '', true)"
                    )
                return await work(conn)
        finally:
            await conn.close()

    return _run
