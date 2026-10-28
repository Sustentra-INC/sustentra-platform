"""Encrypted and signed Outlook messages (.msg): which are refused, which are listed, which are read.

An encrypted message (S/MIME enveloped or authEnveloped data, or rights-protected) is refused as
``password_protected`` with the .eml reader's sentence when it is the message itself, and listed as
not read, with the covering message read, when it is embedded in one. A signed message is read: an
opaque-signed one like any other (its ``smime.p7m`` listed), a clear-signed one through the .eml
reader, whose attachments and forwarded messages replace the wrapper in the listing. Every file is
written by ``_msg_builder``; the clear-signed wrappers are stdlib MIME.
"""

from __future__ import annotations

import random
import time
import tracemalloc
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from email.message import EmailMessage
from typing import Any

import pytest

from backend.app.adapters.parsers import email_reader, msg_reader
from backend.app.adapters.parsers.email_parser import email_text, email_warnings
from backend.app.adapters.parsers.email_reader import (
    DAMAGED_EMAIL,
    ENCRYPTED_EMAIL,
    MAX_DEPTH,
    MAX_PARTS,
    EmailError,
    EmailPackage,
    read_eml,
)
from backend.app.adapters.parsers.msg_reader import NOT_AN_OUTLOOK_MESSAGE, read_msg
from backend.tests.adapters.parsers._msg_builder import (
    OID_AUTH_ENVELOPED_DATA,
    OID_ENVELOPED_DATA,
    OID_SIGNED_DATA,
    Attachment,
    Embedded,
    Message,
    Recipient,
    cms,
    msg_bytes,
    msg_tree,
)
from backend.tests.adapters.parsers._ole_builder import Tree, ole_tree
from backend.tests.adapters.parsers._timing import budget

SMIME = "IPM.Note.SMIME"
CLEAR_SIGNED = "IPM.Note.SMIME.MultipartSigned"
PKCS7 = "application/pkcs7-mime"
PDF = b"%PDF" * 1000
SENT = "Mon, 10 Feb 2025 09:15:00 -0500"
TEXT = "Total Usage: 120 therms"
ENCRYPTED_FORWARD = "the forwarded message is encrypted"
FORWARD_FAILED = "the forwarded message could not be read"
PROTECTED = ("password_protected", ENCRYPTED_EMAIL, None)  # code, message and cause of an explicit refusal


def _refused(data: bytes) -> EmailError:
    with pytest.raises(EmailError) as refused:
        read_msg(data)
    return refused.value


def _verdict(error: EmailError) -> tuple[str, str, BaseException | None]:
    return error.code, error.message, error.__cause__


def _smime(oid: str, *, cls: str = SMIME, **fields: Any) -> Message:
    """A message of class ``cls`` whose one attachment is CMS data of the content type ``oid``."""

    fields.setdefault("subject", "Your bill")
    return Message(message_class=cls, attachments=[Attachment("smime.p7m", cms(oid), mime=PKCS7)], **fields)


def _notes(package: EmailPackage) -> list[str]:
    return [code for code, _ in package.all_notes()]


def _walk(package: EmailPackage) -> list[EmailPackage]:
    """The message and every message forwarded in it, however deep."""

    found, pending = [], [package]
    while pending:
        found.append(pending.pop())
        pending += found[-1].nested
    return found


