"""COMP-001: user erasure (soft delete + anonymize), through the real app and Postgres (RLS on).

Reuses the ORG-002 fixtures: org Acme with admins A1 (the caller) and A2, member MEM
(two sessions, an unused reset token), invited INV; org Beta with B_ADMIN; a provider.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.app.core.security_primitives import hash_password
from backend.tests.db.test_org_users import (  # noqa: F401 - `seeded` is the autouse fixture
    A1,
    A2,
    B_ADMIN,
    GONE,
    INV,
    MEM,
    ORG_A,
    ORG_B,
    admin,
    call,
    seeded,
    status_of,
    users_url,
)

PASSWORD = "a-perfectly-fine-passphrase-42"


def login(email: str) -> Any:
    return call("POST", "/api/v1/auth/login", None, {"email": email, "password": PASSWORD, "org_slug": "acme"})


def test_delete_anonymizes_revokes_and_keeps_the_row() -> None:
    admin("UPDATE users SET password_hash = $1 WHERE id = $2", hash_password(PASSWORD), MEM)
    assert login("mem@acme.test").status_code == 200  # works before
    assert call("GET", "/api/v1/auth/me", "mem").status_code == 200

    response = call("DELETE", users_url(user=MEM))
    assert response.status_code == 204 and response.content == b""

    [row] = admin("SELECT email, first_name, last_name, full_name, status, password_hash, deleted_at, role "
                  "FROM users WHERE id = $1", MEM)
    assert row["email"] == f"deleted_{MEM}@deleted"
    assert (row["first_name"], row["last_name"], row["full_name"]) == ("Deleted", "User", "Deleted User")
    assert row["status"] == "deleted" and row["password_hash"] is None and row["deleted_at"] is not None
    assert row["role"] == "org_member"

    assert admin("SELECT count(*) AS n FROM sessions WHERE user_id = $1", MEM)[0]["n"] == 0
    assert admin("SELECT count(*) AS n FROM auth_tokens WHERE user_id = $1", MEM)[0]["n"] == 0
    for token in ("mem", "mem_2"):
        assert call("GET", "/api/v1/auth/me", token).status_code == 401


def test_login_with_the_old_email_gets_the_generic_401() -> None:
    admin("UPDATE users SET password_hash = $1 WHERE id = $2", hash_password(PASSWORD), MEM)
    assert call("DELETE", users_url(user=MEM)).status_code == 204
    after = login("mem@acme.test")
    unknown = login("nobody@acme.test")
    assert after.status_code == unknown.status_code == 401
    assert after.json() == unknown.json()


def test_the_deleted_user_is_gone_from_the_api() -> None:
    assert call("DELETE", users_url(user=MEM)).status_code == 204
    assert call("GET", users_url(user=MEM)).status_code == 404
    assert call("DELETE", users_url(user=MEM)).status_code == 404
    assert call("POST", users_url(user=MEM, action="reactivate")).status_code == 404
    emails = [u["email"] for u in call("GET", users_url()).json()["items"]]
    assert "mem@acme.test" not in emails and not [e for e in emails if e.startswith("deleted_")]


def test_audit_records_the_actor_without_personal_data_and_old_rows_survive() -> None:
    admin("INSERT INTO audit_logs (org_id, actor_user_id, actor_role, event_type, target_type, target_id) "
          "VALUES ($1, $2, 'org_member', 'login_succeeded', 'user', $3)", ORG_A, MEM, str(MEM))
    assert call("DELETE", users_url(user=MEM)).status_code == 204
    rows = admin("SELECT event_type, actor_user_id, target_id, org_id, metadata::text AS metadata FROM audit_logs "
                 "ORDER BY created_at")
    deleted = [r for r in rows if r["event_type"] == "user_deleted"]
    assert len(deleted) == 1
    d = deleted[0]
    assert (d["actor_user_id"], d["target_id"], d["org_id"]) == (A1, str(MEM), ORG_A)
    assert "mem@acme.test" not in d["metadata"] and "Meg" not in d["metadata"]
    assert '"sessions_revoked": 2' in d["metadata"]
    # The deleted user's own history is still there and still points at the (kept) row.
    assert [r for r in rows if r["event_type"] == "login_succeeded" and r["actor_user_id"] == MEM]


def test_deleting_frees_the_seat_and_the_email_can_be_invited_again() -> None:
    before = call("GET", users_url()).json()["seats_used"]
    assert call("DELETE", users_url(user=INV)).status_code == 204
    assert call("GET", users_url()).json()["seats_used"] == before - 1
    again = call("POST", f"/api/v1/orgs/{ORG_A}/invites", "a1",
                 {"email": "inv@acme.test", "role": "org_member", "first_name": "Ivy", "last_name": "Again"})
    assert again.status_code == 201, again.text


def test_an_admin_cannot_delete_themselves() -> None:
    response = call("DELETE", users_url(user=A1))
    assert response.status_code == 409 and response.json()["detail"] == "You cannot delete yourself"
    assert status_of(A1) == ("org_admin", "active")


def test_the_last_active_admin_cannot_be_deleted() -> None:
    assert call("DELETE", users_url(user=A2)).status_code == 204  # another admin: fine
    response = call("DELETE", users_url(user=A1), "provider")
    assert response.status_code == 409
    assert response.json()["detail"] == "The organization must keep at least one active admin"
    assert status_of(A1) == ("org_admin", "active")


@pytest.mark.parametrize(("token", "org", "user", "code"), [
    ("mem", ORG_A, INV, 403),
    (None, ORG_A, INV, 401),
    ("b_admin", ORG_A, INV, 404),
    ("a1", ORG_A, B_ADMIN, 404),
    ("a1", ORG_A, GONE, 404),
    ("a1", ORG_A, uuid.uuid4(), 404),
    ("a1", ORG_A, "nope", 404),
    ("provider", ORG_B, INV, 404),
])
def test_access(token: str | None, org: uuid.UUID, user: Any, code: int) -> None:
    assert call("DELETE", users_url(org, user), token).status_code == code
    assert status_of(INV) == ("org_member", "invited")


def test_provider_admin_can_delete_in_any_org() -> None:
    assert call("DELETE", users_url(ORG_A, INV), "provider").status_code == 204
    assert status_of(INV) == ("org_member", "deleted")
