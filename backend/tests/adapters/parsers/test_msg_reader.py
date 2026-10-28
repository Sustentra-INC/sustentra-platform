"""Reading an Outlook message (.msg) into the same ``EmailPackage`` the .eml reader builds.

Every message is written here by ``_msg_builder`` (a real compound file, byte by byte). The parity
test builds each case twice, as an ``EmailMessage`` for ``read_eml`` and as a ``Message`` for
``read_msg``, and compares what the email parser makes of the two packages. The hostile tests
build files the format allows but no mail program writes: huge streams, thousands of recipients,
messages inside messages, streams that share sectors or loop, random damage.
"""

from __future__ import annotations

import codecs
import random
import struct
import time
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import pytest

from backend.app.adapters.parsers import email_reader, msg_reader
from backend.app.adapters.parsers.email_parser import email_text, email_warnings
from backend.app.adapters.parsers.email_reader import (
    DAMAGED_EMAIL,
    MAX_DEPTH,
    MAX_PARTS,
    EmailError,
    EmailPackage,
    codepage_codec,
    read_eml,
)
from backend.app.adapters.parsers.msg_reader import (
    MAX_MSG_PROPERTIES,
    MAX_RECIPIENTS,
    NOT_AN_OUTLOOK_MESSAGE,
    read_msg,
)
from backend.tests.adapters.parsers._msg_builder import (
    PROPERTIES,
    Attachment,
    Embedded,
    Message,
    Recipient,
    msg_bytes,
    msg_tree,
)
from backend.tests.adapters.parsers._ole_builder import Tree, ole_tree
from backend.tests.adapters.parsers._timing import budget
from backend.tests.adapters.parsers._xls_builder import xls_bytes

PDF = b"%PDF" * 1000
SENT = "Mon, 10 Feb 2025 09:15:00 -0500"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(300)
CSV = b"month,therms\nJanuary,120\n"
HTML = ("<html><body><p>Total Usage: 120 therms</p><table><tr><td>Month</td><td>Therms</td></tr></table>"
        "</body></html>")
SENDER = "Acme Gas <billing@acme.example>"
TO = 'Jane Doe <jane@client.example>, "Doe, John" <john@client.example>'
BY_VALUE_PDF = "application/pdf"
LINK = "a link to a file, not the file itself"
OBJECT = "an embedded object; its contents can't be read here"
FORWARD_FAILED = "the forwarded message could not be read"


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _read(message: Message, **options: Any) -> EmailPackage:
    return read_msg(msg_bytes(message, **options))


def _refused(data: bytes) -> EmailError:
    with pytest.raises(EmailError) as refused:
        read_msg(data)
    return refused.value


def _notes(package: EmailPackage) -> list[str]:
    return [code for code, _ in package.all_notes()]


# --- the same message as an .eml and as a .msg ---------------------------------------------------
def _eml(subject: str = "Your February bill", body: str | None = "Total Usage: 120 therms", *,
         sender: str = SENDER, to: str = TO, cc: str | None = "ap@client.example", date: str = SENT
         ) -> EmailMessage:
    message = EmailMessage()
    message["From"], message["To"], message["Date"], message["Subject"] = sender, to, date, subject
    if cc:
        message["Cc"] = cc
    if body is not None:
        message.set_content(body)
    return message


def _msg(subject: str = "Your February bill", body: str | None = "Total Usage: 120 therms", **fields: Any
         ) -> Message:
    return Message(
        subject=subject, sender_name="Acme Gas", sender_smtp="billing@acme.example",
        recipients=[Recipient("Jane Doe", "jane@client.example"), Recipient("Doe, John", "john@client.example"),
                    Recipient("", "ap@client.example", kind=2)],
        body=body, transport_headers=f"Date: {SENT}\r\n", **fields)


def _plain_with_attachment() -> tuple[EmailMessage, Message]:
    eml = _eml()
    eml.add_attachment(PDF, maintype="application", subtype="pdf", filename="bill.pdf")
    return eml, _msg(attachments=[Attachment("bill.pdf", PDF, mime=BY_VALUE_PDF)])


def _html_only() -> tuple[EmailMessage, Message]:
    eml = _eml(body=None)
    eml.set_content(HTML, subtype="html")
    return eml, _msg(body=None, html=HTML.encode())


def _inline_logo() -> tuple[EmailMessage, Message]:
    eml = _eml()
    eml.add_attachment(PNG, maintype="image", subtype="png", filename="logo.png", disposition="inline", cid="<logo>")
    eml.add_attachment(CSV, maintype="text", subtype="csv", filename="usage.csv")
    return eml, _msg(attachments=[Attachment("logo.png", PNG, mime="image/png", hidden=True, content_id="logo"),
                                  Attachment("usage.csv", CSV, mime="text/csv")])


def _forwarded() -> tuple[EmailMessage, Message]:
    inner = _eml("March invoice", "March usage: 98 therms", to="ap@client.example", cc=None,
                 date="Tue, 11 Mar 2025 10:00:00 -0500")
    inner.add_attachment(PDF, maintype="application", subtype="pdf", filename="march.pdf")
    eml = _eml("Fwd: March invoice", "Forwarding the March invoice")
    eml.add_attachment(inner)
    forwarded = Message(
        subject="March invoice", sender_name="Acme Gas", sender_smtp="billing@acme.example",
        recipients=[Recipient("", "ap@client.example")], body="March usage: 98 therms",
        transport_headers="Date: Tue, 11 Mar 2025 10:00:00 -0500\r\n",
        attachments=[Attachment("march.pdf", PDF, mime=BY_VALUE_PDF)])
    return eml, _msg("Fwd: March invoice", "Forwarding the March invoice", attachments=[Embedded(forwarded)])


def _no_body() -> tuple[EmailMessage, Message]:
    return _eml(body=None), _msg(body=None)


