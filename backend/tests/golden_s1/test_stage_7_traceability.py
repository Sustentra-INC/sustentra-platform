from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import read_json


def test_traceability_expectations_are_loadable(golden_paths) -> None:
    payload = read_json(golden_paths.fixture_root / "stage_7_evidence_validation" / "evidence_expected.json")
    assert payload["documents"]
    assert all("source_reference_requirements" in item for item in payload["documents"])
