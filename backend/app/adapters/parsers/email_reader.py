"""An email (.eml: RFC 822 / MIME) read into plain data.

``read_eml`` turns a message's bytes into an ``EmailPackage``: its headers, its message
text, the messages forwarded inside it and its attachments. It does no I/O and stores
nothing. The email parser renders a package as lines; the attachments are kept (with
their original bytes) so that a later step can add them as evidence of their own.

Nothing is fetched or run, and the work is bounded:

- the message text is the plain-text body, else the HTML body turned into text here
  (scripts, styles and the head dropped, table cells tab-separated; no image, link or
  stylesheet is ever loaded);
- forwarded messages are read ``MAX_DEPTH`` levels deep and at most ``MAX_PARTS`` MIME
  parts are walked in the whole email; a body is cut at ``MAX_BODY_CHARS``;
- an unknown character set falls back to UTF-8 with replacement characters;
- S/MIME and PGP signatures are skipped; winmail.dat (Outlook rich text) is listed, not read.
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass, field
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import cast

MAX_DEPTH = 3  # forwarded messages read inside one another
MAX_PARTS = 200  # MIME parts walked in the whole email
MAX_BODY_CHARS = 2_000_000  # per message text, before and after HTML becomes text
MAX_NAME_CHARS = 120
MAX_HEADER_CHARS = 64 * 1024  # a longer header is not parsed
SHOWN_HEADER_CHARS = 1_000

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SIGNATURE_TYPES = {"application/pkcs7-signature", "application/x-pkcs7-signature", "application/pgp-signature"}
_TNEF_TYPES = {"application/ms-tnef", "application/vnd.ms-tnef"}


class EmailError(ValueError):
    """The file cannot be read as an email; ``code`` is the parser warning code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EmailPart:
    """An attachment, with its original bytes."""

    name: str
    content_type: str
    data: bytes
    inline: bool = False  # shown in the message body (a logo, a signature image)
    content_id: str | None = None
    path: list[str] = field(default_factory=list)  # the forwarded messages it sits in, outermost first
    note: str | None = None  # why it could not be read even as an attachment

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class EmailPackage:
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    sent_at: str = ""
    message_id: str = ""
    body_text: str = ""
    body_source: str = "none"  # plain | html | none
    attachments: list[EmailPart] = field(default_factory=list)
    nested: list[EmailPackage] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)  # (warning code, sentence)

    def all_attachments(self) -> list[EmailPart]:
        """This message's attachments, then those of the messages forwarded in it."""

        return [*self.attachments, *(part for nested in self.nested for part in nested.all_attachments())]

    def all_notes(self) -> list[tuple[str, str]]:
        return [*self.notes, *(note for nested in self.nested for note in nested.all_notes())]


class _Walk:
    """What is left of the walk's budget, shared by every level of the email."""

    def __init__(self) -> None:
        self.parts = 0
        self.stopped = False

    def take(self) -> bool:
        self.parts += 1
        if self.parts > MAX_PARTS:
            self.stopped = True
        return not self.stopped


def read_eml(data: bytes) -> EmailPackage:
    """Read an RFC 822 message. Raises ``EmailError`` when the bytes are not an email."""

    if data.startswith(OLE_SIGNATURE):
        raise EmailError(
            "not_an_eml",
            "This file is an Outlook message (.msg), which can't be read here yet. "
            "Upload its attachments on their own instead.",
        )
    last_error: Exception | None = None
    # The modern policy decodes headers and character sets; the legacy one is the fallback
    # for a message the modern one trips over.
    for parse_policy in (policy.default, policy.compat32):
        try:
            message = cast(EmailMessage, BytesParser(_class=EmailMessage, policy=parse_policy).parsebytes(data))
            if not message.keys():
                raise EmailError("not_an_email", "This file is not an email: it has no headers (From, To, Subject).")
            walk = _Walk()
            package = _package(message, depth=0, walk=walk, path=[])
            if walk.stopped:
                package.notes.append(("email_parts_limit", f"The email has more than {MAX_PARTS} parts; "
                                                           "only the first ones were read."))
            return package
        except EmailError:
            raise
        except RecursionError as exc:
            raise EmailError("email_load_failed", "The email is nested too deeply to read.") from exc
        except Exception as exc:  # noqa: BLE001 - a malformed message; try the lenient policy
            last_error = exc
    raise EmailError("email_load_failed", f"The email could not be read: {type(last_error).__name__}.")


