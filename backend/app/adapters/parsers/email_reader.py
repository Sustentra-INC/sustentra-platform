"""An email (.eml: RFC 822 / MIME) read into plain data.

``read_eml`` turns a message's bytes into an ``EmailPackage``: its headers, its message
text, the messages forwarded inside it and its attachments. It does no I/O and stores
nothing. The email parser renders a package as lines; the attachments are kept (with
their original bytes) so that a later step can add them as evidence of their own.

Nothing is fetched or run, and a crafted file cannot make the work outgrow the file:

- The bytes are cut before the parser sees them so that it never builds more than
  ``MAX_PART_LINES`` MIME parts or ``MAX_LINES`` lines for the whole email (attached
  ``.eml`` files included). Forwarded messages are read ``MAX_DEPTH`` levels deep, and an
  attached ``.eml`` deeper than that is not even parsed.
- The structure is parsed with the legacy ``compat32`` policy, which keeps header values
  as text; the modern policy's structured header parser is quadratic on crafted headers.
  Every header is cut to ``MAX_HEADER_CHARS`` as it is read (MIME headers, whose
  parameters are parsed, to ``MAX_MIME_HEADER_CHARS`` and ``MAX_MIME_PARAMS``), and at
  most ``MAX_HEADERS`` are read. Display headers are decoded from that short raw text.
- Text is decoded with any stdlib text codec except the quadratic or non-text ones named in
  ``_DENY_CODECS`` (punycode, idna, the escape codecs); a denied or unknown charset, or a
  codec that is not a text encoding, is read as UTF-8 with replacement characters. At most
  ``MAX_BODY_CHARS`` of a body are decoded, at most ``MAX_HTML_CHARS``
  of HTML are turned into text, and the message text of the whole email (forwarded
  messages included) is cut at ``MAX_TEXT_CHARS`` and ``MAX_TEXT_LINES``.
- The message text is the plain-text body, else the HTML body turned into text here
  (scripts, styles and the head dropped, table cells tab-separated; no image, link or
  stylesheet is ever loaded).
- S/MIME and PGP signatures are skipped; winmail.dat (Outlook rich text) is listed, not
  read. An encrypted email (S/MIME enveloped data, PGP/MIME) is refused as
  ``password_protected``.
"""

from __future__ import annotations

import base64
import codecs
import mimetypes
import quopri
import re
from dataclasses import dataclass, field
from email._policybase import Compat32
from email.message import EmailMessage, Message
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import cast
from urllib.parse import unquote_to_bytes

MAX_DEPTH = 3  # forwarded messages read inside one another
MAX_PARTS = 200  # MIME parts walked in the whole email
MAX_PART_LINES = 1_000  # lines that could open a MIME part ("--..."), parsed in the whole email
MAX_LINES = 1_000_000  # lines parsed in the whole email (a 25 MB base64 attachment is about 330,000)
# The stdlib parser tests every line against the boundary of every enclosing multipart, so its
# cost is lines x nesting depth. Cap that product: a deeply nested email reads fewer lines.
MAX_LINE_DEPTH_PRODUCT = 4_000_000
MAX_HEADERS = 10_000  # headers parsed in the whole email
MAX_HEADER_CHARS = 8 * 1024  # a header is cut to this as it is read
MAX_MIME_HEADER_CHARS = 2 * 1024  # Content-* headers, whose parameters are parsed
MAX_MIME_PARAMS = 32
MAX_BODY_CHARS = 2_000_000  # decoded from one body
MAX_TEXT_CHARS = 1_000_000  # message text kept for the whole email
MAX_HTML_CHARS = 1_000_000  # HTML turned into text for the whole email (about 1 s at worst)
MAX_TEXT_LINES = 10_000
MAX_NAME_CHARS = 120
SHOWN_HEADER_CHARS = 1_000

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SIGNATURE_TYPES = {"application/pkcs7-signature", "application/x-pkcs7-signature", "application/pgp-signature"}
_PKCS7_MIME_TYPES = {"application/pkcs7-mime", "application/x-pkcs7-mime"}
_TNEF_TYPES = {"application/ms-tnef", "application/vnd.ms-tnef"}
# Character sets refused: not text at all, or quadratic. Everything else stdlib offers (every
# ISO-8859, Windows and DOS code page, the CJK codecs, tis-620, mac-*, utf-7, utf-8-sig, ...) is
# linear and kept; a codec that is not a str<->bytes text encoding raises at decode time and
# falls back to UTF-8 (see ``_decode_bytes``). punycode and idna are the only quadratic text codecs.
def _canonical(name: str) -> str | None:
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