CASES: dict[str, tuple[Callable[[], tuple[EmailMessage, Message]], list[str]]] = {
    # what both readers must give (so the comparison cannot pass on two empty results)
    "plain text and a PDF": (_plain_with_attachment, [
        f"From: {SENDER}", f"To: {TO}", "Cc: ap@client.example", f"Sent: {SENT}", "Subject: Your February bill",
        "", "Total Usage: 120 therms", "", "Attachments: bill.pdf"]),
    "HTML only": (_html_only, ["", "Total Usage: 120 therms", "Month\tTherms"]),
    "an inline logo": (_inline_logo, ["", "Attachments: usage.csv"]),
    "a forwarded message": (_forwarded, ["Forwarded message", "Subject: March invoice", "", "Attachments: march.pdf"]),
    "no body": (_no_body, ["Subject: Your February bill"]),
}


@pytest.mark.parametrize("case", CASES)
def test_a_message_reads_like_the_same_eml(case: str) -> None:
    build, expected = CASES[case]
    eml, msg = build()
    from_eml, from_msg = read_eml(eml.as_bytes()), read_msg(msg_bytes(msg))
    text = email_text(from_msg)
    assert text == email_text(from_eml)
    assert email_warnings(from_msg) == email_warnings(from_eml)
    assert all(line in text.split("\n") for line in expected)  # not two equal, empty results
    note = next((warning["message"] for warning in email_warnings(from_msg) if warning["code"] == "attachments_not_read"),
                "")
    if case == "an inline logo":
        assert "logo.png (1 KB, in the message body)" in note
    if case == "a forwarded message":
        assert "March invoice › march.pdf" in note
    if case == "no body":
        assert [warning["code"] for warning in email_warnings(from_msg)] == ["no_message_text"]


def test_the_checked_headers_of_the_first_case() -> None:
    eml, msg = _plain_with_attachment()
    expected = ('Acme Gas <billing@acme.example> | Jane Doe <jane@client.example>, "Doe, John" <john@client.example> | '
                "ap@client.example | Mon, 10 Feb 2025 09:15:00 -0500")
    for package in (read_eml(eml.as_bytes()), read_msg(msg_bytes(msg))):  # the .eml reader's output, checked
        assert " | ".join((package.sender, package.to, package.cc, package.sent_at)) == expected
        assert (package.subject, package.body_text, package.body_source) == (
            "Your February bill", "Total Usage: 120 therms", "plain")
        [part] = package.attachments
        assert (part.name, part.content_type, part.data, part.inline, part.size) == (
            "bill.pdf", BY_VALUE_PDF, PDF, False, 4_000)


def test_version_4_messages_are_read() -> None:
    eml, msg = _plain_with_attachment()
    package = read_msg(msg_bytes(msg, sector_shift=12))
    assert email_text(package) == email_text(read_eml(eml.as_bytes()))
    assert package.attachments[0].data == PDF
    forwarded = read_msg(msg_bytes(_forwarded()[1], sector_shift=12))
    assert [nested.subject for nested in forwarded.nested] == ["March invoice"]


# --- headers --------------------------------------------------------------------------------------
def test_senders_and_recipients() -> None:
    def sender(**fields: Any) -> str:
        return _read(Message(**fields)).sender

    exchange = {"sender_name": "Acme Gas", "sender_type": "EX", "sender_email": "/O=ACME/OU=EXCH/CN=BILLING"}
    assert sender(**exchange, sender_smtp="billing@acme.example") == "Acme Gas <billing@acme.example>"
    assert sender(**exchange) == "Acme Gas"  # an Exchange address is not shown
    assert sender(sender_name="Acme Gas", sender_email="billing@acme.example") == "Acme Gas <billing@acme.example>"
    assert sender(sender_name="billing@acme.example", sender_smtp="billing@acme.example") == "billing@acme.example"
    assert sender(sender_smtp="billing@acme.example") == "billing@acme.example"
    assert sender(sender_name="Doe, Jane", sender_smtp="jane@x.example") == '"Doe, Jane" <jane@x.example>'
    assert sender() == ""
    # the name of whom it was sent for, when the sender has none
    assert sender(extra={0x0042001F: _utf16("On behalf"), 0x5D02001F: _utf16("rep@x.example")}) == (
        "On behalf <rep@x.example>")
    assert sender(sender_name="Acme", extra={0x0042001F: _utf16("On behalf")}) == "Acme"

    package = _read(Message(recipients=[
        Recipient("Jane Doe", "jane@client.example"), Recipient("Doe, John", "john@client.example"),
        Recipient("Quiet", "quiet@client.example", kind=3),  # Bcc: not shown
        Recipient("Boss", "boss@client.example", kind=2), Recipient("Mailing list", "list@x.example", kind=7),
        Recipient("Exchange user", "/O=ACME/CN=USER", address_type="EX"),  # no SMTP address: the name alone
        Recipient("Plain Name", "plain@client.example", address_type="SMTP")]))
    assert package.to == ('Jane Doe <jane@client.example>, "Doe, John" <john@client.example>, Exchange user, '
                          "Plain Name <plain@client.example>")
    assert package.cc == "Boss <boss@client.example>"

    # no recipient storages: the display lists, names separated by ";"
    package = _read(Message(display_to="Jane Doe; Doe, John", display_cc=" Boss ;; "))
    assert (package.to, package.cc) == ('Jane Doe, "Doe, John"', "Boss")
    # recipient storages win over the display lists
    package = _read(Message(display_to="Someone Else", recipients=[Recipient("Jane Doe", "jane@client.example")]))
    assert package.to == "Jane Doe <jane@client.example>"


def test_a_subject_and_message_id_are_one_clean_line() -> None:
    package = _read(Message(subject="\x01\x05RE:   Your\tFebruary\r\nbill\x00",
                            extra={0x1035001F: _utf16("<feb-bill@acme.example>")}))
    assert (package.subject, package.message_id) == ("RE: Your February bill", "<feb-bill@acme.example>")


