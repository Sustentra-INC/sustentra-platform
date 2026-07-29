from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import expected_candidate_files, read_json


def test_candidate_expectation_files_are_loadable(golden_paths) -> None:
    files = expected_candidate_files(golden_paths)
    assert files

    for path in files:
        payload = read_json(path)
        assert payload["document_id"]
        assert payload.get("expected_fields") or payload.get("expected_records")
