from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.api.identity_deps import configure_identity_service, get_identity_service
from backend.app.main import app
from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.security.totp import totp
from backend.app.services.identity_service import IdentityService

FROZEN = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def identity_service():
    original = get_identity_service()
    service = IdentityService(
        repository=IdentityRepository.in_memory(),
        clock=lambda: FROZEN,
        totp_time=lambda: int(FROZEN.timestamp()),
        return_dev_tokens=True,
    )
    configure_identity_service(service)
    try:
        yield service
    finally:
        configure_identity_service(original)


@pytest.fixture
def client(identity_service):
    return TestClient(app)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def bootstrap_admin(client: TestClient, username="admin", password="password123") -> dict:
    response = client.post(
        "/v1/users",
        json={
            "username": username,
            "email": f"{username}@sustentra.local",
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    login = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return {"user": response.json(), "token": body["token"], "login": body}


def test_auth_status_without_db(client):
    response = client.get("/v1/auth/status")
    assert response.status_code == 200
    body = response.json()
    assert body["bootstrap_required"] is True
    assert body["persistence"] == "memory"


def test_bootstrap_create_user_and_login(client):
    created = client.post(
        "/v1/users",
        json={
            "username": "vivian",
            "email": "vivian@sustentra.local",
            "password": "password123",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["username"] == "vivian"
    assert body["role"] == "admin"
    assert "password_hash" not in body
    assert "password_salt" not in body

    login = client.post(
        "/v1/auth/login", json={"username": "vivian", "password": "password123"}
    )
    assert login.status_code == 200
    session = login.json()
    assert session["mfa_required"] is False
    assert session["actor_type"] == "sustentra_user"
    assert session["token"]

    me = client.get("/v1/auth/me", headers=auth_header(session["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "vivian"


def test_second_user_requires_auth(client):
    bootstrap_admin(client)
    response = client.post(
        "/v1/users",
        json={
            "username": "operator",
            "email": "operator@sustentra.local",
            "password": "password123",
        },
    )
    assert response.status_code == 403


def test_password_reset_without_email_provider(client):
    bootstrap_admin(client, username="resetme")
    requested = client.post(
        "/v1/auth/password-reset/request", json={"email": "resetme@sustentra.local"}
    )
    assert requested.status_code == 200
    token = requested.json()["dev_reset_token"]
    confirmed = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "newpass123"},
    )
    assert confirmed.status_code == 200
    failed = client.post(
        "/v1/auth/login", json={"username": "resetme", "password": "password123"}
    )
    assert failed.status_code == 401
    ok = client.post(
        "/v1/auth/login", json={"username": "resetme", "password": "newpass123"}
    )
    assert ok.status_code == 200


def test_mfa_setup_and_login(client):
    admin = bootstrap_admin(client)
    setup = client.post("/v1/auth/mfa/setup", headers=auth_header(admin["token"]))
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = totp(secret, at=int(FROZEN.timestamp()))
    confirm = client.post(
        "/v1/auth/mfa/confirm",
        json={"code": code},
        headers=auth_header(admin["token"]),
    )
    assert confirm.status_code == 200
    assert confirm.json()["mfa_enabled"] is True
    assert len(confirm.json()["recovery_codes"]) == 8

    challenge = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "password123"}
    )
    assert challenge.status_code == 200
    body = challenge.json()
    assert body["mfa_required"] is True
    complete = client.post(
        "/v1/auth/login/mfa",
        json={"mfa_token": body["mfa_token"], "code": totp(secret, at=int(FROZEN.timestamp()))},
    )
    assert complete.status_code == 200
    assert complete.json()["token"]
    assert complete.json()["mfa_required"] is False