def test_sent_is_the_date_as_sent_else_the_submit_time_in_utc() -> None:
    headers = "Received: x\r\nDate: Mon, 10 Feb 2025\r\n 09:15:00 -0500\r\nSubject: s\r\n\r\nDate: no"
    assert _read(Message(transport_headers=headers)).sent_at == SENT
    assert _read(Message(transport_headers="subject: s\nDATE:  Tue, 11 Feb 2025 10:00:00 +0000 \n")
                 ).sent_at == "Tue, 11 Feb 2025 10:00:00 +0000"  # any letter case, LF line ends
    assert _read(Message(transport_headers=f"Date: {SENT}\r\nSubject: s\r\nDate: Tue, 11 Feb 2025 09:15:00 -0500")
                 ).sent_at == SENT  # the first one
    when = datetime(2025, 2, 10, 14, 15, tzinfo=UTC)
    assert _read(Message(submit_time=when)).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    # headers that have no usable Date give the submit time; a Date header wins over it
    assert _read(Message(submit_time=when, transport_headers="Received: x\r\n\r\nDate: no")
                 ).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    assert _read(Message(submit_time=when, transport_headers="Date:\r\nSubject: s")
                 ).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    assert _read(Message(submit_time=when, transport_headers=f"Date: {SENT}")).sent_at == SENT
    # the delivery time when there is no submit time
    delivered = struct.pack("<Q", (1_739_196_900 + 11_644_473_600) * 10_000_000)
    assert _read(Message(extra={0x0E060040: delivered})).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    assert _read(Message()).sent_at == ""
    assert _read(Message(transport_headers="Received: x")).sent_at == ""

    for ticks in (2**63 - 1, 2**64 - 1, 0):  # out of range, or not set: no Sent line, no error
        package = _read(Message(subject="s", extra={0x00390040: struct.pack("<Q", ticks)}))
        assert package.sent_at == "" and "Sent:" not in email_text(package)


# --- code pages -------------------------------------------------------------------------------------
def test_ansi_strings_use_the_message_code_page() -> None:
    russian = _read(Message(subject="Счёт за газ", body="Итого: 120", unicode=False, codepage=1251,
                            recipients=[Recipient("Иван", "ivan@client.example")],
                            attachments=[Attachment("счёт.pdf", b"x")]))
    assert (russian.subject, russian.body_text, russian.to) == ("Счёт за газ", "Итого: 120",
                                                                 "Иван <ivan@client.example>")
    assert russian.attachments[0].name == "счёт.pdf"
    assert _read(Message(subject="Café", unicode=False)).subject == "Café"  # no code page: Windows-1252
    assert _read(Message(subject="Café", unicode=False, codepage=99999)).subject == "Café"  # unknown: the same
    assert _read(Message(subject="Café", unicode=False, codepage=1252)).subject == "Café"
    assert _read(Message(subject="日本語", unicode=False, codepage=932)).subject == "日本語"
    # the internet code page, when the message code page is absent
    tree = msg_tree(Message(subject="Счёт", unicode=False, codepage=1251))
    stream = tree[PROPERTIES]
    assert isinstance(stream, bytes) and struct.pack("<I", 0x3FFD0003) in stream
    tree[PROPERTIES] = stream.replace(struct.pack("<I", 0x3FFD0003), struct.pack("<I", 0x3FDE0003))
    assert read_msg(ole_tree(tree)).subject == "Счёт"
    # UTF-16 strings do not depend on it
    assert _read(Message(subject="Счёт", codepage=1252)).subject == "Счёт"


@pytest.mark.parametrize(("codepage", "codec"), [
    (None, "cp1252"), (1252, "cp1252"), (1251, "cp1251"), (65001, "utf-8"), (20127, "ascii"), (28591, "iso8859-1"),
    (28599, "iso8859-9"), (28603, "iso8859-13"), (28605, "iso8859-15"), (50220, "iso2022_jp"),
    (50221, "iso2022_jp"), (50222, "iso2022_jp"), (51932, "euc_jp"), (51949, "euc_kr"), (54936, "gb18030"),
    (936, "gbk"), (20866, "koi8_r"), (21866, "koi8_u"), (10000, "mac_roman"), (932, "cp932"),
    (99999, "cp1252"), (0, "cp1252"), (-1, "cp1252"), (2**31 - 1, "cp1252"), (28600, "cp1252"), (1200, "cp1252"),
])
def test_code_pages_name_a_codec(codepage: int | None, codec: str) -> None:
    assert codecs.lookup(codepage_codec(codepage)) == codecs.lookup(codec)
    assert msg_reader.codepage_codec is codepage_codec


def test_a_code_page_cannot_reach_a_denied_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    for denied in ("punycode", "idna", "unicode_escape", "raw_unicode_escape"):
        monkeypatch.setitem(email_reader._CODEPAGE_CODECS, 4321, denied)
        assert codepage_codec(4321) == "cp1252"
    # .eml's own resolver is unchanged: an unknown charset still reads as UTF-8
    assert email_reader._codec("cp99999") == "utf-8" and email_reader._codec("punycode") == "utf-8"


def test_html_bytes_use_the_internet_code_page_else_utf_8() -> None:
    html = "<p>Café</p>"
    assert _read(Message(html=html.encode("utf-8"))).body_text == "Café"  # no code page: UTF-8
    latin = {0x3FDE0003: struct.pack("<i", 28591)}
    assert _read(Message(html=html.encode("latin-1"), extra=latin)).body_text == "Café"
    assert _read(Message(html=html.encode("latin-1"), extra={0x3FDE0003: struct.pack("<i", 99999)})
                 ).body_text == "Café"  # unknown: Windows-1252
    assert _read(Message(html=html.encode("utf-8"), extra={0x3FDE0003: struct.pack("<i", 65001)})).body_text == "Café"
    # an HTML body stored as a string property
    assert _read(Message(extra={0x1013001F: html.encode("utf-16-le")})).body_text == "Café"