def _peak(read: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        read()
    except EmailError:
        pass
    finally:
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return peak


def _signed_mime(text: str | None = TEXT, *, attachments: int = 1, forward: EmailMessage | None = None) -> bytes:
    """What Outlook keeps for a clear-signed message: the whole MIME, multipart/signed, here with
    the text, ``attachments`` PDFs (``bill.pdf``, ...), the signature and maybe a forwarded message."""

    mime = EmailMessage()
    mime["From"], mime["To"], mime["Date"], mime["Subject"] = (
        "Acme Gas <billing@acme.example>", "ap@client.example", SENT, "Your February bill")
    if text is not None:
        mime.set_content(text)
    for number in range(attachments):
        mime.add_attachment(PDF, maintype="application", subtype="pdf",
                            filename="bill.pdf" if attachments == 1 else f"bill{number}.pdf")
    if forward is not None:
        mime.add_attachment(forward)
    mime.add_attachment(b"MIAGCSqGSIb3DQEHAqCA", maintype="application", subtype="pkcs7-signature",
                        filename="smime.p7s")
    mime.replace_header("Content-Type", "multipart/signed")
    mime.set_param("protocol", "application/pkcs7-signature")
    mime.set_param("micalg", "sha-256")
    return mime.as_bytes()


def _clear_signed(mime: bytes, *, body: str | None = None, cls: str = CLEAR_SIGNED, **fields: Any) -> Message:
    return Message(subject="Your February bill", message_class=cls, body=body, transport_headers=f"Date: {SENT}\r\n",
                   attachments=[Attachment("smime.p7m", mime, mime="multipart/signed")], **fields)


# --- encrypted: refused when it is the message ---------------------------------------------------
@pytest.mark.parametrize("oid", [OID_ENVELOPED_DATA, OID_AUTH_ENVELOPED_DATA], ids=["enveloped", "authenveloped"])
@pytest.mark.parametrize("cls", [SMIME, "ipm.note.smime", "IPM.NOTE.SMIME.MessagePartSigned"],
                         ids=["exact", "lower_case", "other_suffix"])
def test_an_smime_encrypted_message_is_password_protected(oid: str, cls: str) -> None:
    data = bytes.fromhex("3080" + oid + "a080") + bytes(100)  # written out, as the .eml reader would find it
    assert data == cms(oid)
    message = Message(subject="Your bill", message_class=cls, body="Cannot be read",
                      attachments=[Attachment("smime.p7m", data, mime=PKCS7)])
    assert _verdict(_refused(msg_bytes(message))) == PROTECTED
    assert ENCRYPTED_EMAIL == ("This email is encrypted. Ask the client to send it without encryption, or upload "
                               "its attachments on their own.")  # the .eml reader's sentence, word for word


@pytest.mark.parametrize(("oid", "last"), [(OID_ENVELOPED_DATA, 51), (OID_AUTH_ENVELOPED_DATA, 49)],
                         ids=["enveloped", "authenveloped"])
def test_the_oid_is_looked_for_in_the_first_64_bytes_only(oid: str, last: int) -> None:
    """The OID ends inside the 64th byte at ``last`` filler bytes; one more and it ends past it."""

    inside = Message(message_class=SMIME, attachments=[Attachment("smime.p7m", cms(oid, before=last), mime=PKCS7)])
    assert _verdict(_refused(msg_bytes(inside))) == PROTECTED
    past = Message(message_class=SMIME, attachments=[Attachment("smime.p7m", cms(oid, before=last + 1), mime=PKCS7)])
    assert [part.name for part in read_msg(msg_bytes(past)).attachments] == ["smime.p7m"]


@pytest.mark.parametrize("message", [
    _smime(OID_ENVELOPED_DATA, cls="IPM.Note"),  # encrypted data attached to an ordinary message
    _smime(OID_ENVELOPED_DATA, cls=CLEAR_SIGNED),  # clear-signed has no encrypted form
    Message(message_class=SMIME, attachments=[Attachment("smime.p7m", b"MIAGCSqGSIb3DQEHAQ" * 10, mime=PKCS7)]),
    Message(message_class=SMIME, attachments=[Attachment("smime.p7m", b"", mime=PKCS7)]),
    Message(message_class=SMIME, attachments=[Attachment("smime.p7m", cms(OID_ENVELOPED_DATA), mime=PKCS7, method=2)]),
    Message(message_class=SMIME),
    Message(message_class="IPM.Note.SMIMEX", attachments=[Attachment("a.p7m", cms(OID_ENVELOPED_DATA), mime=PKCS7)]),
    Message(message_class=""),
], ids=["ordinary_class", "clear_signed_class", "no_oid", "empty", "a_link", "no_attachment", "other_class",
        "no_class"])
def test_what_is_not_an_encrypted_message_is_read(message: Message) -> None:
    package = read_msg(msg_bytes(replace(message, body="Still readable")))
    assert package.body_text == "Still readable"


def test_an_encrypted_message_is_refused_before_any_text_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    def decoded(*_: object, **__: object) -> None:
        raise AssertionError("text was decoded")

    for name in ("_body", "_sender", "_recipients", "_sent", "_attachments"):
        monkeypatch.setattr(msg_reader, name, decoded)
    for message in (_smime(OID_ENVELOPED_DATA, body="b" * 100),
                    Message(message_class="IPM.Note.rpmsg.Microsoft.Voicemail.UM", body="b" * 100)):
        assert _verdict(_refused(msg_bytes(message))) == PROTECTED


def test_an_encrypted_message_is_refused_whatever_else_is_damaged() -> None:
    """The check comes right after the properties and the attachments' own: a damaged recipient does not hide it."""

    tree = msg_tree(_smime(OID_ENVELOPED_DATA, recipients=[Recipient("Jane", "jane@client.example")]))
    recipient = tree["__recip_version1.0_#00000000"]
    assert isinstance(recipient, dict)
    recipient["__substg1.0_3001001F"] = b"\xff" * 3
    assert _verdict(_refused(ole_tree(tree))) == PROTECTED


# --- signed: opaque ----------------------------------------------------------------------------------
def test_an_opaque_signed_message_is_read() -> None:
    package = read_msg(msg_bytes(_smime(OID_SIGNED_DATA, body=TEXT)))
    assert (package.body_text, package.body_source) == (TEXT, "plain")
    [part] = package.attachments
    assert (part.name, part.content_type, part.data, part.note) == ("smime.p7m", PKCS7, cms(OID_SIGNED_DATA), None)
    assert email_text(package).endswith(f"{TEXT}\n\nAttachments: smime.p7m\n")
    assert _notes(package) == []


def test_an_opaque_signed_message_reads_like_the_same_eml() -> None:
    eml = EmailMessage()
    eml["From"], eml["To"], eml["Date"], eml["Subject"] = (
        "Acme Gas <billing@acme.example>", "ap@client.example", SENT, "Your February bill")
    eml.set_content(TEXT)
    eml.add_attachment(cms(OID_SIGNED_DATA), maintype="application", subtype="pkcs7-mime", filename="smime.p7m",
                       params={"smime-type": "signed-data"})
    msg = Message(subject="Your February bill", sender_name="Acme Gas", sender_smtp="billing@acme.example",
                  recipients=[Recipient("", "ap@client.example")], body=TEXT, message_class=SMIME,
                  transport_headers=f"Date: {SENT}\r\n",
                  attachments=[Attachment("smime.p7m", cms(OID_SIGNED_DATA), mime=PKCS7)])
    from_eml, from_msg = read_eml(eml.as_bytes()), read_msg(msg_bytes(msg))
    assert email_text(from_msg) == email_text(from_eml)
    assert email_warnings(from_msg) == email_warnings(from_eml)
    assert "smime.p7m" in email_text(from_msg)


def test_a_signed_xml_p7m_invoice_is_listed_not_refused() -> None:
    """An Italian e-invoice is a signed XML file, `.xml.p7m`: signed-data, in a message of any class."""

    name = "IT01234567890_00001.xml.p7m"
    for cls in ("IPM.Note", SMIME):
        package = read_msg(msg_bytes(Message(body="Invoice attached", message_class=cls, attachments=[
            Attachment(name, cms(OID_SIGNED_DATA, after=2_000), mime=PKCS7)])))
        assert [(part.name, part.content_type, part.note) for part in package.attachments] == [(name, PKCS7, None)]


# --- signed: clear ---------------------------------------------------------------------------------------
def test_a_clear_signed_message_reads_its_mime() -> None:
    mime = _signed_mime()
    package = read_msg(msg_bytes(_clear_signed(mime)))
    assert (package.body_text, package.body_source) == (TEXT, "plain")  # the MAPI body is blank
    assert [(part.name, part.data) for part in package.attachments] == [("bill.pdf", PDF)]  # the wrapper is not listed
    assert email_text(package).endswith(f"{TEXT}\n\nAttachments: bill.pdf\n")
    # the same MIME read as an .eml gives the same text and the same attachments
    expected = read_eml(mime)
    assert (package.body_text, [(part.name, part.content_type, part.data) for part in package.attachments]) == (
        expected.body_text, [(part.name, part.content_type, part.data) for part in expected.attachments])
    assert "smime.p7s" not in email_text(package) and _notes(package) == []


def test_a_clear_signed_message_with_html_only_text_reads_the_html() -> None:
    mime = EmailMessage()
    mime["From"], mime["Subject"] = "billing@acme.example", "s"
    mime.set_content("<html><body><p>Total Usage: 120 therms</p></body></html>", subtype="html")
    mime.add_attachment(b"MIAG", maintype="application", subtype="pkcs7-signature", filename="smime.p7s")
    mime.replace_header("Content-Type", "multipart/signed")
    package = read_msg(msg_bytes(_clear_signed(mime.as_bytes())))
    assert (package.body_text, package.body_source) == (TEXT, "html")


def test_a_clear_signed_message_with_a_body_keeps_it() -> None:
    package = read_msg(msg_bytes(_clear_signed(_signed_mime(), body="The text Outlook stored")))
    assert (package.body_text, package.body_source) == ("The text Outlook stored", "plain")
    assert [part.name for part in package.attachments] == ["bill.pdf"]  # the wrapper's attachment is still listed
    assert TEXT not in email_text(package)


def test_a_clear_signed_class_and_tag_are_compared_without_regard_to_case() -> None:
    message = _clear_signed(_signed_mime(), cls="ipm.note.smime.MULTIPARTSIGNED")
    message.attachments = [Attachment("smime.p7m", _signed_mime(), mime="Multipart/Signed")]
    package = read_msg(msg_bytes(message))
    assert (package.body_text, [part.name for part in package.attachments]) == (TEXT, ["bill.pdf"])


@pytest.mark.parametrize(("cls", "attachment"), [
    ("IPM.Note", Attachment("a.pdf", PDF, mime="application/pdf")),  # no wrapper
    ("IPM.Note", Attachment("smime.p7m", _signed_mime(), mime="multipart/signed")),  # not a clear-signed class
    (CLEAR_SIGNED, Attachment("smime.p7m", _signed_mime(), mime="multipart/signed", method=2)),  # a link
    (CLEAR_SIGNED, Attachment("smime.p7m", _signed_mime(), mime="application/pkcs7-mime")),  # not tagged signed
], ids=["no_wrapper", "ordinary_class", "wrapper_is_a_link", "other_tag"])
def test_a_message_is_clear_signed_only_by_class_and_by_value_attachment(cls: str, attachment: Attachment) -> None:
    package = read_msg(msg_bytes(Message(message_class=cls, body="Plain", attachments=[attachment])))
    assert package.body_text == "Plain" and [part.name for part in package.attachments] == [attachment.name]
    assert "bill.pdf" not in [part.name for part in package.all_attachments()]  # the wrapper was not opened


def test_a_clear_signed_wrapper_that_is_refused_is_listed_as_not_read() -> None:
    for wrapper in (b"just some text, no headers", b"", bytes.fromhex("d0cf11e0a1b11ae1") + bytes(600),
                    b"From: a@example.com\n" + b"X-Header: v\n" * (email_reader.MAX_HEADERS + 1)):
        package = read_msg(msg_bytes(_clear_signed(wrapper, body="Stored text")))
        assert package.body_text == "Stored text"
        [part] = package.attachments
        assert (part.name, part.content_type, part.data, part.note) == (
            "smime.p7m", "multipart/signed", wrapper, FORWARD_FAILED)
        assert "smime.p7m" in email_warnings(package)[-1]["message"] and FORWARD_FAILED in (
            email_warnings(package)[-1]["message"])


def test_a_clear_signed_wrapper_forwards_its_messages_in_its_place() -> None:
    forwarded = EmailMessage()
    forwarded["From"], forwarded["Subject"], forwarded["Date"] = "a@acme.example", "March invoice", SENT
    forwarded.set_content("March usage: 98 therms")
    forwarded.add_attachment(PDF, maintype="application", subtype="pdf", filename="march.pdf")
    package = read_msg(msg_bytes(_clear_signed(_signed_mime(forward=forwarded))))
    assert [part.name for part in package.attachments] == ["bill.pdf"]
    [nested] = package.nested
    assert (nested.subject, nested.body_text) == ("March invoice", "March usage: 98 therms")
    assert [(part.name, part.path) for part in nested.attachments] == [("march.pdf", ["March invoice"])]
    assert "Forwarded message" in email_text(package)


def test_a_clear_signed_message_embedded_in_another_is_read_one_level_down() -> None:
    inner = _clear_signed(_signed_mime())
    inner.subject = "Signed bill"
    package = read_msg(msg_bytes(Message(subject="Fwd", body="See below", attachments=[Embedded(inner)])))
    [nested] = package.nested
    assert (nested.body_text, [(part.name, part.path) for part in nested.attachments]) == (
        TEXT, [("bill.pdf", ["Signed bill"])])


def test_a_clear_signed_message_that_was_encrypted_first_is_encrypted() -> None:
    enveloped = (b"Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name=smime.p7m\r\n"
                 b"Content-Transfer-Encoding: base64\r\n\r\nMIAGCSqGSIb3DQEHA6CAMIACAQAxggE=\r\n")
    wrapper = (b'From: a@example.com\r\nSubject: s\r\nContent-Type: multipart/signed; boundary="s"; '
               b'protocol="application/pkcs7-signature"\r\n\r\n--s\r\n' + enveloped
               + b"--s\r\nContent-Type: application/pkcs7-signature; name=smime.p7s\r\n\r\nMIAG\r\n--s--\r\n")
    assert _verdict(_refused(msg_bytes(_clear_signed(wrapper, body="x")))) == PROTECTED
    package = read_msg(msg_bytes(Message(body="Cover", attachments=[Embedded(_clear_signed(wrapper), size=900)])))
    assert [(part.note, part.size) for part in package.attachments] == [(ENCRYPTED_FORWARD, 900)]


# --- the wrapper is read under the message's own budgets ------------------------------------------------
def test_the_parts_of_a_wrapper_count_against_the_messages_limit() -> None:
    message = _clear_signed(_signed_mime(attachments=150), body="x")
    message.attachments += [Attachment(f"a{n}.pdf", b"x") for n in range(100)]
    package = read_msg(msg_bytes(message))
    assert len(package.attachments) <= MAX_PARTS == 200  # 250 were there: the limit is the message's, not twice
    assert package.attachments[0].name == "bill0.pdf" and package.attachments[-1].name.startswith("a")
    assert _notes(package) == ["email_parts_limit"]  # said once, for the whole message


def test_the_text_of_a_wrapper_counts_against_the_messages_text_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_reader, "MAX_TEXT_CHARS", 1_000)
    forwarded = EmailMessage()
    forwarded["Subject"] = "March invoice"
    forwarded.set_content("f" * 800)
    message = _clear_signed(_signed_mime("w" * 800, forward=forwarded), body="m" * 800)
    package = read_msg(msg_bytes(message))
    texts = [package.body_text, *(nested.body_text for nested in package.nested)]
    assert sum(len(text) for text in texts) <= 1_000 and package.body_text == "m" * 800
    assert _notes(package) == ["body_truncated"]  # once
    # the same wrapper alone is cut by the same budget, as an email of its own
    assert len(read_eml(_signed_mime("w" * 2_000)).body_text) == 1_000


