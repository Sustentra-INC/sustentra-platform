"""AUTH-004 unit tests: role matrix, session validity rules, cookie attributes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Response

from backend.app.core.auth import ROLES, require_role, role_allowed
from backend.app.services.sessions import (
    SESSION_COOKIE,
    ResolvedSession,
    clear_session_cookie,
    set_session_cookie,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

# Which roles may pass each guard (the RBAC matrix used by later tickets).
MATRIX = {
    ("provider_admin",): {"provider_admin"},
    ("org_admin",): {"org_admin"},
    ("org_member",): {"org_member"},
    ("org_admin", "org_member"): {"org_admin", "org_member"},
    ("provider_admin", "org_admin"): {"provider_admin", "org_admin"},
}


@pytest.mark.parametrize("allowed", list(MATRIX))
@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(role: str, allowed: tuple[str, ...]) -> None:
    assert role_allowed(role, allowed) == (role in MATRIX[allowed])


def test_require_role_rejects_unknown_or_empty_roles() -> None:
    with pytest.raises(ValueError):
        require_role("superuser")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        require_role()


def _session(**overrides: object) -> ResolvedSession:
    values: dict[str, object] = {
        "session_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "created_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=6),
        "last_seen_at": NOW - timedelta(minutes=5),
        "revoked_at": None,
        "user_role": "org_member",
        "user_status": "active",
        "org_status": "active",
    }
    values.update(overrides)
    return ResolvedSession(**values)  # type: ignore[arg-type]


def test_valid_session() -> None:
    assert _session().is_valid(NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expires_at": NOW - timedelta(seconds=1)},  # absolute expiry (7 days)
        {"last_seen_at": NOW - timedelta(hours=8, seconds=1)},  # idle timeout (8 h)
        {"last_seen_at": None, "created_at": NOW - timedelta(hours=9)},
        {"revoked_at": NOW - timedelta(minutes=1)},
        {"user_status": "suspended"},
        {"user_status": "disabled"},
        {"org_status": "suspended"},
    ],
)
def test_invalid_sessions(overrides: dict[str, object]) -> None:
    assert not _session(**overrides).is_valid(NOW)


def test_provider_admin_session_has_no_org_and_is_valid() -> None:
    assert _session(org_id=None, org_status=None, user_role="provider_admin").is_valid(NOW)


def test_session_cookie_attributes() -> None:
    response = Response()
    set_session_cookie(response, "tok")
    header = response.headers["set-cookie"]
    assert header.startswith(f"{SESSION_COOKIE}=tok")
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=604800"):
        assert attribute.lower() in header.lower()
    assert "domain=" not in header.lower()  # __Host- cookies must not set Domain


def test_clear_cookie_sets_max_age_zero() -> None:
    response = Response()
    clear_session_cookie(response)
    assert "max-age=0" in response.headers["set-cookie"].lower()
