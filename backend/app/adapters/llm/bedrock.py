"""The Amazon Bedrock provider (``AI_PROVIDER=bedrock``).

Signs with the instance role in ``AWS_REGION`` and needs no key. It uses the Bedrock Mantle
endpoint (``bedrock-mantle`` SigV4, IAM ``bedrock-mantle:CreateInference``), where the model
id is ``anthropic.<claude-api-id>`` (no cross-region ``us.`` profile). Not yet tried live.
``AI_BEDROCK_MODEL_ID`` replaces the derived id verbatim when set. Prices stay keyed by the
bare id, and the cost is an estimate: AWS bills at its own rates.
"""

from __future__ import annotations

import anthropic

from backend.app.adapters.llm._claude_sdk import ClaudeSdkClient
from backend.app.adapters.llm.base import MAX_RETRIES, REQUEST_TIMEOUT_S, LlmNotConfigured
from backend.app.adapters.llm.pricing import BEDROCK_MODEL_PREFIX
from backend.app.core.config import AiEffort, AiProvider, Settings


class BedrockClient(ClaudeSdkClient):
    def __init__(self, sdk: anthropic.AnthropicBedrockMantle, *, model: str, effort: AiEffort,
                 bedrock_model_id: str | None = None) -> None:
        self._bedrock_model_id = bedrock_model_id
        super().__init__(sdk, model=model, effort=effort)

    @property
    def provider(self) -> AiProvider:
        return "bedrock"

    def _request_model(self) -> str:
        # The override is sent as given; prices and cost stay keyed by the Claude API id.
        return self._bedrock_model_id or BEDROCK_MODEL_PREFIX + self._model


def build_sdk_client(timeout_s: float = REQUEST_TIMEOUT_S,
                     max_retries: int = MAX_RETRIES) -> anthropic.AnthropicBedrockMantle:
    try:
        # Region from AWS_REGION; credentials from the default chain (the instance role).
        return anthropic.AnthropicBedrockMantle(timeout=timeout_s, max_retries=max_retries, open_telemetry=False)
    except anthropic.AnthropicError as exc:
        raise LlmNotConfigured(f"Bedrock is not configured: {exc}") from exc


def build_client(settings: Settings, *, timeout_s: float = REQUEST_TIMEOUT_S,
                 max_retries: int = MAX_RETRIES) -> BedrockClient:
    return BedrockClient(
        build_sdk_client(timeout_s, max_retries),
        model=settings.ai_model,
        effort=settings.ai_effort,
        bedrock_model_id=settings.ai_bedrock_model_id,
    )
