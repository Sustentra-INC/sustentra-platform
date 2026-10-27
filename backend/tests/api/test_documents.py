from __future__ import annotations

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.parser_service import ParserService
from backend.tests.api.conftest import ORG_A, make_user, seeded_document


class FakePipelineService:
    def __init__(self, status: str = "completed") -> None:
        self.calls: list[dict] = []
        self._status = status

    def process_local_document(self, **kwargs) -> dict:
        self.calls.append(copy.deepcopy(kwargs))
        return {
            "pipeline_run": {
                "pipeline_run_id": "pipeline::EV-1::01",
                "status": self._status,
                "errors": [],
            },
            "parser_output": {"status": "parsed"},
            "classification_result": {"status": "classified"},
            "extraction_targets": [],
            "extraction_result": {
                "candidate_count": 0,
                "items": [],
            },
        }


@pytest.fixture
def client_context(tmp_path: Path):
    original_upload = documents_api._upload_service
    original_pipeline = documents_api._pipeline_service
    original_storage = documents_api._storage_service

    storage_service = LocalStorageService(tmp_path / "uploads")
    repository = InMemoryDocumentRepository()
    # Uploads may only attach to evidence that already exists in the caller's org.
    for evidence_id in ("EV-1", "EV-123", "EV-PIPE", "EV-9"):
        repository.save({**seeded_document(evidence_id, document_id=f"SEED-{evidence_id}"), "engagement_id": "ENG-SEED"})

    counters = {"document": 0, "evidence": 0}

    def id_factory(prefix: str, engagement_id: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}::{engagement_id}::{counters[prefix]:02d}"

    upload_service = DocumentUploadService(
        storage_service=storage_service,
        document_repository=repository,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )
    pipeline_service = FakePipelineService(status="completed")

    documents_api.configure_services(
        upload_service=upload_service,
        pipeline_service=pipeline_service,
        storage_service=storage_service,
    )

    try:
        with TestClient(app) as client:
            yield {
                "client": client,
                "upload_service": upload_service,
                "pipeline_service": pipeline_service,
                "storage_service": storage_service,
            }
    finally:
        documents_api.configure_services(
            upload_service=original_upload,
            pipeline_service=original_pipeline,
            storage_service=original_storage,
        )


def test_upload_endpoint_stores_file_and_returns_metadata(client_context):
    client = client_context["client"]

    response = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample-bill.pdf", b"pdf-bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
            "evidence_id": "EV-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["engagement_id"] == "ENG-1"
    assert body["evidence_id"] == "EV-1"
    assert body["processing_status"] == "not_started"
    assert client_context["storage_service"].exists(body["storage_uri"]) is True


def test_upload_records_the_signed_in_uploader(client_context):
    client = client_context["client"]
    response = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample-bill.pdf", b"pdf-bytes", "application/pdf")},
        # a client-supplied uploaded_by is ignored (SEC-001)
        data={"document_role": "source_evidence", "uploaded_by": "someone-else@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["uploaded_by"] == make_user().email
    assert response.json()["org_id"] == str(ORG_A)


UNREADABLE = (
    "{name} can't be read here. Upload a PDF, Word (.docx), Excel (.xls or .xlsx), CSV or text file, "
    "an email (.eml), or a scan or photo (PNG, JPG or TIFF)."
)


@pytest.mark.parametrize(("name", "mime"), [
    ("qa_archive.zip", "application/zip"),
    ("page.html", "text/html"),
    ("old-bill.doc", "application/msword"),
    # Outlook messages are not read yet, whatever media type the browser gives them.
    ("Fwd March bill.msg", "application/vnd.ms-outlook"),
    ("Fwd March bill.msg", "message/rfc822"),
    ("readings", "application/octet-stream"),
    # Images the readers can't open (Textract reads PNG, JPEG and TIFF), even though the
    # parser would call them images: by extension, then by media type.
    ("photo.webp", "image/webp"),
    ("photo.gif", "image/gif"),
    ("scan.bmp", "image/bmp"),
    ("photo.webp", "image/png"),
    ("logo.svg", "image/svg+xml"),
    ("scan", "image/heic"),
    ("photo.heic", "image/heic"),
])
def test_upload_refuses_a_file_no_parser_can_read(client_context, name: str, mime: str):
    client = client_context["client"]
    response = client.post(
        "/api/v1/engagements/ENG-1/documents/upload",
        files={"file": (name, b"PK\x03\x04 not readable", mime)},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == UNREADABLE.format(name=name)
    # Refused before anything is stored: no file on disk and no document in Evidence.
    storage_root = client_context["storage_service"].storage_root
    assert not storage_root.exists() or not any(path.is_file() for path in storage_root.rglob("*"))
    assert client.get("/v1/engagements/ENG-1/documents").json()["items"] == []


@pytest.mark.parametrize(("name", "mime"), [
    ("bill.pdf", "application/pdf"),
    ("letter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("log.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("log.xlsm", "application/octet-stream"),
    ("legacy.xls", "application/vnd.ms-excel"),
    ("legacy.XLS", "application/octet-stream"),
    ("readings.csv", "text/csv"),
    ("notes.txt", "text/plain"),
    ("notes.md", "text/markdown"),
    ("Fwd March bill.eml", "message/rfc822"),
    ("Fwd March bill.EML", "application/octet-stream"),
    ("meter.PNG", "image/png"),
    ("meter.jpg", "image/jpeg"),
    ("meter.jpeg", "image/jpeg"),
    ("scan.tif", "image/tiff"),
    ("scan.tiff", "image/tiff"),
    # No extension: the mime type decides, as in the parser.
    ("scan", "image/png"),
    ("photo", "image/jpeg"),
    ("fax", "image/tiff"),
    ("export", "text/csv; charset=utf-8"),
    ("export", "application/vnd.ms-excel"),
    ("message", "message/rfc822"),
])
def test_upload_accepts_every_file_a_parser_can_read(client_context, name: str, mime: str):
    response = client_context["client"].post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": (name, b"bytes", mime)},
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("name", "mime"), [
    ("photo.webp", "image/webp"),
    ("photo.gif", None),
    ("scan.bmp", None),
    ("scan", "image/heic"),
])
def test_stored_images_are_still_detected_as_images_at_parse_time(name: str, mime: str | None):
    # Only the upload check is narrowed: documents stored before it behave as before.
    assert ParserService.parser_kind(Path(name), mime) == "image"


def test_get_document_returns_uploaded_document(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={"document_role": "source_evidence", "uploaded_by": "dev@example.com"},
    ).json()

    fetched = client.get(f"/v1/documents/{created['document_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["document_id"] == created["document_id"]


def test_get_documents_by_engagement_returns_uploaded_document(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
            "evidence_id": "EV-1",
        },
    ).json()

    response = client.get("/v1/engagements/ENG-1/documents")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["document_id"] == created["document_id"] for item in items)


def test_get_documents_by_evidence_returns_uploaded_document(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
            "evidence_id": "EV-123",
        },
    ).json()

    response = client.get("/v1/evidence/EV-123/documents")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["document_id"] == created["document_id"] for item in items)


