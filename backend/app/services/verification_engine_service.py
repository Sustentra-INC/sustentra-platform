"""Verification engine v0 for Subsystem 2 PR11."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from backend.app.domain.verification_rule import RuntimeVerificationRule

VerificationStatus = Literal[
    "passed",
    "failed",
    "not_applicable",
    "provisional",
    "unsupported",
    "cannot_verify",
]

EXECUTABLE_RULE_TYPES = {"guard", "gate", "invariant"}
LIMIT_RULE_TYPES = {"limit"}


@dataclass(frozen=True)
class VerificationRuleResult:
    rule_id: str
    rule_type: str | None
    assertion: str | None
    status: VerificationStatus
    applies_to: tuple[str, ...]
    methodology_value_ids: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "assertion": self.assertion,
            "status": self.status,
            "applies_to": list(self.applies_to),
            "methodology_value_ids": list(self.methodology_value_ids),
            "reason": self.reason,
        }


class VerificationEngineService:
    """Executes the safest verification rule subset.

    PR11 does not evaluate arbitrary Rule_Expression text. It checks whether
    concrete Applies_To fields have methodology values for simple guard/gate/
    invariant rules, marks CONFIRM rules provisional, and reports limit rules as
    cannot_verify until supporting evidence semantics are defined.
    """

    def evaluate(
        self,
        *,
        engagement_id: str,
        rules: tuple[RuntimeVerificationRule, ...],
        methodology_values: list[dict],
    ) -> dict:
        if not engagement_id or not engagement_id.strip():
            raise ValueError("engagement_id is required.")
        values_by_field = self._index_values(methodology_values)
        results = [
            self._evaluate_rule(rule, values_by_field)
            for rule in rules
        ]
        status_counts = Counter(result.status for result in results)
        return {
            "engagement_id": engagement_id,
            "status_counts": dict(sorted(status_counts.items())),
            "results": [result.to_dict() for result in results],
        }

    def _evaluate_rule(
        self,
        rule: RuntimeVerificationRule,
        values_by_field: dict[str, list[dict]],
    ) -> VerificationRuleResult:
        if rule.is_provisional:
            return _result(
                rule,
                status="provisional",
                reason="CONFIRM rule requires ESG confirmation before execution",
            )

        rule_type = (rule.rule_type or "").strip().casefold()
        if not rule.resolvable_applies_to:
            return _result(
                rule,
                status="not_applicable" if rule.unresolved_applies_to else "unsupported",
                reason="rule has no concrete Applies_To methodology fields",
            )

        if rule_type in LIMIT_RULE_TYPES:
            return _result(
                rule,
                status="cannot_verify",
                methodology_value_ids=_value_ids(rule, values_by_field),
                reason="limit rules require evidence semantics not available in PR11",
            )

        if rule_type not in EXECUTABLE_RULE_TYPES:
            return _result(
                rule,
                status="unsupported",
                methodology_value_ids=_value_ids(rule, values_by_field),
                reason=f"rule_type '{rule.rule_type}' is not executable in PR11",
            )

        missing = [
            field_id
            for field_id in rule.resolvable_applies_to
            if not values_by_field.get(field_id)
        ]
        if missing:
            return _result(
                rule,
                status="failed",
                methodology_value_ids=_value_ids(rule, values_by_field),
                reason=f"missing methodology value(s): {missing}",
            )
        return _result(
            rule,
            status="passed",
            methodology_value_ids=_value_ids(rule, values_by_field),
            reason="all concrete Applies_To fields have methodology values",
        )

    @staticmethod
    def _index_values(methodology_values: list[dict]) -> dict[str, list[dict]]:
        indexed: defaultdict[str, list[dict]] = defaultdict(list)
        for value in methodology_values:
            field_id = value.get("methodology_field_id")
            value_id = value.get("methodology_value_id")
            if field_id and value_id and _has_populated_value(value.get("approved_value")):
                indexed[str(field_id)].append(value)
        return indexed


def _result(
    rule: RuntimeVerificationRule,
    *,
    status: VerificationStatus,
    methodology_value_ids: tuple[str, ...] = (),
    reason: str | None,
) -> VerificationRuleResult:
    return VerificationRuleResult(
        rule_id=rule.rule_id,
        rule_type=rule.rule_type,
        assertion=rule.assertion,
        status=status,
        applies_to=rule.resolvable_applies_to,
        methodology_value_ids=methodology_value_ids,
        reason=reason,
    )


def _value_ids(
    rule: RuntimeVerificationRule,
    values_by_field: dict[str, list[dict]],
) -> tuple[str, ...]:
    return tuple(
        str(value["methodology_value_id"])
        for field_id in rule.resolvable_applies_to
        for value in values_by_field.get(field_id, ())
    )


def _has_populated_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True
