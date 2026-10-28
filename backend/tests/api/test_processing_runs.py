"""Processing runs over the API: POST /documents/{id}/processing-runs, GET /processing-runs/{id},
GET /engagements/{id}/processing-runs, and POST .../pipeline/process reading through the same
executor. The run queue is in memory (``run_queue`` in conftest)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api import documents as documents_api
from backend.app.api import processing_runs as processing_runs_api
from backend.app.core.config import Settings
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.processing_run_repository import InMemoryProcessingRunRepository
from backend.app.services.document_processing_service import STILL_READING_MESSAGE, WORKER_ERROR_MESSAGE
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.api.conftest import ORG_A, ORG_B, make_user

BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"
CORRUPT_PDF = b"%PDF-1.4\n%%EOF\n"
FUEL = "CT-S1-FUELQTY"
SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "processing_run.schema.json").read_text())


def assert_contract(run: dict[str, Any]) -> dict[str, Any]:
    """The run matches contracts/processing_run.schema.json (jsonschema is a dev requirement;
    without it, as in a bare local venv, only the field names are checked)."""

    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover - CI installs requirements-dev.txt
        assert set(SCHEMA["required"]) <= set(run) <= set(SCHEMA["properties"]), sorted(run)
        return run
    validator = Draft202012Validator(SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(run), key=str)
    assert not errors, [error.message for error in errors]
    return run


class Raising:
    """A pipeline that raises instead of reading."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def process_local_document(self, **_kwargs: Any) -> dict:
        raise self.error


@pytest.fixture
def env(tmp_path: Path, act_as, run_queue: InMemoryProcessingRunRepository) -> Iterator[dict]:
    storage = LocalStorageService(tmp_path / "uploads")
    documents = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository(),
                                      clock=lambda: "2026-01-01T00:00:00+00:00")
    pipeline_runs = InMemoryPipelineRunRepository()
    pipeline = PipelineOrchestrationService(pipeline_repository=pipeline_runs,
                                            extraction_result_repository=InMemoryExtractionResultRepository())
    originals = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    documents_api.configure_services(upload_service=documents, pipeline_service=pipeline, storage_service=storage)
    client = TestClient(app)

    def upload(name: str = "bill.txt", body: bytes = BILL, mime: str = "text/plain", org=ORG_A) -> dict:
        act_as("org_member", org)
        response = client.post("/v1/engagements/ENG-1/documents/upload", files={"file": (name, body, mime)})
        assert response.status_code == 200, response.text
        return response.json()

    def status_of(document: dict, org=ORG_A) -> str:
        act_as("org_member", org)
        return client.get(f"/v1/documents/{document['document_id']}").json()["processing_status"]

    try:
        yield {"client": client, "act_as": act_as, "upload": upload, "status_of": status_of,
               "pipeline_runs": pipeline_runs, "queue": run_queue}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(s1_processing="queued", s1_store="postgres+jsonl", git_sha="abc1234")
    monkeypatch.setattr(processing_runs_api, "get_settings", lambda: settings)


def runs_url(document: dict) -> str:
    return f"/v1/documents/{document['document_id']}/processing-runs"


# --- inline (the default): read in the request ----------------------------------------------

def test_inline_reads_the_document_and_returns_the_finished_run(env: dict) -> None:
    doc = env["upload"]()
    response = env["client"].post(runs_url(doc), json={"canonical_type_id_override": FUEL})
    assert response.status_code == 200, response.text
    run = assert_contract(response.json())
    assert (run["status"], run["attempt"], run["max_attempts"]) == ("completed", 1, 3)
    assert (run["document_id"], run["evidence_id"], run["engagement_id"]) == (
        doc["document_id"], doc["evidence_id"], "ENG-1")
    assert run["requested_by"] == make_user("org_member", ORG_A).email
    assert run["canonical_type_id_override"] == FUEL
    assert run["started_at"] and run["completed_at"] and run["error"] is None and run["error_code"] is None

    recorded = env["pipeline_runs"].get_by_id(run["pipeline_run_id"])
    assert recorded["processing_run_id"] == run["run_id"]  # the pipeline run names the processing run
    assert recorded["canonical_type_id"] == FUEL
    assert env["status_of"](doc) == "completed"
    assert env["client"].get(f"/v1/processing-runs/{run['run_id']}").json() == run


def test_a_halt_is_a_failed_run_with_its_reason(env: dict) -> None:
    doc = env["upload"]("scan.pdf", CORRUPT_PDF, "application/pdf")
    run = assert_contract(env["client"].post(runs_url(doc)).json())  # no body: the defaults
    assert (run["status"], run["error_code"]) == ("failed", "unreadable_document")
    assert run["error"].startswith("Unreadable document") and run["pipeline_run_id"]
    assert env["status_of"](doc) == "failed"