def test_process_endpoint_calls_pipeline_with_stored_path(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
            "evidence_id": "EV-PIPE",
        },
    ).json()

    response = client.post(
        f"/v1/documents/{created['document_id']}/pipeline/process",
        json={"canonical_type_id_override": "CT-S1-FUELQTY", "persist_run": True},
    )

    assert response.status_code == 200
    assert len(client_context["pipeline_service"].calls) == 1
    call = client_context["pipeline_service"].calls[0]
    assert Path(call["local_file_path"]).exists()
    assert call["document_id"] == created["document_id"]
    assert call["evidence_id"] == "EV-PIPE"



def test_process_endpoint_updates_processing_status(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
        },
    ).json()

    response = client.post(
        f"/v1/documents/{created['document_id']}/pipeline/process",
        json={"canonical_type_id_override": "CT-S1-FUELQTY", "persist_run": True},
    )
    assert response.status_code == 200

    fetched = client.get(f"/v1/documents/{created['document_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["processing_status"] == "completed"



def test_process_endpoint_missing_document_returns_404(client_context):
    client = client_context["client"]
    response = client.post(
        "/v1/documents/does-not-exist/pipeline/process",
        json={"canonical_type_id_override": "CT-S1-FUELQTY", "persist_run": True},
    )
    assert response.status_code == 404



def test_process_endpoint_missing_stored_file_returns_400(client_context):
    client = client_context["client"]
    created = client.post(
        "/v1/engagements/ENG-1/documents/upload",
        files={"file": ("sample.pdf", b"bytes", "application/pdf")},
        data={
            "document_role": "source_evidence",
            "uploaded_by": "dev@example.com",
        },
    ).json()

    path = client_context["storage_service"].resolve_storage_uri(created["storage_uri"])
    path.unlink()

    response = client.post(
        f"/v1/documents/{created['document_id']}/pipeline/process",
        json={"canonical_type_id_override": "CT-S1-FUELQTY", "persist_run": True},
    )
    assert response.status_code in {400, 404}



def test_metadata_create_endpoint_is_service_backed(client_context):
    client = client_context["client"]
    response = client.post(
        "/v1/engagements/ENG-1/documents",
        json={
            "file_name": "metadata-only.pdf",
            "mime_type": "application/pdf",
            "storage_uri": f"uploads/{ORG_A}/ENG-1/EV-9/DOC-9/metadata-only.pdf",
            "document_role": "source_evidence",
            "document_type": "utility_bill",
            "uploaded_by": "dev@example.com",
            "evidence_id": "EV-9",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"].startswith("document::ENG-1::")
    assert body["evidence_id"] == "EV-9"

    list_response = client.get("/v1/engagements/ENG-1/documents")
    assert list_response.status_code == 200
    assert any(item["document_id"] == body["document_id"] for item in list_response.json()["items"])
