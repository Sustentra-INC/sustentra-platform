from __future__ import annotations

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