@pytest.mark.parametrize(("error", "code", "message"), [
    (ValueError("engagement_id is required."), "invalid_request", "engagement_id is required."),
    (RuntimeError("database went away"), "worker_error", WORKER_ERROR_MESSAGE),
])
def test_a_read_that_raises_fails_at_once_inline(env: dict, error: Exception, code: str, message: str) -> None:
    doc = env["upload"]()
    documents_api.configure_services(pipeline_service=Raising(error))  # type: ignore[arg-type]
    run = assert_contract(env["client"].post(runs_url(doc), json={}).json())
    assert (run["status"], run["error_code"], run["error"], run["attempt"]) == ("failed", code, message, 1)
    assert run["pipeline_run_id"] is None
    assert env["status_of"](doc) == "failed"


def test_inline_reads_a_run_that_was_left_queued(env: dict) -> None:
    doc = env["upload"]()
    left, _ = env["queue"].enqueue(  # e.g. queued before a switch back to inline
        org_id=str(ORG_A), engagement_id="ENG-1", document_id=doc["document_id"], evidence_id=doc["evidence_id"],
        params={"canonical_type_id_override": None, "include_optional": True, "include_deprecated": False,
                "persist_run": True},
        requested_by="earlier@example.com")
    response = env["client"].post(runs_url(doc), json={})
    assert response.status_code == 200, response.text
    assert (response.json()["run_id"], response.json()["status"]) == (left.run_id, "completed")


# --- queued: only queued ------------------------------------------------------------------

def test_queued_only_queues_and_asking_again_returns_the_same_run(env: dict, queued: None) -> None:
    doc = env["upload"]()
    response = env["client"].post(runs_url(doc), json={"canonical_type_id_override": FUEL})
    assert response.status_code == 202, response.text
    run = assert_contract(response.json())
    assert (run["status"], run["attempt"], run["started_at"], run["completed_at"]) == ("queued", 0, None, None)
    assert run["pipeline_version"] == "abc1234"
    assert env["status_of"](doc) == "queued"
    assert env["pipeline_runs"].list_all() == []  # nothing was read

    again = env["client"].post(runs_url(doc), json={"canonical_type_id_override": FUEL})
    assert (again.status_code, again.json()["run_id"]) == (202, run["run_id"])

    other_type = env["client"].post(runs_url(doc), json={"canonical_type_id_override": "CT-S1-ELEC"})
    assert (other_type.status_code, other_type.json()["detail"]) == (409, STILL_READING_MESSAGE)


def test_a_run_being_read_is_returned_as_it_is(env: dict, queued: None) -> None:
    doc = env["upload"]()
    run = env["client"].post(runs_url(doc), json={}).json()
    assert env["queue"].claim("reader:1", 120).run_id == run["run_id"]
    response = env["client"].post(runs_url(doc), json={})
    assert response.status_code == 202
    assert (response.json()["run_id"], response.json()["status"]) == (run["run_id"], "in_progress")


# --- who may see and start runs -------------------------------------------------------------

def test_other_orgs_get_404_and_the_provider_reads_but_cannot_start(env: dict) -> None:
    doc = env["upload"]()
    run = env["client"].post(runs_url(doc), json={}).json()
    client, act_as = env["client"], env["act_as"]

    act_as("org_member", ORG_B)
    assert client.get(f"/v1/processing-runs/{run['run_id']}").status_code == 404
    assert client.post(runs_url(doc), json={}).status_code == 404
    assert client.get("/v1/engagements/ENG-1/processing-runs").json()["items"] == []
    assert client.get("/v1/processing-runs/no-such-run").status_code == 404

    act_as("provider_admin")
    assert client.get(f"/v1/processing-runs/{run['run_id']}").status_code == 200
    assert [r["run_id"] for r in client.get("/v1/engagements/ENG-1/processing-runs").json()["items"]] == [
        run["run_id"]]
    assert client.post(runs_url(doc), json={}).status_code == 403


def test_a_document_without_its_file_cannot_be_read(env: dict, tmp_path: Path) -> None:
    doc = env["upload"]()
    for stored in (tmp_path / "uploads").rglob("bill.txt"):
        stored.unlink()
    response = env["client"].post(runs_url(doc), json={})
    assert (response.status_code, response.json()["detail"]) == (400, "Stored document file is missing.")
    assert env["queue"].latest_per_document("ENG-1") == []


def test_the_engagement_list_has_each_documents_latest_run(env: dict) -> None:
    first_doc, second_doc = env["upload"](), env["upload"]("other.txt")
    client = env["client"]
    client.post(runs_url(first_doc), json={})
    reread = client.post(runs_url(first_doc), json={"canonical_type_id_override": FUEL}).json()
    other = client.post(runs_url(second_doc), json={}).json()

    listed = client.get("/v1/engagements/ENG-1/processing-runs").json()
    assert listed["engagement_id"] == "ENG-1"
    assert [r["run_id"] for r in listed["items"]] == [reread["run_id"], other["run_id"]]
    for item in listed["items"]:
        assert_contract(item)
    assert client.get("/v1/engagements/ENG-2/processing-runs").json()["items"] == []


