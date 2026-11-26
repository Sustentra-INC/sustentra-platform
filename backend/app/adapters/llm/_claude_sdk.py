"""What the two Claude providers share: the ``anthropic`` SDK call, the reply and the errors.

Only ``anthropic_api.py`` and ``bedrock.py`` import this; both reach Claude through the
same SDK and Messages shape and differ in the client, the model id, and the extras they send.
This is the one place that knows the SDK's types: replies leave as ``base.StructuredReply``
and failures as ``base.LlmRequestRejected`` / ``base.LlmUnavailable``.

* ``structured()`` sends one request whose reply must match a pydantic model (structured
  outputs, ``output_config.format``).
* Privacy: nothing here logs the key, prompts or replies, and the SDK's OpenTelemetry spans
  are turned off by the provider modules.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any

import anthropic
from anthropic.types.beta import (
    BetaFallbackMessageIterationUsage,
    BetaMessage,
    BetaMessageIterationUsage,
    BetaUsage,
)
from pydantic import ValidationError

from backend.app.adapters.llm.base import (
    LlmClient,
    LlmRequestRejected,
    LlmUnavailable,
    ModelT,
    Outcome,
    StructuredReply,
    TokenUsage,
)
from backend.app.adapters.llm.pricing import UnknownModelError, canonical_model, cost_microusd, price_for
from backend.app.core.config import AiEffort, AiProvider

logger = logging.getLogger(__name__)
# At DEBUG the SDK logs whole request bodies, i.e. prompts and document text. Keep its
# logger at INFO even if the root level is lowered (and never set ANTHROPIC_LOG).
logging.getLogger("anthropic").setLevel(logging.INFO)

# HTTP statuses where the request itself is wrong, so retrying cannot help.
REJECTED_STATUSES = (400, 401, 403, 404, 422)

SdkClient = anthropic.Anthropic | anthropic.AnthropicBedrockMantle


class ClaudeSdkClient(LlmClient):
    """``LlmClient`` over the official ``anthropic`` SDK. Subclasses fix the provider."""

    def __init__(self, sdk: SdkClient, *, model: str, effort: AiEffort) -> None:
        self._model = canonical_model(model)
        price_for(self.provider, self._model)  # refuse a model we cannot price
        self._sdk = sdk
        self._effort: AiEffort = effort

    @property
    @abstractmethod
    def provider(self) -> AiProvider: ...

    @property
    def model(self) -> str:
        return self._model

    @abstractmethod
    def _request_model(self) -> str:
        """The model id as this provider expects it on the wire."""

    def _extra_request_args(self) -> dict[str, Any]:
        """Provider-only request arguments (for example a beta flag)."""
        return {}

    def structured(
        self,
        *,
        system: str,
        content: str,
        output_type: type[ModelT],
        max_tokens: int,
    ) -> StructuredReply[ModelT]:
        # transform_schema makes the pydantic schema acceptable to structured outputs
        # (additionalProperties false, unsupported limits moved into descriptions). Those
        # limits are enforced again by model_validate_json below.
        schema = anthropic.transform_schema(output_type.model_json_schema())
        try:
            response = self._sdk.beta.messages.create(
                model=self._request_model(),
                max_tokens=max_tokens,
                # Thinking is adaptive by default on the 5.5 models; effort is the only dial.
                output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                **self._extra_request_args(),
            )
        except anthropic.APIError as exc:
            raise _translate(exc) from exc
        return _reply(response, output_type, provider=self.provider, requested_model=self._model)


def _translate(exc: anthropic.APIError) -> LlmRequestRejected | LlmUnavailable:
    """The SDK's error as a neutral one. Status, error type, message and request id are kept."""

    cause = type(exc).__name__
    if not isinstance(exc, anthropic.APIStatusError):
        return LlmUnavailable(cause, cause_name=cause)
    body: dict[str, Any] = exc.body if isinstance(exc.body, dict) else {}
    inner = body.get("error")
    error: dict[str, Any] = inner if isinstance(inner, dict) else body
    error_type = error.get("type")
    fields: dict[str, Any] = {
        "cause_name": cause,
        "status_code": exc.status_code,
        "error_type": str(error_type) if error_type else None,
        "message": str(error.get("message", "")),
        "request_id": exc.request_id,
    }
    if exc.status_code in REJECTED_STATUSES:
        return LlmRequestRejected(f"{cause}: HTTP {exc.status_code}", **fields)
    return LlmUnavailable(f"{cause}: HTTP {exc.status_code}", **fields)


def _reply(response: BetaMessage, output_type: type[ModelT], *, provider: AiProvider,
           requested_model: str) -> StructuredReply[ModelT]:
    usage, cost = _usage_and_cost(response, provider, requested_model)
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


def _usage_and_cost(response: BetaMessage, provider: AiProvider,
                    requested_model: str) -> tuple[TokenUsage, int | None]:
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
            part_cost = cost_microusd(provider, model, usage)
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
