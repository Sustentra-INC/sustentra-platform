"""Pick the AI provider from the settings (``AI_PROVIDER``)."""

from __future__ import annotations

from backend.app.adapters.llm import anthropic_api, bedrock
from backend.app.adapters.llm.base import MAX_RETRIES, REQUEST_TIMEOUT_S, LlmClient
from backend.app.adapters.llm.pricing import price_for
from backend.app.core.config import Settings, get_settings


def get_llm(settings: Settings | None = None, *, timeout_s: float = REQUEST_TIMEOUT_S,
            max_retries: int = MAX_RETRIES) -> LlmClient | None:
    """The configured AI client, or None when AI_PROVIDER=anthropic has no key.

    Raises UnknownModelError for an AI_MODEL without a price, and LlmNotConfigured when
    Bedrock has no AWS region. It does not look at AI_SUGGESTIONS_ENABLED or at the
    organization's opt-in: the routes check those before they ask for a client.
    """
    settings = settings or get_settings()
    price_for(settings.ai_provider, settings.ai_model)
    if settings.ai_provider == "bedrock":
        return bedrock.build_client(settings, timeout_s=timeout_s, max_retries=max_retries)
    if settings.anthropic_api_key is None:
        return None
    return anthropic_api.build_client(settings, timeout_s=timeout_s, max_retries=max_retries)
