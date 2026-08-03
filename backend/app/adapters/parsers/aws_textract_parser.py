"""Live AWS Textract parser adapter.

This adapter calls AWS Textract for local PDF/image bytes, then reuses the
saved-JSON Textract normalizer so downstream parser_output shape stays the
same for live and offline Textract payloads.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from backend.app.adapters.parsers.base import (
    PARSER_RUNTIME_VERSION,
    build_failed_parser_output,
    build_warning,
)
from backend.app.adapters.parsers.textract_parser import TextractParser

PARSER_NAME = "aws_textract"

TextractClientFactory = Callable[..., Any]


class AwsTextractParser:
    """Adapter that makes a synchronous AWS Textract AnalyzeDocument call."""

    parser_name = PARSER_NAME
    parser_version = PARSER_RUNTIME_VERSION

    def __init__(
        self,
        *,
        client_factory: TextractClientFactory | None = None,
        region_name: str | None = None,
        feature_types: list[str] | None = None,
        normalizer: TextractParser | None = None,
    ) -> None:
        self._client_factory = client_factory or self._default_client_factory
        self._region_name = region_name
        self._feature_types = feature_types
        self._normalizer = normalizer or TextractParser()

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        path = Path(file_path)
        try:
            document_bytes = path.read_bytes()
            response = self._client().analyze_document(
                Document={"Bytes": document_bytes},
                FeatureTypes=self._resolved_feature_types(),
            )
        except Exception as exc:  # AWS client errors differ by botocore version.
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[
                    build_warning(
                        "textract_call_failed",
                        f"AWS Textract AnalyzeDocument failed: {type(exc).__name__}.",
                        severity="error",
                    )
                ],
            )

        output = self._normalizer.parse(response, document_id, processing_run_id)
        output["parser_name"] = self.parser_name
        output["parser_output_id"] = (
            f"PO-{self.parser_name}-{document_id}-{processing_run_id}"
        )
        return output

    def _client(self) -> Any:
        region_name = (
            self._region_name
            or os.environ.get("TEXTRACT_REGION")
            or os.environ.get("AWS_REGION")
        )
        kwargs = {"region_name": region_name} if region_name else {}
        return self._client_factory("textract", **kwargs)

    def _resolved_feature_types(self) -> list[str]:
        if self._feature_types is not None:
            return self._feature_types
        raw = os.environ.get("TEXTRACT_FEATURE_TYPES", "FORMS,TABLES")
        return [part.strip().upper() for part in raw.split(",") if part.strip()]

    @staticmethod
    def _default_client_factory(service_name: str, **kwargs: Any) -> Any:
        import boto3

        return boto3.client(service_name, **kwargs)
