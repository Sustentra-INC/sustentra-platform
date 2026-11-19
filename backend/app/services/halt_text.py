"""The sentence a client sees for a halt, from one map.

The pipeline words a halt for the people who debug it: the closest classifier match and its
score, an internal type id, what the parser said. That raw text stays in the pipeline run record
(and the processing run's stored error) and never goes to a client. The API answers with the
halt's code and this plain sentence instead.

The wording matches the frontend's ``HALT_REASONS`` (``features/s1/constants/copy.ts``), so the
screen and the API agree.
"""

from __future__ import annotations

# A halt code to the sentence for it. ``document_too_long`` is not here: its own sentence is
# already plain and carries the page counts (see ``plain_halt``).
PLAIN_HALT: dict[str, str] = {
    "unreadable_document": "File could not be read.",
    "ocr_required": "Photo or scan: its text is read once OCR is switched on. Ask for a text PDF meanwhile.",
    "password_protected": "Password-protected: ask the client for a copy without a password.",
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
