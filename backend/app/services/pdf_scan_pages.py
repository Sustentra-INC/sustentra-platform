"""Which PDF pages are scans that carry some typed text (a fax header, a "RECEIVED" stamp, a footer).

A page with almost no text is a scan for sure; one with a stamp over a full-page image is a scan too,
but its few typed characters hide it. Such a page is mostly raster image and has little typed text.
A searchable scan (an OCR text layer, hundreds of characters) stays a text page: Textract is billed per page.
Anything that cannot be measured is not a scan here, so the text-only rule stays as it was.
"""

from __future__ import annotations

import re
from typing import Any

SCAN_IMAGE_COVER = 0.5  # share of the page covered by raster images
SCAN_MAX_TYPED_CHARACTERS = 200  # non-space typed characters at or above this: a text page, whatever the images
SCAN_MAX_TYPED_FONT = 14.0  # points on a 792 pt tall page: headers, footers, stamps; titles are larger
SCAN_PAPER_ASPECT = (1.2, 1.7)  # long side over short side of Letter, A4, Legal; slides and receipts are outside
BLANK_ZOOM = 0.5
BLANK_INK_SHADE = 200  # of 255: darker than this is ink, paper and faint scanner noise are lighter
BLANK_MAX_INK = 0.002  # share of the page
MAX_MEASURED_IMAGES = 200  # a page drawing more images than this is not measured (bounded work)


def image_cover(page: Any) -> float | None:
    """Share (0-1) of the page covered by images, overlaps and tiles counted once; ``None`` when it
    cannot be measured (cropped page, unreadable images, zero size, too many images)."""

    try:
        import fitz

        if page.cropbox != page.mediabox:  # image boxes and the page box would not share an origin
            return None
        # image boxes are in the unrotated page; the page's own box may be turned a quarter
        area = fitz.Rect(page.rect * page.derotation_matrix).normalize()
        if area.is_empty or area.width * area.height <= 0:
            return None
        infos = page.get_image_info()
        if len(infos) > MAX_MEASURED_IMAGES:
            return None
        boxes = []
        for info in infos:
            box = fitz.Rect(info["bbox"]).normalize() & area
            if not box.is_empty:
                boxes.append((box.x0, box.y0, box.x1, box.y1))
        return _union_area(boxes) / (area.width * area.height)
    except Exception:  # noqa: BLE001 - a page that cannot be measured keeps the text-only rule
        return None


def _union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Area covered by axis-aligned boxes: sweep the x edges, merge the y spans inside each strip."""

    xs = sorted({x for b in boxes for x in (b[0], b[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((b[1], b[3]) for b in boxes if b[0] <= left and b[2] >= right)
        covered, end = 0.0, None
        for top, bottom in spans:
            if end is None or top > end:
                covered += bottom - top
                end = bottom
            elif bottom > end:
                covered += bottom - end
                end = bottom
        total += covered * (right - left)
    return total


def _paper_shaped(page: Any) -> bool:
    width, height = float(page.rect.width), float(page.rect.height)
    if min(width, height) <= 0:
        return False
    return SCAN_PAPER_ASPECT[0] <= max(width, height) / min(width, height) <= SCAN_PAPER_ASPECT[1]


def _typed_font(page: Any) -> float:
    """Largest typed font on the page, in points as if the page were 792 pt tall."""

    scale = 792.0 / max(float(page.rect.width), float(page.rect.height))
    sizes = [float(span.get("size") or 0) for block in page.get_text("dict").get("blocks", [])
             for line in block.get("lines", []) or [] for span in line.get("spans", []) or []
             if str(span.get("text", "")).strip()]
    return max(sizes, default=0.0) * scale


def is_scan_with_text(page: Any, typed_characters: int) -> bool:
    """True when the page is a paper-shaped sheet that is mostly image, with only a little small typed text on it
    (fax header, footer, stamp). Slides and designed covers (large type, other shapes) are not scans."""

    if typed_characters >= SCAN_MAX_TYPED_CHARACTERS:
        return False
    try:
        if not _paper_shaped(page) or _typed_font(page) > SCAN_MAX_TYPED_FONT:
            return False
    except Exception:  # noqa: BLE001 - not measurable: keep the text-only rule
        return False
    cover = image_cover(page)
    return cover is not None and cover >= SCAN_IMAGE_COVER


def is_blank(page: Any) -> bool:
    """True when almost nothing is drawn on the page (a blank back, with or without scanner specks). Asked only of a
    page OCR found no text on: one with ink on it that OCR could not read is not blank, and is named as unread."""

    try:
        import fitz

        shade = page.get_pixmap(matrix=fitz.Matrix(BLANK_ZOOM, BLANK_ZOOM), colorspace=fitz.csGRAY, alpha=False)
        ink = sum(1 for value in shade.samples if value < BLANK_INK_SHADE)
        return bool(shade.samples) and ink / len(shade.samples) < BLANK_MAX_INK
    except Exception:  # noqa: BLE001 - not measurable: not called blank, so it is still named
        return False


# --- scan pages that were not read: how the parser words them, and how the pipeline finds them again ---

OCR_PAGE_LIMIT = "ocr_page_limit"  # scans beyond the per-document OCR cap
SCAN_PAGE_UNREAD = "scan_page_unread"  # a scan with typed text, OCR off
SCAN_CAP_REACHED = "scan_cap_reached"  # scans not read because the month's AI and scan limit is reached
SCAN_LIMIT_SENTENCE = "Not read: this month's AI and scan limit is reached. It can be read later."
SCAN_UNCHECKED = "scan_limit_unchecked"  # scans not read because the limit could not be checked
SCAN_UNCHECKED_SENTENCE = "Not read: the scan limit could not be checked. It will be retried."
_UNREAD_CODES = (OCR_PAGE_LIMIT, SCAN_PAGE_UNREAD, "ocr_page_failed", SCAN_CAP_REACHED, SCAN_UNCHECKED)
_PAGES = re.compile(r"^Pages? ([0-9][0-9, \-]*) (?:is a scan|are scans|has no text layer)")


def page_list(numbers: list[int]) -> str:
    """"3, 5-7, 9": page numbers with runs joined."""

    runs: list[list[int]] = []
    for number in sorted(set(numbers)):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def unread_scan_message(numbers: list[int], reason: str) -> str:
    return f"{'Page' if len(set(numbers)) == 1 else 'Pages'} {page_list(numbers)} " \
           f"{'is a scan' if len(set(numbers)) == 1 else 'are scans'} {reason}"


def unread_scan_pages(parser_output: dict) -> list[tuple[int, int]]:
    """Page ranges named by the parser's scan-not-read warnings (over the OCR cap, OCR off, OCR failed)."""

    found: list[tuple[int, int]] = []
    for warning in parser_output.get("warnings") or []:
        if not isinstance(warning, dict) or warning.get("code") not in _UNREAD_CODES:
            continue
        match = _PAGES.match(str(warning.get("message") or ""))
        for part in (match.group(1).split(",") if match else []):
            low, _, high = part.strip().partition("-")
            if low.isdigit() and (not high or high.isdigit()):
                found.append((int(low), int(high or low)))
    return found
