import io
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser, image_aspect
from backend.app.adapters.parsers.textract_parser import TextractParser
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


class RecordingTextractClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def analyze_document(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def test_aws_textract_parser_calls_analyze_document_and_normalizes_response(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"image bytes")
    client = RecordingTextractClient(
        {
            "Blocks": [
                {
                    "Id": "line-1",
                    "BlockType": "LINE",
                    "Text": "Usage 32,400 MMBtu",
                    "Page": 1,
                    "Confidence": 99.0,
                }
            ]
        }
    )

    parser = AwsTextractParser(
        client_factory=lambda service_name, **kwargs: client,
        region_name="us-east-1",
        feature_types=["FORMS", "TABLES"],
    )
    output = parser.parse(source, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["parser_name"] == "aws_textract"
    assert output["status"] == "parsed"
    assert output["text_blocks"][0]["text"] == "Usage 32,400 MMBtu"
    assert client.calls == [
        {
            "Document": {"Bytes": b"image bytes"},
            "FeatureTypes": ["FORMS", "TABLES"],
        }
    ]


def test_aws_textract_parser_returns_failed_output_when_call_fails(tmp_path: Path) -> None:
    source = tmp_path / "scan.png"
    source.write_bytes(b"image bytes")

    def failing_client_factory(service_name: str, **kwargs: Any) -> Any:
        raise RuntimeError("no credentials")

    output = AwsTextractParser(client_factory=failing_client_factory).parse(
        source, document_id="DOC-1", processing_run_id="RUN-1"
    )

    assert_parser_output_shape(output)
    assert output["parser_name"] == "aws_textract"
    assert output["status"] == "failed"
    assert any(w["code"] == "textract_call_failed" for w in output["warnings"])


def _image_bytes(size: tuple[int, int], image_format: str = "PNG", orientation: int | None = None) -> bytes:
    buffer = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation  # EXIF Orientation
    Image.new("RGB", size, "white").save(buffer, image_format, **({"exif": exif} if orientation else {}))
    return buffer.getvalue()


def test_image_aspect_is_width_over_height_in_pixels() -> None:
    assert image_aspect(_image_bytes((620, 120))) == 620 / 120
    assert image_aspect(_image_bytes((918, 1188), "JPEG")) == 918 / 1188
    # Upside down keeps the page's shape.
    assert image_aspect(_image_bytes((620, 120), "JPEG", orientation=3)) == 620 / 120


def test_image_aspect_is_unknown_for_a_quarter_turn_photo_and_for_non_images() -> None:
    # Stored on its side: Textract may or may not apply the EXIF rotation, so the shape is ambiguous.
    assert image_aspect(_image_bytes((1188, 918), "JPEG", orientation=6)) is None
    assert image_aspect(_image_bytes((1188, 918), "PNG", orientation=8)) is None
    assert image_aspect(b"%PDF-1.7\n...") is None
    assert image_aspect(b"image bytes") is None


class AspectRecordingNormalizer(TextractParser):
    def __init__(self) -> None:
        self.page_aspects: list[float | None] = []

    def parse(self, textract_source: Any, document_id: str, processing_run_id: str,
              page_aspect: float | None = None) -> dict:
        self.page_aspects.append(page_aspect)
        return super().parse(textract_source, document_id, processing_run_id, page_aspect=page_aspect)


def test_the_image_shape_reaches_the_textract_reader(tmp_path: Path) -> None:
    wide, unreadable = tmp_path / "wide.png", tmp_path / "scan.png"
    wide.write_bytes(_image_bytes((620, 120)))
    unreadable.write_bytes(b"image bytes")
    client = RecordingTextractClient({"Blocks": []})
    normalizer = AspectRecordingNormalizer()
    parser = AwsTextractParser(client_factory=lambda service_name, **kwargs: client, normalizer=normalizer)

    parser.parse(wide, document_id="DOC-1", processing_run_id="RUN-1")
    parser.parse(unreadable, document_id="DOC-2", processing_run_id="RUN-1")

    assert normalizer.page_aspects == [620 / 120, None]
