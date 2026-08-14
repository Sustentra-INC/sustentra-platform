from backend.app.domain.verification_rule import RuntimeVerificationRule
from backend.app.services.verification_engine_service import VerificationEngineService


def test_guard_rule_passes_when_values_exist() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(_rule("G-001", rule_type="guard", applies_to=("S1-STC-010",)),),
        methodology_values=[_value("mv-001", "S1-STC-010", 28100)],
    )

    assert result["results"][0]["status"] == "passed"
    assert result["results"][0]["methodology_value_ids"] == ["mv-001"]


def test_gate_rule_fails_when_value_missing() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(_rule("GATE-001", rule_type="gate", applies_to=("S1-STC-010",)),),
        methodology_values=[],
    )

    assert result["results"][0]["status"] == "failed"
    assert "S1-STC-010" in (result["results"][0]["reason"] or "")


def test_confirm_rule_is_provisional() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(
            _rule(
                "CONFIRM-001",
                rule_type="guard",
                applies_to=("S1-STC-010",),
                status="CONFIRM",
                is_provisional=True,
            ),
        ),
        methodology_values=[_value("mv-001", "S1-STC-010", 28100)],
    )

    assert result["results"][0]["status"] == "provisional"


def test_limit_rule_cannot_verify() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(_rule("LIMIT-001", rule_type="limit", applies_to=("S1-STC-010",)),),
        methodology_values=[_value("mv-001", "S1-STC-010", 28100)],
    )

    assert result["results"][0]["status"] == "cannot_verify"


def test_recompute_rule_is_unsupported() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(_rule("REC-001", rule_type="recompute", applies_to=("S1-STC-010",)),),
        methodology_values=[_value("mv-001", "S1-STC-010", 28100)],
    )

    assert result["results"][0]["status"] == "unsupported"


def test_prose_only_rule_is_not_applicable() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(
            _rule(
                "PROSE-001",
                rule_type="guard",
                applies_to=(),
                unresolved=("Any row with a non-null Condition",),
            ),
        ),
        methodology_values=[],
    )

    assert result["results"][0]["status"] == "not_applicable"


def test_blank_values_do_not_satisfy_rule() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(_rule("G-001", rule_type="guard", applies_to=("S1-STC-010",)),),
        methodology_values=[_value("mv-001", "S1-STC-010", " ")],
    )

    assert result["results"][0]["status"] == "failed"


def test_status_counts() -> None:
    result = VerificationEngineService().evaluate(
        engagement_id="ENG-1",
        rules=(
            _rule("PASS", rule_type="guard", applies_to=("S1-STC-010",)),
            _rule("FAIL", rule_type="guard", applies_to=("S1-MOB-010",)),
            _rule("LIMIT", rule_type="limit", applies_to=("S1-STC-010",)),
        ),
        methodology_values=[_value("mv-001", "S1-STC-010", 28100)],
    )

    assert result["status_counts"] == {
        "cannot_verify": 1,
        "failed": 1,
        "passed": 1,
    }


def _rule(
    rule_id: str,
    *,
    rule_type: str,
    applies_to: tuple[str, ...],
    unresolved: tuple[str, ...] = (),
    status: str = "Active",
    is_provisional: bool = False,
) -> RuntimeVerificationRule:
    return RuntimeVerificationRule(
        rule_id=rule_id,
        layer="S1",
        rule_type=rule_type,
        assertion="completeness",
        applies_to=(*applies_to, *unresolved),
        grain_key="-",
        rule_expression="Synthetic rule expression",
        source="test",
        status=status,
        notes=None,
        is_provisional=is_provisional,
        resolvable_applies_to=applies_to,
        unresolved_applies_to=unresolved,
        source_workbook="rules.xlsx",
        source_sheet="Verification_Rules",
        source_row_number=2,
    )


def _value(methodology_value_id: str, field_id: str, value: object) -> dict:
    return {
        "methodology_value_id": methodology_value_id,
        "engagement_id": "ENG-1",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "methodology_field_id": field_id,
        "data_schema_field": "quantity_combusted",
        "grain": "fuel_record",
        "record_key": "record-1",
        "approved_value": value,
        "approved_unit": "MMBtu",
        "source_reference": {},
        "approved_evidence_id": "approved-001",
        "review_decision_id": "review-001",
        "value_origin": "approved_evidence",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
