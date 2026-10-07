"""S1-BE-001: extraction-result/latest, download and preview."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.main import app
from backend.app.repositories.document_repository import InMemoryDocumentRepository
from backend.app.repositories.extraction_result_repository import (
    InMemoryExtractionResultRepository,
    JsonlExtractionResultRepository,
)
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.document_upload_service import DocumentUploadService
from backend.app.services.local_storage_service import LocalStorageService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.api.conftest import ORG_A, ORG_B

BILL = b"Fuel Type: Natural Gas\nTotal Usage: 120 therms\nService Period: 01/01/2024 - 01/31/2024\n"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
HTML = b"<html><script>alert(document.cookie)</script></html>"

# The fields `features/s1/adapters/fieldAdapter.ts` reads from each candidate.
ADAPTER_FIELDS = {"candidate_id", "evidence_id", "document_id", "field_name", "display_label",
                  "normalized_value", "unit", "confidence", "validation_flags", "source_reference"}


@pytest.fixture
def env(tmp_path: Path, act_as) -> Iterator[dict]:
    storage = LocalStorageService(tmp_path / "uploads")
    repository = InMemoryDocumentRepository()
    documents = DocumentUploadService(storage_service=storage, document_repository=repository,
                                      clock=lambda: "2026-01-01T00:00:00+00:00")
    results = InMemoryExtractionResultRepository()
    pipeline = PipelineOrchestrationService(pipeline_repository=InMemoryPipelineRunRepository(),
                                            extraction_result_repository=results)
    originals = (documents_api._upload_service, documents_api._pipeline_service, documents_api._storage_service)
    documents_api.configure_services(upload_service=documents, pipeline_service=pipeline, storage_service=storage)
    client = TestClient(app)

    def upload(name: str, body: bytes, mime: str, org=ORG_A, evidence_id: str | None = None) -> dict:
        act_as("org_member", org)
        data = {"evidence_id": evidence_id} if evidence_id else {}
        response = client.post("/v1/engagements/ENG-1/documents/upload", files={"file": (name, body, mime)},
                               data=data)
        assert response.status_code == 200, response.text
        return response.json()

    def process(document: dict, org=ORG_A, **payload) -> dict:
        act_as("org_member", org)
        response = client.post(f"/v1/documents/{document['document_id']}/pipeline/process", json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    try:
        yield {"client": client, "act_as": act_as, "upload": upload, "process": process, "storage": storage,
               "repository": repository, "results": results}
    finally:
        documents_api.configure_services(upload_service=originals[0], pipeline_service=originals[1],
                                         storage_service=originals[2])


def url(document: dict, what: str) -> str:
    return f"/v1/documents/{document['document_id']}/{what}"


# --- extraction-result/latest ---------------------------------------------------------------
def test_latest_extraction_result_matches_the_frontend_adapter(env: dict) -> None:
    doc = env["upload"]("bill.txt", BILL, "text/plain")
    processed = env["process"](doc, canonical_type_id_override="CT-S1-FUELQTY")

    response = env["client"].get(url(doc, "extraction-result/latest"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_id"] == doc["document_id"]
    assert body["evidence_id"] == doc["evidence_id"]
    assert body["canonical_type_id"] == "CT-S1-FUELQTY"
    assert body["pipeline_run_id"] == processed["pipeline_run"]["pipeline_run_id"]
    assert body["candidate_count"] == len(body["items"]) > 0
    assert body["items"] == processed["extraction_result"]["items"]
    for item in body["items"]:
        assert ADAPTER_FIELDS <= set(item), ADAPTER_FIELDS - set(item)
        assert item["document_id"] == doc["document_id"]
    quantity = next(i for i in body["items"] if i["field_name"] == "activity_quantity")
    assert quantity["normalized_value"] is not None and "120" in str(quantity["raw_value"])


def test_latest_is_the_most_recent_run(env: dict) -> None:
    doc = env["upload"]("bill.txt", BILL, "text/plain")
    env["process"](doc, canonical_type_id_override="CT-S1-FUELQTY")
    second = env["process"](doc, canonical_type_id_override="CT-S1-FUELQTY")
    body = env["client"].get(url(doc, "extraction-result/latest")).json()
    assert body["pipeline_run_id"] == second["pipeline_run"]["pipeline_run_id"]
    assert len(env["results"].list_by_document(doc["document_id"])) == 2


def test_a_halted_run_is_the_latest_result_with_no_candidates(env: dict) -> None:
    doc = env["upload"]("notes.txt", b"nothing to see here", "text/plain")
    processed = env["process"](doc)
    body = env["client"].get(url(doc, "extraction-result/latest")).json()
    assert body["pipeline_run_id"] == processed["pipeline_run"]["pipeline_run_id"]
    assert body["items"] == [] and body["candidate_count"] == 0


def test_no_result_before_processing_or_without_persisting(env: dict) -> None:
    doc = env["upload"]("bill.txt", BILL, "text/plain")
    assert env["client"].get(url(doc, "extraction-result/latest")).status_code == 404
    env["process"](doc, canonical_type_id_override="CT-S1-FUELQTY", persist_run=False)
    response = env["client"].get(url(doc, "extraction-result/latest"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Extraction result not found."


def test_results_are_stored_in_jsonl_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    service = PipelineOrchestrationService()
    assert isinstance(service._extraction_result_repository, JsonlExtractionResultRepository)
    service._extraction_result_repository.save({"document_id": "D", "items": []})
    assert (tmp_path / "local-data/extraction-results/extraction_results.jsonl").exists()
    assert service.list_extraction_results_by_document("D") == [{"document_id": "D", "items": []}]


# --- download / preview ---------------------------------------------------------------------
def test_download_is_an_attachment_with_the_original_bytes(env: dict) -> None:
    doc = env["upload"]("March bill.pdf", PDF, "application/pdf")
    response = env["client"].get(url(doc, "download"))
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-disposition"] == 'attachment; filename="March_bill.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "private, no-store"


def test_pdf_preview_is_inline_and_frameable_by_the_app_only(env: dict) -> None:
    doc = env["upload"]("bill.pdf", PDF, "application/pdf")
    response = env["client"].get(url(doc, "preview"))
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_image_preview_is_sandboxed(env: dict) -> None:
    doc = env["upload"]("meter.png", PNG, "image/png")
    response = env["client"].get(url(doc, "preview"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    csp = response.headers["content-security-policy"]
    assert "sandbox" in csp and "frame-ancestors 'self'" in csp and "default-src 'none'" in csp


def test_the_served_type_comes_from_the_bytes_not_the_upload(env: dict) -> None:
    # HTML claiming to be a PDF: never rendered as HTML, never previewed.
    doc = env["upload"]("bill.pdf", HTML, "application/pdf")
    assert env["client"].get(url(doc, "preview")).status_code == 415
    download = env["client"].get(url(doc, "download"))
    assert download.headers["content-type"] == "application/octet-stream"
    assert download.headers["content-disposition"].startswith("attachment;")
    # A real PDF uploaded as text/html is still served as a PDF.
    pdf = env["upload"]("x.html", PDF, "text/html")
    assert env["client"].get(url(pdf, "preview")).headers["content-type"] == "application/pdf"


@pytest.mark.parametrize(("name", "media"), [
    ("data.csv", "text/csv"),
    ("data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("page.html", "application/octet-stream"),
    ("logo.svg", "application/octet-stream"),
])
def test_other_files_download_but_do_not_preview(env: dict, name: str, media: str) -> None:
    doc = env["upload"](name, b"a,b\n1,2\n", "text/html")
    response = env["client"].get(url(doc, "download"))
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == media
    preview = env["client"].get(url(doc, "preview"))
    assert preview.status_code == 415
    assert preview.json()["detail"] == "Preview is not available for this file type."


def test_missing_file_is_404(env: dict) -> None:
    doc = env["upload"]("bill.pdf", PDF, "application/pdf")
    env["storage"].resolve_storage_uri(doc["storage_uri"]).unlink()
    for what in ("download", "preview"):
        response = env["client"].get(url(doc, what))
        assert response.status_code == 404
        assert response.json()["detail"] == "Stored document file is missing."


def test_a_record_pointing_into_another_orgs_folder_is_not_served(env: dict) -> None:
    theirs = env["upload"]("secret.pdf", PDF, "application/pdf", org=ORG_B)
    mine = env["upload"]("bill.pdf", PDF, "application/pdf")
    env["repository"].save({**mine, "storage_uri": theirs["storage_uri"]})  # e.g. a tampered record
    env["act_as"]("org_member", ORG_A)
    for what in ("download", "preview"):
        assert env["client"].get(url(mine, what)).status_code == 404


# --- auth and org scoping -------------------------------------------------------------------
def test_unknown_and_cross_org_documents_are_404(env: dict) -> None:
    doc = env["upload"]("bill.pdf", PDF, "application/pdf")
    env["process"](doc)
    client = env["client"]
    for what in ("extraction-result/latest", "download", "preview"):
        env["act_as"]("org_member", ORG_A)
        assert client.get(f"/v1/documents/DOC-NOPE/{what}").status_code == 404
        env["act_as"]("org_admin", ORG_B)
        response = client.get(url(doc, what))
        assert response.status_code == 404, what
        assert response.json()["detail"] == "Document not found."


def test_provider_admin_can_read_every_org(env: dict) -> None:
    doc = env["upload"]("bill.pdf", PDF, "application/pdf")
    env["process"](doc)
    env["act_as"]("provider_admin")
    for what in ("extraction-result/latest", "download", "preview"):
        assert env["client"].get(url(doc, what)).status_code == 200, what


def test_signed_out_is_401_on_both_mounts(env: dict) -> None:
    doc = env["upload"]("bill.pdf", PDF, "application/pdf")
    env["act_as"](None)
    for prefix in ("", "/api"):
        for what in ("extraction-result/latest", "download", "preview"):
            assert env["client"].get(prefix + url(doc, what)).status_code == 401
