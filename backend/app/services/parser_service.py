"""Parser runtime service (PR4).

Routes a local document file to the appropriate parser adapter and returns a
normalized ``parser_output``-shaped dictionary conforming to
``contracts/parser_output.schema.json``.

Scope for runtime v0:
    * detection by file extension and/or mime type
    * text / Word / Excel (.xlsx and 97-2003 .xls) / CSV / PDF / email (.eml) parsing and an
      explicit image stub
    * optional live Textract when ``TEXTRACT_ENABLED`` is true: images, and only the
      PDF pages without a text layer (rendered, one synchronous call per page)
    * Textract JSON normalization via an explicit method

Out of scope (later PRs): field extraction, extraction_candidate generation,
review persistence, RAG, and S2 methodology. By default this service makes no
external network, AWS, or OpenAI calls.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_failed_parser_output,
    build_warning,
    make_parser_output_id,
)
from backend.app.adapters.parsers.csv_parser import CsvParser
from backend.app.adapters.parsers.excel_parser import ExcelParser
from backend.app.adapters.parsers.image_parser import ImageParser
from backend.app.adapters.parsers.docx_parser import DocxParser
from backend.app.adapters.parsers.email_parser import EmailParser
from backend.app.adapters.parsers.pdf_parser import PdfParser
from backend.app.adapters.parsers.text_parser import TextParser
from backend.app.adapters.parsers.textract_parser import TextractParser
from backend.app.adapters.parsers.xls_parser import XlsParser
from backend.app.services.pdf_scan_pages import (
    OCR_PAGE_LIMIT,
    SCAN_CAP_REACHED,
    SCAN_MAX_TYPED_CHARACTERS,
    SCAN_UNCHECKED,
    SCAN_PAGE_UNREAD,
    is_blank,
    is_scan_with_text,
    unread_scan_message,
)

from backend.app.services.textract_calls import textract_context

logger = logging.getLogger("sustentra.parser_service")

# Warnings that mean a page was left unread because a call failed: such an output is read again next time.
_NOT_KEPT_WARNINGS = {"ocr_page_failed", "textract_call_failed", SCAN_CAP_REACHED, SCAN_UNCHECKED}

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
CSV_EXTENSIONS = {".csv"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
LEGACY_EXCEL_EXTENSIONS = {".xls"}  # Excel 97-2003 (BIFF)
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
EMAIL_EXTENSIONS = {".eml"}  # the message text; attachments are listed, not read
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".bmp", ".webp"}

MIME_TYPE_ROUTES = {
    "text/plain": "text",
    "text/markdown": "text",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.ms-excel": "xls",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "message/rfc822": "email",
}


# A page with fewer non-space characters than this has no usable text layer (a scan, or a
# stamp on an image); with Textract on it is rendered and read. A page with a little more typed text
# that is mostly image is a scan too (see pdf_scan_pages).
OCR_MIN_PAGE_CHARACTERS = 20
OCR_MAX_PAGES = 50  # per document: Textract is billed per page
OCR_ZOOM = 2.0  # ~150 dpi for a letter page, well under the 10 MB synchronous limit


_BACKEND_APP = Path(__file__).resolve().parents[1]
# Every module whose code shapes a parser output: all the parser adapters, the PDF scan rules and this file.
PARSER_SOURCE_FILES: tuple[Path, ...] = (
    *sorted((_BACKEND_APP / "adapters" / "parsers").glob("*.py")),
    _BACKEND_APP / "services" / "pdf_scan_pages.py",
    Path(__file__).resolve(),
)


def reader_source_digest(files: Any = PARSER_SOURCE_FILES) -> str:
    """A short sha256 over the names and source of ``files``. An unreadable file counts as its name only."""

    digest = hashlib.sha256()
    for path in files:
        digest.update(Path(path).name.encode())
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            digest.update(b"?")
    return digest.hexdigest()[:12]


_SOURCE_DIGEST = reader_source_digest()  # once, at import


def _sha256_of(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _worth_keeping(output: Any) -> bool:
    """A finished read: not failed, and no page left unread because a call failed (that is tried again)."""

    if not isinstance(output, dict) or output.get("status") not in ("parsed", "partial", "empty"):
        return False
    return not any(isinstance(w, dict) and w.get("code") in _NOT_KEPT_WARNINGS
                   for w in output.get("warnings") or [])


def _swap_strings_in_place(root: Any, swaps: dict[str, str]) -> None:
    """Replace, inside ``root`` itself, every string equal to a key of ``swaps``. No second copy is built."""

    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            items: Any = list(node.items())
            for key, value in items:
                if isinstance(value, str):
                    if value in swaps:
                        node[key] = swaps[value]
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, str):
                    if value in swaps:
                        node[index] = swaps[value]
                elif isinstance(value, (dict, list)):
                    stack.append(value)


def _for_run(kept: dict, document_id: str, processing_run_id: str) -> dict:
    """Kept output as this read's own: the ids of the document and run it carries are this read's.
    ``kept`` is the store's own fresh copy, so it is changed in place (a large output is never held twice)."""

    swaps: dict[str, str] = {}
    for key, new in (("document_id", document_id), ("processing_run_id", processing_run_id)):
        old = kept.get(key)
        if isinstance(old, str) and old and old != new:
            swaps[old] = new
    if swaps:
        _swap_strings_in_place(kept, swaps)
    kept["document_id"] = document_id
    kept["processing_run_id"] = processing_run_id
    kept["parser_output_id"] = make_parser_output_id(
        document_id, processing_run_id, str(kept.get("parser_name") or "parser"))
    return kept


