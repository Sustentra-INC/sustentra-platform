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
