"""The sentence a client sees for a halt, from one map.

The pipeline words a halt for the people who debug it: the closest classifier match and its
score, an internal type id, what the parser said. That raw text stays in the pipeline run record
(and the processing run's stored error) and never goes to a client. The API answers with the
halt's code and this plain sentence instead.

The wording matches the frontend's ``HALT_REASONS`` (``features/s1/constants/copy.ts``), so the
screen and the API agree.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.app.services.pdf_scan_pages import SCAN_LIMIT_SENTENCE, SCAN_UNCHECKED_SENTENCE

# A halt code to the sentence for it. ``document_too_long`` is not here: its own sentence is
# already plain and carries the page counts (see ``plain_halt``).
PLAIN_HALT: dict[str, str] = {
    "unreadable_document": "File could not be read.",
    "ocr_required": "Photo or scan: its text is read once OCR is switched on. Ask for a text PDF meanwhile.",
    "password_protected": "Password-protected: ask the client for a copy without a password.",
    "scan_limit_reached": SCAN_LIMIT_SENTENCE,
    "scan_limit_unchecked": SCAN_UNCHECKED_SENTENCE,
    "unsupported_document": "We couldn't tell what kind of document this is. Choose its type in Evidence.",
}

# Halts whose server sentence is already plain (no ids, scores or parser output).
_OWN_SENTENCE = frozenset({"document_too_long"})


def is_halt_code(code: str | None) -> bool:
    return bool(code) and (code in PLAIN_HALT or code in _OWN_SENTENCE)


def plain_halt(code: str | None, message: str | None = None) -> str | None:
    """The sentence for a halt code, or ``None`` when the code is not a halt code (then the
    caller's own plain sentence applies). A halt code never falls back to the raw ``message``,
    except for the codes whose sentence is already plain."""

    if code in PLAIN_HALT:
        return PLAIN_HALT[str(code)]
    if code in _OWN_SENTENCE and message and message.strip():
        return message.strip()
    return None


# --- a pipeline run, as a client may see it ---------------------------------------------------
#
# The stored run keeps the pipeline's own sentences (the closest classifier match with its id and
# score, what a parser said, an exception's text). They are for the people who debug it. Every API
# answer that carries a run goes through ``plain_pipeline_run``: the halt says its code and the plain
# sentence, and each warning and error keeps its code and loses internal ids, scores and parser output.

GENERIC_HALT = "Reading stopped. Try uploading the file again."
PIPELINE_FAILED = "pipeline_failed: Processing failed. Try again."
GENERIC_NOTE = "note: This step has a note for the support team."

# Internal wording that must not reach a client: a type id, a classifier score, a parser's own words.
_INTERNAL = re.compile(
    r"CT-[A-Z0-9]+-[A-Z0-9]+|canonical_type_id|\b[Cc]lassifier\b|Parser said|Textract|\bconfidence \d|\b0\.\d{2}\b"
    r"|Traceback|Exception|Error\b"
)
_COST = re.compile(r",? cost \$[0-9.]+")

# (pattern, replacement) in order; the first match wins. Codes are kept as the sentence's prefix.
_WARNING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^ai_type_disagrees:"),
     "ai_type_disagrees: Sustentra's AI read the first pages as a different type than the rules chose. "
     "The type was not changed."),
    (re.compile(r"^ai_routing_ignored:"), "ai_routing_ignored: Sustentra AI's type suggestion was not used."),
    (re.compile(r"^The classifier chose "),
     "type_corrected: The document's content pointed to a different type than the first guess, "
     "so the type was corrected."),
    (re.compile(r"^Classifier confidence "),
     "type_accepted: The type was not certain; it was accepted because of what the document says."),
    (re.compile(r"^(?:Claude|Sustentra's AI) suggested "),
     "ai_type_suggested: Sustentra's AI suggested a type from the first pages; the rules could not place this "
     "document. Confirm the type."),
    (re.compile(r"^No confident canonical_type_id"),
     "no_type: No document type was found with enough confidence, so no values were read."),
    (re.compile(r"^No extraction targets"), "no_targets: No values are read for this document type yet."),
    (re.compile(r"^Pipeline orchestration failed"), PIPELINE_FAILED),
)
# Codes whose text is already counts and ranges only; kept as written.
_KEPT_CODES = ("pages_unread:", "scan_cap_reached:", "scan_limit_unchecked:", "ai_unavailable:", "ai_cap_reached:", "ai_double_check_skipped:", "ai_pages_skipped:", "ai_time_budget:")

logger = logging.getLogger("sustentra.halt_text")


def plain_halt_reason(halt: dict[str, Any] | None) -> dict[str, str] | None:
    """A run's halt as {code, message}: the plain sentence for its code, never the raw one."""

    if not halt:
        return None
    code = str(halt.get("code") or "")
    return {"code": code, "message": plain_halt(code, str(halt.get("message") or "")) or GENERIC_HALT}


_VENDOR_NAME = re.compile(r"\bClaude(?:'s)?")


def _ai_name(text: str) -> str:
    """Notes saved before the rename still say "Claude": show the product's name for the AI at display time."""

    return _VENDOR_NAME.sub(lambda m: "Sustentra AI's" if m.group(0).endswith("'s") else "Sustentra's AI", text)


def plain_note(text: str, halt: dict[str, Any] | None = None) -> str:
    """One warning or error of a run, with its code and without internal ids, scores or parser output."""

    return _ai_name(_plain_note(str(text), halt))


def _plain_note(text: str, halt: dict[str, Any] | None) -> str:
    if halt and text == str(halt.get("message") or ""):
        plain = plain_halt_reason(halt)
        return f"{plain['code']}: {plain['message']}" if plain else GENERIC_HALT
    if text.startswith(_KEPT_CODES):
        return text
    for pattern, replacement in _WARNING_RULES:
        if pattern.search(text):
            return replacement
    if text.startswith("ai_extraction:"):
        return _COST.sub("", text)  # the counts stay; what Claude cost does not
    if _INTERNAL.search(text):
        logger.warning("run note not mapped to a plain sentence (%s)", text.split(":", 1)[0][:40])
        return GENERIC_NOTE
    return text


def plain_pipeline_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """A copy of a pipeline run record that is safe to send to a client."""

    if run is None:
        return None
    halt = run.get("halt_reason") or None
    cleaned = dict(run)
    if "halt_reason" in run:
        cleaned["halt_reason"] = plain_halt_reason(halt)
    for key in ("warnings", "errors"):
        if key in run:
            cleaned[key] = [plain_note(item, halt) for item in run.get(key) or []]
    return cleaned


def plain_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    """A pipeline result (``{pipeline_run, ...}``) with its run made safe to send."""

    if not isinstance(result, dict) or "pipeline_run" not in result:
        return result
    cleaned = {**result, "pipeline_run": plain_pipeline_run(result["pipeline_run"])}
    extraction = result.get("extraction_result")
    if isinstance(extraction, dict) and extraction.get("halt_reason"):
        cleaned["extraction_result"] = {**extraction, "halt_reason": plain_halt_reason(extraction["halt_reason"])}
    return cleaned
