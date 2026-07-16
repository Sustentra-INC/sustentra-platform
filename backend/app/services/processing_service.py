from __future__ import annotations

from pathlib import Path

from backend.app.services.parser_service import ParserService


class ProcessingService:
    """Coordinates processing run lifecycle for uploaded documents."""

    def __init__(self) -> None:
        self._parser_service = ParserService()

    def start_run(self, payload: dict) -> dict:
        return payload

    def parse_document_file(
        self,
        file_path: str | Path,
        document_id: str,
        processing_run_id: str,
        mime_type: str | None = None,
    ) -> dict:
        """Delegate local document parsing to the parser runtime (PR4)."""

        return self._parser_service.parse_document(
            file_path,
            document_id,
            processing_run_id,
            mime_type=mime_type,
        )