# --- POST .../pipeline/process reads through the same executor ------------------------------

def test_the_older_endpoint_records_a_run_and_answers_as_before(env: dict) -> None:
    doc = env["upload"]()
    response = env["client"].post(f"/v1/documents/{doc['document_id']}/pipeline/process",
                                  json={"canonical_type_id_override": FUEL, "persist_run": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"pipeline_run", "parser_output", "classification_result", "extraction_targets",
                         "extraction_result"}

    [run] = env["client"].get("/v1/engagements/ENG-1/processing-runs").json()["items"]
    assert (run["status"], run["pipeline_run_id"]) == ("completed", body["pipeline_run"]["pipeline_run_id"])
    assert body["pipeline_run"]["processing_run_id"] == run["run_id"]
    assert env["status_of"](doc) == "completed"


def test_the_older_endpoint_turns_a_problem_on_our_side_into_a_500(env: dict) -> None:
    doc = env["upload"]()
    documents_api.configure_services(pipeline_service=Raising(RuntimeError("boom")))  # type: ignore[arg-type]
    response = env["client"].post(f"/v1/documents/{doc['document_id']}/pipeline/process", json={})
    assert (response.status_code, response.json()["detail"]) == (500, "Pipeline processing failed: boom")
    assert env["status_of"](doc) == "failed"


def test_the_older_endpoint_waits_for_no_one_while_the_document_is_read(env: dict, queued: None) -> None:
    doc = env["upload"]()
    env["client"].post(runs_url(doc), json={})
    env["queue"].claim("reader:1", 120)
    process = f"/v1/documents/{doc['document_id']}/pipeline/process"

    response = env["client"].post(process, json={})
    assert (response.status_code, response.json()["detail"]) == (409, STILL_READING_MESSAGE)
    other_type = env["client"].post(process, json={"canonical_type_id_override": FUEL})
    assert other_type.status_code == 409
    assert env["pipeline_runs"].list_all() == []


# --- settings -------------------------------------------------------------------------------

def test_queued_reads_need_postgres_backed_stores() -> None:
    assert Settings().s1_processing == "inline"
    assert Settings(s1_processing="queued", s1_store="postgres").s1_processing == "queued"
    with pytest.raises(ValidationError, match="S1_PROCESSING=queued needs S1_STORE"):
        Settings(s1_processing="queued", s1_store="jsonl")


# --- uploads in queued mode: the upload asks for the first read ------------------------------

@pytest.fixture
def queued_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(s1_processing="queued", s1_store="postgres+jsonl", git_sha="abc1234")
    monkeypatch.setattr(documents_api, "get_settings", lambda: settings)
    monkeypatch.setattr(processing_runs_api, "get_settings", lambda: settings)


def test_a_queued_upload_answers_with_its_queued_run(env: dict, queued_uploads: None) -> None:
    doc = env["upload"]()
    assert doc["processing_status"] == "queued"
    run = assert_contract(doc["processing_run"])
    assert (run["status"], run["attempt"], run["document_id"], run["pipeline_version"]) == (
        "queued", 0, doc["document_id"], "abc1234")
    assert env["pipeline_runs"].list_all() == []  # nothing was read
    listed = env["client"].get("/v1/engagements/ENG-1/processing-runs").json()["items"]
    assert [item["run_id"] for item in listed] == [run["run_id"]]
    assert env["status_of"](doc) == "queued"


def test_asking_to_read_a_queued_upload_returns_its_run(env: dict, queued_uploads: None) -> None:
    doc = env["upload"]()
    response = env["client"].post(runs_url(doc), json={})
    assert (response.status_code, response.json()["run_id"]) == (202, doc["processing_run"]["run_id"])


def test_an_inline_upload_is_unchanged(env: dict) -> None:
    doc = env["upload"]()
    assert "processing_run" not in doc
    assert doc["processing_status"] == "not_started"
    assert env["queue"].latest_per_document("ENG-1") == []


def test_an_upload_still_succeeds_when_its_read_cannot_be_queued(
    env: dict, queued_uploads: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def queue_is_down(**_kwargs: Any) -> None:
        raise RuntimeError("db gone")

    monkeypatch.setattr(env["queue"], "enqueue", queue_is_down)
    doc = env["upload"]()
    assert "processing_run" not in doc
    assert doc["processing_status"] == "not_started"
    [record] = [r for r in caplog.records if r.getMessage() == "upload_read_not_queued"]
    assert (record.name, record.document_id) == ("sustentra.processing", doc["document_id"])
