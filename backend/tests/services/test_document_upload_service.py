import copy

import pytest

from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService


def _service(tmp_path, id_factory=None):
    return DocumentUploadService(
        storage_service=LocalStorageService(tmp_path / "uploads"),
        document_repository=InMemoryDocumentRepository(),
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )


def test_upload_document_stores_file_and_metadata(tmp_path):
    service = _service(tmp_path)

    result = service.upload_document(
        engagement_id="ENG-1",
        file_name="sample.pdf",
        content=b"document-bytes",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )

    assert result["document_id"].startswith("document::ENG-1::")
    assert result["evidence_id"].startswith("evidence::ENG-1::")
    assert result["processing_status"] == "not_started"
    assert result["uploaded_at"] == "2026-01-01T00:00:00+00:00"
    assert service.storage_service.exists(result["storage_uri"]) is True


def test_generated_ids_and_uploaded_at_are_deterministic(tmp_path):
    def id_factory(prefix: str, engagement_id: str) -> str:
        return f"{prefix}::{engagement_id}::fixed"

    service = _service(tmp_path, id_factory=id_factory)
    result = service.upload_document(
        engagement_id="ENG-1",
        file_name="sample.pdf",
        content=b"bytes",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )

    assert result["document_id"] == "document::ENG-1::fixed"
    assert result["evidence_id"] == "evidence::ENG-1::fixed"
    assert result["uploaded_at"] == "2026-01-01T00:00:00+00:00"


def test_document_type_optional(tmp_path):
    service = _service(tmp_path)
    result = service.upload_document(
        engagement_id="ENG-1",
        file_name="sample.pdf",
        content=b"bytes",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )
    assert result.get("document_type") is None


def test_get_list_and_list_by_evidence_work(tmp_path):
    service = _service(tmp_path)

    first = service.upload_document(
        engagement_id="ENG-1",
        evidence_id="EV-1",
        file_name="a.pdf",
        content=b"a",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )
    second = service.upload_document(
        engagement_id="ENG-1",
        evidence_id="EV-2",
        file_name="b.pdf",
        content=b"b",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )

    assert service.get_document(first["document_id"]) is not None
    assert len(service.list_documents("ENG-1")) == 2
    assert len(service.list_documents_by_evidence("EV-1")) == 1
    assert second["evidence_id"] == "EV-2"


def test_update_processing_status_works(tmp_path):
    service = _service(tmp_path)
    created = service.upload_document(
        engagement_id="ENG-1",
        file_name="sample.pdf",
        content=b"bytes",
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )

    updated = service.update_processing_status(created["document_id"], "in_progress")
    assert updated["processing_status"] == "in_progress"


def test_input_content_is_not_mutated(tmp_path):
    service = _service(tmp_path)
    content = b"immutable-bytes"
    snapshot = copy.deepcopy(content)

    service.upload_document(
        engagement_id="ENG-1",
        file_name="sample.pdf",
        content=content,
        mime_type="application/pdf",
        document_role="source_evidence",
        uploaded_by="dev@example.com",
    )

    assert content == snapshot


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "engagement_id": "",
            "file_name": "sample.pdf",
            "content": b"x",
            "mime_type": "application/pdf",
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
        },
        {
            "engagement_id": "ENG-1",
            "file_name": "",
            "content": b"x",
            "mime_type": "application/pdf",
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
        },
        {
            "engagement_id": "ENG-1",
            "file_name": "sample.pdf",
            "content": b"x",
            "mime_type": "",
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
        },
        {
            "engagement_id": "ENG-1",
            "file_name": "sample.pdf",
            "content": b"x",
            "mime_type": "application/pdf",
            "document_role": "",
            "uploaded_by": "dev@example.com",
        },
        {
            "engagement_id": "ENG-1",
            "file_name": "sample.pdf",
            "content": b"x",
            "mime_type": "application/pdf",
            "document_role": "source_evidence",
            "uploaded_by": "",
        },
    ],
)
def test_missing_required_fields_raise_value_error(tmp_path, kwargs):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.upload_document(**kwargs)
