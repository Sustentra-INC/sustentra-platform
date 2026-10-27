"""Email reader, review round 3: the line x depth budget counts every "boundary", adjacent
encoded words, encrypted messages forwarded as attachments, parameter quoting and RFC 2231
continuations, display names with commas, every stdlib codec timed on adversarial input,
and MIME charset labels Python knows by another name."""

from __future__ import annotations

import base64
import codecs
import encodings
import encodings.aliases
import pkgutil
import random
import time
import tracemalloc
from email.message import EmailMessage
from email.parser import BytesParser

import pytest

from backend.app.adapters.parsers import email_reader
from backend.app.adapters.parsers.email_parser import email_warnings
from backend.app.adapters.parsers.email_reader import EmailError, read_eml
from backend.tests.adapters.parsers._timing import budget

HEAD = b"From: a@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
ENVELOPED = (b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n'
             b'Content-Disposition: attachment; filename="smime.p7m"\r\n'
             b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CAMIACAQAxggE=\r\n")


def _mixed(*parts: bytes, boundary: bytes = b"m") -> bytes:
    return (HEAD + b'Content-Type: multipart/mixed; boundary="' + boundary + b'"\r\n\r\n'
            + b"".join(b"--" + boundary + b"\r\n" + part for part in parts) + b"--" + boundary + b"--\r\n")


# --- item 1: the line budget counts every "boundary" -------------------------------------------
def _deep(declare: bytes, depth: int = 900, lines: int = 1_000_000) -> bytes:
    raw = b"From: a@example.com\r\nSubject: deep\r\n"
    for level in range(depth):
        raw += b"Content-Type: multipart/mixed; " + declare.replace(b"@", b"b%d" % level) + b"\r\n\r\n--b%d\r\n" % level
    return raw + b"Content-Type: text/plain\r\n\r\n" + b"x\r\n" * lines


@pytest.mark.parametrize("declare", [
    b'boundary\r\n ="@"',  # folded before "="
    b'boundary\x0c="@"',
    b'boundary\x0b="@"',
    b'boundary\x1c="@"',
    b'BOUNDARY="@"',
    b"boundary*0=@",
], ids=["folded", "form_feed", "vertical_tab", "file_separator", "upper_case", "rfc2231"])
def test_every_boundary_declaration_shortens_the_line_budget(declare: bytes) -> None:
    raw = _deep(declare)
    # The stdlib parser honours each of these spellings, so the nesting is real.
    head = BytesParser().parsebytes(raw[:raw.index(b"Content-Type: text/plain")])
    depth, part = 0, head
    while part.is_multipart() and part.get_payload():
        depth, part = depth + 1, part.get_payload()[0]
    assert depth == 900
    # Round 2 counted declarations by a regex that allowed only spaces and tabs before "=": the
    # first four spellings slipped past it and took 53.7 s on 3.12.
    started = time.perf_counter()
    package = read_eml(raw)
    assert time.perf_counter() - started < budget(3)
    assert "email_truncated" in {code for code, _ in package.notes}


def test_boundary_mentions_are_counted_in_chunks_without_a_copy(monkeypatch) -> None:
    data = b"BoUnDaRy" * 3_000_000  # 24 MB; a list of matches took 174 MB
    tracemalloc.start()
    try:
        assert email_reader._boundary_mentions(data) == 3_000_000
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    # A mention that straddles two chunks is counted once.
    monkeypatch.setattr(email_reader, "_MENTION_CHUNK", 5)
    for offset in range(12):
        assert email_reader._boundary_mentions(b"x" * offset + b"boundary" + b"y" * 7) == 1
    assert email_reader._boundary_mentions(b"boundaryBOUNDARYboundar") == 2


def test_a_wide_shallow_real_email_is_read_whole() -> None:
    # 13 boundaries and an 18 MB PDF (316,000 base64 lines): round 2 cut the PDF to 17.53 MB.
    pdf = b"%PDF-1.7\n" + bytes(18_000_000 - 9)
    alternative = (b'Content-Type: multipart/alternative; boundary="alt"\r\n\r\n--alt\r\n'
                   b"Content-Type: text/plain\r\n\r\nInvoice attached.\r\n--alt\r\n"
                   b"Content-Type: text/html\r\n\r\n<p>Invoice attached.</p>\r\n--alt--\r\n")
    small = [b'Content-Type: multipart/related; boundary="r%d"\r\n\r\n--r%d\r\n'
             b'Content-Type: image/png\r\nContent-Disposition: attachment; filename="logo%d.png"\r\n\r\npng\r\n'
             b"--r%d--\r\n" % (n, n, n, n) for n in range(11)]
    raw = _mixed(alternative, *small, b'Content-Type: application/pdf\r\nContent-Disposition: attachment; '
                 b'filename="bill.pdf"\r\nContent-Transfer-Encoding: base64\r\n\r\n' + base64.encodebytes(pdf))
    assert email_reader._boundary_mentions(raw) == 13
    package = read_eml(raw)
    assert package.notes == []
    assert package.body_text == "Invoice attached."
    assert [part.data for part in package.attachments if part.name == "bill.pdf"] == [pdf]


# --- item 2: adjacent encoded words ------------------------------------------------------------
def _subject(value: bytes) -> str:
    return read_eml(b"From: a@example.com\r\nSubject: " + value + b"\r\n\r\nx\r\n").subject


@pytest.mark.parametrize(("value", "expected"), [
    (b"=?utf-8?q?caf?= =?utf-8?q?=C3=A9?=", "caf\u00e9"),
    (b"=?utf-8?q?caf?=\r\n\t=?utf-8?q?=C3=A9?=", "caf\u00e9"),  # folded between the words
    (b"=?utf-8?q?caf?==?utf-8?q?=C3=A9?=", "caf\u00e9"),  # no space at all
    (b"=?utf-8?b?ZsM=?= =?utf-8?b?qXZyaWVy?=", "f\u00e9vrier"),  # a character split across two words
    (b"=?iso-8859-1?q?caf=E9?= =?utf-8?q?_cr=C3=A8me?=", "caf\u00e9 cr\u00e8me"),  # two charsets
    (b"=?utf-8?q?F=C3=A9vrier?= and =?utf-8?q?mars?=", "F\u00e9vrier and mars"),  # text between: kept
    # Two encoded words: the folding between them goes (a mailer that wants a space encodes it).
    (b"Facture =?utf-8?q?f=C3=A9vrier?=\r\n =?utf-8?q?2025?= - 120 kWh", "Facture f\u00e9vrier2025 - 120 kWh"),
    (b"Facture =?utf-8?q?f=C3=A9vrier?=\r\n 2025 - 120 kWh", "Facture f\u00e9vrier 2025 - 120 kWh"),
    (b"=?iso-8859-1*fr?q?F=E9vrier?=", "F\u00e9vrier"),  # RFC 2231 language suffix
])
def test_adjacent_encoded_words_join(value: bytes, expected: str) -> None:
    assert _subject(value) == expected


@pytest.mark.parametrize("subject", [
    "Relev\u00e9 de consommation \u00e9lectrique pour la p\u00e9riode de f\u00e9vrier 2025 \u2013 site 12",
    "\u96fb\u6c17\u6599\u91d1\u306e\u304a\u77e5\u3089\u305b\uff1a2025\u5e742\u6708\u5206\u306e\u3054\u8acb\u6c42"
    "\u91d1\u984d\u3068\u4f7f\u7528\u91cf\u306e\u8a73\u7d30\u306b\u3064\u3044\u3066\uff08\u5951\u7d04\u756a\u53f7 12345\uff09",
    "\u0421\u0447\u0451\u0442 \u0437\u0430 \u043f\u043e\u0442\u0440\u0435\u0431\u043b\u0435\u043d\u0438\u0435 "
    "\u044d\u043b\u0435\u043a\u0442\u0440\u043e\u044d\u043d\u0435\u0440\u0433\u0438\u0438 \u0437\u0430 "
    "\u0444\u0435\u0432\u0440\u0430\u043b\u044c 2025 \u0433\u043e\u0434\u0430 \u043f\u043e "
    "\u043e\u0431\u044a\u0435\u043a\u0442\u0443 \u043d\u043e\u043c\u0435\u0440 12",
], ids=["la_periode", "oshirase", "potreblenie"])
def test_a_long_subject_written_by_python_reads_back_whole(subject: str) -> None:
    message = EmailMessage()
    message["From"] = "a@example.com"
    message["Subject"] = subject
    message.set_content("x")
    raw = message.as_bytes()
    header = raw[:raw.index(b"\n\n") if b"\n\n" in raw else len(raw)]
    assert header.count(b"=?utf-8?") > 1  # folded into several adjacent encoded words
    assert read_eml(raw).subject == subject


def test_an_encoded_word_beside_text_keeps_its_spaces() -> None:
    raw = (b"From: =?utf-8?q?Soci=C3=A9t=C3=A9_G=C3=A9n=C3=A9rale_d'=C3=89nergie?=\r\n <factures@sge.example>\r\n"
           b"Subject: Facture =?utf-8?q?f=C3=A9vrier?=\r\n 2025\r\n\r\nx\r\n")
    package = read_eml(raw)
    assert package.subject == "Facture f\u00e9vrier 2025"
    assert package.sender == "Soci\u00e9t\u00e9 G\u00e9n\u00e9rale d'\u00c9nergie <factures@sge.example>"
    assert _subject(b"Path C:\\users\\unpaid =?utf-8?q?F=C3=A9vrier?=") == "Path C:\\users\\unpaid F\u00e9vrier"


# --- item 3: an encrypted message forwarded as an attachment -----------------------------------
INNER = b"From: supplier@example.com\r\nSubject: Invoice 42\r\nMIME-Version: 1.0\r\n" + ENVELOPED


def test_an_encrypted_message_forwarded_as_an_attachment_is_listed() -> None:
    # Outlook's "forward as attachment": the covering email is read, the forwarded one listed.
    alternative = (b'Content-Type: multipart/alternative; boundary="alt"\r\n\r\n--alt\r\n'
                   b"Content-Type: text/plain\r\n\r\nPlease see the attached invoice.\r\n--alt\r\n"
                   b"Content-Type: text/html\r\n\r\n<p>Please see the attached invoice.</p>\r\n--alt--\r\n")
    package = read_eml(_mixed(alternative, b"Content-Type: message/rfc822\r\n"
                              b'Content-Disposition: attachment; filename="Invoice 42.eml"\r\n\r\n' + INNER))
    assert package.body_text == "Please see the attached invoice."
    [part] = package.attachments
    assert (part.name, part.content_type, part.note) == (
        "Invoice 42.eml", "message/rfc822", "the forwarded message is encrypted")
    assert part.size > len(ENVELOPED)
    assert package.nested == []
    [warning] = email_warnings(package)
    assert warning["code"] == "attachments_not_read"
    assert "the forwarded message is encrypted" in warning["message"]


def test_a_forwarded_encrypted_message_without_a_file_name_is_named_by_its_subject() -> None:
    package = read_eml(_mixed(b"Content-Type: text/plain\r\n\r\nFYI\r\n", b"Content-Type: message/rfc822\r\n\r\n" + INNER))
    assert package.body_text == "FYI"
    assert [(part.name, part.note) for part in package.attachments] == [
        ("Invoice 42.eml", "the forwarded message is encrypted")]


def test_a_forwarded_message_wrapping_an_encrypted_one_is_listed() -> None:
    wrapper = b"From: b@example.com\r\nSubject: Fwd\r\nContent-Type: message/rfc822\r\n\r\n" + INNER
    package = read_eml(_mixed(b"Content-Type: text/plain\r\n\r\nFYI\r\n", b"Content-Type: message/rfc822\r\n\r\n" + wrapper))
    assert [(part.name, part.note) for part in package.attachments] == [
        ("Fwd.eml", "the forwarded message is encrypted")]


@pytest.mark.parametrize("raw", [
    HEAD + b"Content-Type: message/rfc822\r\n\r\n" + INNER,  # the email is a wrapper
    HEAD + b"Content-Type: message/rfc822\r\n\r\nFrom: b@example.com\r\nContent-Type: message/rfc822\r\n\r\n" + INNER,
    _mixed(b"Content-Type: message/rfc822\r\n\r\n" + INNER),  # the only part of the top multipart
    _mixed(b"Content-Type: message/rfc822\r\nContent-Disposition: attachment\r\n\r\n" + INNER),
    HEAD + b'Content-Type: multipart/signed; protocol="application/pkcs7-signature"; boundary="s"\r\n\r\n'
    b"--s\r\nContent-Type: message/rfc822\r\n\r\n" + INNER
    + b'--s\r\nContent-Type: application/pkcs7-signature; name="smime.p7s"\r\n\r\nMIAG\r\n--s--\r\n',
], ids=["top_level_wrapper", "wrapper_of_a_wrapper", "only_part", "only_part_as_attachment", "signed_wrapper"])
def test_an_encrypted_message_that_is_the_whole_email_halts(raw: bytes) -> None:
    with pytest.raises(EmailError) as refused:
        read_eml(raw)
    assert (refused.value.code, refused.value.message) == ("password_protected", email_reader.ENCRYPTED_EMAIL)


def test_a_readable_forwarded_message_is_still_read() -> None:
    inner = b"From: supplier@example.com\r\nSubject: Invoice 42\r\n\r\nTotal 120 kWh\r\n"
    package = read_eml(_mixed(b"Content-Type: text/plain\r\n\r\nFYI\r\n", b"Content-Type: message/rfc822\r\n"
                              b'Content-Disposition: attachment; filename="Invoice 42.eml"\r\n\r\n' + inner))
    [nested] = package.nested
    assert (nested.subject, nested.body_text) == ("Invoice 42", "Total 120 kWh")


# --- item 4: parameters ------------------------------------------------------------------------
def _attachment_name(disposition: bytes) -> str:
    raw = _mixed(b"Content-Type: text/plain\r\n\r\nhi\r\n",
                 b"Content-Type: application/pdf\r\nContent-Disposition: attachment; " + disposition + b"\r\n\r\n%PDF\r\n")
    return read_eml(raw).attachments[0].name


@pytest.mark.parametrize(("disposition", "expected"), [
    (b'filename="a\\"b.pdf"', 'a"b.pdf'),  # a quoted pair is unescaped
    (b'filename="x\\";y.pdf"; size=3', 'x";y.pdf'),  # an escaped quote does not end the value
    (b'filename="a;b.pdf"', "a;b.pdf"),
    (b'filename="a.pdf; size=3', "a.pdf; size=3"),  # an unclosed quote runs to the end
    (b"filename*0*=utf-8''f%C3; filename*1*=%A9vrier.pdf", "f\u00e9vrier.pdf"),  # split character
    (b"filename*0*=utf-8''Fact; filename*1=ure-; filename*2*=f%C3%A9vrier.pdf", "Facture-f\u00e9vrier.pdf"),
    (b"filename=\"fallback.pdf\"; filename*=utf-8''r%C3%A9el.pdf", "r\u00e9el.pdf"),  # filename* wins
    (b"filename*=utf-8''r%C3%A9el.pdf; filename=\"fallback.pdf\"", "r\u00e9el.pdf"),
    (b'filename="first.pdf"; filename="second.pdf"', "first.pdf"),
])
def test_parameters_are_unquoted_and_continuations_joined(disposition: bytes, expected: str) -> None:
    assert _attachment_name(disposition) == expected


# --- item 5: display names ---------------------------------------------------------------------
@pytest.mark.parametrize(("value", "expected"), [
    (b'"Doe, Jane" <jane@example.com>, bob@example.com', '"Doe, Jane" <jane@example.com>, bob@example.com'),
    (b'"Doe; Jane" <jane@example.com>', '"Doe; Jane" <jane@example.com>'),
    (b'"John \\"JJ\\" Doe" <j@example.com>', 'John "JJ" Doe <j@example.com>'),
    (b'"Acme Gas" <billing@acme.example>', "Acme Gas <billing@acme.example>"),
    (b'"=?utf-8?q?Jos=C3=A9?=" <jose@example.com>', "Jos\u00e9 <jose@example.com>"),
    (b"=?utf-8?q?Doe=2C_Jane?= <jane@example.com>", '"Doe, Jane" <jane@example.com>'),
    (b"undisclosed-recipients:;", "undisclosed-recipients:;"),
])
def test_display_names_keep_their_quotes_only_around_a_comma(value: bytes, expected: str) -> None:
    assert read_eml(b"From: a@example.com\r\nTo: " + value + b"\r\nSubject: s\r\n\r\nx\r\n").to == expected


# --- item 6: every stdlib codec, adversarial input ---------------------------------------------
_SIZE = 512 * 1024
_rng = random.Random(7)
ADVERSARIAL = {
    "random": bytes(_rng.randrange(256) for _ in range(_SIZE // 16)) * 16,
    "esc$B": b"\x1b$B" * (_SIZE // 3), "esc(B": b"\x1b(B" * (_SIZE // 3),
    "esc$)C_SO_SI": b"\x1b$)C\x0e\x0f" * (_SIZE // 6), "hz~{": b"~{" * (_SIZE // 2), "utf7+": b"+" * _SIZE,
    "utf7+AAAA-": b"+AAAA-" * (_SIZE // 6), "utf7+2D": b"+2D" * (_SIZE // 3), "fffe": b"\xff\xfe" * (_SIZE // 2),
    "d800": b"\xd8\x00" * (_SIZE // 2), "hibytes": bytes(range(128, 256)) * (_SIZE // 128),
    "lead_only": b"\x81" * _SIZE, "nul": b"\x00" * _SIZE,
    # Valid punycode, superlinear to decode (256 KB: 0.95 s, 512 KB: 2.5 s, 1 MB: > 10 s). With
    # an empty denylist this payload fails the timing test below on its own.
    "punycode": ("\u00e9" * _SIZE).encode("punycode"),
}
DENIED = {"punycode", "idna", "unicode_escape", "raw_unicode_escape"}


def test_the_quadratic_and_escape_codecs_are_refused_by_every_name() -> None:
    assert {codecs.lookup(name).name for name in DENIED} <= email_reader._DENY_CODECS
    labels = {name for name in DENIED}
    labels |= {alias for alias, target in encodings.aliases.aliases.items() if target in DENIED}
    labels |= {module.name for module in pkgutil.iter_modules(encodings.__path__) if module.name in DENIED}
    for label in sorted(labels):
        for spelling in (label, label.upper(), f"x-{label}", f' "{label}" ', label.replace("_", "-")):
            assert email_reader._codec(spelling) == "utf-8", spelling


def test_every_stdlib_codec_decodes_adversarial_input_in_linear_time() -> None:
    modules = sorted(module.name for module in pkgutil.iter_modules(encodings.__path__))
    timed = 0
    for module in modules:
        try:
            canonical = codecs.lookup(module).name
        except LookupError:  # not a codec ("aliases"), or not on this platform ("mbcs")
            assert email_reader._codec(module) == "utf-8"
            continue
        if canonical in email_reader._DENY_CODECS:
            assert email_reader._codec(module) == "utf-8", module
            continue
        assert email_reader._codec(module) == canonical, module  # the reader would use it
        for pattern, payload in ADVERSARIAL.items():
            started = time.perf_counter()
            email_reader._decode_bytes(payload, module)
            elapsed = time.perf_counter() - started
            assert elapsed < budget(1), f"{module} on {pattern}: {elapsed:.2f}s"
        timed += 1
    assert timed > 100  # every text codec stdlib ships (121 modules on 3.12)


# --- item 7: labels Python knows by another name -----------------------------------------------
@pytest.mark.parametrize(("label", "codec", "text"), [
    (b"windows-874", "cp874", "\u0e04\u0e48\u0e32\u0e44\u0e1f\u0e1f\u0e49\u0e32 120 \u0e1a\u0e32\u0e17 \u20ac"),
    (b"x-windows-874", "cp874", "\u0e04\u0e48\u0e32\u0e44\u0e1f\u0e1f\u0e49\u0e32"),
    (b"Windows_874", "cp874", "\u0e04\u0e48\u0e32\u0e44\u0e1f\u0e1f\u0e49\u0e32"),
    (b"iso-8859-8-i", "iso8859-8", "\u05d7\u05e9\u05d1\u05d5\u05df 120"),
    (b"windows-31j", "cp932", "\u8acb\u6c42\u66f8 120"),
])
def test_mime_labels_python_names_otherwise_are_decoded(label: bytes, codec: str, text: str) -> None:
    raw = HEAD + b"Content-Type: text/plain; charset=" + label + b"\r\n\r\n" + text.encode(codec)
    assert read_eml(raw).body_text == text
