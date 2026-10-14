"""The sync engine for the S1 document stores holds each transaction to one organization,
exactly like the request session (RLS via set_config(..., true)).

Needs TEST_DATABASE_URL (owner, for seeding) and TEST_APP_DATABASE_URL (app_user).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.db import tenant_transaction, to_sync_url
from backend.app.core.s1_scope import S1Scope
from backend.tests.db.test_rls_users import ORG_A, ORG_B, seeded  # noqa: F401 - `seeded` is autouse

APP_URL = os.environ.get("TEST_APP_DATABASE_URL")
pytestmark = pytest.mark.skipif(not (APP_URL and os.environ.get("TEST_DATABASE_URL")),
                                reason="TEST_DATABASE_URL / TEST_APP_DATABASE_URL not set")


@pytest.fixture
def engine():  # noqa: ANN201
    built = create_engine(to_sync_url(APP_URL or ""), pool_size=1, max_overflow=0)
    try:
        yield built
    finally:
        built.dispose()


def _emails(engine, scope: S1Scope) -> set[str]:  # noqa: ANN001
    with tenant_transaction(scope, engine) as connection:
        return {row.email for row in connection.execute(text("SELECT email FROM users"))}


def test_a_tenant_transaction_sees_only_its_organization(engine) -> None:  # noqa: ANN001
    assert _emails(engine, S1Scope.tenant(ORG_A)) == {"alice@a.test"}
    assert _emails(engine, S1Scope.tenant(ORG_B)) == {"bob@b.test"}
    assert {"alice@a.test", "bob@b.test", "ops@sustentra.test"} <= _emails(engine, S1Scope.platform())


def test_the_tenant_does_not_reach_the_next_user_of_the_connection(engine) -> None:  # noqa: ANN001
    _emails(engine, S1Scope.tenant(ORG_A))  # the pool has one connection: the next call reuses it
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
        assert connection.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in ("", None)


def test_a_failed_transaction_is_rolled_back(engine) -> None:  # noqa: ANN001
    with pytest.raises(RuntimeError):
        with tenant_transaction(S1Scope.tenant(ORG_A), engine) as connection:
            connection.execute(text("UPDATE users SET first_name = 'changed' WHERE email = 'alice@a.test'"))
            raise RuntimeError("boom")
    with tenant_transaction(S1Scope.tenant(ORG_A), engine) as connection:
        assert connection.execute(text("SELECT first_name FROM users")).scalar() != "changed"