# --- the message text ---------------------------------------------------------------------------------
def test_the_plain_body_wins_unless_it_is_blank() -> None:
    both = _read(Message(body="Plain text", html=b"<p>HTML text</p>"))
    assert (both.body_text, both.body_source) == ("Plain text", "plain")
    blank = _read(Message(body="  \r\n\t", html=b"<p>HTML text</p>"))
    assert (blank.body_text, blank.body_source) == ("HTML text", "html")
    assert _read(Message(body="  \r\n")).body_source == "none"
    assert _read(Message()).body_source == "none"
    assert _read(Message(rtf=b"\x00" * 20)).body_source == "none"  # compressed RTF is not read here
    crlf = _read(Message(body="one\r\n\r\n\r\n\r\ntwo   \r\nthree\x00"))
    assert crlf.body_text == "one\n\ntwo\nthree"


# --- attachments --------------------------------------------------------------------------------------
def test_attachments_are_listed_not_read() -> None:
    package = _read(Message(body="x", attachments=[
        Attachment("bill.pdf", b"x" * 3072, mime=BY_VALUE_PDF),
        Attachment("usage.xlsx", b"y" * 100),
        Attachment("Q1 report.docx", b"z" * 5000, method=4),  # by reference
        Attachment("shared.docx", b"z" * 2048, method=2),
        Attachment("cloud.docx", b"z" * 1024, method=7),  # a web reference
        Attachment("odd.docx", b"z" * 1024, method=-3),  # a method nobody defined
        Attachment("chart.ole", b"o" * 8000, method=6),
        Attachment("none.bin", b"n", method=0)]))  # no attachment: skipped
    by_name = {part.name: part for part in package.attachments}
    assert list(by_name) == ["bill.pdf", "usage.xlsx", "Q1 report.docx", "shared.docx", "cloud.docx", "odd.docx",
                             "chart.ole"]
    assert (by_name["bill.pdf"].data, by_name["bill.pdf"].size, by_name["bill.pdf"].note) == (
        b"x" * 3072, 3072, None)
    assert by_name["usage.xlsx"].content_type == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")  # from the extension
    for name in ("Q1 report.docx", "shared.docx", "cloud.docx", "odd.docx"):
        assert (by_name[name].data, by_name[name].note) == (b"", LINK)
    assert (by_name["Q1 report.docx"].size, by_name["shared.docx"].size) == (5000, 2048)  # as the message states
    assert (by_name["chart.ole"].data, by_name["chart.ole"].size, by_name["chart.ole"].note) == (b"", 8000, OBJECT)
    described = email_warnings(package)[0]["message"]
    assert "bill.pdf (3 KB)" in described and f"Q1 report.docx (5 KB, {LINK})" in described
    assert f"chart.ole (8 KB, {OBJECT})" in described
    assert email_text(package).endswith("Attachments: bill.pdf, usage.xlsx, Q1 report.docx, shared.docx, "
                                        "cloud.docx, odd.docx, chart.ole\n")


def test_attachment_names_come_from_the_long_name_the_short_name_the_display_name_or_the_type() -> None:
    message = Message(attachments=[Attachment("x", b"a") for _ in range(4)] + [Attachment("", b"e", mime="text/csv")])
    tree = msg_tree(message)

    def storage(number: int) -> Tree:
        stored = tree[f"__attach_version1.0_#{number:08X}"]
        assert isinstance(stored, dict)
        return stored

    storage(0).update({"__substg1.0_3707001F": _utf16("Long name.pdf"), "__substg1.0_3704001F": _utf16("LONGNA~1.PDF"),
                       "__substg1.0_3001001F": _utf16("Display")})
    del storage(1)["__substg1.0_3707001F"]
    storage(1)["__substg1.0_3704001F"] = _utf16("short.pdf")
    del storage(2)["__substg1.0_3707001F"], storage(2)["__substg1.0_3704001F"]
    storage(2)["__substg1.0_3001001F"] = _utf16("Display name.pdf")
    for stream in ("3707001F", "3704001F", "3001001F"):
        del storage(3)[f"__substg1.0_{stream}"]
    storage(3)["__substg1.0_370E001F"] = _utf16("application/pdf")
    package = read_msg(ole_tree(tree))
    assert [part.name for part in package.attachments] == [
        "Long name.pdf", "short.pdf", "Display name.pdf", "attachment-4.pdf", "attachment-5.csv"]
    assert [part.content_type for part in package.attachments] == [
        "application/pdf", "application/pdf", "application/pdf", "application/pdf", "text/csv"]


def test_attachment_names_are_short_file_names() -> None:
    package = _read(Message(attachments=[
        Attachment("..\\..\\windows\\evil.exe", b"a"), Attachment("C:/dir/\x07bell.txt", b"b"),
        Attachment("a" * 300 + ".pdf", b"c"), Attachment("   ", b"d", mime="not a type")]))
    assert [part.name for part in package.attachments][:2] == ["evil.exe", "bell.txt"]
    assert len(package.attachments[2].name) == 120 and package.attachments[2].name.endswith(".pdf")
    assert package.attachments[3].name == "attachment-4.bin"
    assert package.attachments[3].content_type == "application/octet-stream"  # the type it stated was not one


def test_an_attachment_in_the_message_body_is_inline() -> None:
    package = _read(Message(attachments=[
        Attachment("hidden.png", b"a", hidden=True), Attachment("flagged.png", b"b", flags=0x4, content_id="<c1>"),
        Attachment("plain.png", b"c", flags=0x1), Attachment("both.png", b"d", hidden=True, flags=0x4)]))
    assert [part.inline for part in package.attachments] == [True, True, False, True]
    assert [part.content_id for part in package.attachments] == [None, "c1", None, None]
    assert email_text(package).endswith("Attachments: plain.png\n")


