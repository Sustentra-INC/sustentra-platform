from pathlib import Path
from typing import Any

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


def test_an_excel_97_2003_workbook_routes_to_the_xls_parser(tmp_path: Path) -> None:
    from backend.tests.adapters.parsers._xls_builder import xls_bytes

    workbook = xls_bytes({"Log": [["Gallons", 450]]})
    for name, mime in (("log.xls", None), ("LOG.XLS", None), ("export", "application/vnd.ms-excel")):
        path = tmp_path / name
        path.write_bytes(workbook)
        output = ParserService().parse_document(path, document_id="DOC-1", processing_run_id="RUN-1", mime_type=mime)
        assert_parser_output_shape(output)
        assert (output["status"], output["parser_name"]) == ("parsed", "xlrd")
        assert [block["text"] for block in output["text_blocks"]] == ["Gallons", "450"]
    assert ParserService.parser_kind(Path("log.xls")) == "xls"
    assert ParserService.parser_kind(Path("export"), "application/vnd.ms-excel; charset=binary") == "xls"


def test_an_email_routes_to_the_email_parser(tmp_path: Path) -> None:
    raw = b"From: billing@acme.example\r\nSubject: February\r\n\r\nTotal Usage: 120 therms\r\n"
    for name, mime in (("bill.eml", None), ("BILL.EML", None), ("message", "message/rfc822")):
        path = tmp_path / name
        path.write_bytes(raw)
        output = ParserService().parse_document(path, document_id="DOC-1", processing_run_id="RUN-1", mime_type=mime)
        assert_parser_output_shape(output)
        assert (output["status"], output["parser_name"]) == ("parsed", "email_parser")
        assert output["text_blocks"][-1]["text"] == "Total Usage: 120 therms"
    assert ParserService.parser_kind(Path("bill.eml")) == "email"
    assert ParserService.parser_kind(Path("bill.msg")) is None  # Outlook's own format: not read yet


