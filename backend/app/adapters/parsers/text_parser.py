"""Plain-text and markdown parser adapter.

Normalizes ``.txt`` / ``.md`` / ``.csv`` files into a ``parser_output`` object.
It performs no field extraction; each non-empty line becomes a traceable text
block with an accompanying source reference.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_empty_parser_output,
    build_parser_output,
    build_source_reference,
    build_text_block,
    build_warning,
    snippet,
)

PARSER_NAME = "text_parser"


class TextParser:
    """Adapter that normalizes UTF-8 text files into ``parser_output`` dicts."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)
        warnings: list[dict[str, str]] = []

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            warnings.append(
                build_warning(
                    "non_utf8_content",
                    "File was not valid UTF-8; undecodable bytes were replaced.",
                )
            )

        lines = raw_text.splitlines()
        non_empty = [(idx, line) for idx, line in enumerate(lines) if line.strip()]

        if not non_empty:
            warnings.append(
                build_warning(
                    "empty_document",
                    "Text file contained no non-empty lines.",
                    severity="info",
                )
            )
            return build_empty_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=warnings,
                pages=[{"page_number": 1, "text": raw_text}],
            )

        text_blocks: list[dict] = []
        source_references: list[dict] = []

        for position, (_line_index, line) in enumerate(non_empty, start=1):
            block_id = f"{self.parser_name}-p1-b{position}"
            source_reference_id = f"SRC-{self.parser_name}-p1-{position}"
            source_references.append(
                build_source_reference(
                    source_reference_id,
                    document_id,
                    page_number=1,
                    text_snippet=snippet(line),
                    parser_block_ids=[block_id],
                    source_kind="page_text",
                )
            )
            text_blocks.append(
                build_text_block(
                    block_id,
                    line.strip(),
                    page_number=1,
                    source_reference_id=source_reference_id,
                )
            )

        return build_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name=self.parser_name,
            status="parsed",
            pages=[{"page_number": 1, "text": raw_text}],
            text_blocks=text_blocks,
            source_references=source_references,
            warnings=warnings,
        )
