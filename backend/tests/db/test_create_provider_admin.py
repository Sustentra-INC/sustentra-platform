"""ORG-000 integration tests: `cli create-provider-admin` against real Postgres.

The CLI runs exactly as in the container: DATABASE_URL = app_user (RLS forced).
TEST_DATABASE_URL (owner) is only used to inspect/seed. Skipped unless both are set.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app import cli
from backend.app.core import db as core_db
from backend.app.core.config import get_settings
from backend.app.core.security_primitives import verify_password
from backend.app.services.login import RequestMeta
from backend.app.services.password_reset import confirm_reset

asyncpg = pytest.importorskip("asyncpg")

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
APP_URL = os.environ.get("TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and APP_URL), reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set"
)

EMAIL = "ops@sustentra.test"
PASSWORD = "violet tractor sings at dawn"
ARGS = ["create-provider-admin", "--email", "OPS@sustentra.test", "--first-name", "Ada", "--last-name", "Ops"]


async def _admin(sql: str, *args: Any) -> list[Any]:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def clean_db(monkeypatch: pytest.MonkeyPatch) -> Any:
    asyncio.run(_admin("TRUNCATE sessions, auth_tokens, users, organizations CASCADE"))
    asyncio.run(_admin("TRUNCATE audit_logs"))
    monkeypatch.setenv("DATABASE_URL", APP_URL or "")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.sustentra.test")
    get_settings.cache_clear()
    yield
    asyncio.run(core_db.dispose_engine())
    get_settings.cache_clear()


def _prompts(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    queue = list(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": queue.pop(0))


def test_creates_provider_admin_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _prompts(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == 0
    _prompts(monkeypatch)  # second run must not prompt
    assert cli.main(ARGS) == 0

    users = asyncio.run(_admin("SELECT * FROM users"))
    assert len(users) == 1
    user = users[0]
    assert (user["email"], user["org_id"], user["role"], user["status"]) == (EMAIL, None, "provider_admin", "active")
    assert (user["first_name"], user["last_name"], user["full_name"]) == ("Ada", "Ops", "Ada Ops")
    assert verify_password(PASSWORD, user["password_hash"])

    events = asyncio.run(_admin("SELECT * FROM audit_logs"))
    assert [e["event_type"] for e in events] == ["provider_admin_created"]
    assert events[0]["org_id"] is None and events[0]["target_id"] == str(user["id"])
    metadata = json.loads(events[0]["metadata"]) if isinstance(events[0]["metadata"], str) else events[0]["metadata"]
    assert metadata == {"source": "cli", "password_set": True, "reset_link_issued": False}


def test_org_user_with_same_email_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    org = asyncio.run(_admin("INSERT INTO organizations (name, slug) VALUES ('Acme', 'acme') RETURNING id"))[0]["id"]
    asyncio.run(_admin("INSERT INTO users (org_id, email, role) VALUES ($1, $2, 'org_admin')", org, EMAIL))
    _prompts(monkeypatch, PASSWORD, PASSWORD)

    assert cli.main(ARGS) == 0

    rows = asyncio.run(_admin("SELECT role FROM users WHERE email = $1 ORDER BY role", EMAIL))
    assert [r["role"] for r in rows] == ["org_admin", "provider_admin"]


def test_reset_link_sets_the_password(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([*ARGS, "--reset-link"]) == 0
    link = next(line.strip() for line in capsys.readouterr().out.splitlines() if "token=" in line)
    assert link.startswith("https://app.sustentra.test/provider-admin/reset-password?token=")
    token = parse_qs(urlsplit(link).query)["token"][0]

    async def use_link() -> int:
        engine = core_db.create_engine(APP_URL or "", pool_size=1, max_overflow=0)
        try:
            async with core_db.build_sessionmaker(engine)() as session, session.begin():
                outcome = await confirm_reset(session, token, PASSWORD, RequestMeta(None, None, None))
            return outcome.status
        finally:
            await engine.dispose()

    assert asyncio.run(use_link()) == 200
    user = asyncio.run(_admin("SELECT password_hash FROM users WHERE email = $1", EMAIL))[0]
    assert verify_password(PASSWORD, user["password_hash"])
