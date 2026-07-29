from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import GROUP_TO_CANONICAL_TYPE, read_json


def test_classification_expectations_report_current_config_gaps(golden_paths) -> None:
    data = read_json(golden_paths.fixture_root / "stage_3_classification" / "classification_expected.json")
    groups = {item["expected_classification_group"] for item in data["documents"]}
    mapped = sorted(group for group in groups if group in GROUP_TO_CANONICAL_TYPE)
    unmapped = sorted(group for group in groups if group not in GROUP_TO_CANONICAL_TYPE)

    assert "fuel_quantity_document" in mapped
    assert unmapped
