"""Image parser adapter (explicit non-OCR stub for runtime v0).

Image OCR is intentionally not implemented in parser runtime v0. This adapter
returns a schema-compliant ``parser_output`` with a ``failed`` status and an
explanatory warning so image inputs are handled predictably without pretending
OCR exists. It makes no external calls.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_failed_parser_output,
    build_warning,
)

PARSER_NAME = "image_ocr"


class ImageParser:
    """Adapter stub for image inputs; OCR is deferred beyond parser runtime v0."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        _ = Path(file_path)
        return build_failed_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            warnings=[
                build_warning(
                    "ocr_not_implemented",
                    "Image OCR is not implemented in parser runtime v0.",
                    severity="warning",
                )
            ],
        )
