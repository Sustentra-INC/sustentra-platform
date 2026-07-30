from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import expected_documents


def test_manifest_files_exist(golden_paths) -> None:
    documents = expected_documents(golden_paths)
    assert documents, "expected at least one golden S1 manifest document"

    missing = []
    for document in documents:
        path = golden_paths.fixture_root / "raw_documents" / "docx" / document["filename"]
        if not path.exists():
            missing.append(str(path))

    assert missing == []


def test_manifest_document_ids_are_stable_and_unique(golden_paths) -> None:
    document_ids = [document["document_id"] for document in expected_documents(golden_paths)]
    assert all(document_ids)
    assert len(document_ids) == len(set(document_ids))
