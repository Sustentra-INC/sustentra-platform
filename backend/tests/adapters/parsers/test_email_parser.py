"""The email (.eml) parser: the message as lines, one traceable block per line, with its
attachments listed but not read."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from backend.app.adapters.parsers import email_parser
from backend.app.adapters.parsers.email_parser import EmailParser, email_text, read_email_file
from backend.tests.adapters.parsers._parser_output_asserts import assert_parser_output_shape


def _message(subject: str = "Your February bill", body: str = "Total Usage: 120 therms") -> EmailMessage:
    message = EmailMessage()
    message["From"] = "Acme Gas <billing@acme.example>"
    message["To"] = "ap@client.example"
    message["Date"] = "Mon, 10 Feb 2025 09:15:00 -0500"
    message["Subject"] = subject
    message.set_content(body)
    return message


def _eml(tmp_path: Path, message: EmailMessage, name: str = "bill.eml") -> Path:
    path = tmp_path / name
    path.write_bytes(message.as_bytes())
    return path


def test_each_line_is_a_block_numbered_like_the_source_pane(tmp_path: Path) -> None:
    message = EmailMessage()
    message["From"] = "billing@acme.example"
    message["Subject"] = "February"
    message.set_content("Total Usage: 120 therms\n")
    output = EmailParser().parse(_eml(tmp_path, message), document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert (output["status"], output["parser_name"]) == ("parsed", "email_parser")
    assert [(b["block_id"], b["text"]) for b in output["text_blocks"]] == [
        ("email_parser-p1-b1", "From: billing@acme.example"),
        ("email_parser-p1-b2", "Subject: February"),
        ("email_parser-p1-b3", "Total Usage: 120 therms"),
    ]
    assert output["source_references"][2]["parser_block_ids"] == ["email_parser-p1-b3"]
    assert output["warnings"] == []


def test_the_email_reads_as_headers_text_forwarded_messages_then_attachments(tmp_path: Path) -> None:
    inner = _message(subject="March invoice", body="Total Usage: 98 therms")
    inner.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="march.pdf")
    outer = _message(subject="Fwd: March invoice", body="See below.")
    outer.add_attachment(b"a,b\n" * 600, maintype="text", subtype="csv", filename="usage.csv")
    outer.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="logo.png", disposition="inline",
                         cid="<logo>")
    outer.add_attachment(inner)

    assert email_text(read_email_file(_eml(tmp_path, outer))).split("\n") == [
        "From: Acme Gas <billing@acme.example>",
        "To: ap@client.example",
        "Sent: Mon, 10 Feb 2025 09:15:00 -0500",
        "Subject: Fwd: March invoice",
        "",
        "See below.",
        "",
        "Attachments: usage.csv",  # the inline logo is part of the message body, not an attachment
        "",
        "Forwarded message",
        "From: Acme Gas <billing@acme.example>",
        "To: ap@client.example",
        "Sent: Mon, 10 Feb 2025 09:15:00 -0500",
        "Subject: March invoice",
        "",
        "Total Usage: 98 therms",
        "",
        "Attachments: march.pdf",
        "",
    ]


def test_attachments_are_listed_in_the_warnings_not_read(tmp_path: Path) -> None:
    inner = _message(subject="March invoice")
    inner.add_attachment(b"%PDF" * 1000, maintype="application", subtype="pdf", filename="march.pdf")
    outer = _message(subject="Fwd: March invoice")
    outer.add_attachment(b"x" * (3 * 1024 * 1024), maintype="application", subtype="vnd.ms-excel",
                         filename="usage.xls")
    outer.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="logo.png", disposition="inline")
    outer.add_attachment(b"tnef", maintype="application", subtype="ms-tnef", filename="winmail.dat")
    outer.add_attachment(inner)
    output = EmailParser().parse(_eml(tmp_path, outer), document_id="DOC-1", processing_run_id="RUN-1")

    assert output["status"] == "parsed"
    assert output["warnings"] == [{
        "code": "attachments_not_read",
        "severity": "info",
        "message": "The email has 4 attachments, which were not read here: usage.xls (3.0 MB); "
                   "logo.png (1 KB, in the message body); winmail.dat (1 KB, Outlook rich-text attachment "
                   "(winmail.dat); its contents can't be read here); March invoice › march.pdf (4 KB). "
                   "Upload an attachment on its own to read it.",
    }]
    # Nothing is imported: the parse output holds the email's own text only.
    assert not any("%PDF" in block["text"] for block in output["text_blocks"])


def test_what_was_cut_is_said(tmp_path: Path, monkeypatch) -> None:
    from backend.app.adapters.parsers import email_reader

    monkeypatch.setattr(email_reader, "MAX_BODY_CHARS", 5)
    output = EmailParser().parse(_eml(tmp_path, _message()), document_id="D", processing_run_id="R")
    assert [w["code"] for w in output["warnings"]] == ["body_truncated"]
    assert output["text_blocks"][-1]["text"] == "Total"


def test_a_message_without_text_says_so(tmp_path: Path) -> None:
    message = EmailMessage()
    message["From"] = "scanner@client.example"
    message["Subject"] = "Scan"
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="scan.pdf")
    output = EmailParser().parse(_eml(tmp_path, message), document_id="D", processing_run_id="R")
    assert [w["code"] for w in output["warnings"]] == ["attachments_not_read", "no_message_text"]
    assert [b["text"] for b in output["text_blocks"]] == [
        "From: scanner@client.example", "Subject: Scan", "Attachments: scan.pdf"]


def test_what_is_not_an_email_fails_with_its_reason(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "renamed.eml"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(600))
    output = EmailParser().parse(path, document_id="D", processing_run_id="R")
    assert_parser_output_shape(output)
    assert output["status"] == "failed"
    assert output["warnings"][0]["code"] == "not_an_eml"
    assert "Outlook message (.msg)" in output["warnings"][0]["message"]

    monkeypatch.setattr(email_parser, "MAX_EMAIL_BYTES", 10)
    output = EmailParser().parse(_eml(tmp_path, _message()), document_id="D", processing_run_id="R")
    assert (output["status"], output["warnings"][0]["code"]) == ("failed", "file_too_large")
