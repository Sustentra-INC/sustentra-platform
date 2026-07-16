from pathlib import Path

from backend.app.adapters.parsers.text_parser import TextParser
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


def test_non_empty_text_file_produces_page_and_blocks(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("Total Usage 28,100 MMBtu\nService address: 1 Main St\n", encoding="utf-8")

    output = TextParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "parsed"
    assert output["parser_name"] == "text_parser"
    assert len(output["pages"]) == 1
    assert output["pages"][0]["page_number"] == 1
    assert len(output["text_blocks"]) == 2
    assert output["text_blocks"][0]["text"] == "Total Usage 28,100 MMBtu"


def test_empty_text_file_is_empty_status_with_warning(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.txt"
    file_path.write_text("   \n\n", encoding="utf-8")

    output = TextParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "empty"
    assert output["text_blocks"] == []
    assert any(w["code"] == "empty_document" for w in output["warnings"])


def test_source_reference_includes_text_snippet(tmp_path: Path) -> None:
    file_path = tmp_path / "note.md"
    file_path.write_text("# Heading\nBody line with content", encoding="utf-8")

    output = TextParser().parse(file_path, document_id="DOC-42", processing_run_id="RUN-9")

    assert output["source_references"], "expected at least one source reference"
    first = output["source_references"][0]
    assert first["document_id"] == "DOC-42"
    assert first["source_kind"] == "page_text"
    assert first["text_snippet"] == "# Heading"


def test_deterministic_parser_output_id(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("content", encoding="utf-8")

    first = TextParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")
    second = TextParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert first["parser_output_id"] == second["parser_output_id"]
