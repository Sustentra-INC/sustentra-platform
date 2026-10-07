"""S1-BE-001 - decide how a stored upload may be served back to the browser.

The upload's ``mime_type`` comes from the client, so it is never trusted for
what the browser renders. The served type is decided from the file's own bytes
(PDF / PNG / JPEG magic numbers); a few spreadsheet types are recognised by
extension for downloads only. Everything else downloads as
``application/octet-stream``. Only PDF and raster images can be previewed
inline: an inline HTML or SVG upload on the app's origin would run script there.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OCTET_STREAM = "application/octet-stream"

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

# Download-only types, by extension (never rendered inline).
_DOWNLOAD_BY_EXTENSION = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

PREVIEWABLE = frozenset(media for _, media in _MAGIC)


@dataclass(frozen=True)
class ServedType:
    media_type: str
    previewable: bool


def served_type(path: Path, file_name: str | None = None) -> ServedType:
    with path.open("rb") as handle:
        head = handle.read(16)
    for magic, media in _MAGIC:
        # PDFs may carry a few junk bytes before the header; browsers accept up to 1 KB.
        if head.startswith(magic) or (magic == b"%PDF-" and _pdf_header_within_first_kb(path)):
            return ServedType(media, previewable=True)
    extension = Path(file_name or path.name).suffix.lower()
    return ServedType(_DOWNLOAD_BY_EXTENSION.get(extension, OCTET_STREAM), previewable=False)


def _pdf_header_within_first_kb(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"%PDF-" in handle.read(1024)
