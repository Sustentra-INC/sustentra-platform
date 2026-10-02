import json
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from backend.app.observability import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    RequestLoggingMiddleware,
    set_request_actor,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    def actor(request: Request) -> dict:
        actor = {"actor_id": "user-1", "client_id": "org-9"}
        set_request_actor(request, actor)
        return actor

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/login")
    def login(_: dict = Depends(actor)) -> dict:
        return {"ok": True}

    return app


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "sustentra.access"]


def test_access_log_has_request_id_status_duration(caplog) -> None:
    caplog.set_level(logging.INFO, logger="sustentra.access")
    response = TestClient(_app()).get("/health?token=supersecret")

    assert response.status_code == 200
    request_id = response.headers[REQUEST_ID_HEADER]
    record = _access_records(caplog)[-1]
    assert record.request_id == request_id
    assert record.status == 200
    assert record.path == "/health"  # query string (and its token) not logged
    assert record.duration_ms >= 0


def test_access_log_includes_user_and_org_and_no_secrets(caplog) -> None:
    caplog.set_level(logging.INFO, logger="sustentra.access")
    response = TestClient(_app()).post("/login", json={"email": "a@b.c", "password": "hunter2", "otp": "123456"})

    assert response.status_code == 200
    record = _access_records(caplog)[-1]
    assert record.user_id == "user-1"
    assert record.org_id == "org-9"
    line = JsonFormatter().format(record)
    assert "hunter2" not in line and "123456" not in line
    assert json.loads(line)["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_incoming_request_id_is_reused_when_safe() -> None:
    client = TestClient(_app())
    assert client.get("/health", headers={REQUEST_ID_HEADER: "abc-123"}).headers[REQUEST_ID_HEADER] == "abc-123"
    unsafe = client.get("/health", headers={REQUEST_ID_HEADER: "bad id;drop"}).headers[REQUEST_ID_HEADER]
    assert unsafe != "bad id;drop"


def test_json_formatter_drops_sensitive_extra_keys() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
    record.password = "hunter2"
    record.request_id = "r1"
    payload = json.loads(JsonFormatter().format(record))
    assert "password" not in payload
    assert payload["request_id"] == "r1"
