from pathlib import Path

import pytest

from backend.app.services.parser_service import ParserService
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


def test_text_file_routes_to_text_parser(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("Hello world", encoding="utf-8")

    output = ParserService().parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "text_parser"
    assert output["status"] == "parsed"


def test_excel_file_routes_to_excel_parser(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook_path = tmp_path / "data.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "Metric"
    workbook.save(workbook_path)

    output = ParserService().parse_document(
        workbook_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "openpyxl"


def test_unsupported_extension_returns_failed_with_warning(tmp_path: Path) -> None:
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"PK\x03\x04 not a real zip")

    output = ParserService().parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["status"] == "failed"
    assert any(w["code"] == "unsupported_file_type" for w in output["warnings"])


def test_invalid_file_path_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        ParserService().parse_document(
            "this/path/does/not/exist.txt",
            document_id="DOC-1",
            processing_run_id="RUN-1",
        )


def test_mime_type_routes_when_extension_unknown(tmp_path: Path) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_text("Line one\nLine two", encoding="utf-8")

    output = ParserService().parse_document(
        file_path,
        document_id="DOC-1",
        processing_run_id="RUN-1",
        mime_type="text/plain",
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "text_parser"


def test_output_includes_all_required_fields_and_source_refs(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("Traceable content line", encoding="utf-8")

    output = ParserService().parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["source_references"], "expected source references for parsed text"


def test_image_extension_returns_ocr_not_implemented_stub(tmp_path: Path) -> None:
    file_path = tmp_path / "scan.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n placeholder bytes")

    output = ParserService().parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["status"] == "failed"
    assert any(w["code"] == "ocr_not_implemented" for w in output["warnings"])
