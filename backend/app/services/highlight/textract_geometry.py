"""Read Textract block geometry (step B), as a standalone reader.

Textract returns a ``Geometry.BoundingBox`` on every block by default. The
current normalizer (``textract_parser.py``) drops it; this module reads it so
the value->block matcher has real geometry to work with. It is deliberately a
new module and does NOT edit the normalizer — wiring it into the pipeline is a
separate step (owner: Jack).

COORDINATE CONVENTION — the one place it is converted, and the one that wins:
    Textract BoundingBox is normalized fractions of the page in [0, 1]:
        {Left, Top, Width, Height}
    We convert once, here, to the frontend overlay convention:
        {x, y, w, h}  with  x=Left, y=Top, w=Width, h=Height
    Everything downstream (matcher, source_reference, frontend) uses {x,y,w,h}
    normalized fractions. Any pixel-space source must be normalized to fractions
    before it reaches this shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BBox:
    """Normalized (0..1) box in the frontend convention."""

    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class WordBlock:
    block_id: str
    text: str
    bbox: BBox
    confidence: float = 100.0  # Textract 0..100; 100 when absent


@dataclass
class LineBlock:
    block_id: str
    text: str
    page_number: int
    bbox: BBox
    confidence: float = 100.0
    words: list[WordBlock] = field(default_factory=list)


def _confidence(raw: dict[str, Any]) -> float:
    try:
        return float(raw.get("Confidence", 100.0))
    except (TypeError, ValueError):
        return 100.0


def _bbox_from_geometry(geometry: dict[str, Any] | None) -> BBox | None:
    if not isinstance(geometry, dict):
        return None
    box = geometry.get("BoundingBox")
    if not isinstance(box, dict):
        return None
    try:
        # The single conversion point: Textract Left/Top/Width/Height -> x/y/w/h.
        return BBox(
            x=float(box["Left"]),
            y=float(box["Top"]),
            w=float(box["Width"]),
            h=float(box["Height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def union_boxes(boxes: list[BBox]) -> BBox | None:
    """Union a set of normalized boxes into one enclosing box."""

    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.x + b.w for b in boxes)
    bottom = max(b.y + b.h for b in boxes)
    return BBox(x=left, y=top, w=right - left, h=bottom - top)


def extract_page_lines(textract_response: dict[str, Any]) -> dict[int, list[LineBlock]]:
    """Group a raw Textract AnalyzeDocument response into LINE blocks (with their
    child WORD blocks) by page number, each carrying a normalized BBox.

    Lines with no usable geometry are skipped — a line we cannot place cannot
    anchor a highlight.
    """

    blocks = textract_response.get("Blocks") if isinstance(textract_response, dict) else None
    if not isinstance(blocks, list):
        return {}

    block_map = {b.get("Id"): b for b in blocks if isinstance(b, dict) and b.get("Id")}

    def word_block(word_id: str) -> WordBlock | None:
        raw = block_map.get(word_id)
        if not isinstance(raw, dict) or raw.get("BlockType") != "WORD":
            return None
        bbox = _bbox_from_geometry(raw.get("Geometry"))
        if bbox is None:
            return None
        return WordBlock(
            block_id=word_id,
            text=str(raw.get("Text", "") or ""),
            bbox=bbox,
            confidence=_confidence(raw),
        )

    pages: dict[int, list[LineBlock]] = {}
    for raw in blocks:
        if not isinstance(raw, dict) or raw.get("BlockType") != "LINE":
            continue
        bbox = _bbox_from_geometry(raw.get("Geometry"))
        if bbox is None:
            continue
        page_number = int(raw.get("Page", 1) or 1)
        words: list[WordBlock] = []
        for rel in raw.get("Relationships", []) or []:
            if rel.get("Type") != "CHILD":
                continue
            for wid in rel.get("Ids", []) or []:
                wb = word_block(wid)
                if wb is not None:
                    words.append(wb)
        line = LineBlock(
            block_id=str(raw.get("Id")),
            text=str(raw.get("Text", "") or ""),
            page_number=page_number,
            bbox=bbox,
            confidence=_confidence(raw),
            words=words,
        )
        pages.setdefault(page_number, []).append(line)
    return pages
