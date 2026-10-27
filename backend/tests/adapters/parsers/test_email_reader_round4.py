"""Email reader, review round 4: an encrypted forwarded message is listed with its size taken
from the bytes the parser read, never by writing it back with the stdlib generator (which
re-folds every header: seconds on a crafted one); and a display name that keeps its quotes
has the quotes inside it escaped again."""

from __future__ import annotations

import base64
import email.generator
import email.message
import time
from collections.abc import Callable
from email.utils import getaddresses
from pathlib import Path
from typing import NoReturn

import pytest

from backend.app.adapters.parsers.email_parser import email_text, email_warnings
from backend.app.adapters.parsers.email_reader import EmailError, read_eml
from backend.app.services.document_content_service import document_content

HEAD = b"From: a@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"
ENVELOPED = (b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n'
             b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CAMIACAQAxggE=\r\n")
PGP = (b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="e"\r\n\r\n'
       b"--e\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n--e\r\n"
       b"Content-Type: application/octet-stream\r\n\r\n-----BEGIN PGP MESSAGE-----\r\n--e--\r\n")
COVER = b"Content-Type: text/plain\r\n\r\nPlease see the forwarded invoice.\r\n"


def _mixed(*parts: bytes, newline: bytes = b"\r\n") -> bytes:
    raw = (HEAD + b'Content-Type: multipart/mixed; boundary="m"\r\n\r\n'
           + b"".join(b"--m\r\n" + part for part in parts) + b"--m--\r\n")
    return raw.replace(b"\r\n", newline)


def _forward(inner: bytes) -> bytes:
    return b'Content-Type: message/rfc822\r\nContent-Disposition: attachment; filename="Invoice 42.eml"\r\n\r\n' + inner


# --- the size of an encrypted forward ----------------------------------------------------------
LF_INNER = (b"From: \xc3\xa9nergie <s@example.com>\nSubject: Invoice 42\nX-Note: a long header,\n folded\n\tonce more\n"
            b"MIME-Version: 1.0\n"
            b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="e"\n\n'
            b"This is an OpenPGP/MIME encrypted message.\n\n--e\nContent-Type: application/pgp-encrypted\n\n"
            b"Version: 1\n--e\nContent-Type: application/octet-stream\n\n-----BEGIN PGP MESSAGE-----\n"
            b"hQEMA\xff\xfe raw bytes\n-----END PGP MESSAGE-----\n--e--\nan epilogue\n")


@pytest.mark.parametrize("inner", [
    LF_INNER,
    HEAD.replace(b"\r\n", b"\n") + ENVELOPED.replace(b"\r\n", b"\n"),
    b"From: b@example.com\nSubject: Fwd\nContent-Type: message/rfc822\n\n"  # a wrapper around the encrypted one
    + HEAD.replace(b"\r\n", b"\n") + PGP.replace(b"\r\n", b"\n"),
    HEAD.replace(b"\r\n", b"\n") + b'Content-Type: multipart/mixed; boundary="z"\n\n--z\n'  # 8-bit text, quadratic charset
    b"Content-Type: text/plain; charset=punycode\n\ncaf\xc3\xa9\n--z\n" + ENVELOPED.replace(b"\r\n", b"\n") + b"--z--\n",
], ids=["pgp_preamble_epilogue_8bit_folded", "smime", "wrapper", "text_part_with_punycode_charset"])
def test_an_encrypted_forward_is_listed_with_the_bytes_it_was_sent_as(inner: bytes) -> None:
    package = read_eml(_mixed(COVER, _forward(inner), newline=b"\n"))
    assert package.body_text == "Please see the forwarded invoice."
    [part] = package.attachments
    assert (part.name, part.note) == ("Invoice 42.eml", "the forwarded message is encrypted")
    # LF line ends: the forward exactly as sent (the line break before "--m" belongs to the delimiter).
    assert part.data == inner[:-1]


def test_a_crafted_encrypted_forward_is_measured_quickly() -> None:
    # Round 3 wrote the forward back with the stdlib generator to measure it, which re-folds
    # every header: on runs of "; " that is about 0.6 us a character (an 18 MB forward took
    # 10.9 s on 3.12; this 3.4 MB one about 2 s). The size now comes from the parsed bytes.
    inner = (b"From: s@example.com\r\nSubject: Invoice 42\r\n"
             + b"".join(b"X-H%d: " % index + b"; " * 3000 + b"\r\n" for index in range(600)) + PGP)
    started = time.perf_counter()
    package = read_eml(_mixed(COVER, _forward(inner)))
    assert time.perf_counter() - started < 0.5
    [part] = package.attachments
    assert part.note == "the forwarded message is encrypted"
    # CRLF line ends: header lines are written back with LF, so the size is a little under the source.
    assert len(inner) * 0.99 < part.size <= len(inner)
    assert "Invoice 42.eml (3.4 MB, the forwarded message is encrypted)" in email_warnings(package)[0]["message"]


@pytest.fixture
def generator_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every stdlib way to write a message back -- Generator.flatten (BytesGenerator included),
    as_bytes, as_string, str(), bytes() on either message class -- recorded and refused. (The
    reader catches exceptions while reading, so the test checks the record, not a raise.)"""

    calls: list[str] = []

    def refuse(name: str) -> Callable[..., NoReturn]:
        def refused(*_args: object, **_kwargs: object) -> NoReturn:
            calls.append(name)
            raise AssertionError(f"an email was written back ({name})")
        return refused

    monkeypatch.setattr(email.generator.Generator, "flatten", refuse("Generator.flatten"))
    for cls in (email.message.Message, email.message.EmailMessage):
        for method in ("as_bytes", "as_string", "__str__", "__bytes__"):
            monkeypatch.setattr(cls, method, refuse(f"{cls.__name__}.{method}"))
    return calls


@pytest.mark.parametrize("raw", [
    _mixed(COVER, _forward(HEAD + ENVELOPED)),
    _mixed(COVER, _forward(HEAD + PGP)),
    _mixed(COVER, _forward(b"From: b@example.com\r\nSubject: Fwd\r\nContent-Type: message/rfc822\r\n\r\n" + HEAD + PGP)),
    _mixed(COVER, b'Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="locked.eml"\r\n'
                  b"Content-Transfer-Encoding: base64\r\n\r\n" + base64.encodebytes(HEAD + PGP)),
    _mixed(COVER, _forward(b"From: s@example.com\r\nSubject: Invoice 42\r\n\r\nTotal 120 kWh\r\n")),
    _mixed(b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Total <b>120</b> kWh</p>\r\n",
           b'Content-Type: application/pdf\r\nContent-Disposition: attachment; filename="bill.pdf"\r\n\r\n%PDF-1.4\r\n'),
], ids=["smime_forward", "pgp_forward", "wrapper_forward", "encrypted_eml_file", "readable_forward", "html_and_pdf"])
def test_reading_an_email_never_writes_it_back(raw: bytes, tmp_path: Path, generator_calls: list[str]) -> None:
    package = read_eml(raw)
    text = email_text(package)
    assert "Please see the forwarded invoice." in text or "Total 120 kWh" in text
    path = tmp_path / "email.eml"
    path.write_bytes(raw)
    pane = document_content(path, "message/rfc822")  # the source pane reads the email the same way
    assert [line.strip() for line in pane["lines"]] == [line.strip() for line in text.splitlines() if line.strip()]
    assert generator_calls == []


def test_an_encrypted_email_still_halts_without_the_generator(generator_calls: list[str]) -> None:
    with pytest.raises(EmailError) as refused:
        read_eml(HEAD + b"Content-Type: message/rfc822\r\n\r\n" + HEAD + PGP)
    assert refused.value.code == "password_protected"
    assert generator_calls == []


# --- display names that keep their quotes ------------------------------------------------------
@pytest.mark.parametrize(("value", "expected", "name"), [
    (b'"Doe, \\"JJ\\" Jane" <j@example.com>', '"Doe, \\"JJ\\" Jane" <j@example.com>', 'Doe, "JJ" Jane'),
    (b'"Doe; \\"JJ\\"" <j@example.com>', '"Doe; \\"JJ\\"" <j@example.com>', 'Doe; "JJ"'),
    (b'"Doe, C:\\\\x" <j@example.com>', '"Doe, C:\\\\x" <j@example.com>', "Doe, C:\\x"),
    (b"=?utf-8?q?Doe=2C_=22JJ=22_Jane?= <j@example.com>", '"Doe, \\"JJ\\" Jane" <j@example.com>', 'Doe, "JJ" Jane'),
    (b'"John \\"JJ\\" Doe" <j@example.com>', 'John "JJ" Doe <j@example.com>', 'John "JJ" Doe'),  # no comma: unquoted
], ids=["comma_and_quotes", "semicolon_and_quotes", "comma_and_backslash", "encoded_comma_and_quotes", "no_comma"])
def test_a_quoted_display_name_reads_as_one_recipient(value: bytes, expected: str, name: str) -> None:
    rendered = read_eml(b"From: a@example.com\r\nTo: " + value + b"\r\nSubject: s\r\n\r\nx\r\n").to
    assert rendered == expected
    if rendered.startswith('"'):  # a name that kept its quotes is one address, read back whole
        assert getaddresses([rendered]) == [(name, "j@example.com")]
