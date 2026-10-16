"""S1_STORE picks the S1 document stores, and postgres+jsonl writes everything twice."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.repositories import s1_stores
from backend.app.repositories.document_repository import (
    InMemoryDocumentRepository,
    JsonlDocumentRepository,
    PostgresDocumentRepository,
)
from backend.app.repositories.evidence_repository import PostgresApprovedEvidenceRepository
from backend.app.repositories.extraction_result_repository import PostgresExtractionResultRepository
from backend.app.repositories.pipeline_repository import (
    InMemoryPipelineRunRepository,
    JsonlPipelineRunRepository,
    PostgresPipelineRunRepository,
)
from backend.app.repositories.review_repository import PostgresReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.postgres_file_store import PostgresFileStore


def _store(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(s1_stores, "get_settings", lambda: SimpleNamespace(s1_store=name))


def test_jsonl_keeps_the_files_on_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch, "jsonl")
    assert isinstance(s1_stores.documents(), JsonlDocumentRepository)
    assert isinstance(s1_stores.pipeline_runs(), JsonlPipelineRunRepository)
    assert isinstance(s1_stores.files(), LocalStorageService)


def test_postgres_uses_only_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch, "postgres")
    assert isinstance(s1_stores.documents(), PostgresDocumentRepository)
    assert isinstance(s1_stores.pipeline_runs(), PostgresPipelineRunRepository)
    assert isinstance(s1_stores.extraction_results(), PostgresExtractionResultRepository)
    assert isinstance(s1_stores.review_decisions(), PostgresReviewDecisionRepository)
    assert isinstance(s1_stores.approved_evidence(), PostgresApprovedEvidenceRepository)
    assert isinstance(s1_stores.files(), PostgresFileStore)


def test_the_services_default_to_the_chosen_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch, "postgres")
    upload = DocumentUploadService()
    assert isinstance(upload.storage_service, PostgresFileStore)
    assert isinstance(upload._document_repository, PostgresDocumentRepository)
    pipeline = PipelineOrchestrationService()
    assert isinstance(pipeline._pipeline_repository, PostgresPipelineRunRepository)
    assert isinstance(pipeline._extraction_result_repository, PostgresExtractionResultRepository)
    approved = ApprovedEvidenceService()
    assert isinstance(approved._review_repository, PostgresReviewDecisionRepository)
    assert isinstance(approved._approved_repository, PostgresApprovedEvidenceRepository)


def test_postgres_plus_jsonl_mirrors_every_store(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(monkeypatch, "postgres+jsonl")
    documents = s1_stores.documents()
    assert isinstance(documents, s1_stores.MirroredRepository)
    assert isinstance(documents._primary, PostgresDocumentRepository)
    assert isinstance(documents._mirror, JsonlDocumentRepository)
    files = s1_stores.files()
    assert isinstance(files, s1_stores.MirroredFileStore)
    assert isinstance(files._primary, PostgresFileStore)


def test_a_mirrored_save_goes_to_both_and_reads_come_from_the_database() -> None:
    primary, mirror = InMemoryDocumentRepository(), InMemoryDocumentRepository()
    documents = s1_stores.MirroredRepository(primary, mirror)
    documents.save({"document_id": "D1", "evidence_id": "EV1", "processing_status": "queued"})
    documents.update_processing_status("D1", "completed")

    assert [d["processing_status"] for d in mirror.list_all()] == ["queued", "completed"]
    assert primary.get_by_id("D1")["processing_status"] == "completed"
    mirror.save({"document_id": "D-only-on-disk", "evidence_id": "EV1"})
    assert [d["document_id"] for d in documents.list_by_evidence("EV1")] == ["D1"]
    with pytest.raises(KeyError):
        documents.update_processing_status("missing", "completed")


class _Broken:
    path = "broken.jsonl"

    def save(self, _record: Any) -> None:
        raise OSError("disk full")


def test_a_failed_mirror_write_is_logged_and_the_save_still_succeeds(caplog: pytest.LogCaptureFixture) -> None:
    primary = InMemoryPipelineRunRepository()
    runs = s1_stores.MirroredRepository(primary, _Broken())
    with caplog.at_level(logging.ERROR, logger="sustentra.s1_store"):
        saved = runs.save({"pipeline_run_id": "R1"})
    assert saved == {"pipeline_run_id": "R1"} and primary.get_by_id("R1") == saved
    assert "broken.jsonl" in caplog.text


def test_a_failure_in_the_database_writes_nothing_to_the_files() -> None:
    mirror = InMemoryPipelineRunRepository()
    runs = s1_stores.MirroredRepository(_Broken(), mirror)
    with pytest.raises(OSError):
        runs.save({"pipeline_run_id": "R1"})
    assert mirror.list_all() == []


class _FakeFileStore:
    def save_upload(self, **kwargs: Any) -> dict:
        return {"storage_uri": f"local-data/uploads/org/ENG/EV/DOC/{kwargs['file_name']}",
                "stored_file_name": kwargs["file_name"], "size_bytes": len(kwargs["content"])}

    def resolve_storage_uri(self, storage_uri: str) -> str:
        return f"db:{storage_uri}"


def test_a_mirrored_upload_is_also_written_to_disk_under_the_same_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # the app's uploads folder is relative: local-data/uploads
    disk = LocalStorageService()
    files = s1_stores.MirroredFileStore(_FakeFileStore(), disk)  # type: ignore[arg-type]
    result = files.save_upload(file_name="bill.pdf", content=b"%PDF bill", engagement_id="ENG",
                               evidence_id="EV", document_id="DOC", owner="org")

    assert (tmp_path / "local-data" / "uploads" / "org" / "ENG" / "EV" / "DOC" / "bill.pdf").read_bytes() == b"%PDF bill"
    assert files.resolve_storage_uri(result["storage_uri"]) == f"db:{result['storage_uri']}"  # reads: the database
