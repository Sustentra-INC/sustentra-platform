"""Record Claude's replies once, replay them for free and deterministically.

``--ai-record DIR`` wraps the real client: every reply is saved as ``DIR/<hash>.json``. ``--ai-replay DIR``
never calls Claude: a request is answered from the file whose hash matches (model + system prompt +
content + output type); a request with no recorded reply is a **miss**, and the harness fails with
"re-record" once the run is done (the AI code swallows exceptions, so a miss is collected, not raised).

The directory holds prompts' replies and a hash of the prompts, not the documents, but replies quote
document text: keep it outside the repository (the CLI refuses a path inside it).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.app.adapters.llm.claude import ClaudeClient, ModelT, StructuredReply, TokenUsage
from backend.app.core.config import AiProvider

# Any fixed UUID: the AI code only needs an organisation id to be present.
HARNESS_ORG_ID = str(uuid.UUID(int=0xACC))


class NullLedger:
    """No usage rows, no database: the harness spends nothing it needs to track."""

    def month_spend_microusd(self, org_id: uuid.UUID) -> int:
        return 0

    def record(self, *, org_id: uuid.UUID, engagement_id: uuid.UUID | None, provider: str,
               reply: StructuredReply[Any]) -> None:
        return None


def request_key(model: str, system: str, content: Any, output_type: type) -> str:
    blob = json.dumps({"model": model, "system": system, "content": content, "output": output_type.__qualname__,
                       "schema": output_type.model_json_schema() if hasattr(output_type, "model_json_schema") else None},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dump(reply: StructuredReply[Any]) -> dict[str, Any]:
    return {
        "outcome": reply.outcome,
        "output": reply.output.model_dump(mode="json") if reply.output is not None else None,
        "model": reply.model,
        "usage": asdict(reply.usage),
        "cost_microusd": reply.cost_microusd,
        "request_id": None,
        "stop_reason": reply.stop_reason,
        "refusal_category": reply.refusal_category,
    }


def _load(data: dict[str, Any], output_type: type[ModelT]) -> StructuredReply[ModelT]:
    output = output_type.model_validate(data["output"]) if data["output"] is not None else None
    return StructuredReply(
        outcome=data["outcome"], output=output, model=data["model"], usage=TokenUsage(**data["usage"]),
        cost_microusd=data["cost_microusd"], request_id=None, stop_reason=data["stop_reason"],
        refusal_category=data["refusal_category"],
    )


class RecordingClaude:
    """Calls the real client and stores each reply."""

    def __init__(self, inner: ClaudeClient, directory: Path) -> None:
        self._inner = inner
        self._dir = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.recorded = 0

    @property
    def provider(self) -> AiProvider:
        return self._inner.provider

    @property
    def model(self) -> str:
        return self._inner.model

    def structured(self, *, system: str, content: Any, output_type: type[ModelT], max_tokens: int) -> StructuredReply[ModelT]:
        reply = self._inner.structured(system=system, content=content, output_type=output_type, max_tokens=max_tokens)
        key = request_key(self._inner.model, system, _plain(content), output_type)
        (self._dir / f"{key}.json").write_text(json.dumps(_dump(reply), indent=1, sort_keys=True), encoding="utf-8")
        self.recorded += 1
        return reply


class ReplayClaude:
    """Answers from recorded replies; never touches the network."""

    def __init__(self, directory: Path, *, model: str, provider: AiProvider = "anthropic") -> None:
        self._dir = directory
        self._model = model
        self._provider: AiProvider = provider
        self.misses: list[str] = []
        self.replayed = 0

    @property
    def provider(self) -> AiProvider:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def structured(self, *, system: str, content: Any, output_type: type[ModelT], max_tokens: int) -> StructuredReply[ModelT]:
        key = request_key(self._model, system, _plain(content), output_type)
        path = self._dir / f"{key}.json"
        if not path.is_file():
            self.misses.append(key[:12])
            raise LookupError(f"no recorded AI reply for request {key[:12]}: re-record with --ai-record")
        self.replayed += 1
        return _load(json.loads(path.read_text(encoding="utf-8")), output_type)


def _plain(content: str | Iterable[Any]) -> Any:
    return content if isinstance(content, str) else list(content)
