from __future__ import annotations

import pytest

from backend.tests.db._db_contract import (
    DatabaseContractError,
    required_database_mode_from_env,
    validate_required_database_setup,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("database")
    group.addoption(
        "--require-test-db",
        action="store_true",
        default=False,
        help=(
            "Fail early unless TEST_DATABASE_URL/TEST_APP_DATABASE_URL point to a reachable, "
            "migrated, disposable PostgreSQL test database."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_test_db: marks tests that rely on TEST_DATABASE_URL and TEST_APP_DATABASE_URL",
    )


def _is_required_database_mode(config: pytest.Config) -> bool:
    return bool(config.getoption("--require-test-db")) or required_database_mode_from_env()


def pytest_collection_finish(session: pytest.Session) -> None:
    if not _is_required_database_mode(session.config):
        return

    has_db_tests = any(
        item.nodeid.replace("\\", "/").startswith("backend/tests/db/")
        for item in session.items
    )
    if not has_db_tests:
        return

    try:
        validate_required_database_setup(required=True)
    except DatabaseContractError as exc:
        raise pytest.UsageError(f"Required test-database validation failed: {exc}") from exc
