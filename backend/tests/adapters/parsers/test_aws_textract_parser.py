from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
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
