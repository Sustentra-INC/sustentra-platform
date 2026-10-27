"""Reading an email (.eml) into plain data: headers, message text, forwarded messages and
attachments. Every message is built here with the standard library."""

from __future__ import annotations

import base64
import time
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


def test_a_message_that_cannot_be_read_is_refused_with_what_to_do(monkeypatch) -> None:
    def broken(message, **kwargs):
        raise ValueError("no")

    monkeypatch.setattr(email_reader, "_package", broken)
    with pytest.raises(EmailError) as refused:
        read_eml(_message().as_bytes())
    assert refused.value.code == "email_load_failed"
    assert refused.value.message == email_reader.DAMAGED_EMAIL


def test_an_html_body_is_found_next_to_attachments() -> None:
    # The body search reads headers as text: an HTML body before an attachment is still found.
    message = _message(body=None)
    message.set_content("<p>Total Usage: 120 therms</p>", subtype="html")
    message.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="bill.pdf")
    package = read_eml(message.as_bytes())
    assert (package.body_text, package.body_source) == ("Total Usage: 120 therms", "html")
    assert [part.name for part in package.attachments] == ["bill.pdf"]


def test_a_related_body_follows_its_start_part() -> None:
    raw = (b'From: a@example.com\r\nSubject: s\r\nContent-Type: multipart/related; boundary="r"; start="<two>"'
           b'\r\n\r\n--r\r\nContent-Type: text/plain\r\nContent-ID: <one>\r\n\r\nnot this\r\n'
           b"--r\r\nContent-Type: text/html\r\nContent-ID: <two>\r\n\r\n<p>this one</p>\r\n--r--\r\n")
    assert read_eml(raw).body_text.startswith("this one")


# --- crafted files: each must finish fast (the times before the fix are in the comments) ----------
HEAD = b"From: a@example.com\r\nTo: b@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"


def _many_parts(count: int) -> bytes:
    body = b"".join(b"--b\r\nContent-Type: text/plain\r\n\r\nx\r\n" for _ in range(count))
    return HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + body + b"--b--\r\n"


def _timed(data: bytes, seconds: float = 1.0):
    started = time.perf_counter()
    try:
        return read_eml(data)
    finally:
        elapsed = time.perf_counter() - started
        assert elapsed < seconds, f"took {elapsed:.2f} s"


def test_a_huge_number_of_parts_is_cut_before_parsing() -> None:
    # 100,000 parts (3.6 MB) took 8 s: every part was built before the walk's limit applied.
    package = _timed(_many_parts(100_000))
    assert {code for code, _ in package.notes} == {"email_parts_limit", "email_truncated"}


def test_lines_are_capped_before_parsing(monkeypatch) -> None:
    # 6 million short lines (12 MB) took 3 s and 860 MB.
    package = _timed(HEAD + b"Content-Type: text/plain\r\n\r\n" + b"a\n" * 6_000_000, 2.0)
    assert {code for code, _ in package.notes} == {"email_truncated", "body_truncated"}
    assert package.body_text.count("\n") + 1 == email_reader.MAX_TEXT_LINES


def test_the_cut_falls_after_a_whole_line_whatever_its_ending() -> None:
    data = b"a\r\nb\rc\nd"
    assert [email_reader._after_lines(data, n) for n in (0, 1, 2, 3, 10)] == [0, 3, 5, 7, len(data)]


def test_an_attached_email_is_not_parsed_deeper_than_the_depth_limit(monkeypatch) -> None:
    # Four attached .eml files inside one another, the innermost with many parts: it was
    # parsed (8.5 s for 100,000 parts) before the depth check threw it away.
    def attaching(inner: bytes, level: int) -> bytes:
        return (HEAD + b'Content-Type: multipart/mixed; boundary="o"\r\n\r\n--o\r\nContent-Type: text/plain\r\n'
                + b"\r\nlevel %d\r\n--o\r\nContent-Type: application/octet-stream\r\n" % level
                + b'Content-Disposition: attachment; filename="l.eml"\r\nContent-Transfer-Encoding: base64\r\n\r\n'
                + base64.encodebytes(inner) + b"--o--\r\n")

    deep = _many_parts(20_000)
    for level in (4, 3, 2, 1):
        deep = attaching(deep, level)
    parsed: list[int] = []
    real_parse = email_reader._parse
    monkeypatch.setattr(email_reader, "_parse", lambda data, walk: parsed.append(len(data)) or real_parse(data, walk))
    package = _timed(deep, 3.0)
    assert len(parsed) == 4  # the email and three attached levels; the fourth is never parsed
    assert ("forwarded_too_deep", 'A message forwarded more than 3 levels deep ("l.eml") was not read.') in (
        package.all_notes())