def _package(message: EmailMessage, *, depth: int, walk: _Walk, path: list[str]) -> EmailPackage:
    package = EmailPackage(
        subject=_header(message, "Subject"),
        sender=_header(message, "From"),
        to=_header(message, "To"),
        cc=_header(message, "Cc"),
        sent_at=_header(message, "Date"),
        message_id=_header(message, "Message-ID"),
    )
    body = _find_body(message)
    if body is not None:
        package.body_text, package.body_source = _body_text(body, package)
    _collect(message, package, body=body, depth=depth, walk=walk, path=path, in_alternative=False)
    return package


def _header(message: Message, name: str) -> str:
    """A header as one line of text, RFC 2047 words decoded. A header too long to be a real
    one is shown as it is rather than parsed."""

    raw = next((value for key, value in message.raw_items() if key.lower() == name.lower()), None)
    if raw is None:
        return ""
    text = str(raw)
    if len(text) <= MAX_HEADER_CHARS:
        try:
            text = str(message.get(name))
        except Exception:  # noqa: BLE001 - a header the modern policy cannot parse: keep its raw text
            pass
        if "=?" in text:  # words left encoded (the legacy policy, or a header the parser gave up on)
            text = _header_text(text)
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return text if len(text) <= SHOWN_HEADER_CHARS else text[:SHOWN_HEADER_CHARS] + "…"


def _find_body(message: EmailMessage) -> EmailMessage | None:
    try:
        body = message.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001 - a structure get_body trips over: no body
        return None
    return body if isinstance(body, EmailMessage) else None


def _body_text(part: EmailMessage, package: EmailPackage) -> tuple[str, str]:
    text = _decoded_text(part)
    html = part.get_content_subtype() == "html"
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS]
        package.notes.append(("body_truncated", "The message text is very long; only its beginning was read."))
    if html:
        text = html_to_text(text)[:MAX_BODY_CHARS]
    return _tidy(text), "html" if html else "plain"


def _decoded_text(part: Message) -> str:
    """A text part's content as text. An unknown character set is read as UTF-8, with
    replacement characters for what does not decode."""

    try:
        content = part.get_content()  # type: ignore[attr-defined]
        if isinstance(content, str):
            return content
    except Exception:  # noqa: BLE001 - LookupError (unknown charset), the legacy policy, a bad encoding
        pass
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def _collect(part: EmailMessage, package: EmailPackage, *, body: EmailMessage | None, depth: int, walk: _Walk,
             path: list[str], in_alternative: bool) -> None:
    """Walk the MIME tree for attachments, forwarded messages and any further message text."""

    if part is body or not walk.take():
        return
    content_type = part.get_content_type()

    if content_type == "message/rfc822":
        inner = _attached_message(part)
        if inner is not None:
            _forwarded(inner, package, depth=depth, walk=walk, path=path)
        return

    if part.is_multipart():
        alternative = content_type == "multipart/alternative"
        if alternative and not in_alternative and not _holds(part, body):
            # Another alternative group (Apple Mail splits a body around inline images):
            # its preferred version is more message text. (Groups inside a group are
            # alternatives themselves, so each part is searched at most once.)
            more = _find_body(part)
            if more is not None:
                _append_text(package, _body_text(more, package)[0])
        for sub in part.iter_parts():
            _collect(sub, package, body=body, depth=depth, walk=walk, path=path,  # type: ignore[arg-type]
                     in_alternative=in_alternative or alternative)
        return

    disposition = part.get_content_disposition()
    filename = _filename(part)
    if content_type in _SIGNATURE_TYPES or (filename or "").lower() == "smime.p7s":
        return
    if part.get_content_maintype() == "text" and not filename and disposition != "attachment":
        if not in_alternative:  # more message text after an inline image or a list footer
            _append_text(package, _body_text(part, package)[0])
        return

    data = part.get_payload(decode=True)
    data = data if isinstance(data, bytes) else b""
    if (filename or "").lower().endswith(".eml"):  # a forwarded message attached as a file
        try:
            inner = BytesParser(_class=EmailMessage, policy=policy.default).parsebytes(data)
        except Exception:  # noqa: BLE001 - keep it as a plain attachment
            inner = None
        if inner is not None and inner.keys():
            _forwarded(inner, package, depth=depth, walk=walk, path=path)
            return

    note = None
    if content_type in _TNEF_TYPES or (filename or "").lower() == "winmail.dat":
        note = "Outlook rich-text attachment (winmail.dat); its contents can't be read here"
    content_id = part.get("Content-ID")
    package.attachments.append(EmailPart(
        name=_safe_name(filename, content_type, len(package.attachments) + 1),
        content_type=content_type,
        data=data,
        inline=disposition == "inline" or (disposition is None and content_id is not None),
        content_id=str(content_id).strip("<> ") if content_id else None,
        path=list(path),
        note=note,
    ))