def test_a_wrapper_forwards_messages_only_as_deep_as_the_message_allows() -> None:
    forwarded = EmailMessage()
    forwarded["Subject"] = "Too deep"
    forwarded.set_content("never read")
    deepest = _clear_signed(_signed_mime(forward=forwarded))
    deepest.subject = "Level 3"
    level = deepest
    for number in range(MAX_DEPTH - 1, 0, -1):  # Level 2, Level 1, then the top message
        level = Message(subject=f"Level {number}", body="x", attachments=[Embedded(level)])
    package = read_msg(msg_bytes(Message(subject="Level 0", body="x", attachments=[Embedded(level)])))
    assert _notes(package) == ["forwarded_too_deep"]
    assert "never read" not in " ".join(nested.body_text for nested in _walk(package))
    assert [part.name for part in package.all_attachments()] == ["bill.pdf"]


@pytest.mark.parametrize("hostile", ["nested", "parts", "lines", "blank lines", "headers"])
def test_a_hostile_signed_wrapper_is_bounded(hostile: str) -> None:
    wrapper = {
        "nested": b"".join(b'Content-Type: multipart/mixed; boundary="b%d"\n\n--b%d\n' % (n, n) for n in range(2_000)),
        "parts": b'From: a@b.example\nContent-Type: multipart/mixed; boundary="b"\n\n'
                 + b"--b\nContent-Type: text/plain\n\nx\n" * 100_000,  # 100,000 parts, 3 MB
        "lines": b"From: a@b.example\nSubject: s\n\n" + b"x\n" * 1_500_000,  # 3 MB, a million and a half lines
        "blank lines": b"\n" * 24_000_000,  # the most a 32 MB file leaves for a wrapper
        "headers": b"From: a@b.example\n" + b"X-Header: v\n" * 200_000 + b"\nbody\n",
    }[hostile]
    data = msg_bytes(_clear_signed(wrapper, body="Stored text"), sector_shift=12)
    started = time.perf_counter()
    try:
        package = read_msg(data)
    except EmailError:
        pass  # the only error the reader may raise
    else:
        assert package.body_text  # the MAPI body is there whether the wrapper was read or listed as not read
    assert time.perf_counter() - started < budget(1)  # about 0.25 s without coverage, the longest of them
    if hostile in ("lines", "blank lines"):  # the file once, a copy while its sectors are joined, and the .eml's own
        assert _peak(lambda: read_msg(data)) < _peak(lambda: read_eml(wrapper)) + 3 * len(data)


