"""Deterministic applicability evaluation (intake Stage 2).

Answers the question "does this data point apply to this client, at this site?"
using the predicates in ``intake/config/applicability.json``. Plain code with an
explicit allow-list of operators - never an LLM, per intake/SPEC.md section 6,
and never ``eval``.

An unknown operator is an error rather than a silent false: a mistyped rule
should fail loudly, not quietly drop a question the client should have answered.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from intake.backend.config import REPO_ROOT

APPLICABILITY_PATH = REPO_ROOT / "intake/config/applicability.json"

OPERATORS = {"always", "all", "any", "not", "profile", "answer", "self_answer"}


@lru_cache(maxsize=1)
def load_applicability() -> dict[str, Any]:
    return json.loads(APPLICABILITY_PATH.read_text(encoding="utf-8"))


def reset_cache() -> None:
    load_applicability.cache_clear()


class ApplicabilityError(Exception):
    """Raised when a condition or operator is not defined."""


class ApplicabilityService:
    """Evaluates applicability conditions against an org's profile and answers."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or load_applicability()

    @property
    def conditions(self) -> dict[str, Any]:
        return self._config["conditions"]

    def is_applicable(
        self,
        condition_ref: str,
        profile: dict[str, Any],
        states: list[dict[str, Any]],
        scope_ref: str | None = None,
        self_state: dict[str, Any] | None = None,
    ) -> bool:
        """True when ``condition_ref`` holds for this org (and site, if scoped)."""
        condition = self.conditions.get(condition_ref)
        if condition is None:
            raise ApplicabilityError(
                f"Unknown applicability condition {condition_ref!r}. "
                f"Known: {sorted(self.conditions)}"
            )
        return self._evaluate(
            condition["predicate"],
            profile=profile,
            states=states,
            scope_ref=scope_ref,
            self_state=self_state,
            condition_ref=condition_ref,
        )

    # -- evaluation ---------------------------------------------------------

    def _evaluate(
        self,
        predicate: dict[str, Any],
        profile: dict[str, Any],
        states: list[dict[str, Any]],
        scope_ref: str | None,
        self_state: dict[str, Any] | None,
        condition_ref: str,
    ) -> bool:
        if not isinstance(predicate, dict) or len(predicate) != 1:
            raise ApplicabilityError(
                f"{condition_ref}: a predicate must be a single-operator object, got {predicate!r}"
            )
        (operator, operand), = predicate.items()
        if operator not in OPERATORS:
            raise ApplicabilityError(
                f"{condition_ref}: unknown operator {operator!r}. Known: {sorted(OPERATORS)}"
            )

        recurse = lambda child: self._evaluate(  # noqa: E731 - local alias keeps calls readable
            child, profile, states, scope_ref, self_state, condition_ref
        )

        if operator == "always":
            return bool(operand)
        if operator == "all":
            return all(recurse(child) for child in operand)
        if operator == "any":
            return any(recurse(child) for child in operand)
        if operator == "not":
            return not recurse(operand)
        if operator == "profile":
            return self._compare(profile.get(operand["field"]), operand)
        if operator == "self_answer":
            value = (self_state or {}).get("value") or {}
            return self._compare(value.get(operand["field"]), operand)
        return self._answer_matches(operand, states, scope_ref)

    def _answer_matches(
        self, operand: dict[str, Any], states: list[dict[str, Any]], scope_ref: str | None
    ) -> bool:
        scope = operand.get("scope", "org_wide")
        if scope not in {"same_site", "org_wide"}:
            raise ApplicabilityError(f"unknown answer scope {scope!r}")

        candidates = [
            state for state in states if state.get("datapoint_id") == operand["datapoint_id"]
        ]
        if scope == "same_site":
            # An org-grain answer (scope_ref None) still counts for a site question.
            candidates = [
                state
                for state in candidates
                if state.get("scope_ref") == scope_ref or state.get("scope_ref") is None
            ]

        for state in candidates:
            value = state.get("value") or {}
            if operand["field"] in value and self._compare(value[operand["field"]], operand):
                return True
        return False

    @staticmethod
    def _compare(actual: Any, operand: dict[str, Any]) -> bool:
        if "equals" in operand:
            return actual == operand["equals"]
        if "in" in operand:
            return actual in operand["in"]
        if "is_set" in operand:
            return (actual is not None) == bool(operand["is_set"])
        raise ApplicabilityError(f"predicate needs one of equals/in/is_set, got {operand!r}")

    # -- diagnostics --------------------------------------------------------

    def unresolved_conditions(self) -> dict[str, Any]:
        """Conditions whose input nothing currently supplies (flagged, not hidden)."""
        return {
            name: condition["unresolved"]
            for name, condition in self.conditions.items()
            if "unresolved" in condition
        }
