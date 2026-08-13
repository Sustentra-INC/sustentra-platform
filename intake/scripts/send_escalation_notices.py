"""Send the escalation digest and reminder emails (Phase D2).

This is the scheduled half of the notification pipeline. Urgent escalations are
emailed the moment they open, from inside the app; everything else waits for
this command:

  * **digests**  - one email per client covering escalations not yet notified
  * **reminders** - one email per client for escalations still open past the
    reminder window (``escalation.reminder_hours``, 12 by default)

Run it from cron, as often as your digest interval::

    */30 * * * * cd /path/to/sustentra-platform && python intake/scripts/send_escalation_notices.py

It is safe to run twice. Each escalation is stamped ``notified_at`` when it
appears in a digest and ``reminded_at`` when it appears in a reminder, and both
jobs skip anything already stamped - so a double run, an overlapping cron and a
manual run in the middle all send nothing extra.

Nothing is sent to a real person unless the email adapter is configured to.
The default adapter writes to a local outbox file.

    python intake/scripts/send_escalation_notices.py --dry-run   # show, send nothing
    python intake/scripts/send_escalation_notices.py --digests   # digests only
    python intake/scripts/send_escalation_notices.py --reminders # reminders only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.config import load_settings  # noqa: E402
from intake.backend.repositories.escalation_repository import (  # noqa: E402
    JsonlEscalationRepository,
)
from intake.backend.repositories.org_repository import JsonlOrgRepository  # noqa: E402
from intake.backend.repositories.site_repository import JsonlSiteRepository  # noqa: E402
from intake.backend.services.email_service import (  # noqa: E402
    EmailService,
    InMemoryEmailSender,
)
from intake.backend.services.notification_service import NotificationService  # noqa: E402


class _ReadOnlyNotifier(NotificationService):
    """A dry-run notifier: renders and reports, but stamps nothing.

    Without this, a dry run would mark escalations as notified and the real run
    would then skip them - the emails would be silently lost.
    """

    def _mark(self, escalation: dict, **stamps: str) -> None:
        return None


def build_service(dry_run: bool = False) -> NotificationService:
    """Wire the real repositories; a dry run swaps the sender and the stamping."""
    settings = load_settings()
    email_service = (
        EmailService(sender=InMemoryEmailSender(), settings=settings)
        if dry_run
        else EmailService(settings=settings)
    )
    build = _ReadOnlyNotifier if dry_run else NotificationService
    return build(
        escalation_repository=JsonlEscalationRepository(),
        org_repository=JsonlOrgRepository(),
        site_repository=JsonlSiteRepository(),
        email_service=email_service,
        settings=settings,
    )


def _report(label: str, results: list[dict]) -> int:
    total = sum(item["count"] for item in results)
    if not results:
        print(f"{label}: nothing due.")
        return 0
    print(f"{label}: {total} escalation(s) across {len(results)} client(s).")
    for item in results:
        print(f"  - {item['org_id']}: {item['count']}")
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--digests", action="store_true", help="Send digests only (default: both)."
    )
    parser.add_argument(
        "--reminders", action="store_true", help="Send reminders only (default: both)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would go out. Sends nothing and stamps nothing.",
    )
    args = parser.parse_args(argv)

    # Neither flag means both, which is what cron wants.
    do_digests = args.digests or not args.reminders
    do_reminders = args.reminders or not args.digests

    settings = load_settings()
    service = build_service(dry_run=args.dry_run)
    if args.dry_run:
        print("DRY RUN - no email is sent and no escalation is stamped.\n")

    print(f"Team addresses: {', '.join(service.team_addresses)}")
    print(
        f"SLA {settings.escalation.sla_hours}h, "
        f"reminder at {settings.escalation.reminder_hours}h.\n"
    )

    sent = 0
    if do_digests:
        sent += _report("Digests", service.send_pending_digests())
    if do_reminders:
        sent += _report("Reminders", service.send_due_reminders())

    if sent == 0:
        print("\nNothing to send. Safe to run again at any time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
