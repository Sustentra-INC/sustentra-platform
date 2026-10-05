from __future__ import annotations

from backend.app.services.extraction_candidate_service import ExtractionCandidateService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor


class ExtractionService:
    """Orchestrates extraction target planning and candidate generation."""

    def __init__(
        self,
        target_service: ExtractionTargetService | None = None,
        candidate_service: ExtractionCandidateService | None = None,
        stationary_extractor: StationaryCombustionExtractor | None = None,
    ) -> None:
        self._target_service = target_service
        self._candidate_service = candidate_service or ExtractionCandidateService()
        self._stationary_extractor = stationary_extractor or StationaryCombustionExtractor()

    def extract(self, payload: dict) -> dict:
        """Generate extraction candidates from parser_output + targets (PR6).

        Expects ``payload`` with ``parser_output`` and ``extraction_targets``.
        ``evidence_id`` is optional. Raises ``ValueError`` if required keys are
        missing. Does not read ``.env`` or call any external service.
        """

        if not isinstance(payload, dict):
            raise ValueError("extract payload must be a dictionary.")
        if "parser_output" not in payload or "extraction_targets" not in payload:
            raise ValueError(
                "extract payload requires 'parser_output' and 'extraction_targets'."
            )

        parser_output = payload["parser_output"]
        extraction_targets = payload["extraction_targets"]
        evidence_id = str(payload.get("evidence_id") or "evidence-unknown")

        if self._stationary_extractor.handles(extraction_targets):
            # EXT-001: CT-S1-FUELQTY has a layout-aware extractor (records, units, halts).
            outcome = self._stationary_extractor.extract(parser_output, extraction_targets, evidence_id)
            result = {
                "evidence_id": evidence_id,
                "document_id": parser_output.get("document_id"),
                "candidate_count": len(outcome.candidates),
                "items": outcome.candidates,
                "record_count": outcome.records,
            }
            if outcome.halt_reason is not None:
                result["halt_reason"] = outcome.halt_reason
            return result

        candidates = self._candidate_service.generate_candidates(
            parser_output=parser_output,
            extraction_targets=extraction_targets,
            evidence_id=evidence_id,
        )

        return {
            "evidence_id": evidence_id,
            "document_id": parser_output.get("document_id"),
            "candidate_count": len(candidates),
            "items": candidates,
        }

    def extract_for_classification_result(
        self,
        parser_output: dict,
        classification_result: dict,
        evidence_id: str,
    ) -> dict:
        """Plan targets from a classification result, then generate candidates.

        Pure orchestration: it does not call the parser or classifier itself.
        """

        targets = self.plan_targets(classification_result)
        return self.extract(
            {
                "parser_output": parser_output,
                "extraction_targets": targets,
                "evidence_id": evidence_id,
            }
        )

    def plan_targets(self, classification_result: dict) -> list[dict]:
        """Return extraction targets for a classification result (PR5).

        Delegates to ``ExtractionTargetService``. This only plans which fields to
        attempt; it does not read ``parser_output`` or extract any values.
        """

        if self._target_service is None:
            self._target_service = ExtractionTargetService()
        return self._target_service.get_targets_for_classification_result(classification_result)
