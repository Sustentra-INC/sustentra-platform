"""An Outlook message (.msg: an OLE2 compound file, [MS-OXMSG]) read into the same
``EmailPackage`` as an .eml, so the email parser renders both alike.

``read_msg`` does no I/O and stores nothing. Every byte comes through ``OleFile``, which claims
each sector it reads, so a crafted container (streams that share sectors, chains that loop,
directories that share children) cannot make the work outgrow the file. On top of that:

- A property stream is read for at most ``MAX_MSG_PROPERTIES`` entries; recipients, for at most
  ``MAX_RECIPIENTS``; the transport headers are scanned for ``Date:`` over their first
  ``MAX_TRANSPORT_HEADER_CHARS`` characters. A header property is decoded for at most
  ``SHOWN_HEADER_CHARS * 8`` characters, a body for what the shared ``_Walk`` still allows (the
  same budgets, caps and notes as the .eml reader: parts, depth, message text, HTML, lines).
- Strings are cut as bytes before they are decoded. 8-bit text uses the message's code page
  (``codepage_codec``: an unknown or denied one reads as Windows-1252).
- Attachments are listed with their bytes (``attach_method`` 1) or without them (a link to a
  file, an embedded object). An embedded message (method 5) is read as a nested package, to
  ``MAX_DEPTH`` levels; a deeper one is named in a note and never opened. Nothing is run.
- ``read_msg`` raises ``EmailError`` and nothing else. A container ``OleFile`` refuses (or a
  stream it cannot read) is ``email_load_failed``, raised without a cause; only a failure this
  reader did not foresee carries one (``__cause__``), which the fuzz tests treat as a bug.

Read order. When two streams of a damaged file share sectors, the first one read keeps them
and the second is refused, so the order decides which. Here it is fixed, and any refusal makes
the whole message ``email_load_failed``, so the answer for a file is the same whichever stream
is the one refused:

1. the top-level property stream, always first (it is under 4,096 bytes in every ordinary
   message, so it also makes ``OleFile`` claim the mini stream, the container of the small
   streams, before any other stream; the reader does not reach into ``OleFile`` to do that
   earlier, as a large property stream gains nothing from it);
2. the subject; the sender; the recipients in storage-name order (each one's property stream,
   then its strings), or the display To and Cc when there are none; the transport headers or the
   times (Sent); the message id;
3. the plain body, then the HTML body only when the plain one is blank;
4. the attachments in storage-name order: each one's property stream, its names, then its data
   (an embedded message is read there, in the same order, one level down).

A stream that is never read (the HTML body of a message with a plain one, a Bcc recipient's
strings, anything past a cap) claims nothing, so sharing sectors with it is not noticed.
"""

from __future__ import annotations

import mimetypes
import re
import struct
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from backend.app.adapters.parsers.email_reader import (
    DAMAGED_EMAIL,
    MAX_BODY_CHARS,
    MAX_DEPTH,
    SHOWN_HEADER_CHARS,
    EmailError,
    EmailPackage,
    EmailPart,
    _closing_notes,
    _safe_name,
    _tidy,
    _Walk,
    _within_text_budget,
    codepage_codec,
    header_text,
    html_to_text,
    mailbox,
    too_deep_note,
)
from backend.app.adapters.parsers.ole import STORAGE, STREAM, OleEntry, OleError, OleFile

MAX_MSG_PROPERTIES = 4_096  # entries read from one property stream
MAX_RECIPIENTS = 500  # recipient storages read from one message
MAX_TRANSPORT_HEADER_CHARS = 65_536  # characters of the transport headers scanned for Date:
NOT_AN_OUTLOOK_MESSAGE = ("This file is not an Outlook message. Ask the client to forward the email again, or upload "
                          "its attachments on their own.")

