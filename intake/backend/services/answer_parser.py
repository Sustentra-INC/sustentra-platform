"""Turn a client's free-text answer into structured fields (Phase D1).

The flow, per intake/SPEC.md sections 2 and 6:

    free text -> model proposes fields + confidence
              -> confident?  play the reading back for the client to confirm
              -> not confident?  ask one clarifying question
              -> still not confident?  escalate to a human

Three properties this module guarantees:

* **The model never writes state.** ``parse`` returns a proposal. The value only
  reaches the profile when the client confirms it and the normal answer path
  writes it, which keeps every existing validation in force.
* **Nothing invented survives.** A proposed value for a field with permitted
  values is rejected unless it is one of them; a field the question does not
  define is dropped. A model that hallucinates a field cannot smuggle it in.
* **Failure is safe.** If no model is configured, or the provider is down, the
  answer goes to a human rather than being guessed at or lost.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from intake.backend.adapters.llm import (
    LLMBudgetExceeded,
    LLMClient,
    LLMError,
    LLMUnavailable,
    TurnBudget,
    new_budget,
)
from intake.backend.config import load_llm_config
from intake.backend.services.field_options import permitted_values, resolve_options

PARSE_PROMPT = "parse_answer"

UNAVAILABLE_MESSAGE = (
    "We couldn't read that one automatically, so we've passed it to the Sustentra "
    "team. You'll have an answer within 24 hours. Let's keep going."
)
EXHAUSTED_MESSAGE = (
    "Thanks for trying - this one is fiddly, so we've passed it to the Sustentra "
    "team rather than keep asking. You'll have an answer within 24 hours."
)


class ParseOutcome(BaseModel):
    """What the caller should do next with a free-text answer."""

    status: str = Field(description="proposed | clarify | escalated")
    datapoint_id: str
    scope_ref: str | None = None
    proposal: dict = Field(default_factory=dict)
    summary: str | None = None
    confidence: float | None = None
    clarifying_question: str | None = None
    unresolved: list = Field(default_factory=list)
    dropped_fields: list[str] = Field(default_factory=list)
    message: str | None = None
    escalation: dict | None = None
    attempts: int = 0
    model_calls: list[dict] = Field(default_factory=list)


class AnswerParser:
    def __init__(
        self,
        llm_client: LLMClient,
        state_repository: Any,
        org_repository: Any,
        site_repository: Any,
        state_machine: Any,
        escalations: Any,
        question_content: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm_client
        self._states = state_repository
        self._orgs = org_repository
        self._sites = site_repository
        self._machine = state_machine
        self._escalations = escalations
        self._content = question_content
        self._config = config or load_llm_config()

    # -- public -------------------------------------------------------------

    def parse(
        self,
        org_id: str,
        datapoint_id: str,
        scope_ref: str | None,
        text: str,
        actor_id: str,
        settings: Any = None,
        budget: TurnBudget | None = None,
    ) -> ParseOutcome:
        content = self._content.get(datapoint_id)
        if content is None:
            raise ValueError(f"{datapoint_id} is not an interview question.")

        state = self._states.find(org_id, datapoint_id, scope_ref)
        if state is None:
            raise ValueError(f"No state for {datapoint_id} (scope {scope_ref!r}).")

        budget = budget or new_budget(self._config)
        fields = [resolve_options(field, settings) for field in content["fields"]]

        try:
            raw = self._llm.complete_json(
                PARSE_PROMPT,
                {
                    "question": content["question"],
                    "explainer": content["explainer"],
                    "field_spec": self._field_spec(content, fields),
                    "client_answer": text,
                    "context": self._context(org_id, scope_ref),
                },
                budget,
            )
        except (LLMUnavailable, LLMBudgetExceeded, LLMError) as exc:
            # No model, no budget, or a bad response: a person takes it from here.
            escalation = self._escalate(
                org_id, state, content, actor_id,
                trigger="failed_clarification",
                attempts=[{"answer": text, "problem": str(exc)}],
            )
            return ParseOutcome(
                status="escalated",
                datapoint_id=datapoint_id,
                scope_ref=scope_ref,
                message=UNAVAILABLE_MESSAGE,
                escalation=escalation,
                attempts=int(state.get("clarification_attempts", 0)),
                model_calls=budget.calls,
            )

        proposal, dropped = self._clean(raw.get("fields") or {}, fields)
        confidence = _as_confidence(raw.get("confidence"))
        threshold = float(self._config["confidence"]["accept_threshold"])
        max_attempts = int(self._config["confidence"]["max_clarification_attempts"])
        attempts = int(state.get("clarification_attempts", 0))

        if confidence >= threshold and proposal:
            return ParseOutcome(
                status="proposed",
                datapoint_id=datapoint_id,
                scope_ref=scope_ref,
                proposal=proposal,
                summary=str(raw.get("summary") or "").strip() or None,
                confidence=confidence,
                unresolved=list(raw.get("unresolved") or []),
                dropped_fields=dropped,
                attempts=attempts,
                model_calls=budget.calls,
            )

        # Not confident enough to show the client a reading.
        attempts += 1
        self._machine.record_clarification_attempt(state, actor_id=actor_id, attempts=attempts)

        if attempts >= max_attempts:
            escalation = self._escalate(
                org_id, state, content, actor_id,
                trigger="failed_clarification",
                attempts=[{"answer": text, "confidence": confidence}],
            )
            return ParseOutcome(
                status="escalated",
                datapoint_id=datapoint_id,
                scope_ref=scope_ref,
                confidence=confidence,
                unresolved=list(raw.get("unresolved") or []),
                dropped_fields=dropped,
                message=EXHAUSTED_MESSAGE,
                escalation=escalation,
                attempts=attempts,
                model_calls=budget.calls,
            )

        return ParseOutcome(
            status="clarify",
            datapoint_id=datapoint_id,
            scope_ref=scope_ref,
            confidence=confidence,
            clarifying_question=(
                str(raw.get("clarifying_question") or "").strip()
                or "Sorry - could you say a bit more about that?"
            ),
            unresolved=list(raw.get("unresolved") or []),
            dropped_fields=dropped,
            attempts=attempts,
            model_calls=budget.calls,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _field_spec(content: dict[str, Any], fields: list[dict[str, Any]]) -> str:
        """A compact description of what this question collects."""
        spec = []
        for field in fields:
            if field["input"] == "derived":
                continue
            entry: dict[str, Any] = {
                "field_id": field["field_id"],
                "label": field["label"],
                "type": field["input"],
                "required": bool(field.get("required")),
            }
            allowed = permitted_values(field)
            if allowed:
                entry["permitted_values"] = sorted(allowed)
            elif field.get("provisional"):
                entry["free_text"] = "no agreed list yet - pass the client's wording through"
            if field.get("help"):
                entry["help"] = field["help"]
            spec.append(entry)

        if content["answer_shape"] == "yes_no":
            spec.insert(
                0,
                {
                    "field_id": "present",
                    "label": "Is this present at all?",
                    "type": "yes_no",
                    "required": True,
                    "permitted_values": [True, False],
                },
            )
        return json.dumps(spec, indent=2)

    def _clean(
        self, proposed: dict[str, Any], fields: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[str]]:
        """Keep only fields this question defines, with values it permits."""
        by_id = {field["field_id"]: field for field in fields}
        cleaned: dict[str, Any] = {}
        dropped: list[str] = []

        for field_id, value in proposed.items():
            if field_id == "present":
                if value in (True, False):
                    cleaned["present"] = value
                else:
                    dropped.append(field_id)
                continue

            field = by_id.get(field_id)
            if field is None or field["input"] == "derived":
                dropped.append(field_id)  # the model invented it
                continue

            allowed = permitted_values(field)
            if allowed and str(value) not in allowed:
                dropped.append(field_id)  # not one of the permitted values
                continue

            cleaned[field_id] = value
        return cleaned, dropped

    def _context(self, org_id: str, scope_ref: str | None) -> str:
        org = self._orgs.get(org_id) or {}
        context = {
            "industry": org.get("industry_overlay_id"),
            "reporting_period": [
                org.get("reporting_period_start"),
                org.get("reporting_period_end"),
            ],
        }
        if scope_ref:
            site = self._sites.get(scope_ref)
            if site:
                context["site_name"] = site.get("site_name")
                context["site_type"] = site.get("site_type")
        return json.dumps(context)

    def _escalate(
        self,
        org_id: str,
        state: dict[str, Any],
        content: dict[str, Any],
        actor_id: str,
        trigger: str,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._escalations.open(
            org_id=org_id,
            datapoint_id=state["datapoint_id"],
            scope_ref=state.get("scope_ref"),
            trigger=trigger,
            question_label=content["question"],
            actor_id=actor_id,
            answer_attempts=attempts,
            seed_context=self._seed_context(org_id, state.get("scope_ref")),
        )

    def _seed_context(self, org_id: str, scope_ref: str | None) -> dict[str, Any]:
        org = self._orgs.get(org_id) or {}
        context = {
            "legal_name": org.get("legal_name"),
            "reporting_period_start": org.get("reporting_period_start"),
            "reporting_period_end": org.get("reporting_period_end"),
        }
        if scope_ref:
            site = self._sites.get(scope_ref)
            if site:
                context["site_name"] = site.get("site_name")
        return context


def _as_confidence(value: Any) -> float:
    """A missing or unreadable confidence is treated as no confidence."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, confidence))
