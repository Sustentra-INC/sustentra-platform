"""Email reader, review round 2: deep nesting, folded encoded words, raw 8-bit parameters,
the charset denylist, splitlines-consistent line caps, encrypted detection anywhere in the
tree, display headers, and attached .eml files over a shared budget."""

from __future__ import annotations

import base64
import time

import pytest

from backend.app.adapters.parsers import email_reader
from backend.app.adapters.parsers.email_reader import EmailError, read_eml
from backend.tests.adapters.parsers._timing import budget

HEAD = b"From: a@example.com\r\nSubject: s\r\nMIME-Version: 1.0\r\n"


def _mixed(*parts: bytes) -> bytes:
    return (HEAD + b'Content-Type: multipart/mixed; boundary="m"\r\n\r\n'
            + b"".join(b"--m\r\n" + part for part in parts) + b"--m--\r\n")


# --- item 1: lines x depth --------------------------------------------------------------------
@pytest.mark.parametrize("depth", [100, 500, 900])
def test_deep_multipart_nesting_with_many_lines_is_read_fast(depth: int) -> None:
    # The parser tests every line against every enclosing boundary: depth 900 with ~1M lines
    # took 51 s on 3.12. The line budget now shrinks with the boundaries declared.
    raw = b"From: a@example.com\r\nSubject: deep\r\n"
    for level in range(depth):
        raw += b'Content-Type: multipart/mixed; boundary="b%d"\r\n\r\n--b%d\r\n' % (level, level)
    raw += b"Content-Type: text/plain\r\n\r\n" + b"\n" * 990_000
    started = time.perf_counter()
    package = read_eml(raw)
    assert time.perf_counter() - started < budget(3)
    assert "email_truncated" in {code for code, _ in package.notes}


# --- item 2: folded encoded words ------------------------------------------------------------
def test_folded_encoded_words_keep_their_spaces() -> None:
    raw = (b"From: =?utf-8?q?Soci=C3=A9t=C3=A9_G=C3=A9n=C3=A9rale_d'=C3=89nergie?=\r\n <factures@sge.example>\r\n"
           b"Subject: Facture =?utf-8?q?f=C3=A9vrier?=\r\n 2025 - 120 kWh\r\n\r\nx\r\n")
    package = read_eml(raw)
    assert package.subject == "Facture f\u00e9vrier 2025 - 120 kWh"
    assert package.sender == "Soci\u00e9t\u00e9 G\u00e9n\u00e9rale d'\u00c9nergie <factures@sge.example>"


def test_a_backslash_beside_an_encoded_word_stays_intact() -> None:
    raw = b"From: a@example.com\r\nSubject: Path C:\\users\\unpaid =?utf-8?q?F=C3=A9vrier?=\r\n\r\nx\r\n"
    assert read_eml(raw).subject == "Path C:\\users\\unpaid F\u00e9vrier"


def test_a_malformed_encoded_word_is_kept_as_written() -> None:
    raw = b"From: a@example.com\r\nSubject: =?utf-8?b?!!!?= ok\r\n\r\nx\r\n"
    assert "ok" in read_eml(raw).subject


# --- item 3: raw 8-bit parameter values ------------------------------------------------------
def _with_attachment(disposition: bytes) -> bytes:
    return _mixed(b"Content-Type: text/plain\r\n\r\nhi\r\n",
                  b"Content-Type: application/pdf\r\nContent-Disposition: attachment; " + disposition
                  + b"\r\n\r\n%PDF\r\n")


def test_a_raw_8bit_filename_is_read_not_replaced() -> None:
    name = read_eml(_with_attachment('filename="Facture f\u00e9vrier.pdf"'.encode())).attachments[0].name
    assert name == "Facture f\u00e9vrier.pdf"


def test_rfc2231_extended_and_continued_filenames_are_decoded() -> None:
    assert read_eml(_with_attachment(b"filename*=utf-8''Facture%20f%C3%A9vrier.pdf")).attachments[0].name == (
        "Facture f\u00e9vrier.pdf")
    continued = b"filename*0*=utf-8''Fact; filename*1=ure-; filename*2*=f%C3%A9vrier.pdf"
    assert read_eml(_with_attachment(continued)).attachments[0].name == "Facture-f\u00e9vrier.pdf"


def test_a_quoted_parameter_with_a_semicolon_is_one_value() -> None:
    assert read_eml(_with_attachment(b'filename="a;b.pdf"')).attachments[0].name == "a;b.pdf"


# --- item 4: charset denylist ----------------------------------------------------------------
def _body(charset: bytes, payload: bytes) -> str:
    return read_eml(HEAD + b"Content-Type: text/plain; charset=" + charset + b"\r\n\r\n" + payload).body_text


def test_linear_codecs_are_kept_and_quadratic_ones_refused() -> None:
    thai = "\u0e43\u0e0a\u0e49\u0e44\u0e1f 120"
    assert _body(b"tis-620", thai.encode("tis-620")) == thai
    assert _body(b"utf-8-sig", "Total 120".encode("utf-8-sig")) == "Total 120"  # BOM stripped again
    assert _body(b"x-mac-cyrillic", "\u0421\u0447\u0451\u0442".encode("mac-cyrillic")) == "\u0421\u0447\u0451\u0442"
    puny = ("\u00e9" * 50_000).encode("punycode")
    assert _body(b"punycode", puny).startswith(puny[:10].decode())  # read as UTF-8, not punycode
    assert _body(b"base64", b"VG90YWw=") == "VG90YWw="  # not a text codec: read as UTF-8


