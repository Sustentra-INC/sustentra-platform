"""Email reader, review round 5: a bounce report's ``message/delivery-status`` part is read
as one piece of text. The stdlib parser builds one message for every blank line in that
part: 900,000 blank lines (0.9 MB) took 3.5 s and about 260 MB, in the parser and in the
source pane alike. A real bounce still reads exactly as it did."""

from __future__ import annotations

import time
import tracemalloc
from email.message import EmailMessage, Message
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

from backend.app.adapters.parsers.email_parser import EmailParser, email_text, email_warnings
from backend.app.adapters.parsers.email_reader import read_eml
from backend.app.services.document_content_service import document_content


def _blocks_and_pane(raw: bytes, tmp_path: Path) -> tuple[list[str], list[str]]:
    """The parser's blocks and the source pane's lines for the same email."""

    path = tmp_path / "bounce.eml"
    path.write_bytes(raw)
    output = EmailParser().parse(path, "D", "R")
    return [block["text"] for block in output["text_blocks"]], document_content(path, "message/rfc822")["lines"]


# --- real bounce reports read as before --------------------------------------------------------
def _stdlib_bounce() -> bytes:
    """A bounce as Python's email package writes one (RFC 3464): a multipart/report holding the
    notice, the delivery-status fields (one block for the message, one per recipient) and the
    returned message."""

    original = EmailMessage()
    original["From"] = "Acme Gas <billing@acme.example>"
    original["To"] = "ap@client.example"
    original["Subject"] = "Your February bill"
    original.set_content("Total due: 1,240 kWh, $182.40\n")

    fields = Message()
    fields.set_type("message/delivery-status")
    for block in ({"Reporting-MTA": "dns; mx.acme.example", "Arrival-Date": "Mon, 10 Feb 2025 09:15:00 -0500"},
                  {"Final-Recipient": "rfc822; ap@client.example", "Action": "failed", "Status": "5.1.1",
                   "Diagnostic-Code": "smtp; 550 5.1.1 User unknown"}):
        part = Message()
        for name, value in block.items():
            part[name] = value
        fields.attach(part)

    report = MIMEMultipart("report", report_type="delivery-status")
    report["From"] = "Mail Delivery System <MAILER-DAEMON@mx.acme.example>"
    report["To"] = "billing@acme.example"
    report["Subject"] = "Undelivered Mail Returned to Sender"
    report.attach(MIMEText("Your message could not be delivered to ap@client.example.\n\nUser unknown.\n"))
    report.attach(fields)
    report.attach(MIMEMessage(original))
    return report.as_bytes()


# As Postfix sends one: a notice, the fields (folded Diagnostic-Code, two recipients) and the
# returned message's headers only (RFC 3462 text/rfc822-headers).
POSTFIX_BOUNCE = b"""\
Return-Path: <>
Date: Mon, 10 Feb 2025 09:15:02 -0500 (EST)
From: MAILER-DAEMON@mx.acme.example (Mail Delivery System)
Subject: Undelivered Mail Returned to Sender
To: billing@acme.example
Auto-Submitted: auto-replied
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status;
\tboundary="3F1A2.1739196902/mx.acme.example"
Content-Transfer-Encoding: 8bit
Message-Id: <20250210141502.3F1A2@mx.acme.example>

This is a MIME-encapsulated message.

--3F1A2.1739196902/mx.acme.example
Content-Description: Notification
Content-Type: text/plain; charset=us-ascii

This is the mail system at host mx.acme.example.

I'm sorry to have to inform you that your message could not
be delivered to one or more recipients.

<ap@client.example>: host mail.client.example[203.0.113.5] said: 550 5.1.1
    <ap@client.example>: Recipient address rejected: User unknown

--3F1A2.1739196902/mx.acme.example
Content-Description: Delivery report
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.acme.example
X-Postfix-Queue-ID: 3F1A2
X-Postfix-Sender: rfc822; billing@acme.example
Arrival-Date: Mon, 10 Feb 2025 09:15:00 -0500 (EST)

Final-Recipient: rfc822; ap@client.example
Original-Recipient: rfc822;ap@client.example
Action: failed
Status: 5.1.1
Remote-MTA: dns; mail.client.example
Diagnostic-Code: smtp; 550 5.1.1 <ap@client.example>: Recipient address rejected:
    User unknown

Final-Recipient: rfc822; energy@client.example
Action: delayed
Status: 4.4.1

--3F1A2.1739196902/mx.acme.example
Content-Description: Undelivered Message Headers
Content-Type: text/rfc822-headers

Return-Path: <billing@acme.example>
From: Acme Gas <billing@acme.example>
To: ap@client.example
Subject: Your February bill
Message-Id: <bill-0210@acme.example>

--3F1A2.1739196902/mx.acme.example--
"""

