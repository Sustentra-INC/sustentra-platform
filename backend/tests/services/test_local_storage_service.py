from pathlib import Path

import pytest

from backend.app.services.local_storage_service import LocalStorageService


def test_save_upload_stores_bytes_and_creates_parent_dirs(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")

    result = service.save_upload(
        file_name="sample-bill.pdf",
        content=b"demo-bytes",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    resolved = service.resolve_storage_uri(result["storage_uri"])
    assert resolved.exists()
    assert resolved.is_file()
    assert resolved.parent.exists()
    assert resolved.read_bytes() == b"demo-bytes"


def test_save_upload_returns_relative_storage_uri(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")
    result = service.save_upload(
        file_name="sample.txt",
        content=b"abc",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    storage_uri = result["storage_uri"]
    assert not Path(storage_uri).is_absolute()


def test_resolve_storage_uri_returns_path_inside_root(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")
    result = service.save_upload(
        file_name="sample.txt",
        content=b"abc",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    resolved = service.resolve_storage_uri(result["storage_uri"])
    assert resolved.is_relative_to((tmp_path / "uploads").resolve())


def test_save_upload_rejects_empty_content(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")
    with pytest.raises(ValueError):
        service.save_upload(
            file_name="sample.txt",
            content=b"",
            engagement_id="ENG-1",
            evidence_id="EV-1",
            document_id="DOC-1",
        )


def test_save_upload_sanitizes_unsafe_file_name(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")

    result = service.save_upload(
        file_name="../unsafe/..\\evil bill?.pdf",
        content=b"abc",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    assert "/" not in result["stored_file_name"]
    assert "\\" not in result["stored_file_name"]
    assert result["stored_file_name"].endswith(".pdf")


def test_resolve_storage_uri_prevents_path_traversal(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")
    with pytest.raises(ValueError):
        service.resolve_storage_uri("../outside.txt")


def test_save_upload_does_not_overwrite_existing_files(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")

    first = service.save_upload(
        file_name="sample.pdf",
        content=b"first",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )
    second = service.save_upload(
        file_name="sample.pdf",
        content=b"second",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    assert first["stored_file_name"] != second["stored_file_name"]
    assert service.resolve_storage_uri(first["storage_uri"]).read_bytes() == b"first"
    assert service.resolve_storage_uri(second["storage_uri"]).read_bytes() == b"second"


def test_exists_returns_true_for_saved_file_and_false_otherwise(tmp_path: Path):
    service = LocalStorageService(tmp_path / "uploads")
    result = service.save_upload(
        file_name="sample.txt",
        content=b"abc",
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
    )

    assert service.exists(result["storage_uri"]) is True
    assert service.exists("uploads/ENG-1/EV-1/DOC-1/missing.txt") is False
