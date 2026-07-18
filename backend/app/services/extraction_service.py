from __future__ import annotations

from backend.app.services.extraction_target_service import ExtractionTargetService


class ExtractionService:
    """Placeholder extraction orchestrator for parser and LLM adapters."""

    def __init__(self, target_service: ExtractionTargetService | None = None) -> None:
        self._target_service = target_service

    def extract(self, payload: dict) -> dict:
        return payload

    def plan_targets(self, classification_result: dict) -> list[dict]:
        """Return extraction targets for a classification result (PR5).

        Delegates to ``ExtractionTargetService``. This only plans which fields to
        attempt; it does not read ``parser_output`` or extract any values.
        """

        if self._target_service is None:
            self._target_service = ExtractionTargetService()
        return self._target_service.get_targets_for_classification_result(classification_result)
