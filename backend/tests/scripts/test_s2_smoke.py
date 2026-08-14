from backend.scripts.s2_smoke import run_smoke


def test_s2_smoke_runs_against_checked_in_reference_data() -> None:
    result = run_smoke()

    assert result["summary"]["engagement_id"] == "ENG-SMOKE-001"
    assert result["summary"]["field_value_count"] == 3
    assert result["summary"]["verification_result_count"] >= 1
    assert result["summary"]["gap_record_count"] == len(result["gap_records"])
