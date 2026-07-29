"""Parser runtime service (PR4).

Routes a local document file to the appropriate parser adapter and returns a
normalized ``parser_output``-shaped dictionary conforming to
``contracts/parser_output.schema.json``.

Scope for runtime v0:
    * detection by file extension and/or mime type
    * text / Excel / PDF parsing and an explicit image stub
    * optional live Textract for PDFs/images when ``TEXTRACT_ENABLED`` is true
    * Textract JSON normalization via an explicit method

Out of scope (later PRs): field extraction, extraction_candidate generation,
review persistence, RAG, and S2 methodology. By default this service makes no
external network, AWS, or OpenAI calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.adapters.parsers.base import build_failed_parser_output, build_warning
from backend.app.adapters.parsers.csv_parser import CsvParser
from backend.app.adapters.parsers.excel_parser import ExcelParser
from backend.app.adapters.parsers.image_parser import ImageParser
from backend.app.adapters.parsers.pdf_parser import PdfParser
from backend.app.adapters.parsers.text_parser import TextParser
from backend.app.adapters.parsers.textract_parser import TextractParser

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
CSV_EXTENSIONS = {".csv"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp"}

MIME_TYPE_ROUTES = {
    "text/plain": "text",
    "text/markdown": "text",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/pdf": "pdf",
}


class ParserService:
    """Detects the correct parser adapter and produces ``parser_output`` dicts."""

    def __init__(self, live_textract_parser: AwsTextractParser | None = None) -> None:
        self._text_parser = TextParser()
        self._csv_parser = CsvParser()
        self._excel_parser = ExcelParser()
        self._pdf_parser = PdfParser()
        self._image_parser = ImageParser()
        self._textract_parser = TextractParser()
        self._live_textract_parser = live_textract_parser or AwsTextractParser()

    def parse_document(
        self,
        file_path: str | Path,
        document_id: str,
        processing_run_id: str,
        mime_type: str | None = None,
    ) -> dict:
        """Parse a local file into a normalized ``parser_output`` dictionary.

        Raises ``FileNotFoundError`` when the input path itself is invalid. All
        other parser-level problems are reported as ``failed``/``partial``
        ``parser_output`` objects rather than raised exceptions.
        """

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Parser input file not found: {file_path}")

        parser_kind = self._detect_parser_kind(path, mime_type)

        if parser_kind == "text":
            return self._text_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "csv":
            return self._csv_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "excel":
            return self._excel_parser.parse(path, document_id, processing_run_id)
        if parser_kind in {"pdf", "image"} and self._textract_enabled():
            return self._live_textract_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "pdf":
            return self._pdf_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "image":
            return self._image_parser.parse(path, document_id, processing_run_id)

        return build_failed_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name="parser_service",
            warnings=[
                build_warning(
                    "unsupported_file_type",
                    f"No parser is available for extension '{path.suffix}' "
                    f"or mime type '{mime_type}'.",
                    severity="error",
                )
            ],
        )

    def parse_textract_json(
        self,
        textract_source: dict[str, Any] | str | Path,
        document_id: str,
        processing_run_id: str,
    ) -> dict:
        """Normalize already-saved Textract JSON (dict or file). Never calls AWS."""

        return self._textract_parser.parse(textract_source, document_id, processing_run_id)

    @staticmethod
    def _textract_enabled() -> bool:
        return os.environ.get("TEXTRACT_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _detect_parser_kind(path: Path, mime_type: str | None) -> str | None:
        """Resolve the parser kind by file extension, then mime type."""

        suffix = path.suffix.lower()
        if suffix in TEXT_EXTENSIONS:
            return "text"
        if suffix in CSV_EXTENSIONS:
            return "csv"
        if suffix in EXCEL_EXTENSIONS:
            return "excel"
        if suffix in PDF_EXTENSIONS:
            return "pdf"
        if suffix in IMAGE_EXTENSIONS:
            return "image"

        if mime_type:
            normalized = mime_type.split(";", 1)[0].strip().lower()
            if normalized in MIME_TYPE_ROUTES:
                return MIME_TYPE_ROUTES[normalized]
            if normalized.startswith("image/"):
                return "image"

        return None