_HEADER_CHARS = SHOWN_HEADER_CHARS * 8  # decoded from any header property
_NAME_CHARS = 4_096  # decoded from a file name
_ENTRY = 16  # [MS-OXMSG] 2.4.2: a property entry is a tag, flags and 8 value bytes
_TOP_HEADER, _EMBEDDED_HEADER, _CHILD_HEADER = 32, 24, 8  # [MS-OXMSG] 2.4: property stream header sizes
_PROPERTIES = "__properties_version1.0"
_RECIPIENT, _ATTACHMENT = "__RECIP_VERSION1.0_#", "__ATTACH_VERSION1.0_#"  # upper case: OleFile compares so
_EMBEDDED_MESSAGE = "__substg1.0_3701000D"  # [MS-OXMSG] 2.2.2.1: the storage of an embedded message
_UNICODE, _STRING8, _BINARY = "001F", "001E", "0102"  # [MS-OXPROPS] property types in a stream's name
_LONG, _BOOLEAN, _SYSTIME = 0x0003, 0x000B, 0x0040  # fixed-size types, held in the property stream itself

# [MS-OXPROPS] property ids
_SUBJECT, _TRANSPORT_HEADERS, _MESSAGE_ID = 0x0037, 0x007D, 0x1035
_SUBMIT_TIME, _DELIVERY_TIME = 0x0039, 0x0E06
_SENDER_NAME, _SENDER_SMTP, _SENDER_ADDRESS, _SENDER_TYPE = 0x0C1A, 0x5D01, 0x0C1F, 0x0C1E
_REPRESENTING_NAME, _REPRESENTING_SMTP = 0x0042, 0x5D02
_DISPLAY_TO, _DISPLAY_CC, _BODY, _HTML = 0x0E04, 0x0E03, 0x1000, 0x1013
_MESSAGE_CODEPAGE, _INTERNET_CODEPAGE = 0x3FFD, 0x3FDE
_RECIPIENT_TYPE, _DISPLAY_NAME, _RECIPIENT_SMTP, _EMAIL_ADDRESS, _ADDRESS_TYPE = 0x0C15, 0x3001, 0x39FE, 0x3003, 0x3002
_ATTACH_METHOD, _ATTACH_DATA, _LONG_FILENAME, _FILENAME = 0x3705, 0x3701, 0x3707, 0x3704
_MIME_TAG, _CONTENT_ID, _ATTACH_FLAGS, _HIDDEN, _ATTACH_SIZE = 0x370E, 0x3712, 0x3714, 0x7FFE, 0x0E20
_RENDERED_IN_BODY = 0x4  # [MS-OXCMSG] 2.2.2.9: attach flags, the attachment is referenced by the HTML body

# The fixed-size properties the reader uses; every other entry is passed over.
_FIXED = frozenset(
    (prop << 16) | kind for prop, kind in (
        (_MESSAGE_CODEPAGE, _LONG), (_INTERNET_CODEPAGE, _LONG), (_SUBMIT_TIME, _SYSTIME),
        (_DELIVERY_TIME, _SYSTIME), (_RECIPIENT_TYPE, _LONG), (_ATTACH_METHOD, _LONG), (_ATTACH_FLAGS, _LONG),
        (_HIDDEN, _BOOLEAN), (_ATTACH_SIZE, _LONG)))

_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)  # [MS-DTYP] 2.3.3: a FILETIME counts 100 ns from here
_LINE_END = re.compile(r"\r\n|\r|\n")
_MIME_TYPE = re.compile(r"[a-z0-9!#$&^_.+-]{1,127}/[a-z0-9!#$&^_.+-]{1,127}")


def read_msg(data: bytes) -> EmailPackage:
    """Read an Outlook message. Raises ``EmailError``: ``not_an_email`` for a compound file that
    is not a message, ``email_load_failed`` for a damaged or crafted one."""

    try:
        return _read(data)
    except EmailError:
        raise
    except OleError:  # the container, or a stream in it, is damaged: refused on purpose
        raise EmailError("email_load_failed", DAMAGED_EMAIL) from None
    except Exception as exc:  # noqa: BLE001 - anything this reader did not foresee, RecursionError included
        raise EmailError("email_load_failed", DAMAGED_EMAIL) from exc


