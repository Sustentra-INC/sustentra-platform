"""The processing-run executor: how each way a read can end is recorded on the run and its
document, retries for problems on our side, and not reading twice what an earlier attempt
already recorded."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.processing_run_repository import InMemoryProcessingRunRepository, ProcessingRun
from backend.app.services.document_processing_service import (
    FILE_MISSING_MESSAGE,
    PIPELINE_FAILED_MESSAGE,
    WORKER_ERROR_MESSAGE,
    DocumentProcessingService,
    RunConflict,
    RunParams,
)
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService

ORG = "aaaaaaaa-0000-4000-8000-00000000000a"
OTHER_ORG = "bbbbbbbb-0000-4000-8000-00000000000b"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


class FakePipeline:
    def __init__(self, result: dict | Exception | None = None, recorded: list[dict] | None = None) -> None:
        self.result = result if result is not None else completed_result()
        self.recorded = recorded or []
        self.calls: list[dict] = []

    def process_local_document(self, **kwargs: Any) -> dict:
        self.calls.append(copy.deepcopy(kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return copy.deepcopy(self.result)

    def list_runs_by_evidence(self, evidence_id: str) -> list[dict]:
        return [run for run in self.recorded if run.get("evidence_id") == evidence_id]


def completed_result(status: str = "completed", halt: dict | None = None) -> dict:
    return {"pipeline_run": {"pipeline_run_id": "P-1", "status": status, "halt_reason": halt, "errors": []},
            "extraction_result": {"items": []}}


@dataclass
class World:
    service: DocumentProcessingService
    runs: InMemoryProcessingRunRepository
    uploads: DocumentUploadService
    pipeline: FakePipeline
    document: dict

    def status(self) -> str:
        return self.uploads.get_document(self.document["document_id"])["processing_status"]

    def request(self, **params: Any) -> ProcessingRun:
        run, _ = self.service.request(document=self.document, org_id=ORG, requested_by="reader@example.com",
                                      params=RunParams(**params))
        return run

    def claimed(self, **params: Any) -> ProcessingRun:
        run = self.request(**params)
        claimed = self.runs.claim("reader:1", 120)
        assert claimed is not None and claimed.run_id == run.run_id
        return claimed


def make_world(tmp_path: Path, pipeline: FakePipeline | None = None, owner: str = ORG) -> World:
    storage = LocalStorageService(tmp_path / "uploads")
    uploads = DocumentUploadService(storage_service=storage, document_repository=InMemoryDocumentRepository())
    document = uploads.upload_document(engagement_id="ENG-1", file_name="bill.txt", content=b"Total: 120 therms",
                                       mime_type="text/plain", document_role="source_evidence",
                                       uploaded_by="reader@example.com", org_id=owner)
    runs = InMemoryProcessingRunRepository(lambda: NOW)
    pipeline = pipeline or FakePipeline()
    service = DocumentProcessingService(runs, uploads, pipeline, storage, worker_id="reader:1")
    return World(service, runs, uploads, pipeline, document)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return make_world(tmp_path)


# --- one attempt ----------------------------------------------------------------------------

def test_a_read_completes_the_run_and_the_document(world: World) -> None:
    run = world.claimed(canonical_type_id_override="CT-S1-FUELQTY")
    outcome = world.service.execute(run)
    assert world.status() == "in_progress"  # while it is read
    assert (outcome.status, outcome.pipeline_run_id) == ("completed", "P-1")
    call = world.pipeline.calls[0]
    assert call["processing_run_id"] == run.run_id and call["org_id"] == ORG
    assert call["canonical_type_id_override"] == "CT-S1-FUELQTY" and Path(call["local_file_path"]).is_file()

    finished = world.service.finish(run, outcome, retry=True)
    assert (finished.status, finished.pipeline_run_id) == ("completed", "P-1")
    assert world.status() == "completed"


@pytest.mark.parametrize(("result", "code", "message"), [
    (completed_result("failed", {"code": "unreadable_document", "message": "Unreadable document."}),
     "unreadable_document", "Unreadable document."),
    (completed_result("failed"), "pipeline_failed", PIPELINE_FAILED_MESSAGE),
    (ValueError("engagement_id is required."), "invalid_request", "engagement_id is required."),
])
def test_a_failure_about_the_document_is_final(tmp_path: Path, result: Any, code: str, message: str) -> None:
    world = make_world(tmp_path, FakePipeline(result))
    run = world.claimed()
    outcome = world.service.execute(run)
    assert (outcome.status, outcome.error_code, outcome.error) == ("failed", code, message)
    finished = world.service.finish(run, outcome, retry=True)
    assert (finished.status, finished.error_code, finished.error, finished.attempts) == ("failed", code, message, 1)
    assert world.status() == "failed"


def test_a_partial_run_is_completed(tmp_path: Path) -> None:  # e.g. an unsupported type: Blocked, as today
    world = make_world(tmp_path, FakePipeline(completed_result("partial", {"code": "unsupported_document",
                                                                             "message": "Unsupported."})))
    run = world.claimed()
    assert world.service.finish(run, world.service.execute(run), retry=True).status == "completed"


def test_a_missing_document_or_file_fails_without_reading(world: World, tmp_path: Path) -> None:
    run = world.claimed()
    for stored in (tmp_path / "uploads").rglob("bill.txt"):
        stored.unlink()
    outcome = world.service.execute(run)
    assert (outcome.status, outcome.error_code, outcome.error) == ("failed", "file_missing", FILE_MISSING_MESSAGE)
    assert world.pipeline.calls == []

    gone = ProcessingRun(**{**run.__dict__, "document_id": "no-such-document"})
    assert world.service.execute(gone).error_code == "document_missing"


def test_a_file_outside_the_runs_organization_is_not_read(tmp_path: Path) -> None:
    world = make_world(tmp_path, owner=OTHER_ORG)  # the record names another organization's folder
    run = world.claimed()
    assert world.service.execute(run).error_code == "file_missing"
    assert world.pipeline.calls == []


# --- problems on our side are read again ----------------------------------------------------

def test_a_problem_on_our_side_is_retried_with_backoff_then_fails(tmp_path: Path) -> None:
    clock = {"now": NOW}
    world = make_world(tmp_path, FakePipeline(RuntimeError("database went away")))
    world.runs = InMemoryProcessingRunRepository(lambda: clock["now"])
    world.service = DocumentProcessingService(world.runs, world.uploads, world.pipeline,
                                              world.service._storage, worker_id="reader:1")
    run = world.claimed()

    for delay in (30, 120):
        outcome = world.service.execute(run)
        assert (outcome.status, outcome.detail) == ("retry", "database went away")
        waiting = world.service.finish(run, outcome, retry=True)
        assert (waiting.status, waiting.error_code) == ("queued", "worker_error")
        assert waiting.run_after == clock["now"] + timedelta(seconds=delay)
        assert world.status() == "queued"
        clock["now"] = waiting.run_after
        run = world.runs.claim("reader:1", 120)  # type: ignore[assignment]
        assert run is not None

    assert run.attempts == 3
    last = world.service.finish(run, world.service.execute(run), retry=True)
    assert (last.status, last.error_code, last.error) == ("failed", "worker_error", WORKER_ERROR_MESSAGE)
    assert world.status() == "failed"


def test_inline_a_problem_on_our_side_fails_at_once(tmp_path: Path) -> None:
    world = make_world(tmp_path, FakePipeline(RuntimeError("boom")))
    finished, outcome = world.service.run_inline(world.request())
    assert outcome is not None and outcome.status == "retry"
    assert (finished.status, finished.error_code, finished.attempts) == ("failed", "worker_error", 1)
    assert world.status() == "failed"


def test_an_earlier_attempts_recorded_result_is_not_read_again(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    run = world.claimed()
    assert world.runs.retry_later(run, "reader:1", 0, "worker_error") is not None  # it stopped after recording
    world.pipeline.recorded = [{"pipeline_run_id": "P-EARLIER", "evidence_id": world.document["evidence_id"],
                                "processing_run_id": run.run_id, "status": "completed"},
                               {"pipeline_run_id": "P-OTHER", "evidence_id": world.document["evidence_id"],
                                "processing_run_id": "another-run", "status": "completed"}]
    second = world.runs.claim("reader:1", 120)
    assert second is not None and second.attempts == 2

    outcome = world.service.execute(second)
    assert (outcome.status, outcome.pipeline_run_id) == ("completed", "P-EARLIER")
    assert world.pipeline.calls == []


def test_the_first_attempt_does_not_look_for_an_earlier_result(world: World) -> None:
    world.pipeline.recorded = [{"pipeline_run_id": "P-X", "evidence_id": world.document["evidence_id"],
                                "processing_run_id": "whatever", "status": "completed"}]
    run = world.claimed()
    world.service.execute(run)
    assert len(world.pipeline.calls) == 1


# --- fencing and asking ---------------------------------------------------------------------

def test_a_reader_that_lost_the_run_records_nothing(world: World) -> None:
    run = world.claimed()
    outcome = world.service.execute(run)
    world.runs.release(run, "reader:1")
    taken = world.runs.claim("reader:2", 120)
    assert taken is not None

    result = world.service.finish(run, outcome, retry=True)
    assert (result.status, result.worker_id) == ("in_progress", "reader:2")
    assert world.status() == "in_progress"  # as the new reader left it


def test_asking_again_returns_the_active_run_unless_it_reads_another_type(world: World) -> None:
    first = world.request()
    assert world.request().run_id == first.run_id
    with pytest.raises(RunConflict) as conflict:
        world.request(canonical_type_id_override="CT-S1-ELEC")
    assert conflict.value.run.run_id == first.run_id

    world.service.mark_queued(first)
    assert world.status() == "queued"


def test_run_inline_leaves_a_run_someone_else_is_reading(world: World) -> None:
    run = world.claimed()
    current, outcome = world.service.run_inline(run)
    assert outcome is None and current.worker_id == "reader:1" and current.status == "in_progress"
    assert world.pipeline.calls == []
