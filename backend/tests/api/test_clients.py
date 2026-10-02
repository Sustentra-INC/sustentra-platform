from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.api.identity_deps import configure_identity_service, get_identity_service
from backend.app.main import app
from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.services.identity_service import IdentityService

FROZEN = datetime(2026, 9, 17, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    original = get_identity_service()
    service = IdentityService(
        repository=IdentityRepository.in_memory(),
        clock=lambda: FROZEN,
        totp_time=lambda: int(FROZEN.timestamp()),
        return_dev_tokens=True,
    )
    configure_identity_service(service)
    try:
        yield TestClient(app)
    finally:
        configure_identity_service(original)


def _admin(client: TestClient) -> str:
    client.post(
        "/v1/users",
        json={"username": "admin", "email": "admin@sustentra.local", "password": "password123"},
    )
    login = client.post("/v1/auth/login", json={"username": "admin", "password": "password123"})
    return login.json()["token"]


def test_client_crud_and_client_user_creation(client):
    token = _admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/v1/clients",
        json={
            "name": "Baldwinsville Brewery",
            "code": "brewery",
            "contact_email": "esg@brewery.example",
            "notes": "Pilot 1 client",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    client_id = created.json()["client_id"]
    assert created.json()["name"] == "Baldwinsville Brewery"

    listed = client.get("/v1/clients", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(
        f"/v1/clients/{client_id}",
        json={"notes": "Updated notes", "status": "active"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["notes"] == "Updated notes"

    user = client.post(
        f"/v1/clients/{client_id}/users",
        json={
            "username": "brew.reviewer",
            "email": "reviewer@brewery.example",
            "password": "password123",
        },
        headers=headers,
    )
    assert user.status_code == 200, user.text
    assert user.json()["client_id"] == client_id
    assert "password_hash" not in user.json()

    login = client.post(
        "/v1/auth/login",
        json={"username": "brew.reviewer", "password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["actor_type"] == "client_user"

    forbidden = client.post(
        "/v1/clients",
        json={"name": "Other Co", "code": "other"},
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert forbidden.status_code == 403

    deleted = client.delete(f"/v1/clients/{client_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    missing = client.get(f"/v1/clients/{client_id}", headers=headers)
    assert missing.status_code == 404

    dead_login = client.post(
        "/v1/auth/login",
        json={"username": "brew.reviewer", "password": "password123"},
    )
    assert dead_login.status_code == 401


def test_audit_log_records_client_and_user_actions(client):
    token = _admin(client)
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/v1/clients",
        json={"name": "Acme", "code": "acme"},
        headers=headers,
    )
    events = client.get("/v1/audit-events", headers=headers)
    assert events.status_code == 200
    actions = {item["action"] for item in events.json()}
    assert "user.create" in actions
    assert "auth.login" in actions
    assert "client.create" in actions
