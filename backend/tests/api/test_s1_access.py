"""SEC-001: every S1 route needs a session; data is scoped to the caller's org."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.api import evidence as evidence_api
from backend.app.api import pipeline as pipeline_api
from backend.app.api import reviews as reviews_api
from backend.app.core.config import Settings
from backend.app.main import S1_ROUTERS, app, create_app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.review_decision_service import ReviewDecisionService
from backend.tests.api.conftest import ORG_A, ORG_B

S1_PATHS = sorted({(route.path, method) for router in S1_ROUTERS for route in router.routes
                   if isinstance(route, APIRoute) for method in route.methods})


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.mark.parametrize(("path", "method"), S1_PATHS)
@pytest.mark.parametrize("mount", ["/api", ""])
def test_every_s1_route_requires_a_session(path: str, method: str, mount: str) -> None:
    from backend.app.core.config import get_settings

    client = TestClient(app)
    # a trusted Origin, so state-changing /api requests pass the CSRF origin check and reach auth
    origin = sorted(get_settings().allowed_origins)[0]
    response = client.request(method, mount + _url(path), json={}, headers={"Origin": origin})
    assert response.status_code == 401, (method, mount + path, response.status_code)


def test_the_sweep_covers_the_known_routers() -> None:
    paths = {path for path, _ in S1_PATHS}
    for expected in ("/v1/engagements/{engagement_id}/documents/upload", "/v1/documents/{document_id}",
                     "/v1/pipeline/runs/{pipeline_run_id}", "/v1/evidence/{evidence_id}/fields/{field_name}/review",
                     "/v1/approved-evidence/{approved_evidence_id}", "/v1/methodology/s2/run"):
        assert expected in paths
    assert len(S1_PATHS) >= 25


# --- an S1 world with data in two orgs ----------------------------------------------------
@pytest.fixture
def world(tmp_path: Path, act_as) -> Iterator[dict]:
    storage = LocalStorageService(tmp_path / "uploads")
    documents = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository(),
                                      clock=lambda: "2026-01-01T00:00:00+00:00")
    pipeline_repo = InMemoryPipelineRunRepository()
    review_repo = InMemoryReviewDecisionRepository()
    approved_repo = InMemoryApprovedEvidenceRepository()
    review_service = ReviewDecisionService(repository=review_repo, clock=lambda: "2026-01-01T00:00:00+00:00")
    approved_service = ApprovedEvidenceService(review_repository=review_repo, approved_repository=approved_repo,
                                               clock=lambda: "2026-01-01T00:00:00+00:00")
    pipeline = PipelineOrchestrationService(pipeline_repository=pipeline_repo, review_service=review_service,
                                            approved_evidence_service=approved_service)
    originals = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service,
                 pipeline_api._service, reviews_api._service, evidence_api._service)
    documents_api.configure_services(upload_service=documents, pipeline_service=pipeline, storage_service=storage)
    pipeline_api.configure_service(pipeline)
    reviews_api.configure_service(review_service)
    evidence_api.configure_service(approved_service)

    client = TestClient(app)
    bill = "Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n".encode()

    def upload(org, evidence_id: str) -> dict:
        act_as("org_member", org)
        response = client.post("/v1/engagements/ENG-1/documents/upload",
                               files={"file": ("bill.txt", bill, "text/plain")},
                               data={"evidence_id": evidence_id})
        assert response.status_code == 200, response.text
        return response.json()

    a_doc = upload(ORG_A, "EV-A")
    b_doc = upload(ORG_B, "EV-B")
    act_as("org_member", ORG_A)
    processed = client.post(f"/v1/documents/{a_doc['document_id']}/pipeline/process",
                            json={"canonical_type_id_override": "CT-S1-FUELQTY"})
    assert processed.status_code == 200, processed.text
    run = processed.json()["pipeline_run"]
    candidate = next(c for c in processed.json()["extraction_result"]["items"]
                     if c["field_name"] == "activity_quantity")
    reviewed = client.put("/v1/evidence/EV-A/fields/activity_quantity/review",
                          json={"candidate": candidate, "decision": "accepted"})
    assert reviewed.status_code == 200, reviewed.text
    approved = client.post("/v1/evidence/EV-A/approved-evidence/project",
                           json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"})
    assert approved.status_code == 200, approved.text
    # A record from before SEC-001 (no owner).
    legacy = documents.create_document_metadata(
        engagement_id="ENG-1", file_name="old.pdf", mime_type="application/pdf", storage_uri="uploads/old.pdf",
        document_role="source_evidence", uploaded_by="old@example.com", evidence_id="EV-OLD")
    try:
        yield {"client": client, "act_as": act_as, "a_doc": a_doc, "b_doc": b_doc, "run": run,
               "candidate": candidate, "review": reviewed.json(), "approved": approved.json(), "legacy": legacy,
               "pipeline_repo": pipeline_repo}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])
        pipeline_api.configure_service(originals[3])
        reviews_api.configure_service(originals[4])
        evidence_api.configure_service(originals[5])


def _reads(w: dict) -> list[str]:
    a_doc, run = w["a_doc"], w["run"]
    return [
        f"/v1/documents/{a_doc['document_id']}",
        f"/v1/pipeline/runs/{run['pipeline_run_id']}",
        "/v1/pipeline/evidence/EV-A/latest-run",
        "/v1/pipeline/evidence/EV-A/status",
        "/v1/evidence/EV-A",
        "/v1/evidence/EV-A/approved-evidence/latest",
        f"/v1/approved-evidence/{w['approved']['approved_evidence_id']}",
        f"/v1/candidates/{w['candidate']['candidate_id']}/reviews/latest",
    ]


def test_records_are_stamped_with_the_callers_org(world: dict) -> None:
    assert world["a_doc"]["org_id"] == str(ORG_A)
    assert world["a_doc"]["storage_uri"].startswith(f"uploads/{ORG_A}/")
    assert world["run"]["org_id"] == str(ORG_A)
    assert world["review"]["org_id"] == str(ORG_A)
    assert world["approved"]["org_id"] == str(ORG_A)
    assert world["pipeline_repo"].get_by_id(world["run"]["pipeline_run_id"])["org_id"] == str(ORG_A)


def test_owner_can_read_everything(world: dict) -> None:
    world["act_as"]("org_admin", ORG_A)
    for url in _reads(world):
        assert world["client"].get(url).status_code == 200, url


def test_other_org_gets_404_for_every_record(world: dict) -> None:
    world["act_as"]("org_admin", ORG_B)
    for url in _reads(world):
        response = world["client"].get(url)
        assert response.status_code == 404, (url, response.status_code)


def test_lists_only_show_the_callers_org(world: dict) -> None:
    client = world["client"]
    world["act_as"]("org_member", ORG_B)
    ids = [d["document_id"] for d in client.get("/v1/engagements/ENG-1/documents").json()["items"]]
    assert ids == [world["b_doc"]["document_id"]]
    assert client.get("/v1/evidence/EV-A/documents").json()["items"] == []
    assert client.get("/v1/evidence/EV-A/reviews").json() == []
    assert client.get(f"/v1/documents/{world['a_doc']['document_id']}/reviews").json() == []
    assert client.get("/v1/engagements/ENG-1/approved-evidence").json() == []


def test_other_org_cannot_write_to_foreign_data(world: dict) -> None:
    client = world["client"]
    world["act_as"]("org_member", ORG_B)
    assert client.post(f"/v1/documents/{world['a_doc']['document_id']}/pipeline/process", json={}).status_code == 404
    assert client.put("/v1/evidence/EV-A/fields/activity_quantity/review",
                      json={"candidate": world["candidate"], "decision": "rejected"}).status_code == 404
    assert client.post("/v1/evidence/EV-A/approved-evidence/project",
                       json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"}).status_code == 404
    # cannot attach a document to org A's evidence
    hijack = client.post("/v1/engagements/ENG-1/documents/upload",
                         files={"file": ("x.txt", b"Natural gas 1 therm", "text/plain")}, data={"evidence_id": "EV-A"})
    assert hijack.status_code == 404
    # cannot point metadata at org A's stored file
    stolen = client.post("/v1/engagements/ENG-1/documents", json={
        "file_name": "bill.txt", "mime_type": "text/plain", "storage_uri": world["a_doc"]["storage_uri"],
        "document_role": "source_evidence"})
    assert stolen.status_code == 400
    # methodology on org A's approved evidence
    assert client.post("/v1/methodology/s2/run",
                       json={"approved_evidence": world["approved"]}).status_code == 404


def test_provider_admin_reads_all_orgs_but_cannot_write(world: dict) -> None:
    client = world["client"]
    world["act_as"]("provider_admin")
    for url in _reads(world):
        assert client.get(url).status_code == 200, url
    items = client.get("/v1/engagements/ENG-1/documents").json()["items"]
    assert len({d["document_id"] for d in items}) == 3  # A, B and the legacy doc
    assert client.post("/v1/engagements/ENG-1/documents/upload",
                       files={"file": ("x.txt", b"x", "text/plain")}).status_code == 403
    assert client.post(f"/v1/documents/{world['a_doc']['document_id']}/pipeline/process", json={}).status_code == 403
    assert client.put("/v1/evidence/EV-A/fields/activity_quantity/review",
                      json={"candidate": world["candidate"], "decision": "rejected"}).status_code == 403


def test_unowned_records_are_visible_to_the_provider_only(world: dict) -> None:
    client = world["client"]
    url = f"/v1/documents/{world['legacy']['document_id']}"
    world["act_as"]("org_admin", ORG_A)
    assert client.get(url).status_code == 404
    # and cannot be adopted by attaching a new document to its evidence
    adopt = client.post("/v1/engagements/ENG-1/documents/upload",
                        files={"file": ("x.txt", b"Natural gas 1 therm", "text/plain")}, data={"evidence_id": "EV-OLD"})
    assert adopt.status_code == 404
    world["act_as"]("provider_admin")
    assert client.get(url).status_code == 200


def test_client_cannot_choose_the_owner(world: dict) -> None:
    world["act_as"]("org_member", ORG_A)
    candidate = copy.deepcopy(world["candidate"])
    response = world["client"].put("/v1/evidence/EV-A/fields/activity_quantity/review",
                                   json={"candidate": candidate, "decision": "accepted", "org_id": str(ORG_B)})
    assert response.status_code == 200
    assert response.json()["org_id"] == str(ORG_A)


# --- production settings ----------------------------------------------------------------------
def _prod_app():
    return create_app(Settings(environment="prod", git_sha="t",  # type: ignore[call-arg]
                               ALLOWED_ORIGINS="https://app.example.com"))


def test_legacy_root_routes_are_not_mounted_in_production() -> None:
    client = TestClient(_prod_app())
    assert client.get("/v1/documents/x").status_code == 404      # legacy root mount: absent
    assert client.get("/v1/users").status_code == 404
    assert client.get("/api/v1/documents/x").status_code == 401  # S1 under /api: present, needs a session
    assert client.get("/api/v1/audit-events").status_code == 404  # legacy JSONL identity: dev-only


def test_local_file_pipeline_is_disabled_in_production(act_as, monkeypatch) -> None:
    from backend.app.api import pipeline as pipeline_module

    class ProdSettings:
        is_production_like = True

    monkeypatch.setattr(pipeline_module, "get_settings", lambda: ProdSettings())
    act_as("org_admin", ORG_A)
    response = TestClient(app).post("/v1/pipeline/local/process-document",
                                    json={"local_file_path": "/etc/passwd", "engagement_id": "E"})
    assert response.status_code == 404


# --- review findings (SEC-001 hardening) -----------------------------------------------------
def test_pre_sec001_evidence_cannot_be_adopted(world: dict) -> None:
    """An evidence id with only unowned reviews / approved evidence is not 'free'."""
    client = world["client"]
    legacy_review = {**world["review"], "review_decision_id": "old-1", "evidence_id": "EV-L",
                     "candidate_id": "candidate::EV-L::OLD::activity_quantity", "document_id": "OLD",
                     "reviewed_value": 4242, "org_id": None}
    reviews_api.current_service()._repository.save(legacy_review)  # noqa: SLF001 - seed an old record
    world["act_as"]("org_member", ORG_B)
    adopt = client.post("/v1/engagements/ENG-1/documents/upload",
                        files={"file": ("x.txt", b"Natural gas 1 therm", "text/plain")}, data={"evidence_id": "EV-L"})
    assert adopt.status_code == 404
    assert client.get("/v1/pipeline/evidence/EV-L/status").status_code == 404
    assert client.post("/v1/evidence/EV-L/approved-evidence/project",
                       json={"engagement_id": "ENG-1", "evidence_type": "CT-S1-FUELQTY"}).status_code == 404


def test_projection_never_uses_another_orgs_decisions() -> None:
    review_repo = InMemoryReviewDecisionRepository()
    for org, value in ((str(ORG_A), 1), (str(ORG_B), 2), (None, 3)):
        review_repo.save({"review_decision_id": f"d-{value}", "candidate_id": "c", "evidence_id": "EV",
                          "document_id": "D", "field_name": f"f{value}", "decision": "accepted",
                          "reviewed_value": value, "reviewed_unit": None, "reviewer_id": "r",
                          "reviewed_at": "2026-01-01T00:00:00+00:00", "reviewer_note": None,
                          "candidate_snapshot": {}, "source_reference": {}, "org_id": org})
    service = ApprovedEvidenceService(review_repository=review_repo,
                                      approved_repository=InMemoryApprovedEvidenceRepository())
    projected = service.project_by_evidence("EV", "ENG", "CT-S1-FUELQTY", org_id=str(ORG_A))
    assert [f["approved_value"] for f in projected["fields"]] == [1]


def test_forged_candidate_ids_are_rejected(world: dict) -> None:
    client = world["client"]
    world["act_as"]("org_member", ORG_B)
    b_candidate = {**world["candidate"], "evidence_id": "EV-B", "document_id": world["b_doc"]["document_id"]}
    # A's candidate id on B's evidence
    forged = client.put("/v1/evidence/EV-B/fields/activity_quantity/review",
                        json={"candidate": b_candidate, "decision": "rejected"})
    assert forged.status_code == 400
    # a document that is not part of the evidence
    b_candidate.update(document_id=world["a_doc"]["document_id"],
                       candidate_id=f"candidate::EV-B::{world['a_doc']['document_id']}::activity_quantity")
    assert client.put("/v1/evidence/EV-B/fields/activity_quantity/review",
                      json={"candidate": b_candidate, "decision": "rejected"}).status_code == 404
    # A still sees its own latest review
    world["act_as"]("org_member", ORG_A)
    url = f"/v1/candidates/{world['candidate']['candidate_id']}/reviews/latest"
    assert world["client"].get(url).json()["org_id"] == str(ORG_A)


def test_latest_review_is_the_callers_own(world: dict) -> None:
    foreign = {**world["review"], "review_decision_id": "foreign", "org_id": str(ORG_B),
               "reviewed_at": "2026-02-01T00:00:00+00:00"}
    reviews_api.current_service()._repository.save(foreign)  # noqa: SLF001 - a later foreign record
    world["act_as"]("org_member", ORG_A)
    url = f"/v1/candidates/{world['candidate']['candidate_id']}/reviews/latest"
    assert world["client"].get(url).json()["review_decision_id"] == world["review"]["review_decision_id"]


def test_methodology_persistence_uses_the_server_copy(world: dict) -> None:
    client = world["client"]
    forged = {**world["approved"], "evidence_id": "EV-B", "fields": []}
    world["act_as"]("org_member", ORG_B)
    response = client.post("/v1/methodology/s2/run",
                           json={"approved_evidence": forged, "persist_methodology_values": True})
    assert response.status_code == 404


def test_local_pipeline_cannot_take_another_orgs_evidence(world: dict, tmp_path: Path) -> None:
    sample = tmp_path / "b.txt"
    sample.write_text("Natural gas\nTotal Usage: 1 therms\n")
    world["act_as"]("org_member", ORG_B)
    response = world["client"].post("/v1/pipeline/local/process-document",
                                     json={"local_file_path": str(sample), "engagement_id": "ENG-1",
                                           "evidence_id": "EV-A"})
    assert response.status_code == 404
