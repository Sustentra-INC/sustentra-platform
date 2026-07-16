"""Shared builders for parser adapters.

These helpers assemble ``parser_output``-shaped dictionaries that conform to
``contracts/parser_output.schema.json``. They contain no parsing logic and make
no external calls; adapters use them to keep output construction consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

PARSER_RUNTIME_VERSION = "v0"

MAX_SNIPPET_LENGTH = 240


def utc_now_iso() -> str:
    """Return the current UTC time as an RFC 3339 / ISO 8601 string."""

    return datetime.now(timezone.utc).isoformat()


def make_parser_output_id(document_id: str, processing_run_id: str, parser_name: str) -> str:
    """Build a deterministic parser_output_id from run context.

    Deterministic ids keep parser outputs stable across repeated runs, which
    makes them straightforward to assert in tests.
    """

    return f"PO-{parser_name}-{document_id}-{processing_run_id}"


def snippet(text: str | None, max_length: int = MAX_SNIPPET_LENGTH) -> str | None:
    """Return a trimmed, length-capped snippet for source traceability."""

    if text is None:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1].rstrip() + "\u2026"


def build_warning(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    """Build a schema-compliant warning object."""

    return {"code": code, "message": message, "severity": severity}


def build_source_reference(
    source_reference_id: str,
    document_id: str,
    *,
    page_number: int | None = None,
    sheet_name: str | None = None,
    cell_or_range: str | None = None,
    text_snippet: str | None = None,
    bounding_box: dict[str, Any] | None = None,
    parser_block_ids: Iterable[str] | None = None,
    source_kind: str | None = None,
) -> dict[str, Any]:
    """Build a schema-compliant source_reference object."""

    return {
        "source_reference_id": source_reference_id,
        "document_id": document_id,
        "page_number": page_number,
        "sheet_name": sheet_name,
        "cell_or_range": cell_or_range,
        "text_snippet": text_snippet,
        "bounding_box": bounding_box,
        "parser_block_ids": list(parser_block_ids) if parser_block_ids else [],
        "source_kind": source_kind,
    }


def build_text_block(
    block_id: str,
    text: str,
    *,
    page_number: int | None = None,
    confidence: float | None = None,
    bounding_box: dict[str, Any] | None = None,
    source_reference_id: str | None = None,
) -> dict[str, Any]:
    """Build a schema-compliant text_block object."""

    return {
        "block_id": block_id,
        "page_number": page_number,
        "text": text,
        "confidence": confidence,
        "bounding_box": bounding_box,
        "source_reference_id": source_reference_id,
    }


def build_parser_output(
    *,
    document_id: str,
    processing_run_id: str,
    parser_name: str,
    status: str,
    parser_version: str = PARSER_RUNTIME_VERSION,
    parser_output_id: str | None = None,
    created_at: str | None = None,
    pages: list[dict[str, Any]] | None = None,
    text_blocks: list[dict[str, Any]] | None = None,
    tables: list[dict[str, Any]] | None = None,
    key_value_pairs: list[dict[str, Any]] | None = None,
    source_references: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, str]] | None = None,
    raw_artifact_uri: str | None = None,
) -> dict[str, Any]:
    """Assemble a full parser_output dictionary with schema defaults."""

    return {
        "parser_output_id": parser_output_id
        or make_parser_output_id(document_id, processing_run_id, parser_name),
        "document_id": document_id,
        "processing_run_id": processing_run_id,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "status": status,
        "created_at": created_at or utc_now_iso(),
        "pages": pages or [],
        "text_blocks": text_blocks or [],
        "tables": tables or [],
        "key_value_pairs": key_value_pairs or [],
        "source_references": source_references or [],
        "warnings": warnings or [],
        "raw_artifact_uri": raw_artifact_uri,
    }


def build_empty_parser_output(
    *,
    document_id: str,
    processing_run_id: str,
    parser_name: str,
    warnings: list[dict[str, str]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    parser_version: str = PARSER_RUNTIME_VERSION,
) -> dict[str, Any]:
    """Assemble an ``empty`` parser_output dictionary."""

    return build_parser_output(
        document_id=document_id,
        processing_run_id=processing_run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        status="empty",
        pages=pages,
        warnings=warnings,
    )


def build_failed_parser_output(
    *,
    document_id: str,
    processing_run_id: str,
    parser_name: str,
    warnings: list[dict[str, str]],
    status: str = "failed",
    parser_version: str = PARSER_RUNTIME_VERSION,
) -> dict[str, Any]:
    """Assemble a ``failed`` (or ``partial``) parser_output dictionary."""

    return build_parser_output(
        document_id=document_id,
        processing_run_id=processing_run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        status=status,
        warnings=warnings,
    )