_DENY_CODECS = frozenset(
    canonical
    for name in ("punycode", "idna", "unicode_escape", "raw_unicode_escape", "unicode_internal")
    if (canonical := _canonical(name)) is not None
)
# The CMS content-type OIDs (DER: 06 LEN <bytes>) that mark an S/MIME part as *encrypted*, not
# signed. enveloped-data 1.2.840.113549.1.7.3 and authEnveloped-data 1.2.840.113549.1.9.16.1.23.
_CMS_ENCRYPTED_OIDS = (
    bytes.fromhex("06092a864886f70d010703"),
    bytes.fromhex("060b2a864886f70d010910 0117".replace(" ", "")),
)
_PART_LINE = re.compile(rb"(?:\A|(?<=[\r\n]))--")  # every MIME delimiter line starts this way
_BOUNDARY = re.compile(rb"(?i)\bboundary\b[ \t]*\*?[0-9]*\*?[ \t]*=")  # a multipart boundary declaration
_SURROGATES = re.compile("[\udc80-\udcff]")  # raw 8-bit bytes the parser kept in a header
_ENCODED_WORD = re.compile(r"=\?([^?]{1,100})\?([bBqQ])\?([^?]{0,700})\?=")  # RFC 2047
# How str.splitlines() breaks lines (so our line count matches TextParser and the pane).
_LINE_BREAK = re.compile("\r\n|[\n\r\v\f\x1c\x1d\x1e\x85  ]")

NOT_AN_EML = ("This file is an Outlook message (.msg), which can't be read here yet. "
              "Upload its attachments on their own instead.")
ENCRYPTED_EMAIL = ("This email is encrypted. Ask the client to send it without encryption, or upload its "
                   "attachments on their own.")
DAMAGED_EMAIL = ("The email could not be read; it may be damaged. Ask the client to forward it again, or upload "
                 "its attachments on their own.")


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
    """What reading this email may still do, shared by every level of it."""

    def __init__(self) -> None:
        self.parts = 0
        self.stopped = False  # more parts than MAX_PARTS were found
        self.cut = False  # the bytes were cut before parsing
        self.lines_left = MAX_LINES
        self.part_lines_left = MAX_PART_LINES
        self.headers = 0
        self.text_chars_left = MAX_TEXT_CHARS
        self.html_chars_left = MAX_HTML_CHARS
        self.text_lines_left = MAX_TEXT_LINES
        self.text_cut = False

    def take(self) -> bool:
        self.parts += 1
        if self.parts > MAX_PARTS:
            self.stopped = True
        return not self.stopped


def read_eml(data: bytes) -> EmailPackage:
    """Read an RFC 822 message. Raises ``EmailError`` when the bytes are not an email, or
    are an encrypted one."""

    if data.startswith(OLE_SIGNATURE):
        raise EmailError("not_an_eml", NOT_AN_EML)
    walk = _Walk()
    try:
        message = _parse(data, walk)
        if not message.keys():
            raise EmailError("not_an_email", "This file is not an email: it has no headers (From, To, Subject).")
        if _is_encrypted(message):
            raise EmailError("password_protected", ENCRYPTED_EMAIL)
        package = _package(message, depth=0, walk=walk, path=[])
    except EmailError:
        raise
    except RecursionError as exc:
        raise EmailError("email_load_failed", DAMAGED_EMAIL) from exc
    except Exception as exc:  # noqa: BLE001 - a malformed message the parser or our walk trips over
        raise EmailError("email_load_failed", DAMAGED_EMAIL) from exc
    if walk.stopped:
        package.notes.append(("email_parts_limit", f"The email has more than {MAX_PARTS} parts; "
                                                   "only the first ones were read."))
    if walk.cut:
        package.notes.append(("email_truncated", "The email has too many lines or parts to read whole; "
                                                 "only its beginning was read."))
    if walk.text_cut:
        package.notes.append(("body_truncated", "The message text is very long; only its beginning was read."))
    return package