# The all-codec timing test moved to test_email_reader_round3.py (adversarial payloads, every
# codec module, the denylist checked through the reader's own resolution).


# --- item 5: splitlines-consistent line cap --------------------------------------------------
def test_text_lines_are_counted_the_way_they_are_split() -> None:
    # 600k "a\x0c" counted as one "\n"-line, but split into 600k blocks (459 MB).
    started = time.perf_counter()
    body = read_eml(HEAD + b"Content-Type: text/plain\r\n\r\n" + b"a\x0c" * 600_000).body_text
    assert time.perf_counter() - started < budget(3)
    assert len([line for line in body.splitlines() if line.strip()]) == email_reader.MAX_TEXT_LINES


# --- item 6: encrypted detection -------------------------------------------------------------
ENVELOPED = (b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n'
             b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CAMIACAQAxggE=\r\n")
PGP = (b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="e"\r\n\r\n'
       b"--e\r\nContent-Type: application/pgp-encrypted\r\n\r\nVersion: 1\r\n--e\r\n"
       b"Content-Type: application/octet-stream\r\n\r\n-----BEGIN PGP MESSAGE-----\r\n--e--\r\n")
FOOTER = b"Content-Type: text/plain\r\n\r\n_______________\r\nlist-users mailing list\r\n"


@pytest.mark.parametrize("raw", [
    _mixed(PGP, FOOTER),
    _mixed(ENVELOPED, b"Content-Type: text/plain\r\n\r\nThis email was scanned by Gateway.\r\n"),
    _mixed(b'Content-Type: multipart/mixed; boundary="n"\r\n\r\n--n\r\n' + PGP + b"--n--\r\n"),
    HEAD + b"Content-Type: message/rfc822\r\n\r\n" + HEAD + ENVELOPED,
    _mixed(b"Content-Type: message/rfc822\r\n\r\n" + HEAD + ENVELOPED),
    HEAD + b"Content-Type: application/x-pkcs7-mime\r\nContent-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CA\r\n",
    HEAD + ENVELOPED.replace(b"enveloped-data", b"authEnveloped-data"),
], ids=["pgp_plus_list_footer", "smime_plus_disclaimer", "two_levels_down", "top_rfc822_wrapping",
        "rfc822_only_part", "der_enveloped_oid", "authenveloped"])
def test_an_encrypted_container_anywhere_halts(raw: bytes) -> None:
    with pytest.raises(EmailError) as refused:
        read_eml(raw)
    assert (refused.value.code, refused.value.message) == ("password_protected", email_reader.ENCRYPTED_EMAIL)


@pytest.mark.parametrize("raw", [
    _mixed(b'Content-Type: application/pkcs7-mime; name="IT01234567890_00001.xml.p7m"\r\n'
           b'Content-Disposition: attachment; filename="IT01234567890_00001.xml.p7m"\r\n'
           b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHAqCA\r\n"),
    HEAD + b'Content-Type: application/pkcs7-mime; smime-type=signed-data; name="smime.p7m"\r\n'
           b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHAqCA\r\n",
], ids=["signed_xml_p7m_invoice", "opaque_signed"])
def test_a_signed_p7m_is_listed_not_refused(raw: bytes) -> None:
    package = read_eml(raw)
    assert [part.content_type for part in package.all_attachments()] == ["application/pkcs7-mime"]


def test_an_encrypted_attached_eml_is_listed_as_not_read() -> None:
    package = read_eml(_mixed(
        b"Content-Type: text/plain\r\n\r\nFYI\r\n",
        b'Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="locked.eml"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\n" + base64.encodebytes(HEAD + PGP)))
    assert package.body_text == "FYI"
    [part] = package.attachments
    assert (part.name, part.note) == ("locked.eml", "the forwarded message is encrypted")


# --- item 7: display headers -----------------------------------------------------------------
def test_display_names_are_unquoted_and_the_date_kept_as_sent() -> None:
    package = read_eml(b'From: "Acme Gas" <billing@acme.example>\r\nTo: "Smith, John" <john@example.com>\r\n'
                       b"Date: Mon, 10 Feb 2025 9:15:00 -0500 (EST)\r\nSubject: s\r\n\r\nx\r\n")
    assert package.sender == "Acme Gas <billing@acme.example>"
    assert package.to == '"Smith, John" <john@example.com>'  # a comma keeps its quotes (round 3)
    assert package.sent_at == "Mon, 10 Feb 2025 9:15:00 -0500 (EST)"


# --- item 8: attached .eml over the shared header budget -------------------------------------
def test_an_attached_eml_over_the_header_budget_is_listed_not_refused(monkeypatch) -> None:
    monkeypatch.setattr(email_reader, "MAX_HEADERS", 50)
    inner = b"From: x@y\r\n" + b"".join(b"X-%d: v\r\n" % n for n in range(200)) + b"\r\nbody\r\n"
    package = read_eml(_mixed(
        b"Content-Type: text/plain\r\n\r\nFYI\r\n",
        b'Content-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="big.eml"\r\n'
        b"Content-Transfer-Encoding: base64\r\n\r\n" + base64.encodebytes(inner)))
    assert package.body_text == "FYI"
    [part] = package.attachments
    assert (part.name, part.note) == ("big.eml", "the forwarded message could not be read")
