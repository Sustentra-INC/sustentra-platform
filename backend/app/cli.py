"""Operational CLI.

    python -m backend.app.cli migrate          # alembic upgrade head (uses DATABASE_URL)
    python -m backend.app.cli show-settings    # effective settings, secrets masked
    python -m backend.app.cli version
    python -m backend.app.cli create-provider-admin \
        --email a@b.com --first-name A --last-name B   # ORG-001 (stub)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core.config import get_settings

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


def _create_provider_admin(args: argparse.Namespace) -> int:
    """ORG-001: bootstrap a provider_admin (org_id NULL). STUB.

    TODO(ORG-001/AUTH-004): open an async session, INSERT a users row with
    role='provider_admin', org_id NULL, status='active' (idempotent on the email),
    then issue an invite/password-reset token so the admin can set a password.
    TODO(EMAIL-001): send the setup email. TODO(DB-003): emit audit 'provider_admin_created'.
    """
    raise NotImplementedError(
        f"ORG-001: create-provider-admin not implemented yet "
        f"(email={args.email!r}, first_name={args.first_name!r}, last_name={args.last_name!r})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sustentra")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=_migrate)
    sub.add_parser("show-settings", help="print effective settings (secrets masked)").set_defaults(
        func=_show_settings
    )
    sub.add_parser("version", help="print the build's git SHA").set_defaults(func=_version)

    create_admin = sub.add_parser(
        "create-provider-admin", help="bootstrap a provider_admin (ORG-001, stub)"
    )
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--first-name", required=True, dest="first_name")
    create_admin.add_argument("--last-name", required=True, dest="last_name")
    create_admin.set_defaults(func=_create_provider_admin)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
