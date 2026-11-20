"""The reason Sustentra's AI gives for a suggestion, as it is kept: plain text, one line, at most 240 characters.
Shared by every feature that suggests something (Methodology prefill, the facility suggestion)."""

from __future__ import annotations

from typing import Any

MAX_REASON = 240
NO_REASON = "Reason not recorded for this suggestion. Re-read the reports to get one."


def clean_reason(raw: Any) -> str:
    """The AI's reason as kept: one line of plain text, at most MAX_REASON characters (cut at a word, with an
    ellipsis, when longer). It is the AI's own words: shown as such and never used to decide anything."""

    text = " ".join(str(raw or "").replace("\x00", "").split())
    if len(text) <= MAX_REASON:
        return text
    return text[:MAX_REASON - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"
