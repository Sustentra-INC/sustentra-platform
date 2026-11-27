"""MVP-245: GET /api/v1/admin/spend is provider_admin only. The role checks need no database."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.core.auth import CurrentUser, get_current_user
from backend.app.core.config import Settings
from backend.app.core.db import get_db_session
from backend.app.main import create_app

URL = "/api/v1/admin/spend"


def _client(role: str | None) -> TestClient:
    app = create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS="https://app.sustentra.test"))  # type: ignore[call-arg]
    async def no_db():  # type: ignore[no-untyped-def]
        yield None

    app.dependency_overrides[get_db_session] = no_db  # the role and month checks never reach a query
    if role is not None:
        user = CurrentUser(id=uuid.uuid4(), email="a@b.test", first_name=None, last_name=None, full_name=None,
                           role=role, org_id=None if role == "provider_admin" else uuid.uuid4(), org_slug=None,
                           session_id=uuid.uuid4())
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.mark.parametrize("role", ["org_admin", "org_member"])
def test_org_roles_get_403(role: str) -> None:
    assert _client(role).get(URL).status_code == 403
    assert _client(role).get(URL, params={"month": "2026-11"}).status_code == 403


def test_no_session_is_401() -> None:
    assert _client(None).get(URL).status_code == 401


@pytest.mark.parametrize("month", ["2026-13", "2026-00", "26-11", "2026-1", "x", "2026-11-01", "' OR 1=1"])
def test_a_bad_month_is_rejected_before_any_query(month: str) -> None:
    assert _client("provider_admin").get(URL, params={"month": month}).status_code == 422


def test_month_bounds_roll_over_the_year() -> None:
    from backend.app.api.v1.admin_spend import _bounds

    start, end = _bounds("2026-12")
    assert (start.year, start.month, end.year, end.month) == (2026, 12, 2027, 1)
