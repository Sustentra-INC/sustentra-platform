"""Word (.docx) parser adapter.

A .docx file is a zip of XML parts; the body text lives in ``word/document.xml``.
Paragraphs become lines and each table row becomes one tab-separated line, in the
order they appear, so the layout-aware extractors read Word bills the way they read
tab-separated text (label/value pairs and usage tables). Headers and footers are
read too (utility names and account numbers often sit there).

Only the standard library is used. The XML is refused if it declares a DOCTYPE
(no entity tricks) and the parts read are capped in size.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from backend.app.adapters.parsers.base import build_failed_parser_output, build_warning
from backend.app.adapters.parsers.text_parser import TextParser

PARSER_NAME = "docx_parser"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_PART_BYTES = 20 * 1024 * 1024


class DocxError(ValueError):
    pass


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_PART_BYTES:
        raise DocxError("The Word document is too large to read.")
    data = archive.read(info)
    if b"<!DOCTYPE" in data[:4096].upper():
        raise DocxError("The Word document declares a DOCTYPE, which is not accepted.")
    return data


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)


def _lines(xml: bytes) -> list[str]:
    root = ElementTree.fromstring(xml)
    body = root.find(f"{_W}body")
    container = body if body is not None else root
    lines: list[str] = []
    for child in container:
        if child.tag == f"{_W}p":
            lines.extend(_paragraph_text(child).split("\n"))
        elif child.tag == f"{_W}tbl":
            for row in child.iter(f"{_W}tr"):
                cells = [
                    " ".join(t for t in (_paragraph_text(p).strip() for p in cell.iter(f"{_W}p")) if t)
                    for cell in row.findall(f"{_W}tc")
                ]
                if any(cells):
                    lines.append("\t".join(cells))
    return lines


def docx_text(path: Path) -> str:
    """The document as text: header lines, then the body, then footer lines."""

    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            body = _read_part(archive, "word/document.xml")
            if body is None:
                raise DocxError("This is not a Word document (word/document.xml is missing).")
            headers = sorted(n for n in names if n.startswith("word/header") and n.endswith(".xml"))
            footers = sorted(n for n in names if n.startswith("word/footer") and n.endswith(".xml"))
            lines: list[str] = []
            for name in headers:
                part = _read_part(archive, name)
                if part:
                    lines.extend(_lines(part))
            lines.extend(_lines(body))
            for name in footers:
                part = _read_part(archive, name)
                if part:
                    lines.extend(_lines(part))
    except zipfile.BadZipFile as exc:
        raise DocxError("The file is not a valid .docx (it could not be opened).") from exc
    except ElementTree.ParseError as exc:
        raise DocxError("The Word document's text could not be read.") from exc
    return "\n".join(lines)


class DocxParser(TextParser):
    """Adapter that normalizes .docx files into ``parser_output`` dicts."""

    parser_name = PARSER_NAME

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        try:
            text = docx_text(Path(file_path))
        except DocxError as exc:
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[build_warning("unreadable_docx", str(exc), severity="error")],
            )
        return self.parse_text(text, document_id, processing_run_id, [])
