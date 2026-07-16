"""Shared assertions for parser_output shape used across parser tests."""

from __future__ import annotations

from typing import Any

REQUIRED_TOP_LEVEL_FIELDS = [
    "parser_output_id",
    "document_id",
    "processing_run_id",
    "parser_name",
    "parser_version",
    "status",
    "created_at",
    "pages",
    "tables",
    "key_value_pairs",
    "text_blocks",
    "source_references",
    "warnings",
]

VALID_STATUSES = {"parsed", "partial", "empty", "failed"}


def assert_parser_output_shape(output: dict[str, Any]) -> None:
    """Assert an object matches the parser_output contract's required shape."""

    missing = [field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in output]
    assert not missing, f"parser_output missing fields: {missing}"

    assert output["status"] in VALID_STATUSES, f"invalid status: {output['status']}"

    for field in ("pages", "tables", "key_value_pairs", "text_blocks", "source_references", "warnings"):
        assert isinstance(output[field], list), f"{field} must be a list"

    for page in output["pages"]:
        assert "page_number" in page and "text" in page

    for block in output["text_blocks"]:
        assert "block_id" in block and "text" in block

    for table in output["tables"]:
        assert "table_id" in table and "rows" in table

    for pair in output["key_value_pairs"]:
        assert "pair_id" in pair and "key" in pair and "value" in pair

    for reference in output["source_references"]:
        assert "source_reference_id" in reference and "document_id" in reference

    for warning in output["warnings"]:
        assert "code" in warning and "message" in warning
