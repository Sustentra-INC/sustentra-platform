from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import evaluate_normalization


def test_normalization_cases_are_evaluated(golden_paths) -> None:
    results = evaluate_normalization(golden_paths)
    assert results
    assert all(result["stage"] == "normalization" for result in results)
