"""ORG-000 unit tests: provider_admin bootstrap service + `cli create-provider-admin`.

No database: a fake AsyncSession records every statement and emulates the
users-table unique constraint. The real-Postgres path is in tests/db/test_create_provider_admin.py.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import pytest

from backend.app import cli
from backend.app.core import db as core_db
from backend.app.core.security_primitives import verify_password
from backend.app.services import provider_admin_bootstrap as bootstrap

PASSWORD = "copper lantern over quiet harbour"


class FakeResult:
    def __init__(self, row: dict[str, Any] | None = None, scalar: Any = None) -> None:
        self._row = row
        self._scalar = scalar

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    """Acts as sessionmaker, session and transaction at once."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self) -> FakeSession:
        return self

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _Tx:
        return _Tx()

    def sql(self, fragment: str) -> list[dict[str, Any]]:
        return [params for sql, params in self.calls if fragment in sql]

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql, params = str(stmt), dict(params or {})
        self.calls.append((sql, params))
        if "INSERT INTO users" in sql:
            if params["email"] in self.users:  # ON CONFLICT DO NOTHING
                return FakeResult(scalar=None)
            user_id = uuid.uuid4()
            self.users[params["email"]] = {**params, "id": user_id, "org_id": None,
                                           "role": "provider_admin", "status": "active"}
            return FakeResult(scalar=user_id)
        if "SELECT id, status FROM users" in sql:
            user = self.users.get(params["email"])
            return FakeResult(row={"id": user["id"], "status": user["status"]} if user else None)
        return FakeResult()


def _create(session: FakeSession, **overrides: Any) -> bootstrap.BootstrapResult:
    kwargs: dict[str, Any] = {"email": "ops@sustentra.test", "first_name": "Ada", "last_name": "Ops",
                              "password_hash": "$2b$12$fakehash", "issue_reset_link": False}
    kwargs.update(overrides)
    return asyncio.run(bootstrap.create_provider_admin(session, **kwargs))


# --- service ---------------------------------------------------------------------

def test_creates_provider_admin_with_null_org_in_provider_scope() -> None:
    session = FakeSession()
    result = _create(session)

    assert result.created and result.status == "active" and result.reset_link is None
    insert_sql = next(sql for sql, _ in session.calls if "INSERT INTO users" in sql)
    assert "VALUES (NULL, :email" in insert_sql  # org_id NULL
    assert "'provider_admin', 'active'" in insert_sql
    assert "ON CONFLICT ON CONSTRAINT uq_users_email_org_id DO NOTHING" in insert_sql
    # RLS provider scope is set before the insert.
    first_sql = session.calls[0][0]
    assert "app.is_provider" in first_sql
    params = session.sql("INSERT INTO users")[0]
    assert params["full_name"] == "Ada Ops" and params["password_hash"] == "$2b$12$fakehash"

    audit = session.sql("INSERT INTO audit_logs")
    assert len(audit) == 1
    assert audit[0]["event_type"] == "provider_admin_created"
    assert audit[0]["org_id"] is None and audit[0]["actor_role"] == "system"
    assert audit[0]["target_id"] == str(result.user_id)
    assert '"password_set": true' in audit[0]["metadata"]


def test_duplicate_email_is_a_noop_without_audit() -> None:
    session = FakeSession()
    first = _create(session)
    session.calls.clear()

    second = _create(session, password_hash="$2b$12$other")

    assert not second.created and second.user_id == first.user_id
    assert len(session.users) == 1
    assert session.users["ops@sustentra.test"]["password_hash"] == "$2b$12$fakehash"  # untouched
    assert session.sql("INSERT INTO audit_logs") == []
    assert session.sql("INSERT INTO auth_tokens") == []


def test_reset_link_mode_stores_only_the_token_hash() -> None:
    session = FakeSession()
    result = _create(session, password_hash=None, issue_reset_link=True)

    assert result.created and result.reset_link and result.reset_expires_at
    assert "/provider-admin/reset-password?token=" in result.reset_link
    token = result.reset_link.split("token=", 1)[1]
    stored = session.sql("INSERT INTO auth_tokens")
    assert len(stored) == 1 and stored[0]["hash"] != token and len(stored[0]["hash"]) == 64
    assert stored[0]["expires"] - stored[0]["now"] == bootstrap.BOOTSTRAP_RESET_TTL
    assert session.users["ops@sustentra.test"]["password_hash"] is None
    audit = session.sql("INSERT INTO audit_logs")[0]
    assert token not in audit["metadata"] and '"reset_link_issued": true' in audit["metadata"]


