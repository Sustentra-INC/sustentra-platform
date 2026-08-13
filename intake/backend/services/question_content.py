"""Loader for the interview question content.

Kept beside the other config loaders rather than inlined so the interview engine
and its tests read the same file, and so a missing or malformed question set
fails at load time rather than mid-interview.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from intake.backend.config import REPO_ROOT

QUESTION_CONTENT_PATH = REPO_ROOT / "intake/config/question_content.json"

REQUIRED_KEYS = ("question", "explainer", "answer_shape", "fields")
ANSWER_SHAPES = {"yes_no", "single_select", "composite"}


@lru_cache(maxsize=1)
def load_question_content() -> dict[str, Any]:
    """Question content keyed by datapoint id, with each entry sanity-checked."""
    payload = json.loads(QUESTION_CONTENT_PATH.read_text(encoding="utf-8"))
    questions = payload.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise RuntimeError(f"{QUESTION_CONTENT_PATH}: no questions found")

    for datapoint_id, content in questions.items():
        missing = [key for key in REQUIRED_KEYS if key not in content]
        if missing:
            raise RuntimeError(f"{datapoint_id}: missing {missing}")
        if content["answer_shape"] not in ANSWER_SHAPES:
            raise RuntimeError(
                f"{datapoint_id}: unknown answer_shape {content['answer_shape']!r}"
            )
        for field in content["fields"]:
            if "field_id" not in field or "input" not in field:
                raise RuntimeError(f"{datapoint_id}: a field is missing field_id or input")
    return questions


@lru_cache(maxsize=1)
def load_question_content_document() -> dict[str, Any]:
    """The whole file, including copy status metadata."""
    return json.loads(QUESTION_CONTENT_PATH.read_text(encoding="utf-8"))


def reset_cache() -> None:
    load_question_content.cache_clear()
    load_question_content_document.cache_clear()
