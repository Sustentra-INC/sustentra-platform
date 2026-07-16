"""PDF text parser adapter.

Extracts embedded text from PDFs using ``pymupdf`` (preferred) or ``pdfplumber``
when available. OCR is intentionally out of scope for parser runtime v0: if a
page has no embedded text it is reported with a warning rather than rasterized.
No Textract or other external calls are made.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_empty_parser_output,
    build_failed_parser_output,
    build_parser_output,
    build_source_reference,
    build_text_block,
    build_warning,
    snippet,
)

PARSER_NAME_PYMUPDF = "pymupdf"
PARSER_NAME_PDFPLUMBER = "pdfplumber"
PARSER_NAME_FALLBACK = "pdf_parser"


class PdfParser:
    """Adapter that normalizes extractable-text PDFs into ``parser_output`` dicts."""

    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)

        page_texts, parser_name, load_error = self._extract_page_texts(path)

        if load_error is not None:
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=parser_name,
                warnings=[load_error],
            )

        if not page_texts:
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=parser_name,
                warnings=[
                    build_warning(
                        "empty_document",
                        "PDF contained no pages.",
                        severity="info",
                    )
                ],
            )

        pages: list[dict] = []
        text_blocks: list[dict] = []
        source_references: list[dict] = []
        warnings: list[dict] = []
        block_counter = 0
        pages_with_text = 0

        for page_number, page_text in enumerate(page_texts, start=1):
            normalized_text = page_text or ""
            pages.append({"page_number": page_number, "text": normalized_text})

            if not normalized_text.strip():
                warnings.append(
                    build_warning(
                        "empty_page_text",
                        f"Page {page_number} had no extractable text.",
                    )
                )
                continue

            pages_with_text += 1
            block_counter += 1
            block_id = f"{parser_name}-p{page_number}-b{block_counter}"
            source_reference_id = f"SRC-{parser_name}-p{page_number}-{block_counter}"
            source_references.append(
                build_source_reference(
                    source_reference_id,
                    document_id,
                    page_number=page_number,
                    text_snippet=snippet(normalized_text),
                    parser_block_ids=[block_id],
                    source_kind="page_text",
                )
            )
            text_blocks.append(
                build_text_block(
                    block_id,
                    normalized_text.strip(),
                    page_number=page_number,
                    source_reference_id=source_reference_id,
                )
            )

        if pages_with_text == 0:
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=parser_name,
                warnings=warnings,
                pages=pages,
            )

        status = "parsed" if pages_with_text == len(page_texts) else "partial"
        return build_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=parser_name,
            status=status,
            pages=pages,
            text_blocks=text_blocks,
            source_references=source_references,
            warnings=warnings,
        )

    def _extract_page_texts(
        self, path: Path
    ) -> tuple[list[str], str, dict[str, str] | None]:
        """Return (page_texts, parser_name, load_error_warning_or_None)."""

        try:
            import fitz  # type: ignore
        except ImportError:
            fitz = None

        if fitz is not None:
            try:
                page_texts: list[str] = []
                with fitz.open(path) as document:
                    for page in document:
                        page_texts.append(page.get_text() or "")
                return page_texts, PARSER_NAME_PYMUPDF, None
            except Exception as exc:  # noqa: BLE001 - normalize any parse failure
                return (
                    [],
                    PARSER_NAME_PYMUPDF,
                    build_warning(
                        "pdf_open_failed",
                        f"pymupdf could not read the PDF: {type(exc).__name__}.",
                        severity="error",
                    ),
                )

        try:
            import pdfplumber  # type: ignore
        except ImportError:
            pdfplumber = None

        if pdfplumber is not None:
            try:
                page_texts = []
                with pdfplumber.open(path) as document:
                    for page in document.pages:
                        page_texts.append(page.extract_text() or "")
                return page_texts, PARSER_NAME_PDFPLUMBER, None
            except Exception as exc:  # noqa: BLE001 - normalize any parse failure
                return (
                    [],
                    PARSER_NAME_PDFPLUMBER,
                    build_warning(
                        "pdf_open_failed",
                        f"pdfplumber could not read the PDF: {type(exc).__name__}.",
                        severity="error",
                    ),
                )

        return (
            [],
            PARSER_NAME_FALLBACK,
            build_warning(
                "missing_dependency",
                "No PDF text dependency available (pymupdf or pdfplumber required).",
                severity="error",
            ),
        )
