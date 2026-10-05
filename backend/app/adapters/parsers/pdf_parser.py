"""PDF text parser adapter.

Extracts embedded text from PDFs using ``pymupdf`` (preferred) or ``pdfplumber``
when available. With ``pymupdf`` every visual text line becomes its own text block
with a bounding box normalized to the page (0-1), so downstream candidates can point
at the exact line they came from. ``pdfplumber`` (fallback) yields one block per page. OCR is intentionally out of scope for parser runtime v0: if a
page has no embedded text it is reported with a warning rather than rasterized.
No Textract or other external calls are made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_empty_parser_output,
    build_failed_parser_output,
    build_parser_output,
    build_source_reference,
    build_text_block,
    build_warning,
    snippet,
    to_reference_box,
)

PARSER_NAME_PYMUPDF = "pymupdf"
PARSER_NAME_PDFPLUMBER = "pdfplumber"
PARSER_NAME_FALLBACK = "pdf_parser"

# (line text, parser_output bounding box {left, top, width, height} normalized 0-1)
PageLine = tuple[str, dict[str, float]]


class PdfParser:
    """Adapter that normalizes extractable-text PDFs into ``parser_output`` dicts."""

    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)

        page_texts, page_lines, parser_name, load_error = self._extract_page_texts(path)

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
            lines = page_lines[page_number - 1] if page_number - 1 < len(page_lines) else []
            if lines:
                for line_text, bounding_box in lines:
                    block_counter += 1
                    block_id = f"{parser_name}-p{page_number}-b{block_counter}"
                    source_reference_id = f"SRC-{parser_name}-p{page_number}-{block_counter}"
                    source_references.append(
                        build_source_reference(
                            source_reference_id,
                            document_id,
                            page_number=page_number,
                            text_snippet=snippet(line_text),
                            bounding_box=to_reference_box(bounding_box),
                            parser_block_ids=[block_id],
                            source_kind="line_text",
                        )
                    )
                    text_blocks.append(
                        build_text_block(
                            block_id,
                            line_text,
                            page_number=page_number,
                            bounding_box=bounding_box,
                            source_reference_id=source_reference_id,
                        )
                    )
                continue

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
    ) -> tuple[list[str], list[list[PageLine]], str, dict[str, str] | None]:
        """Return (page_texts, page_lines, parser_name, load_error_warning_or_None).

        ``page_lines`` holds, per page, ``(text, bounding_box)`` for each visual line
        (pymupdf only; empty for the pdfplumber fallback).
        """

        try:
            import fitz
        except ImportError:
            fitz = None

        if fitz is not None:
            try:
                page_texts: list[str] = []
                page_lines: list[list[PageLine]] = []
                with fitz.open(path) as document:
                    for page in document:
                        page_texts.append(page.get_text() or "")
                        page_lines.append(self._page_lines(page))
                return page_texts, page_lines, PARSER_NAME_PYMUPDF, None
            except Exception as exc:  # noqa: BLE001 - normalize any parse failure
                return (
                    [],
                    [],
                    PARSER_NAME_PYMUPDF,
                    build_warning(
                        "pdf_open_failed",
                        f"pymupdf could not read the PDF: {type(exc).__name__}.",
                        severity="error",
                    ),
                )

        try:
            import pdfplumber
        except ImportError:
            pdfplumber = None  # type: ignore[assignment]

        if pdfplumber is not None:
            try:
                page_texts = []
                with pdfplumber.open(path) as document:
                    for page in document.pages:
                        page_texts.append(page.extract_text() or "")
                return page_texts, [], PARSER_NAME_PDFPLUMBER, None
            except Exception as exc:  # noqa: BLE001 - normalize any parse failure
                return (
                    [],
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
            [],
            PARSER_NAME_FALLBACK,
            build_warning(
                "missing_dependency",
                "No PDF text dependency available (pymupdf or pdfplumber required).",
                severity="error",
            ),
        )

    @staticmethod
    def _page_lines(page: Any) -> list[PageLine]:
        """Visual lines of a pymupdf page with boxes normalized to the page size."""

        width = float(page.rect.width) or 1.0
        height = float(page.rect.height) or 1.0
        lines: list[PageLine] = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []) or []:
                for text, (x0, y0, x1, y1) in PdfParser._line_segments(line.get("spans", []) or []):
                    lines.append(
                        (
                            text,
                            {
                                "left": round(max(0.0, x0 / width), 6),
                                "top": round(max(0.0, y0 / height), 6),
                                "width": round(max(0.0, (x1 - x0) / width), 6),
                                "height": round(max(0.0, (y1 - y0) / height), 6),
                            },
                        )
                    )
        return lines

    @staticmethod
    def _line_segments(spans: list[dict]) -> list[tuple[str, tuple[float, float, float, float]]]:
        """Split a pymupdf line where spans are separated by a column-sized gap.

        pymupdf joins spans that share a baseline into one line even when they are
        separate table cells ("Qty" and "UOM", "1,915.3" and "L"). A gap wider than
        ~0.6 em (a word space is ~0.28 em) starts a new segment.
        """

        segments: list[tuple[str, tuple[float, float, float, float]]] = []
        text_parts: list[str] = []
        box: list[float] | None = None
        previous_x1: float | None = None
        for span in spans:
            span_text = span.get("text", "")
            if not span_text.strip():
                continue
            sx0, sy0, sx1, sy1 = span["bbox"]
            size = float(span.get("size") or (sy1 - sy0) or 10.0)
            if box is not None and previous_x1 is not None and sx0 - previous_x1 > 0.6 * size:
                segments.append((" ".join("".join(text_parts).split()), (box[0], box[1], box[2], box[3])))
                text_parts, box = [], None
            text_parts.append(span_text)
            box = [sx0, sy0, sx1, sy1] if box is None else [min(box[0], sx0), min(box[1], sy0), max(box[2], sx1), max(box[3], sy1)]
            previous_x1 = sx1
        if box is not None:
            joined = " ".join("".join(text_parts).split())
            if joined:
                segments.append((joined, (box[0], box[1], box[2], box[3])))
        return segments
