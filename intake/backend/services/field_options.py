"""Resolve a question field's option list from config.

Options come from one of three places, and never from a hardcoded list in code:
a controlled vocabulary extracted from the methodology workbooks, a list in
intake settings, or explicit options on the field itself.
"""

from __future__ import annotations

from typing import Any

from intake.backend.config import IntakeSettings, vocabulary_is_open, vocabulary_values


def resolve_options(field: dict[str, Any], settings: IntakeSettings) -> dict[str, Any]:
    """Return the field with ``options`` filled in from its ``options_ref``."""
    resolved = dict(field)
    ref = field.get("options_ref")
    if not isinstance(ref, str):
        return resolved

    if ref.startswith("vocabulary:"):
        name = ref.split(":", 1)[1]
        resolved["options"] = [
            {"value": value, "label": value.replace("_", " ")}
            for value in vocabulary_values(name)
        ]
        resolved["vocabulary_open"] = vocabulary_is_open(name)
    elif ref == "settings:industries":
        resolved["options"] = settings.industries
    return resolved


def permitted_values(field: dict[str, Any]) -> set[str] | None:
    """Allowed values for a select field, or None if it is not constrained.

    A vocabulary the workbook marks OPEN is indicative, not closed, so it does
    not constrain the answer.
    """
    if field.get("input") != "select":
        return None
    if field.get("vocabulary_open"):
        return None
    options = field.get("options") or []
    return {option["value"] for option in options} or None
