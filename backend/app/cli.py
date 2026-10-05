"""Operational CLI.

    python -m backend.app.cli migrate          # alembic upgrade head (uses DATABASE_URL)
    python -m backend.app.cli show-settings    # effective settings, secrets masked
    python -m backend.app.cli version
    python -m backend.app.cli create-provider-admin \
        --email a@b.com --first-name A --last-name B [--reset-link]   # ORG-000
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import subprocess
import sys
from pathlib import Path

from .core import db as core_db
from .core import security_primitives
from .core.config import get_settings
from .services import provider_admin_bootstrap as bootstrap

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _migrate(_: argparse.Namespace) -> int:
    # Run alembic from backend/ so alembic.ini and migrations/ resolve.
    return subprocess.call([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR)


def _show_settings(_: argparse.Namespace) -> int:
    settings = get_settings()
    data = settings.model_dump(mode="json")  # SecretStr values render as "**********"
    data["allowed_origins"] = sorted(settings.allowed_origins)
    data["docs_enabled"] = settings.docs_enabled
    print(json.dumps(data, indent=2, default=str))
    return 0


def _version(_: argparse.Namespace) -> int:
    print(get_settings().git_sha)
    return 0


PASSWORD_ATTEMPTS = 3


class _Aborted(Exception):
    pass


def _prompt_password(email: str) -> str:
    """Ask twice (no echo) until the password meets the AUTH-003 policy.

    The password is never accepted as an argument, printed or logged.
    """
    for _ in range(PASSWORD_ATTEMPTS):
        try:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
        except (EOFError, KeyboardInterrupt):
            raise _Aborted("password entry cancelled") from None
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            continue
        violations = security_primitives.validate_password(password, email)
        if violations:
            for violation in violations:
                print(f"- {violation}", file=sys.stderr)
            continue
        return password
    raise _Aborted(f"no acceptable password after {PASSWORD_ATTEMPTS} attempts")


async def _bootstrap_provider_admin(email: str, first_name: str, last_name: str, use_reset_link: bool) -> int:
    sessionmaker = core_db.get_sessionmaker()
    try:
        async with sessionmaker() as session, session.begin():
            existing = await bootstrap.find_provider_admin(session, email)
        if existing is not None:
            print(f"provider_admin {email} already exists (id={existing['id']}, status={existing['status']}); "
                  "nothing changed.")
            return 0

        password_hash: str | None = None
        if not use_reset_link:
            password_hash = security_primitives.hash_password(_prompt_password(email))

        async with sessionmaker() as session, session.begin():
            result = await bootstrap.create_provider_admin(
                session, email=email, first_name=first_name, last_name=last_name,
                password_hash=password_hash, issue_reset_link=use_reset_link,
            )
    finally:
        await core_db.dispose_engine()

    if not result.created:
        print(f"provider_admin {email} already exists (id={result.user_id}, status={result.status}); "
              "nothing changed.")
        return 0
    print(f"Created provider_admin {email} (id={result.user_id}).")
    if result.reset_link:
        expires = result.reset_expires_at.isoformat(timespec="minutes") if result.reset_expires_at else "soon"
        print(f"Set the password with this one-time link (expires {expires}):")
        print(f"  {result.reset_link}")
    print("Sign in at /provider-admin/login (password + email OTP).")
    return 0


def _create_provider_admin(args: argparse.Namespace) -> int:
    """ORG-000: bootstrap a provider_admin (org_id NULL). Idempotent on the email."""
    try:
        email = bootstrap.normalize_email(args.email)
        first_name = bootstrap.normalize_name(args.first_name, "first name")
        last_name = bootstrap.normalize_name(args.last_name, "last name")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_bootstrap_provider_admin(email, first_name, last_name, args.reset_link))
    except _Aborted as exc:
        print(f"error: {exc}; nothing was created.", file=sys.stderr)
        return 1
    except core_db.DatabaseNotConfiguredError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sustentra")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=_migrate)
    sub.add_parser("show-settings", help="print effective settings (secrets masked)").set_defaults(
        func=_show_settings
    )
    sub.add_parser("version", help="print the build's git SHA").set_defaults(func=_version)

    create_admin = sub.add_parser(
        "create-provider-admin",
        help="bootstrap a provider_admin (ORG-000); prompts for the password",
    )
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--first-name", required=True, dest="first_name")
    create_admin.add_argument("--last-name", required=True, dest="last_name")
    create_admin.add_argument(
        "--reset-link", action="store_true", dest="reset_link",
        help="don't prompt; leave the password unset and print a one-time set-password link (1 hour)",
    )
    create_admin.set_defaults(func=_create_provider_admin)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
