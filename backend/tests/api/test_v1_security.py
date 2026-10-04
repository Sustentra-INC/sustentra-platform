"""AUTH-001: health, origin check, JSON-only bodies, auth rate limit, docs toggle."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.core.config import Settings, normalize_origin
from backend.app.core.rate_limit import auth_rate_limit, limiter
from backend.app.main import APP_TITLE, create_app

ORIGIN = "https://app.sustentra.test"
# Test-only endpoint inside /api/v1/auth/* (shares the auth rate-limit bucket) so these
# middleware tests don't need a database now that /login is real (AUTH-005).
PROBE = "/api/v1/auth/_probe"


def _with_probe(app: FastAPI) -> FastAPI:
    @app.post(PROBE)
    @auth_rate_limit
    async def probe(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    return app
GOOD = {"Origin": ORIGIN, "Content-Type": "application/json"}


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"environment": "test", "git_sha": "abc1234", "ALLOWED_ORIGINS": ORIGIN}
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def reset_rate_limits() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(_with_probe(create_app(_settings())))


# --- /health -------------------------------------------------------------------

def test_health_returns_status_and_git_sha(client: TestClient) -> None:
    for path in ("/health", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "abc1234"}


def test_app_title_unchanged(client: TestClient) -> None:
    assert client.app.title == APP_TITLE  # type: ignore[attr-defined]


# --- Origin / Referer check ----------------------------------------------------------

def test_foreign_origin_is_rejected(client: TestClient) -> None:
    response = client.post(PROBE, json={}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden origin"}


def test_missing_origin_and_referer_is_rejected(client: TestClient) -> None:
    assert client.post(PROBE, json={}).status_code == 403


def test_allowed_origin_passes(client: TestClient) -> None:
    assert client.post(PROBE, json={}, headers=GOOD).status_code == 200


def test_allowed_referer_passes_when_no_origin(client: TestClient) -> None:
    headers = {"Referer": f"{ORIGIN}/org/acme/login", "Content-Type": "application/json"}
    assert client.post(PROBE, json={}, headers=headers).status_code == 200


def test_foreign_referer_is_rejected(client: TestClient) -> None:
    headers = {"Referer": "https://evil.example/x", "Content-Type": "application/json"}
    assert client.post(PROBE, json={}, headers=headers).status_code == 403


def test_safe_methods_skip_origin_check(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 200


# --- JSON-only content type ----------------------------------------------------------

def test_form_body_is_rejected_with_415(client: TestClient) -> None:
    response = client.post(
        PROBE, data={"email": "a@b.c"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 415


def test_json_body_is_accepted(client: TestClient) -> None:
    response = client.post(PROBE, json={"email": "a@b.c"}, headers={"Origin": ORIGIN})
    assert response.status_code == 200


# --- rate limit ------------------------------------------------------------------

def test_101st_auth_request_in_window_returns_429(client: TestClient) -> None:
    for _ in range(100):
        assert client.post(PROBE, json={}, headers=GOOD).status_code == 200
    response = client.post(PROBE, json={}, headers=GOOD)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


# --- docs + request id -----------------------------------------------------------

def test_docs_disabled_outside_local() -> None:
    prod = TestClient(create_app(_settings(environment="prod")))
    assert prod.get("/api/v1/docs").status_code == 404
    assert prod.get("/api/v1/openapi.json").status_code == 404


def test_docs_enabled_locally() -> None:
    local = TestClient(create_app(_settings(environment="local")))
    assert local.get("/api/v1/docs").status_code == 200


def test_responses_carry_request_id(client: TestClient) -> None:
    assert client.get("/api/health").headers.get("X-Request-ID")


# --- helpers -----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://App.Example.com", "https://app.example.com"),
        ("https://app.example.com:443/path?q=1", "https://app.example.com"),
        ("http://localhost:3000/", "http://localhost:3000"),
    ],
)
def test_normalize_origin(raw: str, expected: str) -> None:
    assert normalize_origin(raw) == expected
