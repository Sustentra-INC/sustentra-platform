"""Claude, the model behind AI suggestions (runbook: docs/backend_services.md).

Nothing calls this yet. Later PRs build prompts on top of ``ClaudeClient`` and inject a
fake one in tests; no test talks to the network.

* Provider (``AI_PROVIDER``): ``anthropic`` uses ``ANTHROPIC_API_KEY``; ``bedrock`` signs
  with the instance role in ``AWS_REGION`` and needs no key (not yet tried against live
  Bedrock, and the app-host role has no Bedrock permission today).
* One call shape, ``structured()``: one request whose reply must match a pydantic model
  (structured outputs, ``output_config.format``). ``stop_reason`` is checked before the
  content is read, so a refusal or a cut-off reply gives no output, never a partial one.
* Cost: ``PRICES`` (USD per million tokens, Anthropic's price list) and ``cost_microusd``.
  A model without a price is refused, so switching ``AI_MODEL`` forces this table to be
  checked. On Bedrock the figure is an estimate: AWS bills at its own rates.
* Privacy: the key stays a ``SecretStr`` until the SDK client is built. Nothing here logs
  the key, prompts or replies, and the SDK's OpenTelemetry spans are turned off.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Generic, Literal, Protocol, TypeVar

import anthropic
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaFallbackMessageIterationUsage,
    BetaMessage,
    BetaMessageIterationUsage,
    BetaUsage,
)
from pydantic import BaseModel, ValidationError

from backend.app.core.config import AiEffort, AiProvider, Settings, get_settings

logger = logging.getLogger(__name__)
# At DEBUG the SDK logs whole request bodies, i.e. prompts and document text. Keep its
# logger at INFO even if the root level is lowered (and never set ANTHROPIC_LOG).
logging.getLogger("anthropic").setLevel(logging.INFO)

ModelT = TypeVar("ModelT", bound=BaseModel)

# A document suggestion is one synchronous request: fail fast, retry once.
REQUEST_TIMEOUT_S = 90.0
MAX_RETRIES = 1
BEDROCK_MODEL_PREFIX = "anthropic."

# Server-side refusal fallback, Claude API only (Bedrock has none). "default" lets
# Anthropic pick the substitute model by refusal category. Claude Haiku 5.5 has no fallback.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACK = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})


class AiNotConfiguredError(RuntimeError):
    """The settings cannot run AI here (no AWS region for Bedrock, a model with no price...)."""


class UnknownModelError(AiNotConfiguredError):
    """A model with no entry in PRICES."""


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
PRICES: Mapping[str, ModelPrice] = {
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
LONG_PROMPT_PRICES: Mapping[str, ModelPrice] = {
    "claude-haiku-5-5": _usd("0.50", "2.50", "0.05", "0.625", "1"),
}


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_5m_tokens + self.cache_write_1h_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_5m_tokens + other.cache_write_5m_tokens,
            self.cache_write_1h_tokens + other.cache_write_1h_tokens,
        )


def canonical_model(model: str) -> str:
    """'anthropic.claude-sonnet-5-5' (Bedrock) -> 'claude-sonnet-5-5'."""
    model = model.strip()
    return model[len(BEDROCK_MODEL_PREFIX):] if model.startswith(BEDROCK_MODEL_PREFIX) else model


def price_for(model: str, *, prompt_tokens: int = 0) -> ModelPrice:
    model = canonical_model(model)
    if model not in PRICES:
        raise UnknownModelError(f"No price for model {model!r}: add it to PRICES in claude.py first.")
    if prompt_tokens > LONG_PROMPT_TOKENS and model in LONG_PROMPT_PRICES:
        return LONG_PROMPT_PRICES[model]
    return PRICES[model]


def cost_microusd(model: str, usage: TokenUsage) -> int:
    """Cost of one request in micro-USD (USD x 1,000,000), rounded half up."""
    price = price_for(model, prompt_tokens=usage.prompt_tokens)
    # USD per million tokens x tokens = micro-USD.
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_5m_tokens * price.cache_write_5m
        + usage.cache_write_1h_tokens * price.cache_write_1h
    )
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))


# "ok": output is set. "refused": the model declined (stop_reason refusal).
# "incomplete": the reply stopped early (max_tokens or another stop reason).
# "invalid": the reply did not match the output model.
Outcome = Literal["ok", "refused", "incomplete", "invalid"]


@dataclass(frozen=True)
class StructuredReply(Generic[ModelT]):
    outcome: Outcome
    output: ModelT | None
    # The model that served the reply; a server-side fallback can differ from the one asked.
    model: str
    usage: TokenUsage
    # None only when a served model has no price (logged).
    cost_microusd: int | None
    request_id: str | None
    stop_reason: str | None
    refusal_category: str | None = None


class ClaudeClient(Protocol):
    @property
    def provider(self) -> AiProvider: ...

    @property
    def model(self) -> str: ...

    def structured(
        self,
        *,
        system: str,
        content: str | Iterable[BetaContentBlockParam],
        output_type: type[ModelT],
        max_tokens: int,
    ) -> StructuredReply[ModelT]: ...


SdkClient = anthropic.Anthropic | anthropic.AnthropicBedrockMantle


class SdkClaude:
    """``ClaudeClient`` over the official ``anthropic`` SDK (Claude API or Bedrock)."""

    def __init__(self, sdk: SdkClient, *, provider: AiProvider, model: str, effort: AiEffort) -> None:
        self._model = canonical_model(model)
        price_for(self._model)  # refuse a model we cannot price
        self._sdk = sdk
        self._provider: AiProvider = provider
        self._effort: AiEffort = effort

    @property
    def provider(self) -> AiProvider:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def structured(
        self,
        *,
        system: str,
        content: str | Iterable[BetaContentBlockParam],
        output_type: type[ModelT],
        max_tokens: int,
    ) -> StructuredReply[ModelT]:
        # transform_schema makes the pydantic schema acceptable to structured outputs
        # (additionalProperties false, unsupported limits moved into descriptions). Those
        # limits are enforced again by model_validate_json below.
        schema = anthropic.transform_schema(output_type.model_json_schema())
        extra: dict[str, Any] = {}
        if self._provider == "anthropic" and self._model in MODELS_WITH_FALLBACK:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        response = self._sdk.beta.messages.create(
            model=self._request_model(),
            max_tokens=max_tokens,
            # Thinking is adaptive by default on the 5.5 models; effort is the only dial.
            output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            **extra,
        )
        return _reply(response, output_type, requested_model=self._model)

    def _request_model(self) -> str:
        return BEDROCK_MODEL_PREFIX + self._model if self._provider == "bedrock" else self._model


def build_sdk_client(settings: Settings) -> SdkClient:
    if settings.ai_provider == "bedrock":
        try:
            # Region from AWS_REGION; credentials from the default chain (the instance role).
            return anthropic.AnthropicBedrockMantle(
                timeout=REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES, open_telemetry=False
            )
        except anthropic.AnthropicError as exc:
            raise AiNotConfiguredError(f"Bedrock is not configured: {exc}") from exc
    if settings.anthropic_api_key is None:
        raise AiNotConfiguredError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=REQUEST_TIMEOUT_S,
        max_retries=MAX_RETRIES,
        open_telemetry=False,
    )


def get_claude(settings: Settings | None = None) -> ClaudeClient | None:
    """The configured Claude client, or None when AI_PROVIDER=anthropic has no key.

    Raises UnknownModelError for an AI_MODEL without a price, and AiNotConfiguredError
    when Bedrock has no AWS region. It does not look at AI_SUGGESTIONS_ENABLED or at the
    organization's opt-in: the routes check those before they ask for a client.
    """
    settings = settings or get_settings()
    price_for(settings.ai_model)
    if settings.ai_provider == "anthropic" and settings.anthropic_api_key is None:
        return None
    return SdkClaude(
        build_sdk_client(settings), provider=settings.ai_provider, model=settings.ai_model, effort=settings.ai_effort
    )


def _reply(response: BetaMessage, output_type: type[ModelT], *, requested_model: str) -> StructuredReply[ModelT]:
    usage, cost = _usage_and_cost(response, requested_model)
    stop_reason = response.stop_reason
    refusal_category: str | None = None
    output: ModelT | None = None
    outcome: Outcome
    if stop_reason == "refusal":
        outcome = "refused"
        refusal_category = response.stop_details.category if response.stop_details else None
    elif stop_reason != "end_turn":
        outcome = "incomplete"
    else:
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            output = output_type.model_validate_json(text)
            outcome = "ok"
        except ValidationError:
            outcome = "invalid"
    return StructuredReply(
        outcome=outcome,
        output=output,
        model=response.model,
        usage=usage,
        cost_microusd=cost,
        request_id=response._request_id,
        stop_reason=stop_reason,
        refusal_category=refusal_category,
    )


def _usage_and_cost(response: BetaMessage, requested_model: str) -> tuple[TokenUsage, int | None]:
    """Total usage, and its cost priced per model that sampled.

    With a server-side fallback, usage.iterations lists the declined request on the asked
    model and the reply on the fallback model; each is priced at its own model's rate.
    """
    sampled = [
        item for item in response.usage.iterations or []
        if isinstance(item, (BetaMessageIterationUsage, BetaFallbackMessageIterationUsage))
    ]
    parts = [(item.model or requested_model, _token_usage(item)) for item in sampled]
    if not parts:
        parts = [(response.model, _token_usage(response.usage))]
    total = TokenUsage()
    cost: int | None = 0
    for model, usage in parts:
        total = total + usage
        try:
            part_cost = cost_microusd(model, usage)
        except UnknownModelError:
            logger.warning("ai: no price for served model %s; cost not recorded", model)
            cost = None
            continue
        if cost is not None:
            cost += part_cost
    return total, cost


def _token_usage(usage: BetaUsage | BetaMessageIterationUsage | BetaFallbackMessageIterationUsage) -> TokenUsage:
    if usage.cache_creation is not None:
        write_5m = usage.cache_creation.ephemeral_5m_input_tokens or 0
        write_1h = usage.cache_creation.ephemeral_1h_input_tokens or 0
    else:
        write_5m, write_1h = usage.cache_creation_input_tokens or 0, 0
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_5m_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
    )