# --- parsing within bounds ---------------------------------------------------------------------
def _parse(data: bytes, walk: _Walk) -> EmailMessage:
    return cast(EmailMessage, BytesParser(_class=EmailMessage, policy=_policy(walk)).parsebytes(_bounded(data, walk)))


def _bounded(data: bytes, walk: _Walk) -> bytes:
    """``data`` cut before the line that would take the email over its budget of lines, or
    of lines that could open a MIME part, so the parser never builds more than that.

    The parser tests every line against the boundary of every enclosing multipart, so its
    cost is lines x depth. ``data`` declares about one boundary per nesting level, so the
    line budget for this slice is capped at ``MAX_LINE_DEPTH_PRODUCT / boundaries`` -- a
    deeply nested email is read for fewer lines, and the product stays bounded."""

    end = len(data)
    lines = data.count(b"\n") + data.count(b"\r") - data.count(b"\r\n")
    boundaries = len(_BOUNDARY.findall(data))
    line_budget = min(walk.lines_left, MAX_LINE_DEPTH_PRODUCT // max(1, boundaries))
    if lines > line_budget:
        end = _after_lines(data, line_budget)
        walk.cut = True
    walk.lines_left = max(0, walk.lines_left - lines)
    found = 0
    for match in _PART_LINE.finditer(data, 0, end):
        found += 1
        if found > walk.part_lines_left:
            end = match.start()
            walk.cut = True
            break
    walk.part_lines_left = max(0, walk.part_lines_left - found)
    return data[:end]


def _after_lines(data: bytes, count: int) -> int:
    """The offset just after the ``count``-th line ending."""

    def lines(end: int) -> int:
        return data.count(b"\n", 0, end) + data.count(b"\r", 0, end) - data.count(b"\r\n", 0, end)

    # The shortest prefix holding ``count`` line endings, by bisection: about 25 counting
    # passes in C over a 25 MB file, and no per-line objects (a counted regex kept ~200 MB
    # of state for a million lines).
    low, high = 0, len(data)
    while low < high:
        middle = (low + high) // 2
        if lines(middle) >= count:
            high = middle
        else:
            low = middle + 1
    if 0 < low < len(data) and data[low - 1:low + 1] == b"\r\n":
        low += 1  # a CRLF counts once its CR is in: keep the LF with it
    return low


def _policy(walk: _Walk) -> Compat32:
    """The legacy policy (header values stay text), with every header cut as it is read and
    the number of headers capped."""

    class _BoundedHeaders(Compat32):
        def header_source_parse(self, sourcelines: list[str]) -> tuple[str, str]:
            walk.headers += 1
            if walk.headers > MAX_HEADERS:
                raise EmailError("email_load_failed", DAMAGED_EMAIL)
            name, value = super().header_source_parse(sourcelines)
            if name.strip().lower().startswith("content-"):
                # Parameters are parsed (boundary, charset, filename): keep them short and few.
                value = ";".join(value[:MAX_MIME_HEADER_CHARS].split(";", MAX_MIME_PARAMS)[:MAX_MIME_PARAMS])
            return name, value[:MAX_HEADER_CHARS]

    return _BoundedHeaders()


def _is_encrypted(message: EmailMessage) -> bool:
    """True when an encrypted container appears anywhere in this message's own MIME tree,
    within the part budget: S/MIME enveloped-data or authEnveloped-data (by ``smime-type`` or
    by the CMS content-type OID in the first DER bytes), or PGP/MIME (``multipart/encrypted``).

    ``message.walk()`` descends into inline ``message/rfc822`` parts, so a forwarded message
    (or a gateway disclaimer or list footer beside the encrypted part) is covered. An attached
    ``.eml`` file is not an inline part, so it is handled separately (``_forwarded_file``)."""

    for count, part in enumerate(message.walk()):
        if count >= MAX_PARTS:
            break
        if _encrypted_part(part):
            return True
    return False


def _encrypted_part(part: Message) -> bool:
    content_type = part.get_content_type()
    if content_type == "multipart/encrypted":
        return True
    if content_type not in _PKCS7_MIME_TYPES and (_filename(part) or "").lower() != "smime.p7m":
        return False
    smime_type = _param(part, "smime-type").lower()
    if smime_type:  # enveloped-data / authEnveloped-data are encrypted; signed-data / certs-only are not
        return smime_type in ("enveloped-data", "authenveloped-data")
    return _encrypted_cms(part)  # no smime-type: the DER decides


def _encrypted_cms(part: Message) -> bool:
    """The first DER bytes of a ``pkcs7-mime`` part carry the CMS content-type OID: an
    enveloped / authEnveloped OID means encrypted, a signed OID (or anything else) does not."""

    try:
        payload = part.get_payload(decode=True)
    except Exception:  # noqa: BLE001 - a malformed body
        return False
    if not isinstance(payload, bytes):
        return False
    head = payload[:64]
    return any(oid in head for oid in _CMS_ENCRYPTED_OIDS)


# --- the message --------------------------------------------------------------------------------
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
        package.body_text, package.body_source = _body_text(body, walk)
    _collect(message, package, body=body, depth=depth, walk=walk, path=path, in_alternative=False)
    return package


def _raw_header(part: Message, name: str) -> str | None:
    """A header's raw value (already cut while parsing), unfolded, raw 8-bit bytes read as text."""

    raw = next((value for key, value in part.raw_items() if key.lower() == name.lower()), None)
    return None if raw is None else _unfold(_unescaped(str(raw)))


def _unescaped(text: str) -> str:
    if _SURROGATES.search(text):
        return text.encode("utf-8", "surrogateescape").decode("utf-8", errors="replace")
    return text


def _unfold(text: str) -> str:
    # Unfold: drop the CR/LF of a folded header, keep the following whitespace. Decoding the
    # encoded words afterwards (not the raw folded value) keeps the space between two words
    # ("février 2025", not "février2025") and before a <address>.
    return text.replace("\r", "").replace("\n", "")


def _clip(text: str) -> str:
    return text if len(text) <= SHOWN_HEADER_CHARS else text[:SHOWN_HEADER_CHARS] + "…"


def _header(message: Message, name: str) -> str:
    """A header as one line of text: unfolded, RFC 2047 words decoded. Date is kept as sent;
    an address header's display names are unquoted."""

    text = _raw_header(message, name)
    if text is None:
        return ""
    text = text[:SHOWN_HEADER_CHARS * 8]
    if name.lower() == "date":  # kept exactly as sent, bar folding and surrounding space
        return _clip(" ".join(text.split()))
    if "=?" in text:
        text = _decode_words(text)
    if name.lower() in ("from", "to", "cc"):
        text = text.replace('"', "")  # drop the transport quotes around a display name
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return _clip(text)


def _decode_words(text: str) -> str:
    """RFC 2047 encoded words decoded in place, each with a text character set only. Done as a
    substitution so the text between words (including spaces and backslashes) is left verbatim."""

    def decode(match: re.Match[str]) -> str:
        charset, encoding, payload = match.group(1), match.group(2).lower(), match.group(3)
        try:
            if encoding == "b":
                raw = base64.b64decode(payload + "=" * (-len(payload) % 4), validate=False)
            else:  # "q": RFC 2047 quoted-printable, with "_" for space
                raw = quopri.decodestring(payload.replace("_", " ").encode("latin-1", "replace"))
        except Exception:  # noqa: BLE001 - a malformed encoded word: keep it as it was written
            return match.group(0)
        return _decode_bytes(raw, charset)

    return _ENCODED_WORD.sub(decode, text)


def _codec(charset: str | None) -> str:
    label = str(charset or "").strip().strip("'\"").lower()
    # MIME labels such as "x-mac-cyrillic" (Apple Mail) name a codec Python knows without "x-".
    for candidate in (label, label[2:] if label.startswith("x-") else None):
        if not candidate:
            continue
        try:
            name = codecs.lookup(candidate).name
        except (LookupError, TypeError, ValueError):
            continue
        return "utf-8" if name in _DENY_CODECS else name
    return "utf-8"


def _decode_bytes(data: bytes, charset: str | None) -> str:
    try:
        return data.decode(_codec(charset), errors="replace")
    except (LookupError, ValueError):  # not a str<->bytes text codec (base64, hex, zlib, ...)
        return data.decode("utf-8", errors="replace")


def _param(part: Message, name: str, header: str = "content-type") -> str:
    return _params(part, header).get(name.lower(), "")


_PARAM_KEY = re.compile(r"^(?P<name>[^*]+?)(?:\*(?P<index>\d+))?(?P<enc>\*)?$")


def _split_params(raw: str) -> list[str]:
    """Split a header value on ``;`` outside double quotes."""

    segments: list[str] = []
    buffer: list[str] = []
    quoted = False
    for char in raw:
        if char == '"':
            quoted = not quoted
        if char == ";" and not quoted:
            segments.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    segments.append("".join(buffer))
    return segments


def _params(part: Message, header: str = "content-type") -> dict[str, str]:
    """The parameters of a ``Content-*`` header, parsed from its raw (unfolded, 8-bit-decoded)
    value rather than ``get_param``, which under compat32 turns a raw 8-bit value into U+FFFD.
    Quotes are stripped; RFC 2231 extended values (``name*=charset'lang'pct``) and continuations
    (``name*0=`` / ``name*1*=``) are joined and percent-decoded with a text character set only."""

    raw = _raw_header(part, header)
    if raw is None:
        return {}
    simple: dict[str, str] = {}
    continued: dict[str, dict[int, tuple[bool, str]]] = {}
    for segment in _split_params(raw)[1:]:
        key, equals, value = segment.partition("=")
        if not equals:
            continue
        key, value = key.strip().lower(), value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        match = _PARAM_KEY.match(key)
        if not match:
            continue
        name, index, encoded = match.group("name"), match.group("index"), bool(match.group("enc"))
        if index is None and not encoded:
            simple.setdefault(name, value)
        else:
            continued.setdefault(name, {})[int(index) if index else 0] = (encoded, value)

    result = dict(simple)
    for name, parts in continued.items():
        charset = "utf-8"
        pieces: list[str] = []
        for position, index in enumerate(sorted(parts)):
            encoded, value = parts[index]
            if encoded and position == 0 and value.count("'") >= 2:  # charset'lang' prefix
                charset, _language, value = value.split("'", 2)
                charset = charset or "utf-8"
            pieces.append(_decode_bytes(unquote_to_bytes(value), charset) if encoded else value)
        result.setdefault(name, "".join(pieces))
    return result


def _find_body(message: EmailMessage) -> EmailMessage | None:
    """The message text part, plain text before HTML, chosen as ``EmailMessage.get_body``
    chooses it (attachments skipped, a multipart/related followed to its start part), but
    reading headers as text and looking at no more than ``MAX_PARTS`` parts. (``get_body``
    needs the modern policy's header objects, and walks the whole tree.)"""

    best: tuple[int, EmailMessage] | None = None
    pending: list[EmailMessage] = [message]  # depth first, in the order the parts appear
    looked = 0
    while pending and looked < MAX_PARTS:
        part = pending.pop()
        looked += 1
        if part.get_content_disposition() == "attachment":
            continue
        maintype, subtype = part.get_content_maintype(), part.get_content_subtype()
        if maintype == "text":
            if subtype in ("plain", "html"):
                rank = 0 if subtype == "plain" else 1
                if best is None or rank < best[0]:
                    best = (rank, part)
                    if rank == 0:
                        break
            continue
        payload = part.get_payload() if maintype == "multipart" and part.is_multipart() else []
        children = [child for child in payload if isinstance(child, EmailMessage)]
        if subtype == "related" and children:
            start = _param(part, "start")
            children = [next((child for child in children if start and _raw_header(child, "Content-ID") == start),
                             children[0])]
        pending += reversed(children)
    return best[1] if best else None


def _body_text(part: Message, walk: _Walk) -> tuple[str, str]:
    """A text part as text: no more is decoded than the email's budget still allows (HTML
    has its own budget, ``MAX_HTML_CHARS``, since turning it into text costs more)."""

    html = part.get_content_subtype() == "html"
    room = max(0, min(MAX_BODY_CHARS, walk.html_chars_left if html else walk.text_chars_left))
    payload = part.get_payload(decode=True)
    payload = payload if isinstance(payload, bytes) else b""
    if len(payload) > room * 4:  # bytes: up to 4 per character
        walk.text_cut = True
    text = _decode_bytes(payload[:room * 4], _param(part, "charset"))
    if len(text) > room:
        text, walk.text_cut = text[:room], True
    if html:
        walk.html_chars_left -= len(text)
        text = html_to_text(text)
    return _within_text_budget(_tidy(text), walk), "html" if html else "plain"


def _within_text_budget(text: str, walk: _Walk) -> str:
    """The text cut to what is left of the email's message-text budget. Lines are counted the
    way ``str.splitlines`` splits them (on \\x0c, \\u2028 and the rest, not only \\n), so the cap
    matches the block count the parser and the pane produce."""

    if len(text) > walk.text_chars_left:
        text, walk.text_cut = text[:max(0, walk.text_chars_left)], True
    filled = 0
    start = 0
    cut_at: int | None = None
    for match in _LINE_BREAK.finditer(text):
        if text[start:match.start()].strip():
            filled += 1
            if filled > walk.text_lines_left:
                cut_at = start
                break
        start = match.end()
    if cut_at is None and text[start:].strip():
        filled += 1
        if filled > walk.text_lines_left:
            cut_at = start
    if cut_at is not None:
        text, walk.text_cut = text[:cut_at].rstrip("\r\n\v\f\x1c\x1d\x1e\x85  "), True
    walk.text_chars_left -= len(text)
    walk.text_lines_left -= min(filled, walk.text_lines_left)
    return text


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
                _append_text(package, _body_text(more, walk)[0])
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
            _append_text(package, _body_text(part, walk)[0])
        return

    data = part.get_payload(decode=True)
    data = data if isinstance(data, bytes) else b""
    if (filename or "").lower().endswith(".eml") and _forwarded_file(data, filename or "", package, depth=depth,
                                                                     walk=walk, path=path):
        return

    note = None
    if content_type in _TNEF_TYPES or (filename or "").lower() == "winmail.dat":
        note = "Outlook rich-text attachment (winmail.dat); its contents can't be read here"
    content_id = _raw_header(part, "Content-ID")
    package.attachments.append(EmailPart(
        name=_safe_name(filename, content_type, len(package.attachments) + 1),
        content_type=content_type,
        data=data,
        inline=disposition == "inline" or (disposition is None and content_id is not None),
        content_id=content_id.strip("<> ") if content_id else None,
        path=list(path),
        note=note,
    ))


def _forwarded_file(data: bytes, filename: str, package: EmailPackage, *, depth: int, walk: _Walk,
                    path: list[str]) -> bool:
    """Read an attached .eml as a forwarded message; False to keep it as a plain attachment.
    The depth and the email's budget are checked before it is parsed."""

    name = _safe_name(filename, "message/rfc822", len(package.attachments) + 1)
    if depth + 1 > MAX_DEPTH:
        package.notes.append(("forwarded_too_deep", f"A message forwarded more than {MAX_DEPTH} levels deep "
                                                    f"(\"{name}\") was not read."))
        return True
    if walk.lines_left <= 0 or walk.part_lines_left <= 0:
        walk.cut = True
        return False
    try:
        inner = _parse(data, walk)
        readable = bool(inner.keys())
        encrypted = readable and _is_encrypted(inner)
    except EmailError:
        # The attached message blew the shared header budget, or is damaged. List it, rather
        # than refuse the whole outer email.
        _list_not_read(package, name, data, path, "the forwarded message could not be read")
        return True
    except Exception:  # noqa: BLE001 - not a readable message: keep it as a plain attachment
        return False
    if not readable:
        return False
    if encrypted:
        _list_not_read(package, name, data, path, "the forwarded message is encrypted")
        return True
    _forwarded(inner, package, depth=depth, walk=walk, path=path)
    return True


def _list_not_read(package: EmailPackage, name: str, data: bytes, path: list[str], reason: str) -> None:
    package.attachments.append(EmailPart(name=name, content_type="message/rfc822", data=data,
                                         path=list(path), note=reason))


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
    """The part's file name (Content-Disposition filename, else Content-Type name), parsed from
    the raw header (so raw 8-bit bytes survive), RFC 2231 and RFC 2047 encodings decoded with a
    text character set only."""

    for header, param in (("content-disposition", "filename"), ("content-type", "name")):
        name = _params(part, header).get(param)
        if name:
            return _decode_words(name) if "=?" in name else name
    return None


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
