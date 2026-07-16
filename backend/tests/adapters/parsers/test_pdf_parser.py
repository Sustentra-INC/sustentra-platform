from pathlib import Path

import pytest

from backend.app.adapters.parsers.pdf_parser import PdfParser
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


def test_bad_non_pdf_input_is_handled_gracefully(tmp_path: Path) -> None:
    bad_path = tmp_path / "not_a.pdf"
    bad_path.write_bytes(b"this is not a real pdf file")

    output = PdfParser().parse(bad_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] in {"failed", "empty", "partial"}
    assert output["warnings"], "expected a warning for unreadable PDF"


def test_generated_pdf_produces_pages_and_blocks(tmp_path: Path) -> None:
    fitz = pytest.importorskip(
        "fitz", reason="pymupdf not available to generate a PDF fixture"
    )

    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Total Usage 28,100 MMBtu")
    document.save(pdf_path)
    document.close()

    output = PdfParser().parse(pdf_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] in {"parsed", "partial"}
    assert len(output["pages"]) >= 1
    assert output["text_blocks"], "expected extracted text blocks"
    assert any("28,100" in block["text"] for block in output["text_blocks"])


def test_missing_file_raises_is_not_pdf_parser_concern(tmp_path: Path) -> None:
    # The adapter itself is invoked with an existing path by ParserService;
    # here we confirm a directory-like/invalid PDF still returns a normalized output.
    fake_pdf = tmp_path / "empty.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    output = PdfParser().parse(fake_pdf, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] in {"failed", "empty", "partial"}