def test_an_attachment_without_a_method_is_by_value_when_it_has_data() -> None:
    tree = msg_tree(Message(attachments=[Attachment("a.pdf", b"data"), Attachment("b.pdf", b"")]))
    for number in (0, 1):
        stored = tree[f"__attach_version1.0_#{number:08X}"]
        assert isinstance(stored, dict)
        stored[PROPERTIES] = bytes(8)  # no properties at all
        if number == 1:
            del stored["__substg1.0_37010102"]  # and no data
    package = read_msg(ole_tree(tree))
    assert [(part.name, part.data) for part in package.attachments] == [("a.pdf", b"data")]


def test_an_embedded_message_that_cannot_be_read_is_listed() -> None:
    message = Message(subject="Outer", attachments=[
        Embedded(Message(subject="March / invoice\\final", body="x"), size=7000),
        Embedded(Message(subject="Gone", body="x")), Embedded(Message(body="x"))])
    tree = msg_tree(message)
    for number in range(3):
        attachment = tree[f"__attach_version1.0_#{number:08X}"]
        assert isinstance(attachment, dict)
        embedded = attachment["__substg1.0_3701000D"]
        assert isinstance(embedded, dict)
        if number == 1:
            del attachment["__substg1.0_3701000D"]  # the storage is not there at all
        else:
            del embedded[PROPERTIES]  # a message storage with no property stream
    package = read_msg(ole_tree(tree))
    assert package.nested == []
    assert [(part.name, part.content_type, part.note, part.data, part.size) for part in package.attachments] == [
        ("March invoice final.msg", "application/vnd.ms-outlook", FORWARD_FAILED, b"", 7000),
        ("message.msg", "application/vnd.ms-outlook", FORWARD_FAILED, b"", 0),
        ("message.msg", "application/vnd.ms-outlook", FORWARD_FAILED, b"", 0)]
    assert "March invoice final.msg (7 KB, the forwarded message could not be read)" in (
        email_warnings(package)[0]["message"])


def _nested(levels: int, *, attachment: bool = True) -> Message:
    inner: Message | None = None
    for level in range(levels, 0, -1):
        inner = Message(subject=f"Level {level}", body=f"Text {level}",
                        attachments=[*([Attachment(f"l{level}.pdf", b"x")] if attachment else []),
                                     *([Embedded(inner)] if inner else [])])
    return Message(subject="Level 0", body="Text 0", attachments=[Attachment("l0.pdf", b"x")]
                   + ([Embedded(inner)] if inner else []))


def test_forwarded_messages_stop_three_levels_deep() -> None:
    package = _read(_nested(5))
    levels = [package]
    while levels[-1].nested:
        assert len(levels[-1].nested) == 1
        levels.append(levels[-1].nested[0])
    assert [level.subject for level in levels] == ["Level 0", "Level 1", "Level 2", "Level 3"]
    assert len(levels) == MAX_DEPTH + 1
    assert [note for note in package.all_notes()] == [(
        "forwarded_too_deep", f'A message forwarded more than {MAX_DEPTH} levels deep ("Level 4") was not read.')]
    assert [part.name for part in package.all_attachments()] == ["l0.pdf", "l1.pdf", "l2.pdf", "l3.pdf"]
    assert [part.path for part in package.all_attachments()] == [
        [], ["Level 1"], ["Level 1", "Level 2"], ["Level 1", "Level 2", "Level 3"]]
    text = email_text(package)
    assert "Text 3" in text and "Text 4" not in text and text.count("Forwarded message") == 3
    assert "Level 1 › Level 2 › Level 3 › l3.pdf" in email_warnings(package)[-1]["message"]


def test_an_embedded_message_without_a_subject_is_a_forwarded_message() -> None:
    package = _read(Message(attachments=[Embedded(Message(body="x", attachments=[Attachment("a.pdf", b"x")]))]))
    assert package.all_attachments()[0].path == ["Forwarded message"]
    deep = _read(_nested(4))
    assert [note for _, note in deep.all_notes()] == [
        f'A message forwarded more than {MAX_DEPTH} levels deep ("Level 4") was not read.']
    nameless = Message(attachments=[Embedded(Message(attachments=[Embedded(Message(attachments=[Embedded(
        Message(attachments=[Embedded(Message(body="x"))]))]))]))])
    assert [note for _, note in _read(nameless).all_notes()] == [
        f'A message forwarded more than {MAX_DEPTH} levels deep ("Forwarded message") was not read.']


def test_more_than_two_hundred_parts() -> None:
    package = _read(Message(body="x", attachments=[Attachment(f"a{n}.pdf", b"x") for n in range(250)]))
    assert len(package.attachments) == MAX_PARTS == 200
    assert [part.name for part in package.attachments][:3] == ["a0.pdf", "a1.pdf", "a2.pdf"]
    assert _notes(package) == ["email_parts_limit"]
    # embedded messages count as parts too, shared across the levels
    mixed = _read(Message(attachments=[Embedded(Message(body="x", attachments=[
        Attachment(f"b{n}.pdf", b"x") for n in range(150)])) for _ in range(2)]))
    assert len(mixed.all_attachments()) < 300 and _notes(mixed) == ["email_parts_limit"]


def test_storage_names_set_the_order_whatever_the_case() -> None:
    tree = msg_tree(Message(attachments=[Attachment(name, b"x") for name in ("first", "second", "third")]))
    renamed: Tree = {}
    for name, content in tree.items():
        renamed[name.replace("#00000001", "#0000000b").lower().replace("__attach", "__ATTACH")
                if name.startswith("__attach") else name] = content
    assert [part.name for part in read_msg(ole_tree(renamed)).attachments] == ["first", "third", "second"]


