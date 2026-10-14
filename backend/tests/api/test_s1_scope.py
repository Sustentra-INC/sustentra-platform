"""The S1 scope: every S1 request carries the signed-in user's organization (or provider
scope) for the synchronous document stores, and nothing reads S1 data without one."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.core.db import to_sync_url
from backend.app.core.s1_scope import MissingS1Scope, S1Scope, current_scope, scoped
from backend.app.main import app
from backend.tests.api.conftest import ORG_A


def test_nothing_is_bound_outside_a_request() -> None:
    with pytest.raises(MissingS1Scope):
        current_scope()


def test_a_scope_is_bound_explicitly_and_released() -> None:
    with scoped(S1Scope.platform()) as scope:
        assert current_scope() is scope and scope.provider
    with pytest.raises(MissingS1Scope):
        current_scope()


def test_a_scope_is_one_organization_or_provider_scope() -> None:
    assert S1Scope.tenant(str(ORG_A)).org_id == ORG_A
    with pytest.raises(ValueError):
        S1Scope(None)
    with pytest.raises(ValueError):
        S1Scope(uuid.uuid4(), provider=True)


@pytest.mark.parametrize(("role", "expected"), [("org_member", S1Scope.tenant(ORG_A)),
                                                ("provider_admin", S1Scope.platform())])
def test_each_s1_request_carries_the_signed_in_users_scope(act_as, monkeypatch, role: str,
                                                           expected: S1Scope) -> None:
    seen: list[S1Scope] = []

    def get_document(document_id: str) -> None:  # runs in the threadpool, like the stores will
        seen.append(current_scope())

    monkeypatch.setattr(documents_api._upload_service, "get_document", get_document)
    act_as(role, ORG_A)
    with TestClient(app) as client:
        assert client.get("/v1/documents/DOC-1/pages").status_code == 404
    assert seen == [expected]


def test_signed_out_requests_never_reach_the_stores(act_as, monkeypatch) -> None:
    monkeypatch.setattr(documents_api._upload_service, "get_document",
                        lambda document_id: pytest.fail("reached the store"))
    act_as(None)
    with TestClient(app) as client:
        assert client.get("/v1/documents/DOC-1/pages").status_code == 401


def test_the_sync_url_keeps_tls() -> None:
    assert to_sync_url("postgresql+asyncpg://u:p@h:5432/db?ssl=require") == (
        "postgresql+psycopg2://u:p@h:5432/db?sslmode=require")
    assert to_sync_url("postgresql://u:p@h/db?sslmode=verify-full") == "postgresql+psycopg2://u:p@h/db?sslmode=verify-full"
