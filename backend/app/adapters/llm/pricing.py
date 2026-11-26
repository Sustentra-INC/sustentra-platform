"""Prices (USD per million tokens), one table per provider, and the cost of a request.

A model without a price is refused (``UnknownModelError``), so switching ``AI_MODEL`` forces
these tables to be checked. The Anthropic API and Bedrock can differ; today both follow
Anthropic's list, and the Bedrock figure is an estimate (AWS bills at its own rates).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from backend.app.adapters.llm.base import LlmNotConfigured, TokenUsage
from backend.app.core.config import AiProvider

# On Bedrock the model id is "anthropic.<id>"; prices are keyed by the bare id.
BEDROCK_MODEL_PREFIX = "anthropic."


class UnknownModelError(LlmNotConfigured):
    """A model with no entry in the provider's price table."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal


def _usd(input: str, output: str, cache_read: str, cache_write_5m: str, cache_write_1h: str) -> ModelPrice:
    return ModelPrice(Decimal(input), Decimal(output), Decimal(cache_read), Decimal(cache_write_5m),
                      Decimal(cache_write_1h))


# platform.claude.com/docs/en/about-claude/pricing, read 2026-10-26. Re-check on any change.
# Claude Opus 5.5 and Claude Sonnet 5.5 read the cache at 0.05x input, the others at 0.1x.
ANTHROPIC_PRICES: Mapping[str, ModelPrice] = {
    "claude-opus-5-5": _usd("4", "20", "0.20", "5", "8"),
    "claude-sonnet-5-5": _usd("2", "10", "0.10", "2.50", "4"),
    "claude-haiku-5-5": _usd("0.10", "0.50", "0.01", "0.125", "0.20"),
    # Server-side fallback targets: a declined request can be served by one of these.
    "claude-opus-5": _usd("5", "25", "0.50", "6.25", "10"),
    "claude-opus-4-8": _usd("5", "25", "0.50", "6.25", "10"),
    "claude-sonnet-5": _usd("2", "10", "0.20", "2.50", "4"),
}
# Claude Haiku 5.5 bills a request whose prompt (input + cache reads + cache writes) is
# over 100,000 tokens at a second rate card.
LONG_PROMPT_TOKENS = 100_000
ANTHROPIC_LONG_PROMPT_PRICES: Mapping[str, ModelPrice] = {
    "claude-haiku-5-5": _usd("0.50", "2.50", "0.05", "0.625", "1"),
}

# Bedrock: no separate rate card known yet, so the same figures; edit here when AWS differs.
BEDROCK_PRICES: Mapping[str, ModelPrice] = dict(ANTHROPIC_PRICES)
BEDROCK_LONG_PROMPT_PRICES: Mapping[str, ModelPrice] = dict(ANTHROPIC_LONG_PROMPT_PRICES)

PRICES: Mapping[AiProvider, Mapping[str, ModelPrice]] = {
    "anthropic": ANTHROPIC_PRICES,
    "bedrock": BEDROCK_PRICES,
}
LONG_PROMPT_PRICES: Mapping[AiProvider, Mapping[str, ModelPrice]] = {
    "anthropic": ANTHROPIC_LONG_PROMPT_PRICES,
    "bedrock": BEDROCK_LONG_PROMPT_PRICES,
}


def canonical_model(model: str) -> str:
    """'anthropic.claude-sonnet-5-5' (Bedrock) -> 'claude-sonnet-5-5'."""
    model = model.strip()
    return model[len(BEDROCK_MODEL_PREFIX):] if model.startswith(BEDROCK_MODEL_PREFIX) else model


def price_for(provider: AiProvider, model: str, *, prompt_tokens: int = 0) -> ModelPrice:
    model = canonical_model(model)
    table = PRICES[provider]
    if model not in table:
        raise UnknownModelError(f"No price for model {model!r} on {provider}: add it to pricing.py first.")
    long_prompt = LONG_PROMPT_PRICES[provider]
    if prompt_tokens > LONG_PROMPT_TOKENS and model in long_prompt:
        return long_prompt[model]
    return table[model]


def cost_microusd(provider: AiProvider, model: str, usage: TokenUsage) -> int:
    """Cost of one request in micro-USD (USD x 1,000,000), rounded half up."""
    price = price_for(provider, model, prompt_tokens=usage.prompt_tokens)
    # USD per million tokens x tokens = micro-USD.
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_5m_tokens * price.cache_write_5m
        + usage.cache_write_1h_tokens * price.cache_write_1h
    )
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))
