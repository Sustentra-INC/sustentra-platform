from __future__ import annotations

import pytest

from backend.app.adapters.parsers.textract_parser import TextractParser


def _line(block_id: str, text: str, geometry: dict | None) -> dict:
    block = {"Id": block_id, "BlockType": "LINE", "Page": 1, "Text": text, "Confidence": 98.5}
    if geometry is not None:
        block["Geometry"] = geometry
    return block


def test_line_geometry_becomes_bounding_boxes() -> None:
    payload = {"Blocks": [
        _line("a", "Total Usage 1,284", {"BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.02}}),
        _line("b", "no geometry", None),
    ]}
    output = TextractParser().parse(payload, document_id="DOC", processing_run_id="RUN")

    first, second = output["text_blocks"]
    assert first["bounding_box"] == {"left": 0.1, "top": 0.2, "width": 0.3, "height": 0.02}
    assert second["bounding_box"] is None
    refs = {r["source_reference_id"]: r for r in output["source_references"]}
    assert refs[first["source_reference_id"]]["bounding_box"] == {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.02}
    assert refs[second["source_reference_id"]]["bounding_box"] is None


def _words_line(block_id: str, words: list[tuple[str, float, float]], height: float = 0.02) -> list[dict]:
    """A LINE and its WORD children: (text, left, width) per word, all on one row."""

    word_blocks = [
        {"Id": f"{block_id}-w{n}", "BlockType": "WORD", "Page": 1, "Text": text,
         "Geometry": {"BoundingBox": {"Left": left, "Top": 0.5, "Width": width, "Height": height}}}
        for n, (text, left, width) in enumerate(words)
    ]
    left = words[0][1]
    right = words[-1][1] + words[-1][2]
    line = _line(block_id, " ".join(w[0] for w in words),
                 {"BoundingBox": {"Left": left, "Top": 0.5, "Width": right - left, "Height": height}})
    line["Relationships"] = [{"Type": "CHILD", "Ids": [w["Id"] for w in word_blocks]}]
    return [line, *word_blocks]


def test_a_line_holding_two_side_by_side_fields_becomes_two_text_blocks() -> None:
    # "Total kWh Used: 41,200" then a gap of 1.25 line heights, then "Service Period: 05/01/2025".
    blocks = _words_line("L", [
        ("Total", 0.10, 0.03), ("kWh", 0.135, 0.02), ("Used:", 0.16, 0.03), ("41,200", 0.195, 0.04),
        ("Service", 0.26, 0.04), ("Period:", 0.305, 0.04), ("05/01/2025", 0.35, 0.06),
    ])
    output = TextractParser().parse({"Blocks": blocks}, document_id="DOC", processing_run_id="RUN")

    assert [b["text"] for b in output["text_blocks"]] == ["Total kWh Used: 41,200", "Service Period: 05/01/2025"]
    first, second = output["text_blocks"]
    assert first["bounding_box"]["left"] == 0.10
    assert round(first["bounding_box"]["width"], 6) == round(0.235 - 0.10, 6)
    assert second["bounding_box"]["left"] == 0.26
    assert len({first["source_reference_id"], second["source_reference_id"]}) == 2
    # The page text keeps the line whole.
    assert output["pages"][0]["text"] == "Total kWh Used: 41,200 Service Period: 05/01/2025"


def test_ordinary_word_spacing_keeps_a_line_whole() -> None:
    blocks = _words_line("L", [("Natural", 0.10, 0.05), ("Gas", 0.159, 0.03), ("Usage", 0.198, 0.04)])
    output = TextractParser().parse({"Blocks": blocks}, document_id="DOC", processing_run_id="RUN")

    assert [b["text"] for b in output["text_blocks"]] == ["Natural Gas Usage"]
    assert output["text_blocks"][0]["block_id"] == "L"


# Textract boxes are fractions of the page: left/width of its width, top/height of its height. The
# lines below are in pixels (text, left, width per word; 16 px line height), as on the electric bill
# regression sample: ordinary spacing 4-6 px, 14 px between the two side-by-side fields.
SIDE_BY_SIDE_FIELDS_PX = [
    ("Total", 30, 37), ("kWh", 72, 33), ("Used:", 110, 42), ("41,200", 157, 51), ("kWh", 212, 33),
    ("Service", 259, 55), ("Period:", 319, 51), ("05/01/2025", 375, 83), ("to", 462, 14), ("05/31/2025", 481, 83),
]
SIDE_BY_SIDE_PARTS = ["Total kWh Used: 41,200 kWh", "Service Period: 05/01/2025 to 05/31/2025"]
ORDINARY_SPACING_PX = [("Natural", 40, 52), ("Gas", 97, 26), ("Usage", 128, 44), ("32,400", 178, 48), ("MMBtu", 232, 46)]
WIDE_CROP = (620, 120)  # a strip cut from a bill, or a landscape photo
LETTER_SCAN = (918, 1188)
TALL_RECEIPT = (640, 2560)


def _px_words_line(block_id: str, words_px: list[tuple[str, float, float]], page_px: tuple[int, int]) -> list[dict]:
    """_words_line on a page of (width, height) pixels, the words given in pixels."""

    page_width, page_height = page_px
    words = [(text, left / page_width, width / page_width) for text, left, width in words_px]
    return _words_line(block_id, words, height=16 / page_height)


def _parts(blocks: list[dict], page_aspect: float | None) -> list[str]:
    output = TextractParser().parse({"Blocks": blocks}, document_id="DOC", processing_run_id="RUN",
                                    page_aspect=page_aspect)
    return [b["text"] for b in output["text_blocks"]]


def test_a_wide_page_splits_side_by_side_fields() -> None:
    # The 14 px gap is 0.023 of the page width and the line 0.133 of its height: compared as they
    # came, the gap looked narrow and the line stayed whole (the service period was not found).
    blocks = _px_words_line("L", SIDE_BY_SIDE_FIELDS_PX, WIDE_CROP)

    assert _parts(blocks, page_aspect=620 / 120) == SIDE_BY_SIDE_PARTS


def test_a_wide_page_keeps_ordinary_word_spacing_whole() -> None:
    blocks = _px_words_line("L", ORDINARY_SPACING_PX, WIDE_CROP)

    assert _parts(blocks, page_aspect=620 / 120) == ["Natural Gas Usage 32,400 MMBtu"]


def test_a_tall_receipt_keeps_ordinary_word_spacing_whole() -> None:
    # A 6 px gap is 0.009 of the page width and the line 0.006 of its height: compared as they
    # came, ordinary spacing on a narrow receipt looked wide and split the line.
    blocks = _px_words_line("L", ORDINARY_SPACING_PX, TALL_RECEIPT)

    assert _parts(blocks, page_aspect=640 / 2560) == ["Natural Gas Usage 32,400 MMBtu"]


@pytest.mark.parametrize("page_px", [WIDE_CROP, LETTER_SCAN, TALL_RECEIPT], ids=["wide", "letter", "tall"])
@pytest.mark.parametrize("shape_known", [True, False], ids=["page-shape", "character-widths"])
def test_the_split_depends_on_the_text_not_on_the_page_shape(page_px: tuple[int, int], shape_known: bool) -> None:
    page_aspect = page_px[0] / page_px[1] if shape_known else None

    assert _parts(_px_words_line("A", SIDE_BY_SIDE_FIELDS_PX, page_px), page_aspect) == SIDE_BY_SIDE_PARTS
    assert _parts(_px_words_line("B", ORDINARY_SPACING_PX, page_px), page_aspect) == ["Natural Gas Usage 32,400 MMBtu"]


def test_without_the_page_shape_words_without_text_keep_the_line_whole() -> None:
    blocks = _words_line("L", [("", 0.10, 0.05), ("", 0.40, 0.05)])
    output = TextractParser().parse({"Blocks": blocks}, document_id="DOC", processing_run_id="RUN")

    assert [b["block_id"] for b in output["text_blocks"]] == ["L"]