def _squash(text: str) -> str:
    """Lower-case letters and digits only: lines compare the same whatever the spacing or punctuation."""

    return re.sub(r"[\W_]+", "", text.lower())


def _not_read_by_ocr(line: str, ocr_all: str, ocr_lines: set[str]) -> bool:
    """A typed line OCR left out: not inside OCR's text (a short one: not one of OCR's lines)."""

    key = _squash(line)
    if not key:
        return False
    return key not in ocr_all if len(key) >= 4 else key not in ocr_lines


class ParserService:
    """Detects the correct parser adapter and produces ``parser_output`` dicts."""

    # Names the reader code: it changes whenever a module that shapes the stored output changes, so kept text
    # from before a parser fix is read again (see ``reader_source_digest``).
    READER_VERSION = f"{PARSER_RUNTIME_VERSION}-{_SOURCE_DIGEST}"

    def __init__(self, live_textract_parser: AwsTextractParser | None = None,
                 parsed_texts: Any | None = None) -> None:
        # The store of kept parser outputs; None: the app's own (``s1_stores.parsed_texts``), opened on first use.
        self._parsed_texts = parsed_texts
        self._text_parser = TextParser()
        self._csv_parser = CsvParser()
        self._excel_parser = ExcelParser()
        self._xls_parser = XlsParser(self._excel_parser)
        self._pdf_parser = PdfParser()
        self._docx_parser = DocxParser()
        self._email_parser = EmailParser()
        self._image_parser = ImageParser()
        self._textract_parser = TextractParser()
        self._live_textract_parser = live_textract_parser or AwsTextractParser()

    def reader_version(self) -> str:
        """Names everything that changes what a read produces: the reader build, whether OCR is on, and
        the OCR settings. Kept text is reused only under the same version, so switching OCR on re-reads
        the scans a read without OCR left unread."""

        if not self._textract_enabled():
            return f"{self.READER_VERSION}|ocr=off"
        features = os.environ.get("TEXTRACT_FEATURE_TYPES", "FORMS,TABLES").upper().replace(" ", "")
        return (f"{self.READER_VERSION}|ocr=on|{features}|zoom={OCR_ZOOM}|max={OCR_MAX_PAGES}"
                f"|min={OCR_MIN_PAGE_CHARACTERS}")

    def parse_document(
        self,
        file_path: str | Path,
        document_id: str,
        processing_run_id: str,
        mime_type: str | None = None,
        pages: tuple[int, int] | None = None,
        org_id: str | None = None,
    ) -> dict:
        """Parse a local file into a normalized ``parser_output`` dictionary.

        ``pages`` (PDF only; 1-based, inclusive): read only those pages, which keep the
        document's own page numbers. The OCR page cap then applies to that range.

        ``org_id``: when given, the output is kept under (organization, SHA-256 of the file, reader
        version, pages) and reused by every later read of the same bytes in that organization, so a scan
        is sent to Textract once. Another organization's rows are never read. Without it nothing is kept.

        Raises ``FileNotFoundError`` when the input path itself is invalid. All
        other parser-level problems are reported as ``failed``/``partial``
        ``parser_output`` objects rather than raised exceptions.
        """

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Parser input file not found: {file_path}")

        digest = _sha256_of(path) if org_id else None
        with textract_context(org_id=org_id, document_id=document_id, sha256=digest):
            store = self._store() if digest else None
            if store is None or digest is None or org_id is None:
                return self._read_document(path, document_id, processing_run_id, mime_type, pages)
            version = self.reader_version()
            page_from, page_to = pages if pages else (0, 0)
            kind = path.suffix.lower() + (f"|{mime_type.split(';', 1)[0].strip().lower()}" if mime_type else "")
            try:
                kept = store.get(org_id, digest, version, page_from, page_to, kind)
            except Exception as exc:  # noqa: BLE001 - a store fault means "not kept": read the file
                logger.warning("kept text unreadable (%s); reading the file", type(exc).__name__)
                kept = None
            if kept is not None:
                return _for_run(kept, document_id, processing_run_id)
            output = self._read_document(path, document_id, processing_run_id, mime_type, pages)
            if _worth_keeping(output):
                try:
                    store.put(org_id, digest, version, page_from, page_to, output, kind)
                except Exception as exc:  # noqa: BLE001 - the read succeeded; keeping it is best effort
                    logger.warning("parsed text not kept (%s)", type(exc).__name__)
            return output

    def _store(self) -> Any | None:
        if self._parsed_texts is None:
            try:
                from backend.app.repositories.s1_stores import parsed_texts

                self._parsed_texts = parsed_texts()
            except Exception as exc:  # noqa: BLE001
                logger.warning("parsed-text store unavailable (%s)", type(exc).__name__)
                return None
        return self._parsed_texts

    def _read_document(self, path: Path, document_id: str, processing_run_id: str, mime_type: str | None,
                       pages: tuple[int, int] | None) -> dict:
        parser_kind = self._detect_parser_kind(path, mime_type)

        if parser_kind == "text":
            return self._text_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "docx":
            return self._docx_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "email":
            return self._email_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "csv":
            return self._csv_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "excel":
            return self._excel_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "xls":
            return self._xls_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "image" and self._textract_enabled():
            return self._live_textract_parser.parse(path, document_id, processing_run_id)
        if parser_kind == "pdf":
            return self._parse_pdf(path, document_id, processing_run_id, pages)
        if parser_kind == "image":
            return self._image_parser.parse(path, document_id, processing_run_id)

        return build_failed_parser_output(
            document_id=document_id,
            processing_run_id=processing_run_id,
            parser_name="parser_service",
            warnings=[
                build_warning(
                    "unsupported_file_type",
                    f"No parser is available for extension '{path.suffix}' "
                    f"or mime type '{mime_type}'.",
                    severity="error",
                )
            ],
        )

    def parse_textract_json(
        self,
        textract_source: dict[str, Any] | str | Path,
        document_id: str,
        processing_run_id: str,
    ) -> dict:
        """Normalize already-saved Textract JSON (dict or file). Never calls AWS."""

        return self._textract_parser.parse(textract_source, document_id, processing_run_id)

    def _parse_pdf(self, path: Path, document_id: str, processing_run_id: str,
                   pages: tuple[int, int] | None = None) -> dict:
        """A PDF's own text layer first. With Textract on, only the scan pages are rendered and read
        by Textract, one page per synchronous call, so text PDFs never leave the server and a
        multi-page scan needs no S3 round trip. A scan page has no text layer, or is mostly image
        with only a little typed text on it (a stamp, a fax header). A PDF the local reader cannot
        open goes to Textract whole. Scan pages that are not read are named in a warning."""

        output = self._pdf_parser.parse(path, document_id, processing_run_id, pages)
        enabled = self._textract_enabled()
        if enabled and output.get("status") == "failed" and pages is None:  # a chunk is retried, not read whole
            return self._live_textract_parser.parse(path, document_id, processing_run_id)
        stamped = self._scans_with_text(path, output)
        if not enabled:
            if stamped:
                output = {**output, "warnings": [*(output.get("warnings") or []), build_warning(
                    SCAN_PAGE_UNREAD, unread_scan_message(
                        stamped, "with some typed text on it; the scan was not read because OCR is off."))]}
            return output
        scanned = sorted({
            *(int(page["page_number"]) for page in output.get("pages") or []
              if len(re.sub(r"\s", "", str(page.get("text") or ""))) < OCR_MIN_PAGE_CHARACTERS),
            *stamped,
        })
        return self._ocr_pages(path, output, scanned, document_id, processing_run_id) if scanned else output

    @staticmethod
    def _scans_with_text(path: Path, output: dict) -> list[int]:
        """Pages with some typed text (too little to be a text page) that are mostly image. Only pages
        in that text band are measured; one that cannot be measured is left as a text page."""

        typed = {int(p["page_number"]): len(re.sub(r"\s", "", str(p.get("text") or "")))
                 for p in output.get("pages") or []}
        band = [n for n, chars in typed.items() if OCR_MIN_PAGE_CHARACTERS <= chars < SCAN_MAX_TYPED_CHARACTERS]
        if not band:
            return []
        found: list[int] = []
        try:
            import fitz

            with fitz.open(path) as pdf:
                for number in band:
                    if 0 < number <= pdf.page_count and is_scan_with_text(pdf[number - 1], typed[number]):
                        found.append(number)
        except Exception:  # noqa: BLE001 - the text-only rule stays when the file cannot be measured
            return []
        return found

    def _ocr_pages(self, path: Path, output: dict, page_numbers: list[int], document_id: str,
                   processing_run_id: str) -> dict:
        import fitz  # PyMuPDF, already used to read PDFs

        merged = {key: list(output.get(key) or []) for key in
                  ("pages", "text_blocks", "tables", "key_value_pairs", "source_references", "warnings")}
        read: list[int] = []
        capped: list[int] = []  # scans left unread because the month's limit is reached, or could not be checked
        cap_code = SCAN_CAP_REACHED
        with fitz.open(path) as pdf:
            for number in page_numbers[:OCR_MAX_PAGES]:
                if capped:  # the limit only grows within a read: no more checks, no more calls
                    capped.append(number)
                    continue
                image = pdf[number - 1].get_pixmap(matrix=fitz.Matrix(OCR_ZOOM, OCR_ZOOM)).tobytes("png")
                page = self._live_textract_parser.parse_bytes(image, document_id, processing_run_id)
                refusal = next((w for w in page.get("warnings") or []
                                if isinstance(w, dict) and w.get("code") in (SCAN_CAP_REACHED, SCAN_UNCHECKED)), None)
                if refusal is not None:
                    capped.append(number)
                    cap_code = str(refusal["code"])
                    continue
                if page.get("status") == "empty" and is_blank(pdf[number - 1]):
                    continue  # the blank back of a sheet: nothing to read, so nothing was missed
                if page.get("status") not in ("parsed", "partial"):
                    merged["warnings"].append(build_warning(
                        "ocr_page_failed", f"Page {number} is a scan and could not be read.", severity="warning"))
                    continue
                read.append(number)
                self._merge_ocr_page(merged, number, page)
        if capped:
            one = len(capped) == 1
            tail = ("because this month's AI and scan limit could not be checked. It will be retried."
                    if cap_code == SCAN_UNCHECKED else
                    f"because this month's AI and scan limit is reached. {'It' if one else 'They'} can be read later.")
            merged["warnings"].append(build_warning(cap_code, unread_scan_message(
                capped, f"and {'was' if one else 'were'} not read {tail}"), severity="warning"))
        if len(page_numbers) > OCR_MAX_PAGES:
            merged["warnings"].append(build_warning(OCR_PAGE_LIMIT, unread_scan_message(
                page_numbers[OCR_MAX_PAGES:],
                f"and were not read: only the first {OCR_MAX_PAGES} scanned pages of a document are read."),
                severity="warning"))
        if read:
            merged["warnings"] = [w for w in merged["warnings"] if not (
                w.get("code") == "empty_page_text" and any(f"Page {n} " in str(w.get("message")) for n in read))]
            merged["warnings"].append(build_warning(
                "ocr_applied", f"Read as a scan (OCR): page {', '.join(map(str, read))}.", severity="info"))
        empty = [p for p in merged["pages"] if not str(p.get("text") or "").strip()]
        status = "parsed" if not empty else "partial" if len(empty) < len(merged["pages"]) else output["status"]
        return {**output, **merged, "status": status}

    @staticmethod
    def _merge_ocr_page(merged: dict, number: int, ocr: dict) -> None:
        """Put one OCR-read page into the merged output. OCR's blocks replace the page's typed ones; a typed
        line OCR did not read (not found in OCR's text) is kept, so nothing typed is lost and nothing is
        read twice. The page's text is OCR's text, then the kept typed lines. Page numbers stay the PDF's."""

        ocr_text = "\n".join(str(p.get("text") or "") for p in ocr.get("pages") or []).strip()
        ocr_all = _squash(ocr_text)
        ocr_lines = {_squash(str(b.get("text") or "")) for b in ocr.get("text_blocks") or []}
        typed = [b for b in merged["text_blocks"] if b.get("page_number") == number]
        kept = [b for b in typed if _not_read_by_ocr(str(b.get("text") or ""), ocr_all, ocr_lines)]
        dropped = {b.get("block_id") for b in typed} - {b.get("block_id") for b in kept}
        merged["text_blocks"] = [b for b in merged["text_blocks"] if b.get("block_id") not in dropped
                                 or b.get("page_number") != number]
        merged["source_references"] = [
            r for r in merged["source_references"]
            if not (r.get("page_number") == number and r.get("parser_block_ids")
                    and set(r["parser_block_ids"]) <= dropped)]
        for key in ("text_blocks", "tables", "key_value_pairs", "source_references"):
            for item in ocr.get(key) or []:
                merged[key].append({**item, "page_number": number})
        text = "\n".join([ocr_text, *(str(b.get("text") or "") for b in kept)]).strip()
        merged["pages"] = [{**p, "text": text} if int(p["page_number"]) == number else p
                           for p in merged["pages"]]

    @staticmethod
    def _textract_enabled() -> bool:
        return os.environ.get("TEXTRACT_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def parser_kind(path: Path, mime_type: str | None = None) -> str | None:
        """Which parser reads this file ("pdf", "excel", "xls", "csv", "docx", "email", "text", "image")."""

        return ParserService._detect_parser_kind(path, mime_type)

    @staticmethod
    def _detect_parser_kind(path: Path, mime_type: str | None) -> str | None:
        """Resolve the parser kind by file extension, then mime type."""

        suffix = path.suffix.lower()
        if suffix in TEXT_EXTENSIONS:
            return "text"
        if suffix in CSV_EXTENSIONS:
            return "csv"
        if suffix in EXCEL_EXTENSIONS:
            return "excel"
        if suffix in LEGACY_EXCEL_EXTENSIONS:
            return "xls"
        if suffix in PDF_EXTENSIONS:
            return "pdf"
        if suffix in DOCX_EXTENSIONS:
            return "docx"
        if suffix in EMAIL_EXTENSIONS:
            return "email"
        if suffix in IMAGE_EXTENSIONS:
            return "image"

        if mime_type:
            normalized = mime_type.split(";", 1)[0].strip().lower()
            if normalized in MIME_TYPE_ROUTES:
                return MIME_TYPE_ROUTES[normalized]
            if normalized.startswith("image/"):
                return "image"

        return None
