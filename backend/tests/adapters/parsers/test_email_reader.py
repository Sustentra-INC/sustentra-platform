"""Reading an email (.eml) into plain data: headers, message text, forwarded messages and
attachments. Every message is built here with the standard library."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from backend.app.adapters.parsers import email_reader
from backend.app.adapters.parsers.email_reader import EmailError, html_to_text, read_eml


def _message(subject: str = "Your February bill", body: str | None = "Total Usage: 120 therms", **headers: str
             ) -> EmailMessage:
    message = EmailMessage()
    message["From"] = headers.get("sender", "Acme Gas <billing@acme.example>")
    message["To"] = headers.get("to", "ap@client.example")
    message["Date"] = headers.get("date", "Mon, 10 Feb 2025 09:15:00 -0500")
    message["Subject"] = subject
    message["Message-ID"] = "<feb-bill@acme.example>"
    if body is not None:
        message.set_content(body)
    return message


def test_a_plain_message_gives_its_headers_and_text() -> None:
    package = read_eml(_message().as_bytes())
    assert (package.sender, package.to, package.sent_at, package.subject) == (
        "Acme Gas <billing@acme.example>", "ap@client.example", "Mon, 10 Feb 2025 09:15:00 -0500", "Your February bill")
    assert package.message_id == "<feb-bill@acme.example>"
    assert (package.body_text, package.body_source) == ("Total Usage: 120 therms", "plain")
    assert package.attachments == [] and package.nested == [] and package.notes == []


def test_the_plain_text_is_preferred_and_the_html_alternative_is_not_read_twice() -> None:
    message = _message(body="Total Usage: 120 therms")
    message.add_alternative("<p>Total Usage: <b>120</b> therms</p>", subtype="html")
    package = read_eml(message.as_bytes())
    assert (package.body_text, package.body_source) == ("Total Usage: 120 therms", "plain")


def test_an_html_only_message_becomes_text_with_tab_separated_table_cells() -> None:
    message = _message(body=None)
    message.set_content(
        "<html><head><title>Bill</title><style>td { color: red }</style></head><body>"
        "<h1>Acme&nbsp;Gas</h1><p>Account   1234<br>Service period: 01/01/2025 - 01/31/2025</p>"
        "<table><tr><th>Item</th><th>Amount</th></tr><tr><td>Total Usage</td><td>1,234 therms</td></tr>"
        "<tr><td>Amount due</td><td>&#36;98.10</td></tr></table>"
        "<script>document.write('hidden')</script><img src='https://tracker.example/pixel.png'></body></html>",
        subtype="html",
    )
    package = read_eml(message.as_bytes())
    assert package.body_source == "html"
    assert package.body_text.split("\n") == [
        "Acme Gas", "Account 1234", "Service period: 01/01/2025 - 01/31/2025",
        "Item\tAmount", "Total Usage\t1,234 therms", "Amount due\t$98.10",
    ]


def test_html_to_text_drops_what_is_not_visible_and_survives_broken_markup() -> None:
    assert html_to_text("<head><title>x").strip() == ""
    assert html_to_text("<title>Subject<body><p>Hello</p>").strip() == "Hello"  # an unclosed title ends at <body>
    assert html_to_text("<div>a<div>b</div></div><pre>1  2</pre>").split() == ["a", "b", "1", "2"]
    assert html_to_text("<p>x</p><<<>>&bogus;").strip().startswith("x")


def test_encoded_headers_are_decoded_and_kept_on_one_line() -> None:
    raw = (b"From: =?utf-8?q?Caf=C3=A9_Gas?= <billing@cafe.example>\r\n"
           b"Subject: =?iso-8859-1?q?F=E9vrier?= bill\r\n\tcontinued\r\n"
           b"Content-Type: text/plain; charset=utf-8\r\n\r\nHello\r\n")
    package = read_eml(raw)
    assert package.sender == "Café Gas <billing@cafe.example>"
    assert package.subject == "Février bill continued"


def test_a_header_too_long_to_be_real_is_shown_cut_not_parsed() -> None:
    recipients = ", ".join(f"person{n}@client.example" for n in range(4000))  # about 100 KB
    raw = f"From: a@example.com\r\nTo: {recipients}\r\nSubject: s\r\n\r\nHello\r\n".encode()
    package = read_eml(raw)
    assert len(package.to) == email_reader.SHOWN_HEADER_CHARS + 1 and package.to.endswith("…")
    assert package.to.startswith("person0@client.example, person1@client.example")


def test_an_unknown_charset_is_read_as_utf8() -> None:
    raw = (b"From: a@example.com\r\nSubject: s\r\nContent-Type: text/plain; charset=x-unknown-8\r\n"
           b"Content-Transfer-Encoding: 8bit\r\n\r\nCaf\xc3\xa9 \xff total\r\n")
    assert read_eml(raw).body_text == "Café \ufffd total"


def test_attachments_are_kept_with_their_bytes_names_and_where_they_sit() -> None:
    message = _message()
    message.add_attachment(b"%PDF-1.4 bill", maintype="application", subtype="pdf", filename="bill.pdf")
    message.add_attachment(b"Month,Usage\nJan,120\n", maintype="text", subtype="csv", filename="usage.csv")
    message.add_attachment(b"\x89PNG logo", maintype="image", subtype="png", filename="logo.png",
                           disposition="inline", cid="<logo@acme>")
    message.add_attachment(b"sig", maintype="application", subtype="pkcs7-signature", filename="smime.p7s")
    message.add_attachment(b"tnef", maintype="application", subtype="ms-tnef", filename="winmail.dat")
    package = read_eml(message.as_bytes())

    assert package.body_text == "Total Usage: 120 therms"
    assert [(p.name, p.content_type, p.data, p.inline) for p in package.attachments] == [
        ("bill.pdf", "application/pdf", b"%PDF-1.4 bill", False),
        ("usage.csv", "text/csv", b"Month,Usage\nJan,120\n", False),
        ("logo.png", "image/png", b"\x89PNG logo", True),
        ("winmail.dat", "application/ms-tnef", b"tnef", False),  # the S/MIME signature is skipped
    ]
    assert package.attachments[2].content_id == "logo@acme"
    assert package.attachments[3].note and "winmail.dat" in package.attachments[3].note


def test_attachment_names_are_plain_short_file_names() -> None:
    message = _message()
    for name in ("../../etc/evil.pdf", "C:\\Users\\me\\bill.pdf", "x" * 300 + ".xlsx", "bad\x00name.csv"):
        message.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=name)
    message.add_attachment(b"x", maintype="application", subtype="pdf")  # no name at all
    names = [part.name for part in read_eml(message.as_bytes()).attachments]
    assert names[:2] == ["evil.pdf", "bill.pdf"]
    assert len(names[2]) == email_reader.MAX_NAME_CHARS and names[2].endswith(".xlsx")
    assert names[3] == "badname.csv"
    assert names[4] == "attachment-5.pdf"


def test_a_forwarded_message_is_read_as_a_nested_message() -> None:
    inner = _message(subject="March invoice", body="Total Usage: 98 therms", sender="Acme <b@acme.example>")
    inner.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="march.pdf")
    outer = _message(subject="Fwd: March invoice", body="See below.", sender="Pat <pat@client.example>")
    outer.add_attachment(inner)
    package = read_eml(outer.as_bytes())

    assert package.body_text == "See below." and package.attachments == []
    [nested] = package.nested
    assert (nested.subject, nested.sender, nested.body_text) == ("March invoice", "Acme <b@acme.example>",
                                                                 "Total Usage: 98 therms")
    assert [(p.name, p.path) for p in package.all_attachments()] == [("march.pdf", ["March invoice"])]


def test_an_eml_attached_as_a_file_is_read_as_a_forwarded_message() -> None:
    outer = _message(subject="Fwd", body="Attached.")
    outer.add_attachment(_message(subject="Original").as_bytes(), maintype="application", subtype="octet-stream",
                         filename="original.eml")
    package = read_eml(outer.as_bytes())
    assert [nested.subject for nested in package.nested] == ["Original"] and package.attachments == []


def test_forwarding_is_read_three_levels_deep() -> None:
    message = _message(subject="level 10", body="deepest")
    for level in range(9, -1, -1):
        outer = _message(subject=f"level {level}", body=f"text {level}")
        outer.add_attachment(message)
        message = outer
    package = read_eml(message.as_bytes())

    depth, current = 0, package
    while current.nested:
        current, depth = current.nested[0], depth + 1
    assert depth == email_reader.MAX_DEPTH and current.subject == "level 3"
    assert ("forwarded_too_deep", 'A message forwarded more than 3 levels deep ("level 4") was not read.') in (
        package.all_notes())


def test_the_walk_stops_after_its_part_limit() -> None:
    message = _message()
    for index in range(300):
        message.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"f{index}.bin")
    package = read_eml(message.as_bytes())
    assert len(package.attachments) < email_reader.MAX_PARTS
    assert [code for code, _ in package.notes] == ["email_parts_limit"]


def test_text_split_around_an_inline_image_is_all_read() -> None:
    # Apple Mail sends text, an inline photo, then more text as separate parts.
    message = _message(body="Meter photo below:")
    message.add_attachment(b"\xff\xd8\xff photo", maintype="image", subtype="jpeg", filename="meter.jpg",
                           disposition="inline")
    tail = EmailMessage()
    tail.set_content("Reading: 4,512 kWh")
    message.attach(tail)
    package = read_eml(message.as_bytes())
    assert package.body_text == "Meter photo below:\n\nReading: 4,512 kWh"
    assert [(p.name, p.inline) for p in package.attachments] == [("meter.jpg", True)]


def test_a_long_body_is_cut(monkeypatch) -> None:
    monkeypatch.setattr(email_reader, "MAX_BODY_CHARS", 10)
    package = read_eml(_message(body="0123456789abcdef").as_bytes())
    assert package.body_text == "0123456789"
    assert [code for code, _ in package.notes] == ["body_truncated"]


def test_a_message_with_only_attachments_has_no_text() -> None:
    message = _message(body=None)
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="bill.pdf")
    package = read_eml(message.as_bytes())
    assert (package.body_text, package.body_source) == ("", "none")
    assert [p.name for p in package.attachments] == ["bill.pdf"]


@pytest.mark.parametrize(("body", "code"), [
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(600), "not_an_eml"),  # an Outlook .msg
    (b"%PDF-1.4\n1 0 obj<<>>endobj\n", "not_an_email"),
    (b"", "not_an_email"),
])
def test_bytes_that_are_not_an_email_are_refused(body: bytes, code: str) -> None:
    with pytest.raises(EmailError) as refused:
        read_eml(body)
    assert refused.value.code == code


def test_a_message_the_modern_policy_trips_over_is_read_leniently(monkeypatch) -> None:
    calls: list[str] = []
    original = email_reader._package

    def flaky(message, **kwargs):
        calls.append(type(message.policy).__name__)
        if len(calls) == 1:
            raise ValueError("header parser bug")
        return original(message, **kwargs)

    monkeypatch.setattr(email_reader, "_package", flaky)
    raw = b"From: a@example.com\r\nSubject: =?utf-8?q?F=C3=A9vrier?=\r\n\r\nTotal Usage: 120 therms\r\n"
    package = read_eml(raw)
    assert calls == ["EmailPolicy", "Compat32"]
    assert (package.subject, package.body_text) == ("Février", "Total Usage: 120 therms")


def test_a_message_neither_policy_reads_is_refused(monkeypatch) -> None:
    def broken(message, **kwargs):
        raise ValueError("no")

    monkeypatch.setattr(email_reader, "_package", broken)
    with pytest.raises(EmailError) as refused:
        read_eml(_message().as_bytes())
    assert refused.value.code == "email_load_failed"


def test_deep_mime_nesting_is_refused_not_crashed() -> None:
    depth = 2000
    raw = b"From: a@example.com\r\nSubject: deep\r\n"
    for level in range(depth):
        raw += f'Content-Type: multipart/mixed; boundary="b{level}"\r\n\r\n--b{level}\r\n'.encode()
    raw += b"Content-Type: text/plain\r\n\r\nx\r\n"
    try:
        package = read_eml(raw)
    except EmailError as refused:
        assert refused.code == "email_load_failed"
    else:
        assert package.subject == "deep"
