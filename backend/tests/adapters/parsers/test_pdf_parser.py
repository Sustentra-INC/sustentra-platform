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


def test_lines_become_blocks_with_normalized_boxes(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz", reason="pymupdf not available to generate a PDF fixture")

    pdf_path = tmp_path / "bill.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((60, 100), "Account Number: A-1", fontsize=10)
    page.insert_text((60, 130), "Total Usage: 1,284 therms", fontsize=10)
    # two cells on one baseline separated by a column gap
    page.insert_text((60, 160), "Qty", fontsize=10)
    page.insert_text((140, 160), "UOM", fontsize=10)
    document.save(pdf_path)
    document.close()

    output = PdfParser().parse(pdf_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    texts = [block["text"] for block in output["text_blocks"]]
    assert texts == ["Account Number: A-1", "Total Usage: 1,284 therms", "Qty", "UOM"]
    usage = output["text_blocks"][1]
    box = usage["bounding_box"]
    assert box["left"] == pytest.approx(0.1, abs=0.01)
    assert 0.14 < box["top"] < 0.16 and 0 < box["width"] < 1 and 0 < box["height"] < 0.05
    reference = next(r for r in output["source_references"] if r["source_reference_id"] == usage["source_reference_id"])
    assert reference["bounding_box"] == {"x": box["left"], "y": box["top"], "width": box["width"], "height": box["height"]}
    assert reference["parser_block_ids"] == [usage["block_id"]]
    assert output["pages"][0]["text"].startswith("Account Number: A-1")