def test_a_wrapper_the_eml_reader_refuses_is_listed_not_read() -> None:
    nested = b"".join(b'Content-Type: multipart/mixed; boundary="b%d"\n\n--b%d\n' % (n, n) for n in range(2_000))
    with pytest.raises(EmailError) as eml_refused:
        read_eml(nested)
    package = read_msg(msg_bytes(_clear_signed(nested, body="Stored text")))
    assert eml_refused.value.code == "email_load_failed"
    assert [(part.note, part.size) for part in package.attachments] == [(FORWARD_FAILED, len(nested))]
    assert _notes(package) == ["email_truncated"]  # the lines the .eml reader did not read, said once


def test_a_large_signed_wrapper_is_read_whole() -> None:
    big = b"%PDF" * 2_000_000  # 8 MB, 11 MB as base64 in the wrapper
    mime = EmailMessage()
    mime["From"] = "billing@acme.example"
    mime.set_content(TEXT)
    mime.add_attachment(big, maintype="application", subtype="pdf", filename="bill.pdf")
    mime.add_attachment(b"MIAG", maintype="application", subtype="pkcs7-signature", filename="smime.p7s")
    mime.replace_header("Content-Type", "multipart/signed")
    wrapper = mime.as_bytes()
    data = msg_bytes(_clear_signed(wrapper), sector_shift=12)
    started = time.perf_counter()
    package = read_msg(data)
    assert time.perf_counter() - started < budget(1)  # about 0.2 s without coverage
    assert [(part.name, part.data == big) for part in package.attachments] == [("bill.pdf", True)]
    assert _peak(lambda: read_msg(data)) < _peak(lambda: read_eml(wrapper)) + 3 * len(data)