# As Exchange sends one: the notice in plain text and HTML, the fields, the returned message.
EXCHANGE_BOUNCE = b"""\
From: Microsoft Outlook <postmaster@client.example>
To: <billing@acme.example>
Subject: Undeliverable: Your February bill
Content-Type: multipart/report; report-type=delivery-status;
\tboundary="_000_ndr_"
MIME-Version: 1.0

--_000_ndr_
Content-Type: multipart/alternative; differences=Content-Type;
\tboundary="_001_ndr_"

--_001_ndr_
Content-Type: text/plain; charset="us-ascii"

Delivery has failed to these recipients or groups:

ap@client.example
The email address you entered couldn't be found.

--_001_ndr_
Content-Type: text/html; charset="us-ascii"

<html><body><p>Delivery has failed to these recipients or groups:</p></body></html>

--_001_ndr_--

--_000_ndr_
Content-Type: message/delivery-status

Reporting-MTA: dns;EX01.client.example
Received-From-MTA: dns;mx.acme.example
Arrival-Date: Mon, 10 Feb 2025 14:15:00 +0000

Final-Recipient: rfc822;ap@client.example
Action: failed
Status: 5.1.10
Diagnostic-Code: smtp;550 5.1.10 RESOLVER.ADR.RecipientNotFound; Recipient not found by SMTP address lookup

--_000_ndr_
Content-Type: message/rfc822

From: Acme Gas <billing@acme.example>
To: ap@client.example
Subject: Your February bill
Content-Type: multipart/mixed; boundary="b"

--b
Content-Type: text/plain

Total due: 1,240 kWh, $182.40
--b
Content-Type: application/pdf
Content-Disposition: attachment; filename="bill.pdf"

%PDF-1.4
--b--

--_000_ndr_--
"""

BOUNCES = {
    "python_email_package": (_stdlib_bounce(), [
        "From: Mail Delivery System <MAILER-DAEMON@mx.acme.example>",
        "To: billing@acme.example",
        "Subject: Undelivered Mail Returned to Sender",
        "Your message could not be delivered to ap@client.example.",
        "User unknown.",
        "Forwarded message",
        "From: Acme Gas <billing@acme.example>",
        "To: ap@client.example",
        "Subject: Your February bill",
        "Total due: 1,240 kWh, $182.40",
    ], []),
    "postfix": (POSTFIX_BOUNCE, [
        "From: MAILER-DAEMON@mx.acme.example (Mail Delivery System)",
        "To: billing@acme.example",
        "Sent: Mon, 10 Feb 2025 09:15:02 -0500 (EST)",
        "Subject: Undelivered Mail Returned to Sender",
        "This is the mail system at host mx.acme.example.",
        "I'm sorry to have to inform you that your message could not",
        "be delivered to one or more recipients.",
        "<ap@client.example>: host mail.client.example[203.0.113.5] said: 550 5.1.1",
        "    <ap@client.example>: Recipient address rejected: User unknown",
        # The returned headers are text, read as more message text (as they were).
        "Return-Path: <billing@acme.example>",
        "From: Acme Gas <billing@acme.example>",
        "To: ap@client.example",
        "Subject: Your February bill",
        "Message-Id: <bill-0210@acme.example>",
    ], []),
    "exchange": (EXCHANGE_BOUNCE, [
        "From: Microsoft Outlook <postmaster@client.example>",
        "To: <billing@acme.example>",
        "Subject: Undeliverable: Your February bill",
        "Delivery has failed to these recipients or groups:",
        "ap@client.example",
        "The email address you entered couldn't be found.",
        "Forwarded message",
        "From: Acme Gas <billing@acme.example>",
        "To: ap@client.example",
        "Subject: Your February bill",
        "Total due: 1,240 kWh, $182.40",
        "Attachments: bill.pdf",
    ], ["attachments_not_read"]),
}


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("name", list(BOUNCES))
def test_a_bounce_reads_as_before(name: str, newline: bytes, tmp_path: Path) -> None:
    raw, lines, codes = BOUNCES[name]
    raw = raw.replace(b"\r\n", b"\n").replace(b"\n", newline)
    package = read_eml(raw)
    # The notice and the returned message are read; the delivery-status fields never were.
    assert [line for line in email_text(package).splitlines() if line.strip()] == lines
    assert not any(field in email_text(package) for field in ("Reporting-MTA", "Final-Recipient", "Status: 5"))
    assert [warning["code"] for warning in email_warnings(package)] == codes
    blocks, pane = _blocks_and_pane(raw, tmp_path)
    # Line n of the pane is the parser's block n (the pane keeps a line's indent).
    assert pane == lines
    assert blocks == [line.strip() for line in pane]