def _forwarded(inner: EmailMessage, package: EmailPackage, *, depth: int, walk: _Walk, path: list[str]) -> None:
    subject = _header(inner, "Subject") or "Forwarded message"
    if depth + 1 > MAX_DEPTH:
        package.notes.append(("forwarded_too_deep", f"A message forwarded more than {MAX_DEPTH} levels deep "
                                                    f"(\"{subject}\") was not read."))
        return
    package.nested.append(_package(inner, depth=depth + 1, walk=walk, path=[*path, subject]))


def _attached_message(part: EmailMessage) -> EmailMessage | None:
    payload = part.get_payload()
    if isinstance(payload, list) and payload and isinstance(payload[0], EmailMessage):
        return payload[0]
    if isinstance(payload, EmailMessage):
        return payload
    return None


def _holds(container: EmailMessage, body: EmailMessage | None) -> bool:
    if body is None:
        return False
    for count, sub in enumerate(container.walk()):
        if sub is body:
            return True
        if count >= MAX_PARTS:
            return False
    return False


def _append_text(package: EmailPackage, text: str) -> None:
    if text.strip():
        package.body_text = f"{package.body_text}\n\n{text}" if package.body_text else text
        if package.body_source == "none":
            package.body_source = "plain"


def _filename(part: Message) -> str | None:
    try:
        name = part.get_filename()
    except Exception:  # noqa: BLE001 - a malformed RFC 2231 name
        return None
    return _header_text(name) if name else None


def _header_text(text: str) -> str:
    if "=?" in text:
        try:
            return str(make_header(decode_header(text)))
        except Exception:  # noqa: BLE001
            return text
    return text


def _safe_name(raw: str | None, content_type: str, index: int) -> str:
    """The attachment's own name, as a short file name: no folders, no control characters."""

    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip().strip(".")
    if not name:
        name = f"attachment-{index}{mimetypes.guess_extension(content_type) or ''}"
    if len(name) > MAX_NAME_CHARS:
        stem, dot, extension = name.rpartition(".")
        if dot and 0 < len(extension) <= 10:
            name = f"{stem[:MAX_NAME_CHARS - len(extension) - 1]}.{extension}"
        else:
            name = name[:MAX_NAME_CHARS]
    return name


class _HtmlText(HTMLParser):
    """HTML as text: block elements end lines, table cells are separated by tabs, and
    nothing outside the visible text is kept."""

    _SKIP = {"script", "style", "head", "title", "noscript", "template", "svg"}
    _BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
              "blockquote", "pre", "section", "article", "header", "footer", "address", "dd", "dt", "dl"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.skip = 0  # an unclosed <head> or <title> ends here
        if tag in self._SKIP:
            self.skip += 1
        elif tag in ("td", "th"):
            self.out.append("\t")
        elif tag in self._BLOCK:
            self.out.append("\n")
        if tag == "pre":
            self.pre += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self._BLOCK:
            self.out.append("\n")
        if tag == "pre":
            self.pre = max(0, self.pre - 1)

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self.out.append(data if self.pre else re.sub(r"[ \t\r\n\f\v]+", " ", data))


def html_to_text(html: str) -> str:
    """The visible text of an HTML body, one line per block and tab-separated table cells."""

    # What comes before <body> is never shown. Starting there also keeps an unclosed <title>
    # from hiding the whole message (newer Pythons read a title's text up to its end tag).
    body = re.search(r"<body[\s>/]", html, flags=re.IGNORECASE)
    parser = _HtmlText()
    try:
        parser.feed(html[body.start():] if body else html)
        parser.close()
    except Exception:  # noqa: BLE001 - html.parser is lenient; keep what was read
        pass
    lines = []
    for line in "".join(parser.out).replace("\xa0", " ").split("\n"):
        cells = [" ".join(cell.split()) for cell in line.split("\t")]
        lines.append("\t".join(cell for cell in cells if cell))
    return "\n".join(line for line in lines if line)