def test_a_wrapper_is_read_under_the_callers_walk_which_keeps_the_closing_notes() -> None:
    walk = email_reader._Walk()
    mime = EmailMessage()
    mime["From"] = "a@b.example"
    mime.set_content("x")
    for number in range(250):
        mime.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"a{number}.bin")
    package = email_reader.read_eml_within(mime.as_bytes(), walk, depth=2, path=["Outer"])
    assert walk.stopped and len(package.attachments) < MAX_PARTS  # the walk's limit was reached ...
    assert _notes(package) == [] and {tuple(part.path) for part in package.attachments} == {("Outer",)}
    assert [code for code, _ in read_eml(mime.as_bytes()).notes] == ["email_parts_limit"]  # ... .eml says so itself


# --- rights-protected ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("message", [
    Message(message_class="IPM.Note.rpmsg.Microsoft.Voicemail.UM", body="Voice message"),
    Message(message_class="IPM.NOTE.RPMSG", body="x", attachments=[Attachment("a.pdf", b"x")]),
    Message(message_class="IPM.Note", body="This message is protected", attachments=[
        Attachment("message.rpmsg", bytes(300), mime="application/x-microsoft-rpmsg-message")]),
    Message(message_class="IPM.Note", attachments=[Attachment("a.pdf", b"x"), Attachment("Message.RPMSG", b"x")]),
], ids=["voicemail_class", "class_in_capitals", "rpmsg_attachment", "name_in_capitals"])
def test_a_rights_protected_message_is_encrypted(message: Message) -> None:
    assert _verdict(_refused(msg_bytes(message))) == PROTECTED


