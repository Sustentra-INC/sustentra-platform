"""Operational CLI.

    python -m backend.app.cli migrate          # alembic upgrade head (uses DATABASE_URL)
    python -m backend.app.cli show-settings    # effective settings, secrets masked
    python -m backend.app.cli version
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sustentra")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=_migrate)
    sub.add_parser("show-settings", help="print effective settings (secrets masked)").set_defaults(
        func=_show_settings
    )
    sub.add_parser("version", help="print the build's git SHA").set_defaults(func=_version)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