def test_requires_a_password_or_a_reset_link() -> None:
    with pytest.raises(ValueError):
        _create(FakeSession(), password_hash=None, issue_reset_link=False)


@pytest.mark.parametrize("raw, expected", [(" Ops@Sustentra.TEST ", "ops@sustentra.test")])
def test_normalize_email(raw: str, expected: str) -> None:
    assert bootstrap.normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["", "no-at-sign", "a@b", "two words@x.com"])
def test_normalize_email_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        bootstrap.normalize_email(raw)


def test_normalize_name() -> None:
    assert bootstrap.normalize_name("  Ada   Lovelace ", "first name") == "Ada Lovelace"
    with pytest.raises(ValueError):
        bootstrap.normalize_name("   ", "first name")
    with pytest.raises(ValueError):
        bootstrap.normalize_name("x" * 101, "last name")


# --- cli -------------------------------------------------------------------------

ARGS = ["create-provider-admin", "--email", "Ops@Sustentra.test", "--first-name", "Ada", "--last-name", "Ops"]


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    fake = FakeSession()

    async def no_dispose() -> None:
        return None

    monkeypatch.setattr(core_db, "get_sessionmaker", lambda: fake)
    monkeypatch.setattr(core_db, "dispose_engine", no_dispose)
    return fake


def _answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> list[str]:
    prompts: list[str] = []
    queue = list(answers)

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return queue.pop(0)

    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
    return prompts


def test_cli_creates_admin_and_never_logs_the_password(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _answers(monkeypatch, PASSWORD, PASSWORD)

    assert cli.main(ARGS) == 0

    user = session.users["ops@sustentra.test"]
    assert user["org_id"] is None and user["role"] == "provider_admin" and user["status"] == "active"
    assert verify_password(PASSWORD, user["password_hash"])  # same hasher as login (bcrypt)
    out, err = capsys.readouterr()
    assert "Created provider_admin ops@sustentra.test" in out
    for haystack in (out, err, caplog.text, repr(session.calls)):
        assert PASSWORD not in haystack


def test_cli_password_is_not_an_argument() -> None:
    with pytest.raises(SystemExit):
        cli.main([*ARGS, "--password", PASSWORD])


def test_cli_twice_does_not_duplicate_or_prompt_again(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == 0
    prompts = _answers(monkeypatch)  # any prompt would pop from an empty queue and fail

    assert cli.main(ARGS) == 0

    assert prompts == [] and len(session.users) == 1
    assert len(session.sql("INSERT INTO users")) == 1
    assert len(session.sql("INSERT INTO audit_logs")) == 1
    assert "already exists" in capsys.readouterr().out


def test_cli_reprompts_on_mismatch_and_weak_password(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts = _answers(monkeypatch, PASSWORD, "different password here", "short", "short", PASSWORD, PASSWORD)

    assert cli.main(ARGS) == 0

    assert len(prompts) == 6
    err = capsys.readouterr().err
    assert "do not match" in err and "at least 12 characters" in err
    assert "different password here" not in err  # violations are echoed, never the input


def test_cli_gives_up_after_three_bad_attempts(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _answers(monkeypatch, *["password123"] * 6)

    assert cli.main(ARGS) == 1

    assert session.users == {}
    assert "nothing was created" in capsys.readouterr().err


def test_cli_cancelled_prompt_creates_nothing(session: FakeSession, monkeypatch: pytest.MonkeyPatch) -> None:
    def cancel(prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.getpass, "getpass", cancel)
    assert cli.main(ARGS) == 1
    assert session.users == {}


def test_cli_reset_link_mode_prints_link_without_prompting(
    session: FakeSession, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prompts = _answers(monkeypatch)

    assert cli.main([*ARGS, "--reset-link"]) == 0

    assert prompts == []
    assert session.users["ops@sustentra.test"]["password_hash"] is None
    assert "/provider-admin/reset-password?token=" in capsys.readouterr().out


def test_cli_rejects_invalid_email(session: FakeSession, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["create-provider-admin", "--email", "nope", "--first-name", "A", "--last-name", "B"]) == 2
    assert session.calls == []
    assert "not a valid email" in capsys.readouterr().err


def test_cli_reports_missing_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def not_configured() -> None:
        raise core_db.DatabaseNotConfiguredError("DATABASE_URL is not set")

    monkeypatch.setattr(core_db, "get_sessionmaker", not_configured)
    assert cli.main(ARGS) == 1
    assert "DATABASE_URL is not set" in capsys.readouterr().err
