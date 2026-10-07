"""INFRA-007: document uploads are capped at MAX_UPLOAD_MB with a clear 413."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.core.auth import get_current_user
from backend.app.core.config import Settings
from backend.app.core.security import MULTIPART_OVERHEAD_BYTES
from backend.app.main import create_app
from backend.tests.api.conftest import make_user, owned_upload_service

MB = 1024 * 1024
ORIGIN = {"Origin": "http://localhost:3000"}
UPLOAD = "/api/v1/engagements/ENG-1/documents/upload"
TOO_LARGE = "File is too large. The maximum upload size is 1 MB."


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(max_upload_mb=1))
    app.dependency_overrides[get_current_user] = lambda: make_user()
    original = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    documents_api.configure_services(upload_service=owned_upload_service(tmp_path))
    try:
        yield TestClient(app)
    finally:
        documents_api.configure_services(upload_service=original[0], pipeline_service=original[1],
                                         storage_service=original[2])


def _post(client: TestClient, size: int):
    return client.post(UPLOAD, files={"file": ("bill.pdf", b"x" * size, "application/pdf")}, headers=ORIGIN)


def _chunked(size: int) -> Iterator[bytes]:
    yield (b'--b\r\nContent-Disposition: form-data; name="file"; filename="bill.pdf"\r\n'
           b"Content-Type: application/pdf\r\n\r\n")
    for _ in range(size // (256 * 1024)):
        yield b"x" * (256 * 1024)
    yield b"\r\n--b--\r\n"


def test_a_file_at_the_limit_uploads(client: TestClient) -> None:
    response = _post(client, MB)
    assert response.status_code == 200, response.text


def test_a_file_just_over_the_limit_gets_413_from_the_route(client: TestClient) -> None:
    # Inside the multipart allowance, so it reaches the route, which checks the file itself.
    response = _post(client, MB + 1)
    assert response.status_code == 413
    assert response.json()["detail"] == TOO_LARGE


def test_a_large_declared_body_is_refused_before_parsing(client: TestClient) -> None:
    response = _post(client, MB + MULTIPART_OVERHEAD_BYTES + 1)
    assert response.status_code == 413
    assert response.json()["detail"] == TOO_LARGE
    assert response.headers["connection"] == "close"


def test_a_large_chunked_body_is_refused_while_streaming(client: TestClient) -> None:
    response = client.post(UPLOAD, content=_chunked(3 * MB),
                           headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=b"})
    assert response.status_code == 413
    assert response.json()["detail"] == TOO_LARGE


def test_a_small_chunked_upload_still_works(client: TestClient) -> None:
    response = client.post(UPLOAD, content=_chunked(512 * 1024),
                           headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=b"})
    assert response.status_code == 200, response.text


def test_the_legacy_dev_mount_is_capped_too(client: TestClient) -> None:
    response = client.post("/v1/engagements/ENG-1/documents/upload",
                           files={"file": ("bill.pdf", b"x" * (3 * MB), "application/pdf")})
    assert response.status_code == 413


def test_other_routes_are_not_affected(client: TestClient) -> None:
    # A large JSON body elsewhere is not this middleware's business (Caddy caps it at 1 MB).
    response = client.post("/api/v1/engagements/ENG-1/documents", content=b"{" + b" " * (3 * MB) + b"}",
                           headers={**ORIGIN, "Content-Type": "application/json"})
    assert response.status_code != 413


def test_the_default_limit_is_25_mb(monkeypatch) -> None:
    assert Settings().max_upload_mb == 25
    monkeypatch.setenv("MAX_UPLOAD_MB", "40")
    assert Settings().max_upload_bytes == 40 * MB