@pytest.mark.parametrize("attachment", [
    Attachment("message.rpmsg", b"x", method=2),  # a link, not the message
    Attachment("message.rpmsg.txt", b"x"), Attachment("old-message.rpmsg", b"x"), Attachment("", b"x")],
    ids=["a_link", "other_extension", "other_name", "no_name"])
def test_only_a_by_value_message_rpmsg_makes_the_cover_encrypted(attachment: Attachment) -> None:
    package = read_msg(msg_bytes(Message(message_class="IPM.Note", body="Readable", attachments=[attachment])))
    assert package.body_text == "Readable" and len(package.attachments) == 1


# --- encrypted: embedded -----------------------------------------------------------------------------------------
def test_an_encrypted_forwarded_message_is_listed_and_the_cover_read() -> None:
    encrypted = _smime(OID_ENVELOPED_DATA, body="never shown")
    encrypted.subject = "Invoice 42"
    readable = Message(subject="March invoice", body="March usage: 98 therms",
                       attachments=[Attachment("march.pdf", PDF, mime="application/pdf")])
    cover = Message(subject="Fwd: invoices", body="Two invoices below", attachments=[
        Attachment("note.txt", b"hello"), Embedded(encrypted, size=7_000), Embedded(readable)])
    package = read_msg(msg_bytes(cover))
    assert (package.body_text, [nested.subject for nested in package.nested]) == (
        "Two invoices below", ["March invoice"])
    assert [(part.name, part.content_type, part.data, part.note, part.size, part.path) for part in package.attachments
            ] == [("note.txt", "text/plain", b"hello", None, 5, []),
                  ("Invoice 42.msg", "application/vnd.ms-outlook", b"", ENCRYPTED_FORWARD, 7_000, [])]
    text = email_text(package)
    assert "never shown" not in text and "Attachments: note.txt, Invoice 42.msg" in text
    assert "Invoice 42.msg (7 KB, the forwarded message is encrypted)" in email_warnings(package)[0]["message"]
    assert _notes(package) == []


