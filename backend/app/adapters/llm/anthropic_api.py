"""The Anthropic API provider (``AI_PROVIDER=anthropic``, key in ``ANTHROPIC_API_KEY``).

Sends the model id as configured. Models in ``MODELS_WITH_FALLBACK`` also ask for the
server-side refusal fallback (Claude API only; Bedrock has none).
"""

from __future__ import annotations

from typing import Any

import anthropic

from backend.app.adapters.llm._claude_sdk import ClaudeSdkClient
from backend.app.adapters.llm.base import MAX_RETRIES, REQUEST_TIMEOUT_S, LlmNotConfigured
from backend.app.core.config import AiEffort, AiProvider, Settings

# "default" lets Anthropic pick the substitute model by refusal category. Claude Haiku 5.5
# has no fallback.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACK = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})


class AnthropicApiClient(ClaudeSdkClient):
    def __init__(self, sdk: anthropic.Anthropic, *, model: str, effort: AiEffort) -> None:
        super().__init__(sdk, model=model, effort=effort)

    @property
    def provider(self) -> AiProvider:
        return "anthropic"

    def _request_model(self) -> str:
        return self._model

    def _extra_request_args(self) -> dict[str, Any]:
        if self._model in MODELS_WITH_FALLBACK:
            return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        return {}


def build_sdk_client(settings: Settings, timeout_s: float = REQUEST_TIMEOUT_S,
                     max_retries: int = MAX_RETRIES) -> anthropic.Anthropic:
    if settings.anthropic_api_key is None:
        raise LlmNotConfigured("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=timeout_s,
        max_retries=max_retries,
        open_telemetry=False,
    )


def build_client(settings: Settings, *, timeout_s: float = REQUEST_TIMEOUT_S,
                 max_retries: int = MAX_RETRIES) -> AnthropicApiClient:
    return AnthropicApiClient(
        build_sdk_client(settings, timeout_s, max_retries), model=settings.ai_model, effort=settings.ai_effort
    )
