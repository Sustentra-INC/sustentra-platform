from backend.app.services.condition_evaluator import ConditionEvaluator


def test_blank_condition_is_applicable() -> None:
    result = ConditionEvaluator().evaluate(None, {})

    assert result.status == "applicable"
    assert result.reason == "blank condition"


def test_equals_true_is_applicable() -> None:
    result = ConditionEvaluator().evaluate(
        "ORG-010 = operational_control",
        {"ORG-010": "Operational_Control"},
    )

    assert result.status == "applicable"


def test_equals_false_is_not_applicable() -> None:
    result = ConditionEvaluator().evaluate(
        "ORG-010 = financial_control",
        {"ORG-010": "operational_control"},
    )

    assert result.status == "not_applicable"


def test_in_operator() -> None:
    result = ConditionEvaluator().evaluate(
        "S1-STC-010 IN (natural_gas, diesel)",
        {"S1-STC-010": "Diesel"},
    )

    assert result.status == "applicable"


def test_and_or_precedence() -> None:
    result = ConditionEvaluator().evaluate(
        "A = yes OR B = yes AND C = yes",
        {"A": "no", "B": "yes", "C": "yes"},
    )

    assert result.status == "applicable"


def test_parentheses() -> None:
    result = ConditionEvaluator().evaluate(
        "(A = yes OR B = yes) AND C = yes",
        {"A": "no", "B": "yes", "C": "no"},
    )

    assert result.status == "not_applicable"


def test_missing_runtime_value_is_unknown() -> None:
    result = ConditionEvaluator().evaluate(
        "S2-MTR-010 = market",
        {},
    )

    assert result.status == "unknown"
    assert "S2-MTR-010" in (result.reason or "")


def test_none_runtime_value_is_unknown() -> None:
    result = ConditionEvaluator().evaluate(
        "S2-MTR-010 = market",
        {"S2-MTR-010": None},
    )

    assert result.status == "unknown"


def test_unsupported_operator_is_reported() -> None:
    result = ConditionEvaluator().evaluate(
        "S2-MTR-010 > 100",
        {"S2-MTR-010": 101},
    )

    assert result.status == "unsupported_condition"


def test_unbalanced_parentheses_are_unsupported() -> None:
    result = ConditionEvaluator().evaluate(
        "(A = yes OR B = yes",
        {"A": "yes", "B": "no"},
    )

    assert result.status == "unsupported_condition"
