"""LLM port and adapters (intake Stage 2, Phase D).

The services depend on the ``LLMClient`` port, never on a provider. Three
adapters ship:

* ``DisabledLLMClient`` - the default. Raises ``LLMUnavailable`` so that no
  build, test or smoke run can make a paid call by accident. Callers treat this
  as "the model is not available" and fall back to asking a human, which is a
  safe outcome rather than a broken one.
* ``ScriptedLLMClient`` - returns canned responses for tests and smoke runs.
* ``OpenAIClient`` - the real thing, enabled only when the config says so and a
  key is present.

Two properties are enforced here rather than trusted to callers:

* A **per-turn call budget** (SPEC section 6: at most two calls per turn). The
  budget is an object passed into the call, so exceeding it raises instead of
  quietly costing money.
* **Every call is logged** with its prompt id, model and outcome, so an
  AI-derived answer can be traced later. The client's raw text is recorded
  because it is their own answer, already stored on the datapoint state.

The model never writes state and never chooses questions. It returns a proposal;
the application decides what to do with it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from intake.backend.config import load_llm_config
from intake.backend.services.prompt_library import get_prompt


class LLMError(Exception):
    """Base class for model problems."""


class LLMUnavailable(LLMError):
    """No model is configured, or the provider could not be reached."""


class LLMBudgetExceeded(LLMError):
    """The turn tried to make more model calls than SPEC section 6 permits."""


class LLMResponseError(LLMError):
    """The model returned something that was not usable JSON."""


@dataclass
class TurnBudget:
    """Counts model calls within one turn of the interview."""

    max_calls: int
    used: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def spend(self, prompt_id: str) -> None:
        if self.used >= self.max_calls:
            raise LLMBudgetExceeded(
                f"this turn already used {self.used} model call(s); "
                f"the limit is {self.max_calls} (SPEC section 6)"
            )
        self.used += 1

    def record(self, entry: dict[str, Any]) -> None:
        self.calls.append(entry)

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.used)


class LLMClient:
    """Port. Implementations return parsed JSON for a rendered prompt."""

    name = "port"

    def complete_json(
        self, prompt_id: str, variables: dict[str, Any], budget: TurnBudget
    ) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


class DisabledLLMClient(LLMClient):
    """The default. Makes no calls and says so plainly."""

    name = "disabled"

    def complete_json(
        self, prompt_id: str, variables: dict[str, Any], budget: TurnBudget
    ) -> dict[str, Any]:
        raise LLMUnavailable(
            "No language model is configured. Set INTAKE_LLM_ADAPTER=openai and "
            "OPENAI_API_KEY to enable it; until then free-text answers go to a human."
        )


class ScriptedLLMClient(LLMClient):
    """Deterministic responses for tests and smoke runs.

    Responses are keyed by prompt id; each call pops the next queued response,
    so a test can script a low-confidence parse followed by a better one.
    """

    name = "scripted"

    def __init__(self, responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._responses: dict[str, list[dict[str, Any]]] = {
            key: list(value) for key, value in (responses or {}).items()
        }
        self.calls: list[dict[str, Any]] = []

    def queue(self, prompt_id: str, response: dict[str, Any]) -> None:
        self._responses.setdefault(prompt_id, []).append(response)

    def complete_json(
        self, prompt_id: str, variables: dict[str, Any], budget: TurnBudget
    ) -> dict[str, Any]:
        budget.spend(prompt_id)
        # Render anyway: a prompt that cannot render is a bug worth catching in
        # tests, not only in production.
        rendered = get_prompt(prompt_id).render(variables)
        self.calls.append({"prompt_id": prompt_id, "rendered_chars": len(rendered)})

        queued = self._responses.get(prompt_id)
        if not queued:
            raise LLMUnavailable(f"no scripted response queued for {prompt_id!r}")
        response = queued.pop(0)
        budget.record({"prompt_id": prompt_id, "adapter": self.name, "ok": True})
        return response


class OpenAIClient(LLMClient):
    """Real calls, enabled only by explicit configuration."""

    name = "openai"

    def __init__(self, model: str, timeout_seconds: int, temperature: float = 0) -> None:
        self._model = model
        self._timeout = timeout_seconds
        self._temperature = temperature

    def complete_json(
        self, prompt_id: str, variables: dict[str, Any], budget: TurnBudget
    ) -> dict[str, Any]:
        budget.spend(prompt_id)
        rendered = get_prompt(prompt_id).render(variables)

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise LLMUnavailable("OPENAI_API_KEY is not set.")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise LLMUnavailable("the openai package is not installed") from exc

        started = time.monotonic()
        try:
            client = OpenAI(api_key=api_key, timeout=self._timeout)
            completion = client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": rendered}],
            )
            text = completion.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - network path
            budget.record(
                {"prompt_id": prompt_id, "adapter": self.name, "ok": False, "error": str(exc)}
            )
            raise LLMUnavailable(f"the model could not be reached: {exc}") from exc

        budget.record(
            {
                "prompt_id": prompt_id,
                "adapter": self.name,
                "model": self._model,
                "ok": True,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        )

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(f"{prompt_id}: model did not return JSON") from exc
        if not isinstance(payload, dict):
            raise LLMResponseError(f"{prompt_id}: model returned {type(payload).__name__}")
        return payload


def build_llm_client(config: dict[str, Any] | None = None) -> LLMClient:
    """Construct the configured client. Unknown adapters are an error."""
    config = config or load_llm_config()
    adapter = config.get("adapter", "disabled")

    if adapter == "disabled":
        return DisabledLLMClient()
    if adapter == "scripted":
        return ScriptedLLMClient()
    if adapter == "openai":
        return OpenAIClient(
            model=config["model"],
            timeout_seconds=int(config.get("timeout_seconds", 20)),
            temperature=float(config.get("temperature", 0)),
        )
    raise ValueError(
        f"unknown LLM adapter {adapter!r}. Known: disabled, scripted, openai."
    )


def new_budget(config: dict[str, Any] | None = None) -> TurnBudget:
    config = config or load_llm_config()
    return TurnBudget(max_calls=int(config.get("max_calls_per_turn", 2)))