# --- a delivery-status part of blank lines -----------------------------------------------------
BLANK_LINES = 900_000
HEAD = (b"From: MAILER-DAEMON@mx.acme.example\r\nTo: billing@acme.example\r\nSubject: Undelivered\r\n"
        b"MIME-Version: 1.0\r\n")
HEAD_LINES = ["From: MAILER-DAEMON@mx.acme.example", "To: billing@acme.example", "Subject: Undelivered"]
AS_RFC822 = b"Content-Type: message/rfc822\r\n"
AS_EML_FILE = b'Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="bounce.eml"\r\n'


def _fields(blank: bytes) -> bytes:
    return b"Content-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; mx.acme.example\r\n" + blank * BLANK_LINES


def _report(fields: bytes) -> bytes:
    return (HEAD + b'Content-Type: multipart/report; report-type=delivery-status; boundary="r"\r\n\r\n'
            b"--r\r\nContent-Type: text/plain\r\n\r\nYour message could not be delivered.\r\n--r\r\n" + fields
            + b"--r--\r\n")


def _forwarded(inner: bytes, header: bytes) -> bytes:
    return (HEAD + b'Content-Type: multipart/mixed; boundary="m"\r\n\r\n--m\r\nContent-Type: text/plain\r\n\r\n'
            b"See the bounce below.\r\n--m\r\n" + header + b"\r\n" + inner + b"\r\n--m--\r\n")


REPORT_LINES = [*HEAD_LINES, "Your message could not be delivered."]
FORWARD_LINES = [*HEAD_LINES, "See the bounce below.", "Forwarded message", *REPORT_LINES]
CRAFTED = {
    "top_level": (lambda fields: HEAD + fields, HEAD_LINES),
    "in_a_report": (_report, REPORT_LINES),
    "in_a_forwarded_message": (lambda fields: _forwarded(_report(fields), AS_RFC822), FORWARD_LINES),
    "in_an_attached_eml": (lambda fields: _forwarded(_report(fields), AS_EML_FILE), FORWARD_LINES),  # parsed apart
}


@pytest.mark.parametrize("blank", [b"\n", b"\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("where", list(CRAFTED))
def test_a_delivery_status_part_of_blank_lines_is_read_quickly(where: str, blank: bytes, tmp_path: Path) -> None:
    build, lines = CRAFTED[where]
    path = tmp_path / "bounce.eml"
    path.write_bytes(build(_fields(blank)))

    started = time.perf_counter()
    output = EmailParser().parse(path, "D", "R")
    parsed = time.perf_counter() - started
    started = time.perf_counter()
    pane = document_content(path, "message/rfc822")["lines"]
    shown = time.perf_counter() - started

    # It took 3.5 s (and about 260 MB) each way, in every one of these places.
    assert parsed < 1.0 and shown < 1.0, (parsed, shown)
    assert output["status"] == "parsed"
    assert [block["text"] for block in output["text_blocks"]] == pane == lines
    # One part, not one per blank line: the part budget is not used up.
    assert "email_parts_limit" not in [warning["code"] for warning in output["warnings"]]


def test_a_delivery_status_part_of_blank_lines_takes_little_memory() -> None:
    raw = _report(_fields(b"\n"))
    tracemalloc.start()
    try:
        read_eml(raw)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # One message per blank line peaked at 250 MB for this 0.9 MB file; it is about 13 MB now.
    assert peak < 40 * 1024 * 1024, peak
