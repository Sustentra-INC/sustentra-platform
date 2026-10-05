# EMAIL-001 Sender and Templates

This repository now uses one shared sender entrypoint in backend/app/services/otp_delivery.py:

- send_email(template, to, variables)

Auth callers remain unchanged:

- deliver_login_otp(to, code)
- deliver_password_reset(to, link)
- get_otp_sender()
- get_reset_sender()

A small invite adapter contract is also present for later MVP-19 integration:

- deliver_invite(to, link)
- get_invite_sender()

No invitation business flow is wired in this change.

## Template behavior

Template allowlist (fixed names):

- login_otp
- invite
- password_reset

Each template has both:

- plain text: *.txt.j2
- HTML: *.html.j2

Rendering uses Jinja2 with:

- StrictUndefined (missing variables raise UndefinedError)
- HTML autoescape

Subjects are constants in code, not runtime input.

## Transport behavior

Environment selection is explicit:

- local/test: SMTP multipart to Mailpit (text + HTML)
- staging/prod: SESv2 SendEmail multipart (text + HTML)

There is no production fallback to local SMTP.

### SES API mapping (SESv2)

The issue requirements mention sender, destination, subject, and body fields.
In this implementation those map to SESv2 SendEmail payload keys:

- sender identity -> FromEmailAddress
- recipient list -> Destination.ToAddresses
- subject -> Content.Simple.Subject
- plain body -> Content.Simple.Body.Text
- HTML body -> Content.Simple.Body.Html

This implementation intentionally uses SESv2 field names only and does not mix SESv1 fields.

## Logging and safety

Delivery wrappers catch rendering/transport/configuration failures so auth responses do not fail.
Logs include only:

- template name
- error classification and SES error code (if present)
- masked recipient

Logs must not include OTP values, reset/invite links, token strings, body content, or credentials.
