from pathlib import Path

import pytest

from backend.app.services.parser_service import ParserService
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


class FakeLiveTextractParser:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        self.calls.append(Path(file_path))
        return {
            "parser_output_id": f"PO-aws_textract-{document_id}-{processing_run_id}",
            "document_id": document_id,
            "processing_run_id": processing_run_id,
            "parser_name": "aws_textract",
            "parser_version": "v0",
            "status": "parsed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "pages": [{"page_number": 1, "text": "Textract text"}],
            "text_blocks": [],
            "tables": [],
            "key_value_pairs": [],
            "source_references": [],
            "warnings": [],
            "raw_artifact_uri": None,
        }


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


def test_csv_file_routes_to_csv_parser(tmp_path: Path) -> None:
    file_path = tmp_path / "usage.csv"
    file_path.write_text("Month,Usage\nJanuary,32400\n", encoding="utf-8")

    output = ParserService().parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "csv_parser"
    assert output["tables"][0]["rows"][1] == ["January", "32400"]


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


def test_csv_mime_type_routes_when_extension_unknown(tmp_path: Path) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_text("Month,Usage\nJanuary,32400\n", encoding="utf-8")

    output = ParserService().parse_document(
        file_path,
        document_id="DOC-1",
        processing_run_id="RUN-1",
        mime_type="text/csv",
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "csv_parser"
    assert output["tables"][0]["rows"][0] == ["Month", "Usage"]


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


def test_textract_enabled_routes_pdf_to_live_textract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    file_path = tmp_path / "scan.pdf"
    file_path.write_bytes(b"%PDF placeholder bytes")
    live_parser = FakeLiveTextractParser()

    output = ParserService(live_textract_parser=live_parser).parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "aws_textract"
    assert live_parser.calls == [file_path]


def test_textract_enabled_routes_image_to_live_textract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "yes")
    file_path = tmp_path / "scan.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n placeholder bytes")
    live_parser = FakeLiveTextractParser()

    output = ParserService(live_textract_parser=live_parser).parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "aws_textract"
    assert live_parser.calls == [file_path]


def test_textract_enabled_does_not_route_text_to_live_textract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    file_path = tmp_path / "note.txt"
    file_path.write_text("Hello world", encoding="utf-8")
    live_parser = FakeLiveTextractParser()

    output = ParserService(live_textract_parser=live_parser).parse_document(
        file_path, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert output["parser_name"] == "text_parser"
    assert live_parser.calls == []
