from __future__ import annotations

import json
from typing import Any, Sequence

from backend.app.settings import load_runtime_settings


class LlmExtractionService:
    """Optional structured extraction pass for targets that allow llm_structured."""

    def __init__(self, client: Any | None = None, settings: Any | None = None) -> None:
        self._settings = settings or load_runtime_settings()
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self._settings.llm_extraction_enabled and self._settings.openai_api_key)

    def extract_candidates(
        self,
        *,
        parser_output: dict,
        extraction_targets: Sequence[dict],
        evidence_id: str,
    ) -> list[dict]:
        if not self.is_enabled():
            return []

        llm_targets = [
            target
            for target in extraction_targets
            if "llm_structured" in tuple(target.get("extraction_methods") or ())
        ]
        if not llm_targets:
            return []

        document_id = str(parser_output.get("document_id") or "")
        if not document_id:
            raise ValueError("parser_output must include a non-empty 'document_id'.")

        payload = self._call_model(parser_output=parser_output, extraction_targets=llm_targets)
        values = payload.get("fields") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return []

        candidates: list[dict] = []
        target_by_id = {str(target.get("field_id") or ""): target for target in llm_targets}
        for item in values:
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("field_id") or "")
            target = target_by_id.get(field_id)
            if target is None:
                continue
            raw_value = item.get("value")
            normalized_value = item.get("normalized_value", raw_value)
            page_number = item.get("page_number")
            source_snippet = item.get("source_snippet")
            candidates.append(
                {
                    "candidate_id": f"candidate::{evidence_id}::{document_id}::{field_id}",
                    "evidence_id": evidence_id,
                    "document_id": document_id,
                    "field_name": field_id,
                    "display_label": str(target.get("field_label") or field_id),
                    "raw_value": raw_value,
                    "normalized_value": normalized_value,
                    "unit": item.get("unit"),
                    "confidence": 0.72,
                    "source_reference": {
                        "source_reference_id": f"llm::{document_id}::{field_id}",
                        "document_id": document_id,
                        "page_number": page_number if isinstance(page_number, int) else None,
                        "sheet_name": None,
                        "cell_or_range": None,
                        "text_snippet": source_snippet if isinstance(source_snippet, str) else None,
                        "bounding_box": item.get("bounding_box") if isinstance(item.get("bounding_box"), dict) else None,
                        "parser_block_ids": [],
                        "source_kind": "llm_structured",
                    },
                    "validation_flags": ["llm_structured"],
                }
            )
        return candidates

    def _call_model(self, *, parser_output: dict, extraction_targets: Sequence[dict]) -> dict:
        client = self._client or self._build_client()
        response = client.responses.create(
            model=self._settings.openai_extraction_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Extract audit workpaper fields from the supplied parser text. "
                        "Return only JSON with a fields array. Do not infer values that "
                        "are not present in the document."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "targets": [
                                {
                                    "field_id": target.get("field_id"),
                                    "field_label": target.get("field_label"),
                                    "value_type": target.get("value_type"),
                                    "unit_patterns": target.get("unit_patterns"),
                                }
                                for target in extraction_targets
                            ],
                            "document_text": self._document_text(parser_output),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "s1_extraction_fields",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "fields": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "field_id": {"type": "string"},
                                        "value": {
                                            "type": ["string", "number", "boolean", "null"]
                                        },
                                        "normalized_value": {
                                            "type": ["string", "number", "boolean", "null"]
                                        },
                                        "unit": {"type": ["string", "null"]},
                                        "source_snippet": {"type": ["string", "null"]},
                                        "page_number": {"type": ["integer", "null"]},
                                        "bounding_box": {"type": ["object", "null"]},
                                    },
                                    "required": [
                                        "field_id",
                                        "value",
                                        "normalized_value",
                                        "unit",
                                        "source_snippet",
                                        "page_number",
                                        "bounding_box",
                                    ],
                                },
                            }
                        },
                        "required": ["fields"],
                    },
                }
            },
        )
        return json.loads(response.output_text)

    def _build_client(self) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=self._settings.openai_api_key)

    @staticmethod
    def _document_text(parser_output: dict) -> str:
        parts: list[str] = []
        for page in parser_output.get("pages", []) or []:
            if isinstance(page, dict):
                page_number = page.get("page_number")
                text = page.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(f"[page {page_number}]\n{text}")
        if not parts:
            for block in parser_output.get("text_blocks", []) or []:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n\n".join(parts)[:60000]
