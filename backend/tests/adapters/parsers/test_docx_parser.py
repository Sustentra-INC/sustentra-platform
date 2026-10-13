"""Word (.docx) bills: read into lines, then extracted like any other bill."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from backend.app.adapters.parsers.docx_parser import DocxParser, docx_text
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.parser_service import ParserService
from backend.app.services.stationary_combustion_extractor import StationaryCombustionExtractor

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str) -> str:
    runs = "<w:tab/>".join(f"<w:r><w:t xml:space=\"preserve\">{part}</w:t></w:r>" for part in text.split("\t"))
    return f"<w:p>{runs}</w:p>"


def _table(rows: list[list[str]]) -> str:
    cells = "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>" for row in rows)
    return f"<w:tbl>{cells}</w:tbl>"


def _docx(tmp_path: Path, body: str, header: str | None = None, name: str = "bill.docx") -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document {NS}><w:body>{body}</w:body></w:document>")
        if header:
            archive.writestr("word/header1.xml", f"<w:hdr {NS}>{header}</w:hdr>")
    path = tmp_path / name
    path.write_bytes(buffer.getvalue())
    return path


GAS_BILL = (
    _p("Facility Name\tEastside Bakery")
    + _p("Service Address\t9 Oven Lane, Dayton, OH 45402")
    + _p("Service Period\t03/01/2024 to 03/31/2024")
    + _table([["Meter ID", "Previous Read", "Current Read", "Usage", "Unit"], ["M-1", "100", "412", "312", "Therms"]])
)


def test_paragraphs_tables_and_headers_become_lines_in_order(tmp_path: Path) -> None:
    path = _docx(tmp_path, GAS_BILL, header=_p("Riverside Gas Utilities Inc."))
    assert docx_text(path).splitlines() == [
        "Riverside Gas Utilities Inc.",
        "Facility Name\tEastside Bakery",
        "Service Address\t9 Oven Lane, Dayton, OH 45402",
        "Service Period\t03/01/2024 to 03/31/2024",
        "Meter ID\tPrevious Read\tCurrent Read\tUsage\tUnit",
        "M-1\t100\t412\t312\tTherms",
    ]


def test_a_word_gas_bill_is_extracted_like_any_other(tmp_path: Path) -> None:
    path = _docx(tmp_path, GAS_BILL, header=_p("Riverside Gas Utilities Inc."))
    output = ParserService().parse_document(path, "DOC-1", "RUN-1")
    assert output["status"] == "parsed" and output["parser_name"] == "docx_parser"
    targets = ExtractionTargetService().get_targets_for_canonical_type("CT-S1-FUELQTY")
    fields = {c["field_name"]: c for c in StationaryCombustionExtractor().extract(output, targets, "EV-1").candidates}
    assert fields["activity_quantity"]["normalized_value"] == 31.2  # 312 therms
    assert fields["facility_name"]["normalized_value"] == "Eastside Bakery"
    assert fields["service_period_start"]["normalized_value"] == "2024-03-01"


def test_unsafe_or_broken_files_fail_with_a_reason(tmp_path: Path) -> None:
    doctype = _docx(tmp_path, "", name="evil.docx")
    with zipfile.ZipFile(doctype, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "a">]><w:document/>')
    failed = DocxParser().parse(doctype, "DOC-1", "RUN-1")
    assert failed["status"] == "failed" and "DOCTYPE" in failed["warnings"][0]["message"]

    not_zip = tmp_path / "fake.docx"
    not_zip.write_bytes(b"this is not a zip")
    assert "could not be opened" in DocxParser().parse(not_zip, "DOC-2", "RUN-1")["warnings"][0]["message"]
