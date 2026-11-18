"""Outlook messages (.msg) written byte by byte by the tests themselves, to [MS-OXMSG].

A message is a compound file (``_ole_builder.ole_tree`` writes it) holding a property stream
(``__properties_version1.0``: a header, then 16-byte entries), a stream for every string and
binary property (``__substg1.0_<tag>``), and a storage for every recipient and attachment. An
embedded message is a storage of its own inside its attachment's storage. The constants are literal
values with the section that defines them; nothing is imported from the reader.

``msg_tree`` returns the tree as a plain dict, so a test can add, drop or replace an entry before
``ole_tree`` writes it (a property stream with a million entries, an attachment without a name).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.tests.adapters.parsers._ole_builder import Tree, ole_tree

# [MS-OXCDATA] 2.11.1 property types
PT_LONG, PT_BOOLEAN, PT_SYSTIME, PT_OBJECT = 0x0003, 0x000B, 0x0040, 0x000D
PT_STRING8, PT_UNICODE, PT_BINARY = 0x001E, 0x001F, 0x0102
FIXED_TYPES = (0x0002, PT_LONG, 0x0004, 0x0005, 0x0006, 0x0007, PT_BOOLEAN, 0x0014, PT_SYSTIME)
FLAGS = 0x00000006  # [MS-OXMSG] 2.4.2: PROPATTR_READABLE | PROPATTR_WRITABLE
TOP_HEADER, EMBEDDED_HEADER, CHILD_HEADER = 32, 24, 8  # [MS-OXMSG] 2.4.1: property stream header sizes
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)  # [MS-DTYP] 2.3.3
PROPERTIES = "__properties_version1.0"  # [MS-OXMSG] 2.2.1
METHOD_BY_VALUE, METHOD_EMBEDDED_MESSAGE = 1, 5  # [MS-OXCMSG] 2.2.2.9 PidTagAttachMethod
# DER object identifiers of the CMS content types ([RFC 5652] 3: a ContentInfo is a SEQUENCE that opens
# with its content type; 12.1 and [RFC 5083] 2.1 give the arcs), as tag 06, length, content.
OID_SIGNED_DATA = "06092a864886f70d010702"  # 1.2.840.113549.1.7.2
OID_ENVELOPED_DATA = "06092a864886f70d010703"  # 1.2.840.113549.1.7.3
OID_AUTH_ENVELOPED_DATA = "060b2a864886f70d0109100117"  # 1.2.840.113549.1.9.16.1.23


@dataclass
class Recipient:
    name: str
    address: str
    kind: int = 1  # 1 To, 2 Cc, 3 Bcc
    address_type: str = "SMTP"


@dataclass
class Attachment:
    name: str
    data: bytes
    mime: str | None = None
    hidden: bool = False
    flags: int = 0
    content_id: str | None = None
    method: int = 1  # 1 by value; 2-4, 7 a link; 5 an embedded message; 6 an OLE object


@dataclass
class Embedded:
    message: Message
    size: int = 0  # PidTagAttachSize as the attachment states it (0: not written)


@dataclass
class Message:
    subject: str = ""
    sender_name: str = ""
    sender_smtp: str = ""
    sender_email: str = ""
    sender_type: str = "SMTP"
    recipients: list[Recipient] = field(default_factory=list)
    body: str | None = None
    html: bytes | None = None
    rtf: bytes | None = None
    submit_time: datetime | None = None
    transport_headers: str | None = None
    message_class: str = "IPM.Note"
    attachments: list[Attachment | Embedded] = field(default_factory=list)
    unicode: bool = True  # strings are UTF-16 (001F); otherwise 8-bit in the code page (001E)
    codepage: int | None = None
    display_to: str | None = None
    display_cc: str | None = None
    # Properties written as given, by full tag (id << 16 | type): a fixed-size type is held in the
    # property stream (8 bytes, padded), any other in a stream of its own.
    extra: dict[int, bytes] = field(default_factory=dict)


def cms(oid: str, *, before: int = 0, after: int = 100) -> bytes:
    """The start of an S/MIME attachment (``smime.p7m``): a BER SEQUENCE of indefinite length, the
    content-type ``oid`` (hex, one of ``OID_*``) ``before`` filler bytes in, then ``after`` more."""

    return bytes.fromhex("3080") + bytes(before) + bytes.fromhex(oid) + bytes.fromhex("a080") + bytes(after)


def filetime(moment: datetime) -> int:
    delta = moment - FILETIME_EPOCH
    return (delta.days * 86_400 + delta.seconds) * 10_000_000 + delta.microseconds * 10


class _Storage:
    """The properties of one storage: its property stream entries and its ``__substg1.0_`` streams."""

    def __init__(self, unicode: bool, codepage: int | None) -> None:
        self.unicode = unicode
        self.codepage = codepage
        self.entries: list[bytes] = []
        self.streams: Tree = {}

    def fixed(self, prop: int, kind: int, value: bytes) -> None:
        self.entries.append(struct.pack("<II", (prop << 16) | kind, FLAGS) + value.ljust(8, b"\x00"))

    def long(self, prop: int, value: int) -> None:
        self.fixed(prop, PT_LONG, struct.pack("<i", value))

    def boolean(self, prop: int, value: bool) -> None:
        self.fixed(prop, PT_BOOLEAN, b"\x01" if value else b"\x00")

    def systime(self, prop: int, value: int) -> None:
        self.fixed(prop, PT_SYSTIME, struct.pack("<Q", value))

    def variable(self, tag: int, content: bytes) -> None:
        """A string or binary property: an entry with its size, and the stream that holds it."""

        self.entries.append(struct.pack("<IIII", tag, FLAGS, len(content), 0))
        self.streams[f"__substg1.0_{tag:08X}"] = content

    def binary(self, prop: int, content: bytes) -> None:
        self.variable((prop << 16) | PT_BINARY, content)

    def string(self, prop: int, text: str | None) -> None:
        if text is None:
            return
        if self.unicode:
            self.variable((prop << 16) | PT_UNICODE, text.encode("utf-16-le") + b"\x00\x00")
        else:
            self.variable((prop << 16) | PT_STRING8, _encode8(text, self.codepage) + b"\x00")

    def raw(self, tag: int, content: bytes) -> None:
        if tag & 0xFFFF in FIXED_TYPES:
            self.fixed(tag >> 16, tag & 0xFFFF, content)
        else:
            self.variable(tag, content)

    def stream(self, header: int, counts: tuple[int, int] = (0, 0)) -> bytes:
        """The property stream: its header (recipient and attachment counts where the format has
        them), then the entries."""

        recipients, attachments = counts
        if header == TOP_HEADER:  # 8 reserved, next recipient id, next attachment id, counts, 8 reserved
            head = bytes(8) + struct.pack("<IIII", recipients, attachments, recipients, attachments) + bytes(8)
        elif header == EMBEDDED_HEADER:
            head = bytes(8) + struct.pack("<IIII", recipients, attachments, recipients, attachments)
        else:
            head = bytes(header)
        return head + b"".join(self.entries)


def _encode8(text: str, codepage: int | None) -> bytes:
    try:
        return text.encode(f"cp{codepage}" if codepage else "cp1252", errors="replace")
    except LookupError:  # an unknown code page: Outlook's, and the reader's, default
        return text.encode("cp1252", errors="replace")


def _recipient_tree(recipient: Recipient, message: Message) -> Tree:
    storage = _Storage(message.unicode, message.codepage)
    storage.long(0x0C15, recipient.kind)
    if recipient.name:
        storage.string(0x3001, recipient.name)
    if recipient.address_type == "SMTP":
        storage.string(0x39FE, recipient.address)
    storage.string(0x3003, recipient.address)
    storage.string(0x3002, recipient.address_type)
    return {PROPERTIES: storage.stream(CHILD_HEADER), **storage.streams}


def _attachment_tree(attachment: Attachment | Embedded, message: Message) -> Tree:
    storage = _Storage(message.unicode, message.codepage)
    if isinstance(attachment, Embedded):
        storage.long(0x3705, METHOD_EMBEDDED_MESSAGE)
        storage.string(0x3001, attachment.message.subject)
        if attachment.size:
            storage.long(0x0E20, attachment.size)
        storage.entries.append(struct.pack("<IIII", (0x3701 << 16) | PT_OBJECT, FLAGS, 0xFFFFFFFF, 0))
        return {PROPERTIES: storage.stream(CHILD_HEADER), **storage.streams,
                "__substg1.0_3701000D": _message_tree(attachment.message, EMBEDDED_HEADER)}
    storage.long(0x3705, attachment.method)
    if attachment.name:
        storage.string(0x3707, attachment.name)
        storage.string(0x3704, attachment.name)
        storage.string(0x3001, attachment.name)
    if attachment.mime:
        storage.string(0x370E, attachment.mime)
    if attachment.content_id:
        storage.string(0x3712, attachment.content_id)
    if attachment.flags:
        storage.long(0x3714, attachment.flags)
    if attachment.hidden:
        storage.boolean(0x7FFE, True)
    storage.long(0x0E20, len(attachment.data))
    if attachment.method == METHOD_BY_VALUE:
        storage.binary(0x3701, attachment.data)
    return {PROPERTIES: storage.stream(CHILD_HEADER), **storage.streams}


def _message_tree(message: Message, header: int) -> Tree:
    storage = _Storage(message.unicode, message.codepage)
    if message.codepage is not None:
        storage.long(0x3FFD, message.codepage)
    storage.string(0x001A, message.message_class)
    if message.subject:
        storage.string(0x0037, message.subject)
    for prop, text in ((0x0C1A, message.sender_name), (0x5D01, message.sender_smtp),
                       (0x0C1F, message.sender_email), (0x0C1E, message.sender_type if message.sender_email else "")):
        if text:
            storage.string(prop, text)
    if message.submit_time is not None:
        storage.systime(0x0039, filetime(message.submit_time))
    for prop, text in ((0x007D, message.transport_headers), (0x0E04, message.display_to),
                       (0x0E03, message.display_cc), (0x1000, message.body)):
        storage.string(prop, text)
    if message.html is not None:
        storage.binary(0x1013, message.html)
    if message.rtf is not None:
        storage.binary(0x1009, message.rtf)
    for tag, content in message.extra.items():
        storage.raw(tag, content)

    tree: Tree = dict(storage.streams)
    for number, recipient in enumerate(message.recipients):
        tree[f"__recip_version1.0_#{number:08X}"] = _recipient_tree(recipient, message)
    for number, attachment in enumerate(message.attachments):
        tree[f"__attach_version1.0_#{number:08X}"] = _attachment_tree(attachment, message)
    tree[PROPERTIES] = storage.stream(header, (len(message.recipients), len(message.attachments)))
    return tree


def msg_tree(message: Message) -> Tree:
    """The storages and streams of a top-level message, as ``ole_tree`` takes them."""

    return _message_tree(message, TOP_HEADER)


def msg_bytes(message: Message, *, sector_shift: int = 9, **ole_options: object) -> bytes:
    """The message as a compound file. ``ole_options`` are ``ole_tree``'s hostile shapes (``dag``,
    ``loop``, ``share``, ``mini_loop``); paths in them are the tree's, ``/``-joined."""

    return ole_tree(msg_tree(message), sector_shift=sector_shift, **ole_options)  # type: ignore[arg-type]
