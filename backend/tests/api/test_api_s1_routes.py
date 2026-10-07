"""Frontend integration: S1 workpaper routes reachable under /api/v1, uploads allowed as multipart."""

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.rate_limit import limiter
from backend.app.main import create_app

ORIGIN = "https://app.sustentra.test"


def _app():  # type: ignore[no-untyped-def]
    return create_app(Settings(environment="test", git_sha="t", ALLOWED_ORIGINS=ORIGIN))  # type: ignore[call-arg]


def _paths() -> set[str]:
    # FastAPI >= 0.14x keeps included routers nested (app.routes no longer lists their
    # routes), so read the effective paths from the generated OpenAPI schema instead.
    return set(_app().openapi()["paths"])


def test_frontend_seam_routes_exist_under_api_v1_and_v1() -> None:
    paths = _paths()
    for path in (
        "/v1/engagements/{engagement_id}/documents",
        "/v1/engagements/{engagement_id}/documents/upload",
        "/v1/documents/{document_id}/pipeline/process",
        "/v1/pipeline/evidence/{evidence_id}/latest-run",
        "/v1/documents/{document_id}/reviews",
        "/v1/evidence/{evidence_id}/fields/{field_name}/review",
    ):
        assert path in paths, path
        assert "/api" + path in paths, "/api" + path


def test_the_legacy_identity_routes_are_gone() -> None:
    # CLEANUP-001: the bearer-token JSONL identity API was removed everywhere.
    paths = _paths()
    for path in ("/v1/users", "/v1/clients", "/v1/auth/login", "/v1/auth/mfa/setup", "/v1/audit-events",
                 "/api/v1/users", "/api/v1/clients", "/api/v1/auth/mfa/setup", "/api/v1/audit-events"):
        assert path not in paths, path
    # /api/v1/auth/* is the only auth (AUTH-004..006).
    assert "/api/v1/auth/me" in paths


def test_multipart_upload_passes_the_json_only_rule() -> None:
    limiter.reset()
    client = TestClient(_app())
    response = client.post(
        "/api/v1/engagements/eng-1/documents/upload",
        files={"file": ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code != 415


def test_multipart_elsewhere_is_still_rejected() -> None:
    limiter.reset()
    client = TestClient(_app())
    response = client.post(
        "/api/v1/engagements",
        files={"file": ("x.txt", b"x", "text/plain")},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 415