# --- what is not a message -------------------------------------------------------------------------------
def test_ole_files_that_are_not_messages() -> None:
    word = ole_tree({"WordDocument": bytes(600), "1Table": bytes(100)})
    excel = xls_bytes({"S": [["a", 1]]})
    for data in (word, excel, ole_tree({PROPERTIES.upper().replace("PROPERTIES", "OTHER"): bytes(40)}),
                 ole_tree({PROPERTIES: {"inner": b"x" * 40}})):  # a storage is not the property stream
        refused = _refused(data)
        assert (refused.code, refused.message, refused.__cause__) == (
            "not_an_email", NOT_AN_OUTLOOK_MESSAGE, None)


@pytest.mark.parametrize("data", [b"", b"just text", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(600), bytes(2000),
                                  b"From: a@example.com\r\nSubject: s\r\n\r\nbody\r\n"])
def test_bytes_that_are_not_a_compound_file_are_damaged(data: bytes) -> None:
    refused = _refused(data)
    assert (refused.code, refused.message, refused.__cause__) == ("email_load_failed", DAMAGED_EMAIL, None)


def test_a_failure_nobody_foresaw_is_still_only_an_email_error(monkeypatch: pytest.MonkeyPatch) -> None:
    good = msg_bytes(Message(subject="s"))
    for failure in (RecursionError(), ValueError("x"), MemoryError()):
        def explode(data: bytes, failure: BaseException = failure) -> EmailPackage:
            raise failure

        monkeypatch.setattr(msg_reader, "_read", explode)
        refused = _refused(good)
        assert (refused.code, refused.message) == ("email_load_failed", DAMAGED_EMAIL)
        assert refused.__cause__ is failure  # what the random-damage test treats as a bug in the reader
    monkeypatch.undo()
    # a type the standard library cannot place gives a plain attachment type, not an error
    monkeypatch.setattr(msg_reader.mimetypes, "guess_type", lambda name: (_ for _ in ()).throw(ValueError(name)))
    package = _read(Message(attachments=[Attachment("bill.pdf", b"x")]))
    assert package.attachments[0].content_type == "application/octet-stream"


def test_the_copy_follows_the_design_standard() -> None:
    assert NOT_AN_OUTLOOK_MESSAGE == ("This file is not an Outlook message. Ask the client to forward the email "
                                      "again, or upload its attachments on their own.")


# --- caps are module constants ----------------------------------------------------------------------------
def test_property_streams_are_read_for_a_capped_number_of_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (MAX_MSG_PROPERTIES, MAX_RECIPIENTS) == (4_096, 500)
    data = msg_bytes(Message(subject="s", recipients=[Recipient(f"R{n}", f"r{n}@x.example") for n in range(6)],
                            extra={0x00390040: struct.pack("<Q", (1_739_196_900 + 11_644_473_600) * 10_000_000)}))
    assert read_msg(data).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    monkeypatch.setattr(msg_reader, "MAX_MSG_PROPERTIES", 1)  # the code page (listed first) only
    assert read_msg(data).sent_at == ""
    monkeypatch.setattr(msg_reader, "MAX_RECIPIENTS", 2)
    assert read_msg(data).to == "R0 <r0@x.example>, R1 <r1@x.example>"


def test_a_partial_last_entry_is_ignored() -> None:
    tree = msg_tree(Message(subject="s", extra={0x00390040: struct.pack("<Q", (1_739_196_900 + 11_644_473_600)
                                                                         * 10_000_000)}))
    stream = tree[PROPERTIES]
    assert isinstance(stream, bytes)
    tree[PROPERTIES] = stream + b"\xff" * 15  # a 16-byte entry cut short
    assert read_msg(ole_tree(tree)).sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"
    tree[PROPERTIES] = stream[:32 + 8]  # cut inside the first entry: none are read
    assert read_msg(ole_tree(tree)).sent_at == ""
    tree[PROPERTIES] = stream[:20]  # shorter than the header
    assert read_msg(ole_tree(tree)).sent_at == ""


# --- hostile ----------------------------------------------------------------------------------------------
def _property_stream(entries: int) -> bytes:
    """A top-level property stream of ``entries`` entries: filler, a delivery time among the first
    ones and a submit time (which would win) far past the cap."""

    filler = struct.pack("<IIQ", 0x60000003, 6, 0)  # an id nobody reads, PT_LONG
    stream = bytearray(filler * entries)
    delivered = (1_739_196_900 + 11_644_473_600) * 10_000_000
    stream[10 * 16:11 * 16] = struct.pack("<IIQ", 0x0E060040, 6, delivered)
    stream[5_000 * 16:5_001 * 16] = struct.pack("<IIQ", 0x00390040, 6, delivered + 10**13)
    return bytes(32) + bytes(stream)


