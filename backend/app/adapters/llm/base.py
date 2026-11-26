"""The provider-neutral AI interface (runbook: docs/backend_services.md).

Callers (services, routes, tools) depend on this module only: ``LlmClient``, the reply
dataclasses and the errors below. Nothing outside ``backend/app/adapters/llm/`` imports a
provider's library (enforced by ``tests/adapters/llm/test_no_provider_imports.py``). One
module per provider implements ``LlmClient``: ``anthropic_api.py`` and ``bedrock.py``;
``factory.get_llm`` picks one from the settings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from backend.app.core.config import AiProvider

ModelT = TypeVar("ModelT", bound=BaseModel)

# A document suggestion is one synchronous request: fail fast, retry once.
REQUEST_TIMEOUT_S = 90.0
MAX_RETRIES = 1

# "ok": output is set. "refused": the model declined. "incomplete": the reply stopped early
# (max_tokens or another stop reason). "invalid": the reply did not match the output model.
Outcome = Literal["ok", "refused", "incomplete", "invalid"]


class LlmNotConfigured(RuntimeError):
    """The settings cannot run AI here (no AWS region for Bedrock, a model with no price...)."""


class LlmProviderError(Exception):
    """The provider answered with an error, or could not be reached.

    ``status_code``, ``error_type``, ``message`` and ``request_id`` are set when the provider
    answered with an HTTP error; ``cause_name`` is always the class name of the original error.
    The message describes the request's shape, never the prompt or the documents.
    """

    def __init__(self, summary: str, *, cause_name: str, status_code: int | None = None,
                 error_type: str | None = None, message: str = "", request_id: str | None = None) -> None:
        super().__init__(summary)
        self.cause_name = cause_name
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.request_id = request_id


class LlmRequestRejected(LlmProviderError):
    """The provider refused the request itself (HTTP 400, 401, 403, 404 or 422): retrying cannot help."""


class LlmUnavailable(LlmProviderError):
    """The provider could not serve the request now (network, timeout, rate limit, server error)."""


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


@dataclass(frozen=True)
class StructuredReply(Generic[ModelT]):
    outcome: Outcome
    output: ModelT | None
    # The model that served the reply; a provider-side fallback can differ from the one asked.
    model: str
    usage: TokenUsage
    # None only when a served model has no price (logged).
    cost_microusd: int | None
    request_id: str | None
    stop_reason: str | None
    refusal_category: str | None = None


class LlmClient(ABC):
    """One synchronous call shape: a request whose reply must match a pydantic model.

    ``stop_reason`` is checked before the content is read, so a refusal or a cut-off reply
    gives no output, never a partial one. Provider failures raise ``LlmRequestRejected`` or
    ``LlmUnavailable``.
    """

    @property
    @abstractmethod
    def provider(self) -> AiProvider: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    def structured(
        self,
        *,
        system: str,
        content: str,
        output_type: type[ModelT],
        max_tokens: int,
    ) -> StructuredReply[ModelT]: ...