@pytest.mark.parametrize("embedded", [
    _smime(OID_AUTH_ENVELOPED_DATA, subject="Invoice 42"),
    Message(subject="Invoice 42", message_class="IPM.Note.rpmsg.Microsoft.Voicemail.UM"),
    Message(subject="Invoice 42", attachments=[Attachment("message.rpmsg", b"x")]),
], ids=["authenveloped", "rights_class", "rpmsg_attachment"])
def test_every_kind_of_encrypted_forward_is_listed(embedded: Message) -> None:
    package = read_msg(msg_bytes(Message(body="Cover", attachments=[Embedded(embedded)])))
    assert (package.body_text, package.nested) == ("Cover", [])
    assert [(part.name, part.note) for part in package.attachments] == [("Invoice 42.msg", ENCRYPTED_FORWARD)]


def test_the_name_of_an_encrypted_forward_is_a_safe_file_name() -> None:
    names = []
    for subject in ("March / invoice\\final", "", "x" * 5_000, "a\u0007b\nc"):
        embedded = _smime(OID_ENVELOPED_DATA, subject=subject)
        part = read_msg(msg_bytes(Message(attachments=[Embedded(embedded)]))).attachments[0]
        assert part.note == ENCRYPTED_FORWARD
        names.append(part.name)
    assert names[:2] == ["March invoice final.msg", "message.msg"]
    assert len(names[2]) <= email_reader.MAX_NAME_CHARS and names[2].endswith(".msg")
    assert "/" not in names[3] and "\\" not in names[3] and all(ch.isprintable() for ch in names[3])


def test_an_encrypted_forward_deeper_in_keeps_its_place() -> None:
    encrypted = _smime(OID_ENVELOPED_DATA, subject="Locked")
    level_one = Message(subject="Level 1", body="Level one text", attachments=[Embedded(encrypted), Embedded(Message(
        subject="Level 2", body="Level two text", attachments=[Embedded(_smime(OID_SIGNED_DATA, subject="Signed"))]))])
    package = read_msg(msg_bytes(Message(subject="Top", attachments=[Embedded(level_one)])))
    assert [(part.name, part.note, part.path) for part in package.all_attachments()] == [
        ("Locked.msg", ENCRYPTED_FORWARD, ["Level 1"]), ("smime.p7m", None, ["Level 1", "Level 2", "Signed"])]
    assert sorted(nested.subject for nested in _walk(package)) == ["Level 1", "Level 2", "Signed", "Top"]  # all read
    assert {nested.body_text for nested in _walk(package)} == {"", "Level one text", "Level two text"}


def test_an_encrypted_forward_past_the_depth_limit_is_named_not_opened() -> None:
    inner = _smime(OID_ENVELOPED_DATA, subject="Level 4")
    for number in range(MAX_DEPTH, 0, -1):
        inner = Message(subject=f"Level {number}", body="x", attachments=[Embedded(inner)])
    package = read_msg(msg_bytes(Message(subject="Level 0", attachments=[Embedded(inner)])))
    assert _notes(package) == ["forwarded_too_deep"] and package.all_attachments() == []


