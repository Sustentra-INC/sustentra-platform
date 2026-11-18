"""Document batches over the API: creating one, uploading into it (validated), and the progress view
(per-document status, chunk progress, halt sentence, records found, totals), scoped to the caller's
organization and the batch's engagement. Runs and chunks are in memory (conftest)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.api import processing_runs as processing_runs_api
from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import InMemoryProcessingRunRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.api.conftest import ORG_A, ORG_B

BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"
FUEL = "CT-S1-FUELQTY"
PARAMS = {"canonical_type_id_override": None, "include_optional": True, "include_deprecated": False,
          "persist_run": True}


@pytest.fixture
def env(tmp_path: Path, act_as, run_queue: InMemoryProcessingRunRepository,
        monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    # Queued mode: an upload only queues its read, so the test moves each run along itself.
    settings = Settings(s1_processing="queued", s1_store="postgres+jsonl", git_sha="abc1234")
    monkeypatch.setattr(documents_api, "get_settings", lambda: settings)
    monkeypatch.setattr(processing_runs_api, "get_settings", lambda: settings)
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository(),
                                    clock=lambda: "2026-01-01T00:00:00+00:00")
    pipeline_runs = InMemoryPipelineRunRepository()
    pipeline = PipelineOrchestrationService(pipeline_repository=pipeline_runs,
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    originals = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    documents_api.configure_services(upload_service=uploads, pipeline_service=pipeline, storage_service=storage)
    client = TestClient(app)

    def create_batch(org=ORG_A, engagement: str = "ENG-1", **body: Any) -> str:
        act_as("org_member", org)
        response = client.post(f"/v1/engagements/{engagement}/document-batches", json=body)
        assert response.status_code == 201, response.text
        return response.json()["batch_id"]

    def upload(batch_id: str | None, name: str = "bill.txt", org=ORG_A, engagement: str = "ENG-1"):
        act_as("org_member", org)
        data = {"batch_id": batch_id} if batch_id else {}
        return client.post(f"/v1/engagements/{engagement}/documents/upload", data=data,
                           files={"file": (name, BILL, "text/plain")})

    def view(batch_id: str, org=ORG_A, engagement: str = "ENG-1"):
        act_as("org_member", org)
        return client.get(f"/v1/engagements/{engagement}/document-batches/{batch_id}")

    def claim_and_finish(document: dict, pipeline_run: dict | None, status: str = "completed",
                         error: tuple[str, str] | None = None) -> None:
        run, _ = run_queue.enqueue(org_id=str(ORG_A), engagement_id="ENG-1", document_id=document["document_id"],
                                   evidence_id=document["evidence_id"], params=PARAMS, requested_by="r@example.com")
        started = run_queue.start(run, "w1", 60)
        assert started is not None
        if status == "completed":
            assert pipeline_run is not None
            pipeline_runs.save(pipeline_run)
            run_queue.finalize_completed(started, "w1", pipeline_run["pipeline_run_id"])
        else:
            if pipeline_run is not None:
                pipeline_runs.save(pipeline_run)
            run_queue.finalize_failed(started, "w1", error[0], error[1],  # type: ignore[index]
                                      pipeline_run["pipeline_run_id"] if pipeline_run else None)

    try:
        yield {"client": client, "create_batch": create_batch, "upload": upload, "view": view,
               "queue": run_queue, "finish": claim_and_finish, "act_as": act_as}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])


def pipeline_run(run_id: str, document: dict, status: str = "completed", **fields: Any) -> dict:
    return {"pipeline_run_id": run_id, "engagement_id": "ENG-1", "evidence_id": document["evidence_id"],
            "document_id": document["document_id"], "processing_run_id": "x", "status": status,
            "org_id": str(ORG_A), "created_at": "2026-01-01T00:00:00+00:00", "canonical_type_id": FUEL,
            "found_candidate_count": 4, **fields}


# --- creating and uploading -------------------------------------------------------------------

def test_a_batch_is_created_for_the_engagement(env: dict) -> None:
    env["act_as"]("org_member", ORG_A)
    response = env["client"].post("/v1/engagements/ENG-1/document-batches", json={"label": "March bills"})
    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "March bills" and body["engagement_id"] == "ENG-1" and body["batch_id"]
    # No body at all is fine, and an empty batch has nothing to wait for.
    empty = env["create_batch"]()
    view = env["view"](empty).json()
    assert view["items"] == [] and view["complete"] is True
    assert view["totals"] == {"queued": 0, "reading": 0, "done": 0, "partial": 0, "failed": 0, "not_started": 0}


def test_a_provider_admin_cannot_create_a_batch(env: dict) -> None:
    env["act_as"]("provider_admin", None)
    assert env["client"].post("/v1/engagements/ENG-1/document-batches", json={}).status_code == 403


def test_an_upload_into_the_batch_is_stored_with_its_batch_id(env: dict) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch)
    assert document.status_code == 200, document.text
    assert document.json()["batch_id"] == batch
    assert env["upload"](None).json()["batch_id"] is None  # uploads without a batch are as before


def test_an_unknown_batch_refuses_the_upload_and_stores_nothing(env: dict) -> None:
    response = env["upload"]("no-such-batch")
    assert response.status_code == 404 and response.json()["detail"] == "Batch not found."
    assert documents_api.current_upload_service().list_documents("ENG-1") == []


def test_another_organizations_batch_is_not_found_for_upload_and_for_the_view(env: dict) -> None:
    theirs = env["create_batch"](ORG_B)
    assert env["upload"](theirs, org=ORG_A).status_code == 404
    assert env["view"](theirs, org=ORG_A).status_code == 404
    assert env["view"](theirs, org=ORG_B).status_code == 200


def test_a_batch_of_another_engagement_is_not_found(env: dict) -> None:
    other = env["create_batch"](engagement="ENG-2")
    assert env["upload"](other, engagement="ENG-1").status_code == 404
    assert env["view"](other, engagement="ENG-1").status_code == 404


def test_a_provider_admin_may_read_a_batch(env: dict) -> None:
    batch = env["create_batch"]()
    env["act_as"]("provider_admin", None)
    assert env["client"].get(f"/v1/engagements/ENG-1/document-batches/{batch}").status_code == 200


# --- the progress view ------------------------------------------------------------------------

def test_each_document_shows_its_status_and_the_totals_count_them(env: dict) -> None:
    batch = env["create_batch"]()
    docs = [env["upload"](batch, f"bill-{i}.txt").json() for i in range(5)]
    # 0 stays queued (its run waits for a reader).
    # 1 is being read.
    run, _ = env["queue"].enqueue(org_id=str(ORG_A), engagement_id="ENG-1", document_id=docs[1]["document_id"],
                                  evidence_id=docs[1]["evidence_id"], params=PARAMS, requested_by="r@example.com")
    assert env["queue"].start(run, "w1", 60) is not None
    # 2 is done, 3 partial, 4 failed (the halt's own sentence).
    env["finish"](docs[2], pipeline_run("p2", docs[2]))
    env["finish"](docs[3], pipeline_run("p3", docs[3], "partial", found_candidate_count=1))
    env["finish"](docs[4], pipeline_run("p4", docs[4], "failed", canonical_type_id=None, found_candidate_count=0,
                                        halt_reason={"code": "unreadable_document", "message": "Unreadable document."}),
                  status="failed", error=("unreadable_document", "ignored: the halt speaks"))

    body = env["view"](batch).json()
    by_id = {item["document_id"]: item for item in body["items"]}
    assert [by_id[d["document_id"]]["status"] for d in docs] == ["queued", "reading", "done", "partial", "failed"]
    assert body["totals"] == {"queued": 1, "reading": 1, "done": 1, "partial": 1, "failed": 1, "not_started": 0}
    assert body["complete"] is False
    done, partial, failed = (by_id[docs[i]["document_id"]] for i in (2, 3, 4))
    assert (done["canonical_type_id"], done["records_found"], done["halt_reason"]) == (FUEL, 4, None)
    assert partial["records_found"] == 1
    assert (failed["halt_reason"], failed["canonical_type_id"], failed["records_found"]) == (
        "Unreadable document.", None, 0)
    assert by_id[docs[0]["document_id"]]["file_name"] == "bill-0.txt"


def test_the_view_is_complete_once_nothing_waits_or_reads(env: dict) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch).json()
    assert env["view"](batch).json()["complete"] is False  # a queued run is waiting
    env["finish"](document, pipeline_run("p1", document))
    body = env["view"](batch).json()
    assert body["complete"] is True and body["totals"]["done"] == 1


def test_a_document_with_no_run_is_not_started_and_does_not_hold_the_batch_open(env: dict, run_queue) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch).json()
    # Queued mode queued a first read at upload; remove it to stand for an upload whose read was never asked for.
    run_queue._runs.clear()
    body = env["view"](batch).json()
    item = body["items"][0]
    assert item["document_id"] == document["document_id"]
    assert (item["status"], item["halt_reason"], item["records_found"]) == (
        "not_started", "Reading hasn't started for this file. Open it to start reading.", 0)
    assert body["totals"]["not_started"] == 1 and body["totals"]["queued"] == 0
    assert body["complete"] is True


def test_a_failed_run_with_no_reason_at_all_gets_a_default_sentence(env: dict) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch).json()
    env["finish"](document, None, status="failed", error=("worker_error", ""))
    item = env["view"](batch).json()["items"][0]
    assert (item["status"], item["halt_reason"]) == ("failed", "Reading failed. Try uploading the file again.")


def test_a_failed_run_without_a_halt_says_its_own_error(env: dict) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch).json()
    env["finish"](document, None, status="failed", error=("worker_error", "Reading stopped. Try again."))
    item = env["view"](batch).json()["items"][0]
    assert (item["status"], item["halt_reason"], item["records_found"]) == ("failed", "Reading stopped. Try again.", 0)


def test_a_large_pdf_shows_its_chunk_progress_and_the_pages_that_failed(env: dict, run_queue) -> None:
    batch = env["create_batch"]()
    document = env["upload"](batch).json()
    run, _ = run_queue.enqueue(org_id=str(ORG_A), engagement_id="ENG-1", document_id=document["document_id"],
                               evidence_id=document["evidence_id"], params=PARAMS, requested_by="r@example.com")
    started = run_queue.start(run, "w1", 60)
    chunks = documents_api.current_chunk_repository()
    assert chunks.plan(started, "w1", [(1, 10), (11, 20), (21, 30)])

    def chunk_states() -> dict:
        item = env["view"](batch).json()["items"][0]
        return {"status": item["status"], "chunks": item["chunks"]}

    assert chunk_states() == {"status": "reading", "chunks": {"total": 3, "completed": 0, "failed": 0,
                                                              "failed_pages": []}}
    first, second, third = (chunks.claim("c1", 60) for _ in range(3))
    chunks.finalize_completed(first, "c1", {"status": "parsed"})
    chunks.finalize_failed(second, "c1", "parse_failed")
    chunks.finalize_completed(third, "c1", {"status": "parsed"})
    # Every chunk has ended and the run waits to be assembled: still reading, not queued.
    assert chunk_states() == {"status": "reading", "chunks": {"total": 3, "completed": 2, "failed": 1,
                                                              "failed_pages": [[11, 20]]}}
    # The run reassembles and ends partial: the failed pages are the reason.
    again = run_queue.claim("w2", 60)
    assert again is not None
    pipeline_runs = documents_api.current_pipeline_service()._pipeline_repository
    pipeline_runs.save(pipeline_run("p1", document, "partial"))
    run_queue.finalize_completed(again, "w2", "p1")
    item = env["view"](batch).json()["items"][0]
    assert (item["status"], item["halt_reason"]) == ("partial", "Pages 11-20 could not be read.")
    assert item["chunks"]["failed_pages"] == [[11, 20]]


def test_the_view_lists_only_this_batch_and_only_the_callers_documents(env: dict) -> None:
    mine, other = env["create_batch"](), env["create_batch"]()
    in_mine = env["upload"](mine, "a.txt").json()
    env["upload"](other, "b.txt")
    env["upload"](None, "c.txt")
    items = env["view"](mine).json()["items"]
    assert [item["document_id"] for item in items] == [in_mine["document_id"]]
