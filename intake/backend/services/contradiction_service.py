"""Detect answers that conflict with what the client already told us.

intake/SPEC.md section 3 lists a contradiction as an escalation trigger. This is
deliberately NOT an LLM judgment: the rules live in
``intake/config/contradictions.json`` and are evaluated by the same
deterministic predicate engine that decides applicability. A model that
occasionally imagines a conflict would send clients pointless questions, and one
that occasionally misses a real one would let a wrong inventory through.

Rules are scoped to a single data point, so checking an answer is cheap: only
the rules registered against that data point are evaluated.
"""

from __future__ import annotations

from typing import Any

from intake.backend.config import load_contradiction_rules
from intake.backend.services.applicability_service import ApplicabilityService


class ContradictionService:
    def __init__(
        self,
        applicability: ApplicabilityService,
        rules: dict[str, Any] | None = None,
    ) -> None:
        self._applicability = applicability
        self._rules = (rules or load_contradiction_rules())["rules"]

    @property
    def rules(self) -> dict[str, Any]:
        return self._rules

    def rules_for(self, datapoint_id: str) -> dict[str, Any]:
        return {
            name: rule
            for name, rule in self._rules.items()
            if rule["datapoint_id"] == datapoint_id
        }

    def check(
        self,
        state: dict[str, Any],
        profile: dict[str, Any],
        states: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """The first contradiction this answer raises, or None.

        Returns the rule name and the plain-language message to show the client,
        so the caller never has to compose one.
        """
        for name, rule in self.rules_for(state["datapoint_id"]).items():
            evaluator = ApplicabilityService(
                {"conditions": {name: {"predicate": rule["predicate"]}}}
            )
            if evaluator.is_applicable(
                name,
                profile=profile,
                states=states,
                scope_ref=state.get("scope_ref"),
                self_state=state,
            ):
                return {
                    "rule": name,
                    "description": rule["description"],
                    "client_message": rule["client_message"],
                }
        return None
