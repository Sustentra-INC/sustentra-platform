"""Run the real extraction pipeline over a folder of test documents.

Rule-reader mode (the default) is the production pipeline with every AI hook switched off and Textract
off: deterministic, free, and offline. AI mode swaps in recorded replies (``ai_replay``).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.app.adapters.llm.claude import ClaudeClient
from backend.app.core.config import Settings, get_settings
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.ai_extraction import AiExtraction
from backend.app.services.ai_facility import AiFacility
from backend.app.services.ai_routing import AiRouting
from backend.app.services.parser_service import ParserService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tools.accuracy.ai_replay import HARNESS_ORG_ID, NullLedger
from backend.tools.accuracy.model import ExtractedDoc, Item


@contextmanager
def _env(**values: str) -> Iterator[None]:
    previous = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def build_service(ai_client: ClaudeClient | None = None) -> tuple[PipelineOrchestrationService, str | None]:
    """The pipeline, with AI off (``ai_client`` None) or answering from ``ai_client``. Returns (service, org_id)."""

    base = get_settings()
    off: Settings = base.model_copy(update={"ai_suggestions_enabled": False, "s1_ai_routing_shadow": False})
    if ai_client is None:
        routing = AiRouting(settings=off)
        extraction = AiExtraction(settings=off)
        org_id = None
    else:
        on: Settings = base.model_copy(update={"ai_suggestions_enabled": True, "s1_ai_routing_shadow": False})
        factory: Callable[[Settings], ClaudeClient | None] = lambda _settings: ai_client  # noqa: E731
        routing = AiRouting(settings=on, client_factory=factory, ledger=NullLedger())
        extraction = AiExtraction(settings=on, client_factory=factory, ledger=NullLedger())
        org_id = HARNESS_ORG_ID
    service = PipelineOrchestrationService(
        parser_service=ParserService(),
        pipeline_repository=InMemoryPipelineRunRepository(),
        extraction_result_repository=InMemoryExtractionResultRepository(),
        ai_routing=routing,
        ai_extraction=extraction,
        ai_facility=AiFacility(settings=off),  # needs the database: never on in the harness
    )
    return service, org_id


def _items(result: dict[str, Any]) -> list[Item]:
    items: list[Item] = []
    for raw in (result.get("extraction_result") or {}).get("items") or []:
        confidence = raw.get("confidence")
        items.append(Item(
            field=str(raw.get("field_name")),
            raw=raw.get("raw_value"),
            value=raw.get("normalized_value"),
            unit=raw.get("unit"),
            confidence=float(confidence) if confidence is not None else None,
            flags=tuple(raw.get("validation_flags") or ()),
            record=raw.get("record_index"),
            record_key=raw.get("record_key"),
        ))
    return items


def extract_document(service: PipelineOrchestrationService, org_id: str | None, path: Path) -> ExtractedDoc:
    """One document through the pipeline. A crash is a result (``error``), not an abort."""

    try:
        out = service.process_local_document(
            str(path), engagement_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "accuracy-harness")), persist_run=False,
            org_id=org_id,
        )
    except Exception as exc:  # the harness scores what happened; a document that crashes the reader is a miss
        return ExtractedDoc(filename=path.name, error=f"{type(exc).__name__}")
    run = out["pipeline_run"]
    targets = frozenset(str(t.get("field_id")) for t in out.get("extraction_targets") or [] if t.get("field_id"))
    return ExtractedDoc(
        filename=path.name,
        status=run.get("status"),
        canonical_type_id=run.get("canonical_type_id"),
        halt_code=(run.get("halt_reason") or {}).get("code"),
        targets=targets,
        items=_items(out),
    )


def run_folder(folder: Path, service: PipelineOrchestrationService, org_id: str | None,
               only: set[str] | None = None) -> dict[str, ExtractedDoc]:
    docs: dict[str, ExtractedDoc] = {}
    # Textract is the one network call outside the AI hooks: off, so the run is offline and deterministic.
    with _env(TEXTRACT_ENABLED="false"):
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith(".") or (only is not None and path.name not in only):
                continue
            docs[path.name] = extract_document(service, org_id, path)
    return docs
