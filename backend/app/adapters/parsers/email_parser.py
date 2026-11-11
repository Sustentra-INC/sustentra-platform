"""Email (.eml) parser adapter.

The email is read by ``email_reader`` and rendered as lines, which the text parser turns
into one traceable block per non-empty line (``email_parser-p1-b<N>``), as for Word and
text files:

    From: Acme Gas <billing@acme.example>
    To: ap@client.example
    Sent: Mon, 10 Feb 2025 09:15:00 -0500
    Subject: Your February bill

    <the message text>

    Attachments: bill.pdf, usage.xlsx

    Forwarded message
    From: ... (each forwarded message's headers, text and attachments)

Only the message text is read in this version. The attachments are listed (in the text
and in an ``attachments_not_read`` note with their sizes) but not opened or imported.
The source pane draws the same lines (``email_text``), so a value's block number is its
line there.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.adapters.parsers.base import build_failed_parser_output, build_warning
from backend.app.adapters.parsers.email_reader import EmailError, EmailPackage, EmailPart, read_eml
from backend.app.adapters.parsers.text_parser import TextParser

PARSER_NAME = "email_parser"
MAX_EMAIL_BYTES = 32 * 1024 * 1024  # above the 25 MB upload limit; a larger file is not opened


def read_email_file(path: Path) -> EmailPackage:
    """Read an .eml file. Raises ``EmailError`` when it is too large or not an email."""

    if path.stat().st_size > MAX_EMAIL_BYTES:
        raise EmailError("file_too_large", f"The email is larger than {MAX_EMAIL_BYTES // (1024 * 1024)} MB.")
    return read_eml(path.read_bytes())


def email_text(package: EmailPackage) -> str:
    """The email as the lines the parser and the source pane share."""

    return "\n".join(_lines(package, heading=None)).strip("\n") + "\n"


def _lines(package: EmailPackage, heading: str | None) -> list[str]:
    lines = [heading] if heading else []
    for label, value in (("From", package.sender), ("To", package.to), ("Cc", package.cc),
                         ("Sent", package.sent_at), ("Subject", package.subject)):
        if value:
            lines.append(f"{label}: {value}")
    if package.body_text:
        lines += ["", package.body_text]
    listed = [part.name for part in package.attachments if not part.inline]
    if listed:  # with the message they came with, before the messages forwarded in it
        lines += ["", "Attachments: " + ", ".join(listed)]
    for nested in package.nested:
        lines += ["", *_lines(nested, heading="Forwarded message")]
    return lines


def email_warnings(package: EmailPackage) -> list[dict[str, str]]:
    """What the parse did not read: the attachments (by name and size) and anything cut."""

    warnings = [build_warning(code, message, severity="info") for code, message in package.all_notes()]
    parts = package.all_attachments()
    if parts:
        listed = "; ".join(_described(part) for part in parts)
        count = f"{len(parts)} attachment{'s' if len(parts) != 1 else ''}"
        warnings.append(build_warning(
            "attachments_not_read",
            f"The email has {count}, which {'were' if len(parts) != 1 else 'was'} not read here: {listed}. "
            "Upload an attachment on its own to read it.",
            severity="info",
        ))
    if not package.body_text and not package.nested:
        warnings.append(build_warning("no_message_text", "The email has no message text.", severity="info"))
    return warnings


def _described(part: EmailPart) -> str:
    where = " › ".join([*part.path, part.name])
    details = [_size(part.size)]
    if part.inline:
        details.append("in the message body")
    if part.note:
        details.append(part.note)
    return f"{where} ({', '.join(details)})"


def _size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB" if size else "empty"


class EmailParser(TextParser):
    """Adapter that normalizes .eml files into ``parser_output`` dicts."""

    parser_name = PARSER_NAME

    def parse(self, file_path: str | Path, document_id: str, processing_run_id: str) -> dict:
        try:
            package = read_email_file(Path(file_path))
        except EmailError as exc:
            return build_failed_parser_output(
                document_id=document_id,
                processing_run_id=processing_run_id,
                parser_name=self.parser_name,
                warnings=[build_warning(exc.code, exc.message, severity="error")],
            )
        return self.parse_text(email_text(package), document_id, processing_run_id, email_warnings(package))
