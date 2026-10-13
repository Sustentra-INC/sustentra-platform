from pathlib import Path

import pytest

from backend.app.services.parser_service import ParserService
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


class FakeLiveTextractParser:
    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.byte_calls: list[bytes] = []

    def parse_bytes(self, document_bytes: bytes, document_id: str, processing_run_id: str) -> dict:
        """One page image read by Textract: a LINE on its page 1, with a normalized box."""

        self.byte_calls.append(document_bytes)
        output = self.parse(Path("page.png"), document_id, processing_run_id)
        self.calls.pop()
        output["pages"] = [{"page_number": 1, "text": "Total kWh Used: 700,000 kWh"}]
        output["text_blocks"] = [{"block_id": f"tx-{len(self.byte_calls)}", "text": "Total kWh Used: 700,000 kWh",
                                  "page_number": 1, "confidence": 0.99,
                                  "bounding_box": {"left": 0.1, "top": 0.4, "width": 0.5, "height": 0.03},
                                  "source_reference_id": f"SRC-tx-{len(self.byte_calls)}"}]
        output["source_references"] = [{"source_reference_id": f"SRC-tx-{len(self.byte_calls)}",
                                        "document_id": document_id, "page_number": 1, "sheet_name": None,
                                        "cell_or_range": None, "text_snippet": "Total kWh Used: 700,000 kWh",
                                        "bounding_box": {"x": 0.1, "y": 0.4, "width": 0.5, "height": 0.03},
                                        "parser_block_ids": [f"tx-{len(self.byte_calls)}"]}]
        return output

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


def test_textract_enabled_reads_an_unopenable_pdf_whole(
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


def _pdf(path: Path, page_texts: list[str]) -> Path:
    import fitz

    with fitz.open() as pdf:
        for text in page_texts:
            page = pdf.new_page()
            if text:
                page.insert_text((72, 72), text)
        pdf.save(path)
    return path


def test_textract_enabled_leaves_a_text_pdf_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live_parser = FakeLiveTextractParser()
    path = _pdf(tmp_path / "bill.pdf", ["Electricity bill  Total kWh Used: 1,200 kWh", "Page two of the bill text"])

    output = ParserService(live_textract_parser=live_parser).parse_document(path, "DOC-1", "RUN-1")

    assert output["status"] == "parsed" and output["parser_name"] != "aws_textract"
    assert live_parser.calls == [] and live_parser.byte_calls == []


def test_textract_enabled_reads_only_the_pages_without_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live_parser = FakeLiveTextractParser()
    path = _pdf(tmp_path / "mixed.pdf", ["Cover letter with enough text to count", "", "Back page text that counts"])

    output = ParserService(live_textract_parser=live_parser).parse_document(path, "DOC-1", "RUN-1")

    assert_parser_output_shape(output)
    assert len(live_parser.byte_calls) == 1 and live_parser.byte_calls[0].startswith(b"\x89PNG")
    assert output["status"] == "parsed"
    assert output["pages"][1] == {"page_number": 2, "text": "Total kWh Used: 700,000 kWh"}
    ocr_block = next(b for b in output["text_blocks"] if b["block_id"] == "tx-1")
    assert ocr_block["page_number"] == 2 and ocr_block["bounding_box"]["top"] == 0.4
    assert next(r for r in output["source_references"] if r["source_reference_id"] == "SRC-tx-1")["page_number"] == 2
    codes = [w["code"] for w in output["warnings"]]
    assert "ocr_applied" in codes and "empty_page_text" not in codes


def test_scanned_pages_stay_flagged_without_textract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEXTRACT_ENABLED", raising=False)
    live_parser = FakeLiveTextractParser()
    path = _pdf(tmp_path / "mixed.pdf", ["Cover letter with enough text to count", ""])

    output = ParserService(live_textract_parser=live_parser).parse_document(path, "DOC-1", "RUN-1")

    assert output["status"] == "partial" and live_parser.byte_calls == []
    assert any(w["code"] == "empty_page_text" for w in output["warnings"])


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
