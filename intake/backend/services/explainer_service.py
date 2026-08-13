"""Explain a question a second way when the canned explanation did not land.

intake/SPEC.md section 3: the "Not sure" path is canned explainer, then one
model rephrase, then escalate. This service owns the middle step - exactly one
call, per SPEC section 6.

If no model is configured, or the call fails, the client goes straight to the
escalation they would have reached anyway. Losing the rephrase costs a nicety;
it never costs them their place in the interview.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from intake.backend.adapters.llm import LLMClient, LLMError, TurnBudget, new_budget
from intake.backend.config import load_llm_config

REPHRASE_PROMPT = "rephrase_explainer"


class RephraseOutcome(BaseModel):
    available: bool
    explainer: str | None = None
    suggests_escalation: bool = False
    model_calls: list[dict] = []


class ExplainerService:
    def __init__(
        self,
        llm_client: LLMClient,
        org_repository: Any,
        site_repository: Any,
        question_content: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm_client
        self._orgs = org_repository
        self._sites = site_repository
        self._content = question_content
        self._config = config or load_llm_config()

    def rephrase(
        self,
        org_id: str,
        datapoint_id: str,
        scope_ref: str | None = None,
        budget: TurnBudget | None = None,
    ) -> RephraseOutcome:
        content = self._content.get(datapoint_id)
        if content is None:
            raise ValueError(f"{datapoint_id} is not an interview question.")

        budget = budget or new_budget(self._config)
        try:
            raw = self._llm.complete_json(
                REPHRASE_PROMPT,
                {
                    "question": content["question"],
                    "explainer": content["explainer"],
                    "context": self._context(org_id, scope_ref),
                },
                budget,
            )
        except LLMError:
            return RephraseOutcome(available=False, model_calls=budget.calls)

        text = str(raw.get("explainer") or "").strip()
        if not text:
            return RephraseOutcome(available=False, model_calls=budget.calls)

        return RephraseOutcome(
            available=True,
            explainer=text,
            suggests_escalation=bool(raw.get("suggests_escalation")),
            model_calls=budget.calls,
        )

    def _context(self, org_id: str, scope_ref: str | None) -> str:
        org = self._orgs.get(org_id) or {}
        context: dict[str, Any] = {"industry": org.get("industry_overlay_id")}
        if scope_ref:
            site = self._sites.get(scope_ref)
            if site:
                context["site_name"] = site.get("site_name")
                context["site_type"] = site.get("site_type")
        return json.dumps(context)
