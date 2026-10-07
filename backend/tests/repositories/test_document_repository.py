from pathlib import Path

import pytest

from backend.app.repositories.document_repository import (
    InMemoryDocumentRepository,
    JsonlDocumentRepository,
)


def _document(
    document_id: str,
    engagement_id: str = "ENG-1",
    evidence_id: str | None = "EV-1",
    processing_status: str = "not_started",
) -> dict:
    return {
        "document_id": document_id,
        "engagement_id": engagement_id,
        "evidence_id": evidence_id,
        "file_name": "sample.pdf",
        "mime_type": "application/pdf",
        "storage_uri": "local-data/uploads/ENG-1/EV-1/DOC-1/sample.pdf",
        "document_role": "source_evidence",
        "document_type": None,
        "uploaded_by": "dev@example.com",
        "uploaded_at": "2026-01-01T00:00:00+00:00",
        "processing_status": processing_status,
    }


@pytest.fixture(params=["memory", "jsonl"])
def repository(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryDocumentRepository()
    return JsonlDocumentRepository(tmp_path / "documents.jsonl")


def test_save_and_list_all(repository):
    repository.save(_document("DOC-1"))
    repository.save(_document("DOC-2", evidence_id="EV-2"))
    assert len(repository.list_all()) == 2


def test_get_by_id_returns_latest_version(repository):
    repository.save(_document("DOC-1", processing_status="queued"))
    repository.save(_document("DOC-1", processing_status="completed"))
    latest = repository.get_by_id("DOC-1")
    assert latest is not None
    assert latest["processing_status"] == "completed"


def test_list_by_engagement(repository):
    repository.save(_document("DOC-1", engagement_id="ENG-1"))
    repository.save(_document("DOC-2", engagement_id="ENG-2"))
    assert len(repository.list_by_engagement("ENG-1")) == 1


def test_list_by_evidence(repository):
    repository.save(_document("DOC-1", evidence_id="EV-1"))
    repository.save(_document("DOC-2", evidence_id="EV-2"))
    assert len(repository.list_by_evidence("EV-2")) == 1


def test_get_latest_by_evidence(repository):
    repository.save(_document("DOC-1", evidence_id="EV-1", processing_status="queued"))
    repository.save(_document("DOC-2", evidence_id="EV-1", processing_status="completed"))
    latest = repository.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["document_id"] == "DOC-2"


def test_update_processing_status(repository):
    repository.save(_document("DOC-1", processing_status="queued"))
    updated = repository.update_processing_status("DOC-1", "in_progress")
    assert updated["processing_status"] == "in_progress"

    latest = repository.get_by_id("DOC-1")
    assert latest is not None
    assert latest["processing_status"] == "in_progress"


def test_update_processing_status_missing_document_raises(repository):
    with pytest.raises(KeyError):
        repository.update_processing_status("MISSING", "in_progress")


def test_jsonl_persistence_survives_reinstantiation(tmp_path: Path):
    path = tmp_path / "documents.jsonl"
    first = JsonlDocumentRepository(path)
    first.save(_document("DOC-1", evidence_id="EV-1"))
    first.save(_document("DOC-2", evidence_id="EV-1"))

    second = JsonlDocumentRepository(path)
    assert len(second.list_all()) == 2
    latest = second.get_latest_by_evidence("EV-1")
    assert latest is not None
    assert latest["document_id"] == "DOC-2"


def test_jsonl_uses_temporary_path(tmp_path: Path):
    path = tmp_path / "nested" / "documents.jsonl"
    repository = JsonlDocumentRepository(path)
    repository.save(_document("DOC-1"))
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip()


def test_listings_return_the_latest_version_of_each_document() -> None:
    from backend.app.repositories.document_repository import InMemoryDocumentRepository

    repository = InMemoryDocumentRepository()
    first = {"document_id": "D1", "engagement_id": "E", "evidence_id": "EV", "processing_status": "queued"}
    second = {"document_id": "D2", "engagement_id": "E", "evidence_id": "EV", "processing_status": "queued"}
    repository.save(first)
    repository.save(second)
    repository.save({**first, "processing_status": "completed"})
    for listed in (repository.list_by_engagement("E"), repository.list_by_evidence("EV")):
        assert [(d["document_id"], d["processing_status"]) for d in listed] == [("D1", "completed"), ("D2", "queued")]
    assert len(repository.list_all()) == 3  # the log itself keeps every version
