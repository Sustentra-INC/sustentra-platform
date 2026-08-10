from backend.app.services.s2_gap_record_service import S2GapRecordService


def test_completeness_missing_and_unknown_conditions_emit_gaps() -> None:
    service = _service()
    records = service.from_completeness_result(
        {
            "engagement_id": "ENG-1",
            "results": [
                {"field_id": "S1-STC-010", "status": "missing_required"},
                {
                    "field_id": "S1-CND-010",
                    "status": "provisional_condition_unknown",
                },
                {"field_id": "S1-OK-010", "status": "complete"},
            ],
        }
    )

    assert len(records) == 2
    assert {record["substage"] for record in records} == {"completeness"}
    assert records[0]["stage"] == "S2"
    assert records[0]["severity"] == "high"


def test_verification_failures_emit_gaps_with_rule_id() -> None:
    service = _service()
    records = service.from_verification_result(
        {
            "results": [
                {
                    "rule_id": "RULE-001",
                    "status": "failed",
                    "applies_to": ["S1-STC-010"],
                    "assertion": "completeness",
                },
                {
                    "rule_id": "RULE-002",
                    "status": "passed",
                    "applies_to": ["S1-MOB-010"],
                    "assertion": "completeness",
                },
            ]
        },
        engagement_id="ENG-1",
    )

    assert len(records) == 1
    assert records[0]["substage"] == "verification"
    assert records[0]["rule_id"] == "RULE-001"
    assert records[0]["field_id"] == "S1-STC-010"


def test_derivation_non_derived_statuses_emit_gaps() -> None:
    service = _service()
    records = service.from_derivation_results(
        [
            {"field_id": "S1-DER-010", "status": "missing_dependency"},
            {"field_id": "S1-DER-020", "status": "derived"},
        ],
        engagement_id="ENG-1",
    )

    assert len(records) == 1
    assert records[0]["substage"] == "derivation"
    assert records[0]["gap_type"] == "derivation_missing_dependency"


def test_recompute_mismatch_emits_gap_but_match_does_not() -> None:
    service = _service()

    assert service.from_recompute_result(
        {"status": "matched"},
        engagement_id="ENG-1",
        field_id="S1-STC-040",
    ) == []

    records = service.from_recompute_result(
        {"status": "mismatch"},
        engagement_id="ENG-1",
        field_id="S1-STC-040",
    )

    assert len(records) == 1
    assert records[0]["substage"] == "recompute"
    assert records[0]["severity"] == "high"


def test_gap_record_ids_are_stable_for_same_inputs_and_clock() -> None:
    service = _service()
    first = service.from_recompute_result(
        {"status": "mismatch"},
        engagement_id="ENG-1",
        field_id="S1-STC-040",
    )[0]
    second = service.from_recompute_result(
        {"status": "mismatch"},
        engagement_id="ENG-1",
        field_id="S1-STC-040",
    )[0]

    assert first["gap_record_id"] == second["gap_record_id"]


def _service() -> S2GapRecordService:
    return S2GapRecordService(clock=lambda: "2026-01-01T00:00:00+00:00")