def test_an_xlsx_with_no_extension_is_read_by_its_media_type(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "Metric"
    path = tmp_path / "export"  # openpyxl itself refuses a file name without an Excel extension
    workbook.save(tmp_path / "export.xlsx")
    path.write_bytes((tmp_path / "export.xlsx").read_bytes())

    output = ParserService().parse_document(
        path, document_id="DOC-1", processing_run_id="RUN-1",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert (output["status"], output["parser_name"]) == ("parsed", "openpyxl")


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


# --- scans with typed text on them (a stamp, a fax header) ------------------------------------------------

STAMP = "RECEIVED 12 MAR 2025 ACME CORP MAIL ROOM"  # 33 characters: over the 20 of an empty page


def _picture():
    import fitz

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.clear_with(210)
    return pix


def _scan_pdf(path: Path, pages: list[dict]) -> Path:
    """Each page: ``images`` (rects), ``text`` (typed lines at the top), optional ``rotate``/``cropbox``."""

    import fitz

    with fitz.open() as pdf:
        for spec in pages:
            width, height = spec.get("size") or (595, 842)
            page = pdf.new_page(width=width, height=height)
            if spec.get("cropbox"):
                page.set_cropbox(fitz.Rect(*spec["cropbox"]))
            for rect in spec.get("images", []):
                page.insert_image(fitz.Rect(*rect), pixmap=_picture(), keep_proportion=False)
            for index, line in enumerate(spec.get("text", [])):
                page.insert_text((72, 60 + 14 * index), line, fontsize=spec.get("fontsize", 11))
            if spec.get("rotate"):
                page.set_rotation(spec["rotate"])
        pdf.save(path)
    return path


FULL = (0, 0, 595, 842)  # an A4 page


class RecordingTextract(FakeLiveTextractParser):
    """Reads every page as the given lines (a stamp included or not)."""

    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.lines = lines

    def parse_bytes(self, document_bytes: bytes, document_id: str, processing_run_id: str) -> dict:
        self.byte_calls.append(document_bytes)
        n = len(self.byte_calls)
        out = self.parse(Path("page.png"), document_id, processing_run_id)
        self.calls.pop()
        out["pages"] = [{"page_number": 1, "text": "\n".join(self.lines)}]
        out["text_blocks"] = [{"block_id": f"tx-{n}-{i}", "text": t, "page_number": 1, "confidence": 0.9,
                               "bounding_box": {"left": 0.1, "top": 0.1 * i, "width": 0.5, "height": 0.03},
                               "source_reference_id": f"SRC-tx-{n}-{i}"} for i, t in enumerate(self.lines)]
        out["source_references"] = [{"source_reference_id": f"SRC-tx-{n}-{i}", "document_id": document_id,
                                     "page_number": 1, "sheet_name": None, "cell_or_range": None,
                                     "text_snippet": t, "bounding_box": None, "parser_block_ids": [f"tx-{n}-{i}"]}
                                    for i, t in enumerate(self.lines)]
        return out


@pytest.mark.parametrize("spec,expected", [
    ({"images": [FULL], "text": [STAMP]}, True),  # a scan with a stamp
    ({"images": [(0, 0, 595, 421), (0, 421, 595, 842)], "text": [STAMP]}, True),  # a scan in two strips
    ({"images": [FULL, FULL, (0, 0, 595, 300)], "text": [STAMP]}, True),  # overlapping images
    ({"images": [FULL], "text": [STAMP], "rotate": 90}, True),  # a turned scan
    ({"images": [(100, 100, 200, 200)], "text": [STAMP]}, False),  # a logo
    ({"images": [(0, 0, 595, 350)], "text": [STAMP]}, False),  # under half the page
    ({"images": [FULL, FULL, FULL], "text": [STAMP] * 1}, True),
    ({"images": [FULL], "text": [f"Line {i} of an invoice with real words" for i in range(8)]}, False),  # watermark
    ({"images": [FULL], "text": ["Quarterly Review of Site Energy"], "fontsize": 40}, False),  # a designed cover: big type
    ({"images": [(0, 0, 960, 540)], "text": [STAMP], "size": (960, 540)}, False),  # a slide: not paper-shaped
    ({"images": [], "text": [STAMP]}, False),  # vector page: nothing to measure
    ({"images": [FULL], "text": [STAMP], "cropbox": (50, 50, 560, 700)}, False),  # cropped: not measured
])
def test_a_page_mostly_image_with_a_little_text_is_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spec: dict, expected: bool
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live = RecordingTextract(["Total kWh Used: 700,000 kWh"])
    path = _scan_pdf(tmp_path / "bill.pdf", [spec])

    output = ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")

    assert (len(live.byte_calls) == 1) is expected
    assert ("ocr_applied" in [w["code"] for w in output["warnings"]]) is expected


def test_a_searchable_scan_stays_a_text_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live = RecordingTextract(["x"])
    text = [f"Searchable line {i} from a scan with an OCR layer" for i in range(6)]  # ~280 characters
    path = _scan_pdf(tmp_path / "searchable.pdf", [{"images": [FULL], "text": text}])

    ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")

    assert live.byte_calls == []


def test_ocr_replaces_the_typed_lines_it_read_and_keeps_the_ones_it_did_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live = RecordingTextract(["Electricity bill", "Total kWh Used: 700,000 kWh", "RECEIVED 12 MAR 2025"])
    path = _scan_pdf(tmp_path / "bill.pdf", [
        {"text": ["Cover page text that is typed and long enough"]},
        {"images": [FULL], "text": ["RECEIVED 12 MAR 2025", "Fax ref ZX-991 ACME"]},  # stamp OCR reads; fax line it misses
    ])

    output = ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")

    assert_parser_output_shape(output)
    page2 = [b["text"] for b in output["text_blocks"] if b["page_number"] == 2]
    assert page2.count("RECEIVED 12 MAR 2025") == 1  # read once: OCR's, not the typed copy too
    assert "Fax ref ZX-991 ACME" in page2 and "Total kWh Used: 700,000 kWh" in page2
    assert [b["text"] for b in output["text_blocks"] if b["page_number"] == 1] == [
        "Cover page text that is typed and long enough"]  # a text page is untouched
    text = output["pages"][1]["text"]
    assert text.count("RECEIVED 12 MAR 2025") == 1 and text.endswith("Fax ref ZX-991 ACME")
    ids = {b["block_id"] for b in output["text_blocks"]}
    assert all(set(r["parser_block_ids"]) <= ids for r in output["source_references"] if r["page_number"] == 2)
    assert all(r["page_number"] in (1, 2) for r in output["source_references"])
    assert len({r["source_reference_id"] for r in output["source_references"]}) == len(output["source_references"])


def test_a_stamped_scan_is_named_when_textract_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.pdf_scan_pages import unread_scan_pages

    monkeypatch.delenv("TEXTRACT_ENABLED", raising=False)
    live = RecordingTextract(["x"])
    path = _scan_pdf(tmp_path / "bill.pdf", [{"text": ["Typed page with enough words to count as text here"]},
                                             {"images": [FULL], "text": [STAMP]}])

    output = ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")

    warning = next(w for w in output["warnings"] if w["code"] == "scan_page_unread")
    assert warning["message"].startswith("Page 2 is a scan") and "Textract" not in warning["message"]
    assert unread_scan_pages(output) == [(2, 2)] and live.byte_calls == []


def test_pages_over_the_ocr_limit_are_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services import parser_service
    from backend.app.services.pdf_scan_pages import unread_scan_pages

    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    monkeypatch.setattr(parser_service, "OCR_MAX_PAGES", 2)
    path = _scan_pdf(tmp_path / "many.pdf", [{"images": [FULL], "text": [STAMP]}] * 5)

    output = ParserService(live_textract_parser=RecordingTextract(["a b c d"])).parse_document(path, "DOC-1", "RUN-1")

    limit = next(w for w in output["warnings"] if w["code"] == "ocr_page_limit")
    assert limit["message"].startswith("Pages 3-5 are scans and were not read")
    assert unread_scan_pages(output) == [(3, 5)]


def test_a_failed_ocr_page_is_listed_as_unread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.pdf_scan_pages import unread_scan_pages

    class Failing(RecordingTextract):
        def parse_bytes(self, *args: Any) -> dict:
            return {"status": "failed"}

    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    path = _scan_pdf(tmp_path / "bill.pdf", [{"images": [FULL], "text": [STAMP]}])

    output = ParserService(live_textract_parser=Failing(["x"])).parse_document(path, "DOC-1", "RUN-1")

    assert unread_scan_pages(output) == [(1, 1)]
    assert "ocr_page_failed" in [w["code"] for w in output["warnings"]]


def test_a_chunk_reads_stamped_scans_like_the_whole_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    live = RecordingTextract(["Total kWh Used: 700,000 kWh", "RECEIVED 12 MAR 2025"])
    path = _scan_pdf(tmp_path / "bill.pdf", [{"text": ["Typed page with enough words to count as text here"]},
                                             {"images": [FULL], "text": ["RECEIVED 12 MAR 2025", "Fax ref ZX-991"]},
                                             {"images": [FULL], "text": [STAMP]}])
    whole = ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")
    live_chunk = RecordingTextract(["Total kWh Used: 700,000 kWh", "RECEIVED 12 MAR 2025"])
    chunk = ParserService(live_textract_parser=live_chunk).parse_document(path, "DOC-1", "RUN-1", pages=(2, 3))

    assert [p["page_number"] for p in chunk["pages"]] == [2, 3]
    assert chunk["pages"] == whole["pages"][1:]
    assert [(b["page_number"], b["text"]) for b in chunk["text_blocks"]] == [
        (b["page_number"], b["text"]) for b in whole["text_blocks"] if b["page_number"] >= 2]


def test_a_page_that_cannot_be_measured_keeps_the_text_only_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fitz

    from backend.app.services import pdf_scan_pages

    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    path = _scan_pdf(tmp_path / "bill.pdf", [{"images": [FULL], "text": [STAMP]}])
    live = RecordingTextract(["x y z w"])

    def boom(self: Any) -> Any:
        raise RuntimeError("corrupt xref")

    monkeypatch.setattr(fitz.Page, "get_image_info", boom)
    output = ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")
    assert output["status"] == "parsed" and live.byte_calls == []

    monkeypatch.undo()
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    monkeypatch.setattr(pdf_scan_pages, "MAX_MEASURED_IMAGES", 0)  # a page drawing too many images
    ParserService(live_textract_parser=live).parse_document(path, "DOC-1", "RUN-1")
    assert live.byte_calls == []


def test_thousands_of_images_on_a_page_are_not_measured(tmp_path: Path) -> None:
    import fitz

    from backend.app.services.pdf_scan_pages import image_cover

    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_image(fitz.Rect(0, 0, 9, 9), pixmap=_picture())
        name = page.get_images(full=True)[0][7]
        stream = "".join(f"q 9 0 0 9 {i % 60 * 10} {i // 60 * 10} cm /{name} Do Q\n" for i in range(3000))
        pdf.update_stream(page.get_contents()[0], stream.encode())
        assert image_cover(page) is None


def test_image_cover_counts_overlaps_once_and_ignores_the_rest(tmp_path: Path) -> None:
    import fitz

    from backend.app.services.pdf_scan_pages import _union_area, image_cover

    assert _union_area([(0, 0, 10, 10), (5, 5, 15, 15), (0, 0, 10, 10)]) == 175.0
    path = _scan_pdf(tmp_path / "p.pdf", [{"images": [(0, 0, 595, 421), (0, 0, 595, 421)]}, {}])
    with fitz.open(path) as pdf:
        assert image_cover(pdf[0]) == pytest.approx(0.5)
        assert image_cover(pdf[1]) == 0.0