def _peak(read: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        read()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_a_huge_property_stream_reads_only_its_first_entries() -> None:
    tree = msg_tree(Message(subject="s"))
    tree[PROPERTIES] = _property_stream(1_000_000)  # 16 MB
    data = ole_tree(tree, sector_shift=12)
    started = time.perf_counter()
    package = read_msg(data)
    assert time.perf_counter() - started < budget(0.5)  # about 0.01 s without coverage
    assert package.sent_at == "Mon, 10 Feb 2025 14:15:00 +0000"  # the delivery time among the first entries
    assert _peak(lambda: read_msg(data)) < 3 * len(data)  # the stream once, and a copy while it is joined


def test_a_file_of_large_property_streams_is_read_in_time() -> None:
    """Every recipient and attachment has a property stream of the most entries that are read."""

    message = Message(recipients=[Recipient(f"R{n}", f"r{n}@x.example") for n in range(100)],
                      attachments=[Attachment(f"a{n}.pdf", b"x") for n in range(100)])
    tree = msg_tree(message)
    stream = bytes(8) + struct.pack("<IIQ", 0x60000003, 6, 0) * (2 * MAX_MSG_PROPERTIES)
    for name, storage in tree.items():
        if name.startswith(("__recip", "__attach")):
            assert isinstance(storage, dict)
            storage[PROPERTIES] = stream
    data = ole_tree(tree, sector_shift=12)
    started = time.perf_counter()
    read_msg(data)
    assert time.perf_counter() - started < budget(0.5)  # about 0.07 s without coverage


def test_thousands_of_recipients() -> None:
    message = Message(recipients=[Recipient(f"Person {n:04d}", f"p{n:04d}@client.example") for n in range(1_500)])
    data = msg_bytes(message)  # 9,000 directory entries: the most the container allows is 10,000
    started = time.perf_counter()
    package = read_msg(data)
    assert time.perf_counter() - started < budget(0.5)  # about 0.02 s without coverage
    assert package.to.startswith("Person 0000 <p0000@client.example>, Person 0001") and package.to.endswith("…")
    assert len(package.to) == 1_001 and package.cc == ""
    assert "To: " + package.to in email_text(package)


def test_a_line_that_is_full_does_not_read_the_rest() -> None:
    long_name = "N" * 9_000
    message = Message(recipients=[Recipient(long_name, "first@x.example"), Recipient(long_name, "second@x.example"),
                                  Recipient("Boss", "boss@x.example", kind=2)])
    package = _read(message)
    assert package.to.endswith("…") and "second" not in package.to
    assert package.cc == "Boss <boss@x.example>"  # Cc has its own line
    # The second To recipient is never read: its name shares sectors with the first one's, which
    # would be refused if it were read.
    name = "__recip_version1.0_#0000000{}/__substg1.0_3001001F"
    assert _read(message, share=(name.format(0), name.format(1))).to == package.to


def test_deeply_embedded_messages() -> None:
    data = msg_bytes(_nested(50))
    started = time.perf_counter()
    package = read_msg(data)
    assert time.perf_counter() - started < budget(0.5)  # about 0.01 s without coverage
    assert len(package.all_attachments()) == 4 and _notes(package) == ["forwarded_too_deep"]


def test_shared_and_looping_streams_are_damaged() -> None:
    first, second = "__attach_version1.0_#00000000", "__attach_version1.0_#00000001"
    big = Message(body="x" * 5_000, subject="s" * 80,
                  attachments=[Attachment("a.pdf", b"a" * 5_000), Attachment("b.pdf", b"b" * 5_000)])
    for options in ({"share": (f"{first}/__substg1.0_37010102", f"{second}/__substg1.0_37010102")},
                    {"loop": "__substg1.0_1000001F"}, {"mini_loop": "__substg1.0_0037001F"}, {"dag": True},
                    {"loop": f"{first}/__substg1.0_37010102"}):
        refused = _refused(msg_bytes(big, **options))
        assert (refused.code, refused.message, refused.__cause__) == ("email_load_failed", DAMAGED_EMAIL, None)
    assert read_msg(msg_bytes(big)).attachments[1].data == b"b" * 5_000  # the same message, undamaged


def test_crossed_chains_are_refused_at_the_second_stream_read() -> None:
    """The first stream read keeps the sectors two streams share, and the second is refused. Reading
    runs the body (plain, then HTML when the plain one is blank) before the attachments, so an
    attachment is the one refused; a stream that is never read (here the HTML of a message with a
    plain body) is not noticed."""

    html, attachment = "__substg1.0_10130102", "__attach_version1.0_#00000000/__substg1.0_37010102"
    crossed = {"share": (html, attachment)}
    html_only = Message(html=b"<p>" + b"h" * 5_000, attachments=[Attachment("a.pdf", b"a" * 5_000)])
    refused = _refused(msg_bytes(html_only, **crossed))
    assert (refused.code, refused.message) == ("email_load_failed", DAMAGED_EMAIL)
    plain_too = Message(body="Plain text", html=b"<p>" + b"h" * 5_000, attachments=[Attachment("a.pdf", b"a" * 5_000)])
    package = read_msg(msg_bytes(plain_too, **crossed))
    assert package.body_source == "plain" and package.attachments[0].data.startswith(b"<p>hhh")  # it has the HTML's sectors
    # the other way round: the attachment is read second whichever of the two is the donor
    refused = _refused(msg_bytes(html_only, share=(attachment, html)))
    assert refused.code == "email_load_failed"


@pytest.mark.parametrize("hostile", ["body", "line", "html", "html text", "subject", "headers"])
def test_huge_bodies_are_cut(hostile: str) -> None:
    message = {
        "body": Message(body="a\n" * 10_000_000, unicode=False),  # 20 MB of 8-bit text, a million lines
        "line": Message(body="x" * 3_000_000, unicode=False),  # one line, longer than the text budget
        "html": Message(html=b"<p>x</p>" * 2_500_000),  # 20 MB of tags: the most work for the HTML reader
        "html text": Message(html=b"<p>" + b"word " * 4_000_000),  # 20 MB of text: the most memory
        "subject": Message(subject="s" * 10_000_000),  # 10 MB of characters, 20 MB of UTF-16
        "headers": Message(transport_headers="Received: x\r\n" * 800_000 + "Date: " + SENT, unicode=False),  # 10 MB
    }[hostile]
    data = msg_bytes(message, sector_shift=12)
    started = time.perf_counter()
    package = read_msg(data)
    # about 0.5 s without coverage for the tags (a million characters of HTML, as .eml reads them), under 0.1 s the rest
    assert time.perf_counter() - started < budget(1.5 if hostile == "html" else 0.5)
    if hostile == "body":
        assert "body_truncated" in _notes(package) and package.body_text.count("\n") < 10_000
    elif hostile == "line":
        assert "body_truncated" in _notes(package) and len(package.body_text) == 1_000_000
    elif hostile.startswith("html"):
        assert package.body_source == "html" and "body_truncated" in _notes(package)
        assert len(package.body_text.split("\n")) <= 10_000
    elif hostile == "subject":
        assert len(package.subject) == 1_001 and package.subject.endswith("…")
    else:  # the Date: header lies past the first 65,536 characters: not looked for
        assert package.sent_at == ""
    if hostile != "html":  # tracemalloc slows the HTML reader tenfold; "html text" holds the same bytes
        assert _peak(lambda: read_msg(data)) < 4 * len(data)


@pytest.mark.parametrize(("codec", "unit"), [("utf-16-le", 2), ("cp1252", 1), ("utf-8", 1)])
def test_a_string_is_cut_as_bytes_before_it_is_decoded(codec: str, unit: int) -> None:
    raw = (b"s\x00" if unit == 2 else b"s") * 20_000_000
    tracemalloc.start()
    try:
        text, cut = msg_reader._decode(raw, codec, 8_000)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert (len(text), cut) == (8_000, True) and peak < 200_000, peak


def test_the_text_and_html_budgets_are_shared_with_forwarded_messages() -> None:
    lines = "\n".join(f"line {n}" for n in range(6_000))
    text = _read(Message(body=lines, attachments=[Embedded(Message(subject="Inner", body=lines))]))
    assert text.body_text.count("\n") == 5_999 and text.nested[0].body_text.count("\n") < 4_001
    assert "body_truncated" in _notes(text)  # 12,000 lines asked for, 10,000 allowed
    # HTML is counted by its own budget (markup included): 800,000 characters of tags that show 100,000
    html = b"<b>x</b>" * 100_000
    both = _read(Message(html=html, attachments=[Embedded(Message(subject="Inner", html=html))]))
    assert "body_truncated" in _notes(both)  # 1,600,000 asked for, 1,000,000 allowed
    assert (len(both.body_text), len(both.nested[0].body_text)) == (100_000, 25_000)


def test_a_body_is_decoded_only_as_far_as_the_budget_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    limits: list[int] = []
    decode = msg_reader._decode

    def spy(raw: bytes, codec: str, limit: int) -> tuple[str, bool]:
        limits.append(limit)
        return decode(raw, codec, limit)

    monkeypatch.setattr(msg_reader, "_decode", spy)
    _read(Message(body="x" * 1_500_000, attachments=[Embedded(Message(subject="Inner", body="y" * 100))]))
    assert 1_000_000 in limits and 0 in limits and max(limits) == 1_000_000  # the text budget, then none left


def test_the_date_header_is_found_within_the_scanned_characters_only() -> None:
    filler = "X-Filler: " + "f" * 100 + "\r\n"
    near = filler * 100 + f"Date: {SENT}\r\n"
    far = filler * 1_000 + f"Date: {SENT}\r\n"
    assert _read(Message(transport_headers=near)).sent_at == SENT
    assert _read(Message(transport_headers=far)).sent_at == ""
    huge_value = _read(Message(transport_headers="Date: " + "9" * 200_000))
    assert len(huge_value.sent_at) == 1_001 and huge_value.sent_at.endswith("…")


def _mutations(good: bytes, tree: Tree, rng: random.Random, count: int) -> list[bytes]:
    """``count`` damaged copies of a message: bytes of the file changed, the file cut short, runs
    overwritten, and streams of the message changed before the container is written."""

    damaged = []
    for number in range(count):
        mode = number % 4
        if mode == 3:
            copy = _copy(tree)
            storage, name = rng.choice(_streams_of(copy))
            content = bytearray(storage[name])  # type: ignore[arg-type]
            for _ in range(rng.randint(1, 6)):
                if content:
                    content[rng.randrange(len(content))] = rng.randrange(256)
            storage[name] = bytes(content) if rng.random() < 0.8 else bytes(content[:rng.randrange(len(content) + 1)])
            damaged.append(ole_tree(copy))
            continue
        data = bytearray(good)
        if mode == 0:
            for _ in range(rng.randint(1, 8)):
                data[rng.randrange(len(data))] = rng.randrange(256)
        elif mode == 1:
            del data[rng.randrange(len(data)):]
        else:
            start = rng.randrange(len(data))
            data[start:start + 16] = bytes([rng.choice((0, 255))]) * 16
        damaged.append(bytes(data))
    return damaged


def _copy(tree: Tree) -> Tree:
    return {name: _copy(content) if isinstance(content, dict) else content for name, content in tree.items()}


def _streams_of(tree: Tree) -> list[tuple[Tree, str]]:
    found: list[tuple[Tree, str]] = []
    pending: list[Tree] = [tree]
    while pending:
        storage = pending.pop()
        for name, content in storage.items():
            if isinstance(content, dict):
                pending.append(content)
            else:
                found.append((storage, name))
    return found


@pytest.mark.parametrize("case", ["plain text and a PDF", "a forwarded message"])
def test_random_damage_never_escapes_as_another_error(case: str) -> None:
    message = CASES[case][0]()[1]
    tree = msg_tree(message)
    good = msg_bytes(message)
    rng = random.Random(20251028)
    started = time.perf_counter()
    read = refused = 0
    for data in _mutations(good, tree, rng, 300):
        try:
            package = read_msg(data)
        except EmailError as error:
            # An explicit refusal, not the catch-all (which would carry the unforeseen exception)
            assert error.__cause__ is None, repr(error.__cause__)
            assert (error.code, error.message) in {("email_load_failed", DAMAGED_EMAIL),
                                                   ("not_an_email", NOT_AN_OUTLOOK_MESSAGE)}
            refused += 1
        else:
            email_text(package).encode("utf-8")  # no lone surrogate reaches the text
            email_warnings(package)
            read += 1
    assert time.perf_counter() - started < budget(1)  # about 0.1 s without coverage
    assert read > 20 and refused > 20, (read, refused)