def _read(data: bytes) -> EmailPackage:
    ole = OleFile(data)
    root = ole.directory.root
    if root is None:
        raise OleError("The directory has no root entry.")
    stream = ole.child(root, _PROPERTIES)
    if stream is None or stream.kind != STREAM:
        raise EmailError("not_an_email", NOT_AN_OUTLOOK_MESSAGE)
    walk = _Walk()
    props = _Props(ole, root, _TOP_HEADER)
    package = _message(ole, root, props, props.header(_SUBJECT), depth=0, walk=walk, path=[])
    _closing_notes(package, walk)
    return package


class _Props:
    """The properties of one storage (a message, a recipient or an attachment): the fixed-size
    ones from its property stream, the strings and binaries from their own streams."""

    def __init__(self, ole: OleFile, storage: OleEntry, header: int, codec: str | None = None) -> None:
        self.ole = ole
        self.storage = storage
        self.fixed: dict[int, bytes] = {}
        stream = ole.child(storage, _PROPERTIES)
        self.has_properties = stream is not None and stream.kind == STREAM
        if stream is not None and self.has_properties:
            entries = ole.read(stream)[header:header + MAX_MSG_PROPERTIES * _ENTRY]
            for tag, _flags, value in struct.iter_unpack("<II8s", entries[:len(entries) // _ENTRY * _ENTRY]):
                if tag in _FIXED:
                    self.fixed.setdefault(tag, value)
        # A recipient or an attachment reads its 8-bit text with the code page of its message.
        self.codec = codec if codec is not None else codepage_codec(
            self.number(_MESSAGE_CODEPAGE) or self.number(_INTERNET_CODEPAGE))

    # --- fixed-size values ------------------------------------------------------------------
    def number(self, prop: int) -> int | None:
        value = self.fixed.get((prop << 16) | _LONG)
        return None if value is None else int(struct.unpack("<i", value[:4])[0])

    def flag(self, prop: int) -> bool:
        return any(self.fixed.get((prop << 16) | _BOOLEAN, b"")[:2])

    def filetime(self, prop: int) -> int | None:
        value = self.fixed.get((prop << 16) | _SYSTIME)
        return None if value is None else int(struct.unpack("<Q", value)[0])

    # --- strings and binaries ---------------------------------------------------------------
    def stream(self, prop: int, kind: str) -> bytes | None:
        entry = self.ole.child(self.storage, f"__substg1.0_{prop:04X}{kind}")
        return self.ole.read(entry) if entry is not None and entry.kind == STREAM else None

    def string(self, prop: int, limit: int) -> tuple[str, bool] | None:
        """A string property (UTF-16 before 8-bit) cut to ``limit`` characters, and whether it was cut."""

        raw = self.stream(prop, _UNICODE)
        if raw is not None:
            return _decode(raw, "utf-16-le", limit)
        raw = self.stream(prop, _STRING8)
        return None if raw is None else _decode(raw, self.codec, limit)

    def text(self, prop: int, limit: int = _HEADER_CHARS) -> str:
        found = self.string(prop, limit)
        return "" if found is None else found[0]

    def header(self, prop: int) -> str:
        return header_text(self.text(prop))


def _decode(raw: bytes, codec: str, limit: int) -> tuple[str, bool]:
    """At most ``limit`` characters of ``raw``: cut as bytes first (2 per UTF-16 character, up to
    4 per character otherwise), trailing NULs dropped. Never raises."""

    width = 2 if codec == "utf-16-le" else 4
    piece = raw[:limit * width]
    if width == 2:
        piece = piece[:len(piece) // 2 * 2]
    text = piece.decode(codec, errors="replace").rstrip("\x00")
    cut = len(raw) > limit * width
    if len(text) > limit:
        text, cut = text[:limit], True
    return text, cut


# --- the message --------------------------------------------------------------------------------
def _message(ole: OleFile, storage: OleEntry, props: _Props, subject: str, *, depth: int, walk: _Walk,
             path: list[str]) -> EmailPackage:
    sender = _sender(props)
    to, cc = _recipients(ole, storage, props)
    package = EmailPackage(
        subject=subject, sender=sender, to=to, cc=cc, sent_at=_sent(props), message_id=props.header(_MESSAGE_ID))
    package.body_text, package.body_source = _body(props, walk)
    _attachments(ole, storage, props, package, depth=depth, walk=walk, path=path)
    return package


def _sender(props: _Props) -> str:
    name = props.text(_SENDER_NAME) or props.text(_REPRESENTING_NAME)
    address = props.text(_SENDER_SMTP)
    if not address and props.text(_SENDER_TYPE).strip().upper() == "SMTP":
        address = props.text(_SENDER_ADDRESS)  # an Exchange (EX) address is not shown
    return header_text(mailbox(name, address or props.text(_REPRESENTING_SMTP)))


def _recipients(ole: OleFile, storage: OleEntry, props: _Props) -> tuple[str, str]:
    stored = [entry for entry in ole.children(storage)
              if entry.kind == STORAGE and entry.name.upper().startswith(_RECIPIENT)]
    if not stored:  # the display lists: names separated by ";", no addresses
        return _display_list(props, _DISPLAY_TO), _display_list(props, _DISPLAY_CC)
    lines: dict[int, list[str]] = {1: [], 2: []}  # To, Cc; a Bcc recipient is not shown
    size = {1: 0, 2: 0}
    for entry in stored[:MAX_RECIPIENTS]:
        recipient = _Props(ole, entry, _CHILD_HEADER, props.codec)
        kind = recipient.number(_RECIPIENT_TYPE)
        kind = 1 if kind is None else kind
        if kind not in lines or size[kind] > _HEADER_CHARS:  # that line is full: its rest is not read
            continue
        address = recipient.text(_RECIPIENT_SMTP)
        if not address and recipient.text(_ADDRESS_TYPE).strip().upper() == "SMTP":
            address = recipient.text(_EMAIL_ADDRESS)
        shown = mailbox(recipient.text(_DISPLAY_NAME), address)
        if shown:
            lines[kind].append(shown)
            size[kind] += len(shown) + 2
    return header_text(", ".join(lines[1])[:_HEADER_CHARS]), header_text(", ".join(lines[2])[:_HEADER_CHARS])


def _display_list(props: _Props, prop: int) -> str:
    names = (name for name in props.text(prop).split(";") if name.strip())
    return header_text(", ".join(mailbox(name, "") for name in names))


def _sent(props: _Props) -> str:
    """The Date: header as sent, else the submit time, else the delivery time (in UTC)."""

    sent = _date_header(props.text(_TRANSPORT_HEADERS, MAX_TRANSPORT_HEADER_CHARS))
    if sent:
        return sent
    ticks = props.filetime(_SUBMIT_TIME)
    return _filetime(props.filetime(_DELIVERY_TIME) if ticks is None else ticks)


def _date_header(headers: str) -> str:
    """The value of the first ``Date:`` header, unfolded, up to the first blank line."""

    value: str | None = None
    for line in _LINE_END.split(headers):
        if not line:
            break
        if line[0] in " \t":  # a continuation of the header above
            if value is not None:
                value += line
            continue
        if value is not None:
            break
        name, colon, rest = line.partition(":")
        if colon and name.rstrip().lower() == "date":
            value = rest
    return "" if value is None else header_text(value)


def _filetime(ticks: int | None) -> str:
    if not ticks:  # unset
        return ""
    try:
        return format_datetime(_EPOCH + timedelta(microseconds=ticks // 10))
    except (OverflowError, ValueError):  # past the year 9999
        return ""


def _body(props: _Props, walk: _Walk) -> tuple[str, str]:
    """The plain body if it has text, else the HTML body as text, else nothing; read and cut as
    the .eml reader's ``_body_text`` does (what the email's budget still allows is decoded)."""

    plain = props.string(_BODY, max(0, min(MAX_BODY_CHARS, walk.text_chars_left)))
    if plain is not None and plain[0].strip():
        walk.text_cut = walk.text_cut or plain[1]
        return _within_text_budget(_tidy(plain[0]), walk), "plain"
    room = max(0, min(MAX_BODY_CHARS, walk.html_chars_left))
    html = props.stream(_HTML, _BINARY)
    if html is not None:  # bytes: the internet code page, else UTF-8
        internet = props.number(_INTERNET_CODEPAGE)
        found: tuple[str, bool] | None = _decode(html, "utf-8" if internet is None else codepage_codec(internet), room)
    else:
        found = props.string(_HTML, room)
    if found is None:
        return "", "none"
    text, cut = found
    walk.text_cut = walk.text_cut or cut
    walk.html_chars_left -= len(text)
    return _within_text_budget(_tidy(html_to_text(text)), walk), "html"


# --- attachments --------------------------------------------------------------------------------
def _attachments(ole: OleFile, storage: OleEntry, props: _Props, package: EmailPackage, *, depth: int,
                 walk: _Walk, path: list[str]) -> None:
    for entry in ole.children(storage):
        if entry.kind != STORAGE or not entry.name.upper().startswith(_ATTACHMENT):
            continue
        if not walk.take():
            return
        _attachment(ole, entry, props, package, depth=depth, walk=walk, path=path)


def _attachment(ole: OleFile, entry: OleEntry, message: _Props, package: EmailPackage, *, depth: int,
                walk: _Walk, path: list[str]) -> None:
    attach = _Props(ole, entry, _CHILD_HEADER, message.codec)
    method = attach.number(_ATTACH_METHOD)
    if method is None:  # no method stated: by value when it has data
        method = 1 if ole.child(entry, f"__substg1.0_{_ATTACH_DATA:04X}{_BINARY}") is not None else 0
    if method == 0:  # no attachment
        return
    if method == 5:
        _embedded(ole, entry, attach, package, depth=depth, walk=walk, path=path)
        return
    raw = attach.text(_LONG_FILENAME, _NAME_CHARS) or attach.text(_FILENAME, _NAME_CHARS) or attach.text(
        _DISPLAY_NAME, _NAME_CHARS)
    declared = attach.number(_ATTACH_SIZE)
    mime = header_text(attach.text(_MIME_TAG, 255)).lower()
    mime = mime if _MIME_TYPE.fullmatch(mime) else ""
    name = _safe_name(raw, mime or "application/octet-stream", len(package.attachments) + 1)
    content_type = mime or _guess_type(name)
    part = EmailPart(name=name, content_type=content_type, data=b"", path=list(path),
                     declared_size=declared if declared and declared > 0 else None)
    if method == 1:  # by value
        part.data = attach.stream(_ATTACH_DATA, _BINARY) or b""
        part.inline = attach.flag(_HIDDEN) or bool((attach.number(_ATTACH_FLAGS) or 0) & _RENDERED_IN_BODY)
        content_id = header_text(attach.text(_CONTENT_ID, 255)).strip("<> ")
        part.content_id = content_id or None
    elif method == 6:  # an OLE object
        part.note = "an embedded object; its contents can't be read here"
    else:  # 2, 3, 4 (by reference), 7 (a web link) and anything else: the file is somewhere else
        part.note = "a link to a file, not the file itself"
    package.attachments.append(part)


def _guess_type(name: str) -> str:
    try:
        return mimetypes.guess_type(name)[0] or "application/octet-stream"
    except ValueError:
        return "application/octet-stream"


def _embedded(ole: OleFile, entry: OleEntry, attach: _Props, package: EmailPackage, *, depth: int, walk: _Walk,
              path: list[str]) -> None:
    storage = ole.child(entry, _EMBEDDED_MESSAGE)
    inner = _Props(ole, storage, _EMBEDDED_HEADER) if storage is not None and storage.kind == STORAGE else None
    subject = "" if inner is None else inner.header(_SUBJECT)
    if storage is not None and inner is not None and inner.has_properties:
        label = subject or "Forwarded message"
        if depth + 1 > MAX_DEPTH:  # named, never opened
            package.notes.append(too_deep_note(label))
            return
        package.nested.append(
            _message(ole, storage, inner, subject, depth=depth + 1, walk=walk, path=[*path, label]))
        return
    title = " ".join(subject.replace("/", " ").replace("\\", " ").split()) or "message"
    declared = attach.number(_ATTACH_SIZE)
    package.attachments.append(EmailPart(
        name=_safe_name(f"{title}.msg", "application/vnd.ms-outlook", len(package.attachments) + 1),
        content_type="application/vnd.ms-outlook", data=b"", path=list(path),
        note="the forwarded message could not be read", declared_size=declared if declared and declared > 0 else None))
