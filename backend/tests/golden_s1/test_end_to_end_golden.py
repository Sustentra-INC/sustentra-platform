from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import run_golden_s1


def test_golden_s1_report_generation(golden_paths, tmp_path) -> None:
    result = run_golden_s1(golden_paths.fixture_root, tmp_path / "golden-s1-results")
    summary = result["summary"]

    assert summary["total_checks"] > 0
    assert result["pipeline_results"]
    assert result["failure_analysis"]
    assert result["report"]
