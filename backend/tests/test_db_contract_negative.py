from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from psycopg2 import OperationalError

from backend.tests import conftest as root_pytest_conftest
from backend.tests.db import _db_contract as contract


@dataclass
class _State:
    runtime_identity: tuple[str, str] = ("sustentra", "app_user")
    role_row: tuple[bool, bool, bool, bool] = (False, False, False, False)
    version_table: tuple[str | None] = ("alembic_version",)
    db_revisions: tuple[str, ...] = ("head-rev",)
    present_tables: tuple[str, ...] = (
        "public.organizations",
        "public.users",
        "public.sessions",
        "public.auth_tokens",
        "public.audit_logs",
    )


class _FakeCursor:
    def __init__(self, state: _State) -> None:
        self._state = state
        self._query = ""
        self._params: Any = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        self._query = " ".join(query.split())
        self._params = params

    def fetchone(self) -> Any:
        if "SELECT current_database(), current_user" in self._query:
            return self._state.runtime_identity
        if "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole" in self._query:
            return self._state.role_row
        if "SELECT to_regclass('public.alembic_version')" in self._query:
            return self._state.version_table
        if "SELECT to_regclass(%s)" in self._query:
            table_name = self._params[0]
            if table_name in self._state.present_tables:
                return (table_name,)
            return (None,)
        raise AssertionError(f"Unhandled fetchone query: {self._query}")

    def fetchall(self) -> Any:
        if "SELECT version_num FROM alembic_version ORDER BY version_num" in self._query:
            return [(rev,) for rev in self._state.db_revisions]
        raise AssertionError(f"Unhandled fetchall query: {self._query}")


class _FakeConnection:
    def __init__(self, state: _State) -> None:
        self._state = state

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._state)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(contract.TEST_DATABASE_URL_ENV, "postgresql://owner:pw@localhost:5432/sustentra")
    monkeypatch.setenv(contract.TEST_APP_DATABASE_URL_ENV, "postgresql://app_user:pw@localhost:5432/sustentra")
    monkeypatch.setenv(contract.TEST_DATABASE_DISPOSABLE_ENV, "1")


@pytest.mark.parametrize(
    ("admin_url", "app_url", "expected_message"),
    [
        (None, "postgresql://app_user:pw@localhost:5432/sustentra", "must be set together"),
        ("postgresql://owner:pw@localhost:5432/sustentra", None, "must be set together"),
        (None, None, "are unset"),
    ],
)
def test_missing_test_database_url_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    admin_url: str | None,
    app_url: str | None,
    expected_message: str,
) -> None:
    if admin_url is None:
        monkeypatch.delenv(contract.TEST_DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(contract.TEST_DATABASE_URL_ENV, admin_url)

    if app_url is None:
        monkeypatch.delenv(contract.TEST_APP_DATABASE_URL_ENV, raising=False)
    else:
        monkeypatch.setenv(contract.TEST_APP_DATABASE_URL_ENV, app_url)

    monkeypatch.setenv(contract.TEST_DATABASE_DISPOSABLE_ENV, "1")

    with pytest.raises(contract.DatabaseContractError, match=expected_message):
        contract.validate_required_database_setup(required=True)


def test_missing_disposable_ack_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(contract.TEST_DATABASE_URL_ENV, "postgresql://owner:pw@localhost:5432/sustentra")
    monkeypatch.setenv(contract.TEST_APP_DATABASE_URL_ENV, "postgresql://app_user:pw@localhost:5432/sustentra")
    monkeypatch.delenv(contract.TEST_DATABASE_DISPOSABLE_ENV, raising=False)

    with pytest.raises(contract.DatabaseContractError, match="TEST_DB_DISPOSABLE"):
        contract.validate_required_database_setup(required=True)


def test_unavailable_database_uses_bounded_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setattr(contract, "expected_alembic_heads", lambda: frozenset({"head-rev"}))

    calls: list[dict[str, Any]] = []

    def _connect(url: str, **kwargs: Any) -> Any:
        calls.append({"url": url, "kwargs": kwargs})
        raise OperationalError("simulated connect failure")

    monkeypatch.setattr(contract.psycopg2, "connect", _connect)

    with pytest.raises(contract.DatabaseContractError, match="Unable to connect with TEST_APP_DATABASE_URL"):
        contract.validate_required_database_setup(required=True)

    assert calls
    assert calls[0]["kwargs"].get("connect_timeout") == contract._CONNECT_TIMEOUT_SECONDS


def test_wrong_runtime_user_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setattr(contract, "expected_alembic_heads", lambda: frozenset({"head-rev"}))

    state = _State(runtime_identity=("sustentra", "postgres"))
    monkeypatch.setattr(contract.psycopg2, "connect", lambda _url, **_kwargs: _FakeConnection(state))

    with pytest.raises(contract.DatabaseContractError, match="Runtime app connection user must be"):
        contract.validate_required_database_setup(required=True)


@pytest.mark.parametrize(
    "role_row",
    [
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, True),
    ],
)
def test_forbidden_runtime_role_flags_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    role_row: tuple[bool, bool, bool, bool],
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setattr(contract, "expected_alembic_heads", lambda: frozenset({"head-rev"}))

    state = _State(role_row=role_row)
    monkeypatch.setattr(contract.psycopg2, "connect", lambda _url, **_kwargs: _FakeConnection(state))

    with pytest.raises(contract.DatabaseContractError, match="role flags are unsafe"):
        contract.validate_required_database_setup(required=True)


def test_missing_alembic_version_table_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setattr(contract, "expected_alembic_heads", lambda: frozenset({"head-rev"}))

    state = _State(version_table=(None,))
    monkeypatch.setattr(contract.psycopg2, "connect", lambda _url, **_kwargs: _FakeConnection(state))

    with pytest.raises(contract.DatabaseContractError, match="alembic_version table is missing"):
        contract.validate_required_database_setup(required=True)


@pytest.mark.parametrize(
    ("db_revisions", "expected_heads"),
    [
        (("old-rev",), frozenset({"head-rev"})),
        (("head-rev", "unexpected-rev"), frozenset({"head-rev"})),
    ],
)
def test_non_head_or_unexpected_alembic_revision_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    db_revisions: tuple[str, ...],
    expected_heads: frozenset[str],
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setattr(contract, "expected_alembic_heads", lambda: expected_heads)

    state = _State(db_revisions=db_revisions)
    monkeypatch.setattr(contract.psycopg2, "connect", lambda _url, **_kwargs: _FakeConnection(state))

    with pytest.raises(contract.DatabaseContractError, match="Alembic revision mismatch"):
        contract.validate_required_database_setup(required=True)


def test_required_db_collection_gate_fails_before_destructive_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    destructive_seed_called = False

    def _never_called(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal destructive_seed_called
        destructive_seed_called = True
        raise AssertionError("Destructive setup should not run")

    monkeypatch.setattr(
        root_pytest_conftest,
        "validate_required_database_setup",
        lambda required: (_ for _ in ()).throw(contract.DatabaseContractError("boom")),
    )

    class _Config:
        @staticmethod
        def getoption(name: str) -> bool:
            return name == "--require-test-db"

    class _Item:
        nodeid = "backend/tests/db/test_anything.py::test_case"

    class _Session:
        config = _Config()
        items = [_Item()]

    # Guard against accidental DB setup calls in this path.
    monkeypatch.setattr("backend.tests.db.conftest.asyncpg.connect", _never_called)

    with pytest.raises(pytest.UsageError):
        root_pytest_conftest.pytest_collection_finish(_Session())

    assert destructive_seed_called is False