def test_encrypted_forwards_count_against_the_parts_limit() -> None:
    embedded = [Embedded(_smime(OID_ENVELOPED_DATA, subject=f"Locked {n}")) for n in range(250)]
    package = read_msg(msg_bytes(Message(body="Cover", attachments=embedded)))
    assert len(package.attachments) == MAX_PARTS and _notes(package) == ["email_parts_limit"]


# --- the order the streams are read in ---------------------------------------------------------------------------------
def test_crossed_chains_are_noticed_by_the_stream_read_second() -> None:
    """Rule 2 reads an S/MIME attachment's data before the body. When the two share sectors the
    first read keeps them: for encrypted data the message stops there (the body is never read);
    for signed data the body is the stream refused."""

    body, data = "__substg1.0_1000001F", "__attach_version1.0_#00000000/__substg1.0_37010102"
    for oid, expected in ((OID_ENVELOPED_DATA, PROTECTED), (OID_SIGNED_DATA, ("email_load_failed", DAMAGED_EMAIL, None))):
        message = Message(message_class=SMIME, body="b" * 5_000, attachments=[
            Attachment("smime.p7m", cms(oid, after=10_000), mime=PKCS7)])
        assert _verdict(_refused(msg_bytes(message, share=(data, body)))) == expected
    # the unshared message is fine either way
    assert read_msg(msg_bytes(message)).body_text == "b" * 5_000


# --- random damage -------------------------------------------------------------------------------------------------------
def _tree_of(name: str) -> Tree:
    return {"encrypted": lambda: msg_tree(_smime(OID_ENVELOPED_DATA, subject="Locked", body="x" * 50)),
            "clear-signed": lambda: msg_tree(_clear_signed(_signed_mime())),
            "forwarded": lambda: msg_tree(Message(subject="Cover", body="Cover text", attachments=[
                Embedded(_smime(OID_AUTH_ENVELOPED_DATA, subject="Locked")), Embedded(_clear_signed(_signed_mime()))])),
            "rights-protected": lambda: msg_tree(Message(
                message_class="IPM.Note", attachments=[Attachment("message.rpmsg", bytes(200))]))}[name]()


def _streams(tree: Tree) -> list[tuple[Tree, str]]:
    found: list[tuple[Tree, str]] = []
    pending = [tree]
    while pending:
        storage = pending.pop()
        for name, content in storage.items():
            if isinstance(content, dict):
                pending.append(content)
            else:
                found.append((storage, name))
    return found


def _damaged(name: str, good: bytes, rng: random.Random, count: int) -> list[bytes]:
    """``count`` damaged copies of a message: bytes of the file changed, the file cut short, runs
    overwritten, and bytes of a stream of the message changed before the container is written."""

    damaged = []
    for number in range(count):
        mode = number % 4
        if mode == 3:
            tree = _tree_of(name)
            storage, stream = rng.choice(_streams(tree))
            content = bytearray(storage[stream])  # type: ignore[arg-type]
            for _ in range(rng.randint(1, 6)):
                if content:
                    content[rng.randrange(len(content))] = rng.randrange(256)
            storage[stream] = bytes(content) if rng.random() < 0.8 else bytes(content[:rng.randrange(len(content) + 1)])
            damaged.append(ole_tree(tree))
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


@pytest.mark.parametrize("name", ["encrypted", "clear-signed", "forwarded", "rights-protected"])
def test_random_damage_never_escapes_as_another_error(name: str) -> None:
    good = ole_tree(_tree_of(name))
    rng = random.Random(20251028)
    allowed = {("email_load_failed", DAMAGED_EMAIL), ("not_an_email", NOT_AN_OUTLOOK_MESSAGE),
               ("password_protected", ENCRYPTED_EMAIL)}
    started = time.perf_counter()
    read = 0
    refused: Counter[str] = Counter()
    for data in _damaged(name, good, rng, 200):
        try:
            package = read_msg(data)
        except EmailError as error:
            # an explicit refusal, not the catch-all (which would carry the unforeseen exception)
            assert error.__cause__ is None, repr(error.__cause__)
            assert (error.code, error.message) in allowed
            refused[error.code] += 1
        else:
            email_text(package).encode("utf-8")  # no lone surrogate reaches the text
            email_warnings(package)
            read += 1
    assert time.perf_counter() - started < budget(2)  # about 0.2 s without coverage
    assert read > 3 and refused["email_load_failed"] > 10, (read, refused)  # damage is read through and refused
    if name in ("encrypted", "rights-protected"):
        assert refused["password_protected"] > 10, refused  # and the verdict survives damage elsewhere