def test_attached_emails_share_one_parse_budget() -> None:
    inner = base64.encodebytes(_many_parts(2_000))
    attached = b"".join(
        b'--b\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="f%d.eml"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\n" % n + inner for n in range(150))
    raw = HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + attached + b"--b--\r\n"
    package = _timed(raw, 2.0)
    assert "email_truncated" in {code for code, _ in package.all_notes()}


@pytest.mark.parametrize("raw", [
    # Quotes and semicolons in headers made the modern policy's parsers quadratic.
    HEAD + b"Content-Type: text/plain; a=" + b'"' * 32 * 1024 + b"\r\n\r\nTotal Usage: 120 therms\r\n",  # 25 s
    HEAD + b"Content-Type: text/plain\r\nContent-Disposition: inline; filename=" + b'"' * 32 * 1024
    + b"\r\n\r\nTotal Usage: 120 therms\r\n",  # 2.8 s
    b"From: a@example.com\r\nTo: " + b'"' * 32 * 1024 + b"\r\nSubject: s\r\n\r\nTotal Usage: 120 therms\r\n",  # 9.8 s
    b"From: a@example.com\r\nTo: " + b'"' * 21 * 1024 + b"\r\nCc: " + b'"' * 21 * 1024 + b"\r\nSubject: "
    + b'"' * 21 * 1024 + b"\r\n\r\nTotal Usage: 120 therms\r\n",  # 8.5 s
    HEAD + b'Content-Type: multipart/mixed; a="' + b";" * 1024 * 1024 + b'"; boundary="b"\r\n\r\n'
    + b"--b\r\nContent-Type: text/plain\r\n\r\nTotal Usage: 120 therms\r\n--b--\r\n",  # never finished
], ids=["content_type_quotes", "content_disposition_quotes", "to_quotes", "to_cc_subject_quotes",
        "multipart_semicolons"])
def test_crafted_headers_are_read_fast(raw: bytes) -> None:
    package = _timed(raw)
    if b";;;" in raw:
        # Cut to its first parameters, the header no longer names its boundary: the parts are
        # not found, but nothing hangs.
        assert package.body_text == ""
    else:
        assert "Total Usage: 120 therms" in package.body_text


def test_html_turned_into_text_has_one_budget_for_the_whole_email(monkeypatch) -> None:
    # html.parser takes about 1 s per million characters of "<<<<", and each HTML part may be
    # up to MAX_BODY_CHARS: the email's HTML is converted up to MAX_HTML_CHARS in all.
    monkeypatch.setattr(email_reader, "MAX_HTML_CHARS", 100_000)
    parts = b"".join(b"--b\r\nContent-Type: text/html\r\n\r\n<body>" + b"<" * 200_000 + b"\r\n" for _ in range(20))
    package = _timed(HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n' + parts + b"--b--\r\n")
    assert "body_truncated" in {code for code, _ in package.notes}


def test_too_many_headers_are_refused() -> None:
    with pytest.raises(EmailError) as refused:
        _timed(b"".join(b"X-%d: y\r\n" % n for n in range(email_reader.MAX_HEADERS + 1)) + b"\r\nbody\r\n")
    assert refused.value.code == "email_load_failed"


def test_only_ordinary_text_charsets_decode() -> None:
    # Python's punycode codec is quadratic: a 1 MB body took 10 s, a 0.55 MB file name 3 s.
    body = ("\u00e9" * 300_000).encode("punycode")
    package = _timed(HEAD + b"Content-Type: text/plain; charset=punycode\r\n\r\n" + body + b"\r\n")
    assert package.body_text.startswith(body[:20].decode())  # read as UTF-8: the raw digits
    name = ("\u00e9" * 100_000).encode("punycode")
    package = _timed(HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n--b\r\nContent-Type: text/plain'
                     b"\r\n\r\nhi\r\n--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; "
                     b"filename*=punycode''" + name + b"\r\n\r\n%PDF\r\n--b--\r\n")
    assert package.attachments[0].name == name[:email_reader.MAX_NAME_CHARS].decode()
    package = read_eml(b"From: a@example.com\r\nSubject: =?punycode?q?caf-dma?= =?x-unknown?q?=C3=A9?=\r\n\r\nx\r\n")
    assert package.subject == "caf-dma\u00e9"


@pytest.mark.parametrize("raw", [
    HEAD + b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n'
    b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CAMIACAQAxggE=\r\n",
    HEAD + b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n--b\r\nContent-Type: application/octet-stream\r\n'
    b'Content-Disposition: attachment; filename="smime.p7m"\r\n\r\nMIAGCSqG\r\n--b--\r\n',
    HEAD + b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="b"\r\n\r\n'
    b"--b\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n--b\r\n"
    b'Content-Type: application/octet-stream; name="encrypted.asc"\r\n\r\n-----BEGIN PGP MESSAGE-----\r\n'
    b"hQEMA\r\n-----END PGP MESSAGE-----\r\n--b--\r\n",
], ids=["smime_enveloped", "smime_p7m_as_the_body", "pgp_mime"])
def test_an_encrypted_email_is_refused_as_password_protected(raw: bytes) -> None:
    with pytest.raises(EmailError) as refused:
        read_eml(raw)
    assert (refused.value.code, refused.value.message) == (
        "password_protected",
        "This email is encrypted. Ask the client to send it without encryption, or upload its attachments "
        "on their own.")


def test_a_signed_email_or_an_encrypted_attachment_is_still_read() -> None:
    signed = (HEAD + b'Content-Type: multipart/signed; protocol="application/pkcs7-signature"; boundary="s"\r\n\r\n'
              b"--s\r\nContent-Type: text/plain\r\n\r\nTotal Usage: 120 therms\r\n--s\r\n"
              b'Content-Type: application/pkcs7-signature; name="smime.p7s"\r\n\r\nMIAG\r\n--s--\r\n')
    assert read_eml(signed).body_text == "Total Usage: 120 therms"
    message = _message()
    message.add_attachment(b"MIAG", maintype="application", subtype="pkcs7-mime", filename="smime.p7m")
    assert [part.name for part in read_eml(message.as_bytes()).attachments] == ["smime.p7m"]


def test_the_message_text_of_the_whole_email_shares_one_budget(monkeypatch) -> None:
    monkeypatch.setattr(email_reader, "MAX_TEXT_LINES", 5)
    inner = _message(subject="inner", body="\n".join(f"inner {n}" for n in range(10)))
    outer = _message(subject="outer", body="\n".join(f"outer {n}" for n in range(3)))
    outer.add_attachment(inner)
    package = read_eml(outer.as_bytes())
    assert package.body_text == "outer 0\nouter 1\nouter 2"
    assert package.nested[0].body_text == "inner 0\ninner 1"
    assert [code for code, _ in package.all_notes()] == ["body_truncated"]


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
