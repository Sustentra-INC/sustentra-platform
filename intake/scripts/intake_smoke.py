"""Run the whole Phase B intake flow locally, end to end.

No HTTP server, no database, no real email. Mirrors
``backend/scripts/backend_s1_smoke.py`` in spirit: a single command that proves
the pieces fit together and prints what happened in plain language.

    python intake/scripts/intake_smoke.py

By default it uses in-memory storage and an in-memory mailbox, so it writes
nothing at all. Pass ``--data-dir DIR`` to exercise the real JSONL repositories
and outbox in a directory of your choosing.

Flow:
  1) create a client company and its first owner (internal step)
  2) the owner requests a magic link
  3) the link is consumed and becomes a session
  4) the seed form definition is fetched for the company's industry overlay
  5) the seed form is submitted
  6) the resulting company, sites and provisional flags are printed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.config import load_settings, reset_caches  # noqa: E402
from intake.backend.repositories.magic_link_repository import (  # noqa: E402
    InMemoryMagicLinkTokenRepository,
    JsonlMagicLinkTokenRepository,
)
from intake.backend.repositories.org_repository import (  # noqa: E402
    InMemoryOrgRepository,
    JsonlOrgRepository,
)
from intake.backend.repositories.seed_profile_repository import (  # noqa: E402
    InMemorySeedProfileRepository,
    JsonlSeedProfileRepository,
)
from intake.backend.repositories.session_repository import (  # noqa: E402
    InMemorySessionRepository,
    JsonlSessionRepository,
)
from intake.backend.repositories.site_repository import (  # noqa: E402
    InMemorySiteRepository,
    JsonlSiteRepository,
)
from intake.backend.repositories.user_repository import (  # noqa: E402
    InMemoryUserRepository,
    JsonlUserRepository,
)
from intake.backend.services.auth_service import AuthService  # noqa: E402
from intake.backend.services.email_service import (  # noqa: E402
    EmailService,
    InMemoryEmailSender,
    OutboxEmailSender,
)
from intake.backend.services.org_service import OrgService  # noqa: E402
from intake.backend.services.seed_form_service import SeedFormService  # noqa: E402

OWNER_EMAIL = "sam.owner@northlight.example"

COMPANY = {
    "legal_name": "Northlight Studios Ltd",
    "reporting_year": 2025,
    "responsible_party_name": "Ada Reyes",
    "responsible_party_role": "Facilities Director",
    "responsible_party_email": "ada.reyes@northlight.example",
    "industry": "film_production_facility",
    "reporting_period_start": "2025-01-01",
    "reporting_period_end": "2025-12-31",
    "fiscal_year_basis": "calendar year",
}

SITES = [
    {
        "site_name": "Harbour Stages",
        "address_line": "12 Harbour Road",
        "city": "Wellington",
        "state_region": "Wellington",
        "postal_code": "6011",
        "country_region": "New Zealand",
        "operational_status": "operating all year",
        "site_type": "soundstage_complex",
        "ownership": "leased",
        "lease_type": "operating",
        "ownership_note": "Stage 4 sublet to visiting productions.",
    },
    {
        "site_name": "Kilbirnie Workshop",
        "address_line": "5 Coutts Street",
        "city": "Wellington",
        "state_region": "Wellington",
        "postal_code": "6022",
        "country_region": "New Zealand",
        "operational_status": "opened in March 2025",
        "site_type": "workshop",
        "ownership": "owned",
        "ownership_note": "",
    },
]


def _build(data_dir: Path | None):
    if data_dir is None:
        repos = (
            InMemoryOrgRepository(),
            InMemoryUserRepository(),
            InMemorySiteRepository(),
            InMemoryMagicLinkTokenRepository(),
            InMemorySessionRepository(),
            InMemorySeedProfileRepository(),
        )
        mailbox = InMemoryEmailSender()
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        repos = (
            JsonlOrgRepository(data_dir / "orgs.jsonl"),
            JsonlUserRepository(data_dir / "users.jsonl"),
            JsonlSiteRepository(data_dir / "sites.jsonl"),
            JsonlMagicLinkTokenRepository(data_dir / "magic_link_tokens.jsonl"),
            JsonlSessionRepository(data_dir / "sessions.jsonl"),
            JsonlSeedProfileRepository(data_dir / "seed_profiles.jsonl"),
        )
        mailbox = OutboxEmailSender(data_dir / "outbox.jsonl")
    return repos, mailbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="write real JSONL files here instead of using in-memory storage",
    )
    args = parser.parse_args(argv)

    reset_caches()
    settings = load_settings()
    (orgs, users, sites, tokens, sessions, submissions), mailbox = _build(args.data_dir)
    email_service = EmailService(sender=mailbox, settings=settings)

    auth = AuthService(tokens, sessions, users, email_service, settings=settings)
    org_service = OrgService(orgs, users, sites, settings=settings)
    seed_form = SeedFormService(orgs, sites, submissions, email_service, settings=settings)

    storage = "in-memory (nothing written)" if args.data_dir is None else str(args.data_dir)
    print(f"storage: {storage}")
    print(f"email:   {type(mailbox).__name__} (no real email is sent)\n")

    print("1) creating the client company and its owner")
    created = org_service.create_org(
        legal_name="Northlight Studios",
        owner_name="Sam Owner",
        owner_email=OWNER_EMAIL,
        created_by="internal@sustentra.com",
    )
    org_id = created["org"]["org_id"]
    print(f"   org {org_id} - status {created['org']['profile_status']}")

    print("2) owner requests a sign-in link")
    auth.request_magic_link(OWNER_EMAIL)
    if isinstance(mailbox, InMemoryEmailSender):
        body = mailbox.last_to(OWNER_EMAIL).body
    else:
        body = mailbox.messages()[-1]["body"]
    raw_token = body.split("token=")[1].split()[0].strip()
    print(f"   link emailed, token {raw_token[:8]}... (expires in "
          f"{settings.auth.magic_link_ttl_minutes} min, single use)")

    print("3) consuming the link")
    session = auth.verify_magic_link(raw_token)
    user = auth.resolve_session(session["session_token"])
    print(f"   signed in as {user.email} ({user.role})")

    print("4) fetching the seed form for this company's industry overlay")
    form = seed_form.get_form("film")
    field_count = sum(len(step["fields"]) for step in form["steps"])
    print(f"   {len(form['steps'])} steps, {field_count} inputs, copy status "
          f"'{form['copy_status']}'")

    print("5) submitting the seed form")
    result = seed_form.submit(org_id=org_id, submitted_by=user.user_id,
                              payload={"company": COMPANY, "sites": SITES})

    org = result["org"]
    print(f"\n   company : {org['legal_name']}")
    print(f"   period  : {org['reporting_period_start']} to {org['reporting_period_end']}")
    print(f"   contact : {org['responsible_party']['name']} "
          f"({org['responsible_party']['email']})")
    print(f"   status  : {org['profile_status']}")

    print("\n   sites:")
    for site in result["sites"]:
        lease = f", lease {site['lease_type']}" if site["lease_type"] else ""
        print(f"     - {site['site_name']} [{site['site_type']}] "
              f"{site['ownership']}{lease}")
        print(f"       in scope {site['period_in_scope_start']} to "
              f"{site['period_in_scope_end']} (derived, never asked)")

    provisional = result["submission"]["provisional_values"]
    print(f"\n   flagged for expert sign-off ({len(provisional)}):")
    for value in provisional:
        print(f"     - {value['field_id']} = {value['value']!r} "
              f"-> {value['requires_signoff']}")

    deferred = result["sites"][0]["deferred_boundary_fields"]
    print(f"\n   boundary decisions deliberately NOT made here ({len(deferred)}):")
    for entry in deferred:
        print(f"     - {entry['field_id']}.{entry['schema_field']} "
              f"-> resolved at {entry['deferred_to_datapoint']}")

    print("\n6) confirmation email")
    to = org["responsible_party"]["email"]
    sent = mailbox.last_to(to) if isinstance(mailbox, InMemoryEmailSender) else mailbox.messages()[-1]
    subject = sent.subject if hasattr(sent, "subject") else sent["subject"]
    print(f"   '{subject}' -> {to}")

    print("\nsmoke flow complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
