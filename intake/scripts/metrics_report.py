"""Print the two success metrics (Phase F).

    python intake/scripts/metrics_report.py

intake/SPEC.md section 2 asks for these to be instrumented from day one:
percentage of profiles completed with zero escalations, and median
time-to-complete.

Reads the records that already exist and prints them. Nothing is tracked,
nothing is sent anywhere, and no client data leaves the machine - the numbers
come from the same audit log the profile page reads.

Use ``--json`` to pipe the figures somewhere else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from intake.backend.api.context import build_default_context  # noqa: E402


def _hours(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 48:
        return f"{value:.1f}h"
    return f"{value / 24:.1f} days"


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the raw figures.")
    args = parser.parse_args(argv)

    summary = build_default_context().metrics_service.summary()

    if args.json:
        print(json.dumps(summary, indent=2))
        return 0

    print("Onboarding, so far")
    print("==================\n")
    print(f"  Clients            {summary['clients_total']}")
    print(f"  Started            {summary['clients_started']}")
    print(f"  Finished           {summary['clients_complete']}\n")

    print("The two success metrics")
    print("-----------------------")
    print(
        f"  Completed without getting stuck      {_percent(summary['no_stuck_rate'])}"
        "   <- the one that measures onboarding"
    )
    print(
        f"  Completed with no escalations at all {_percent(summary['zero_escalation_rate'])}"
        "   <- SPEC section 2, word for word"
    )
    print(f"  Median time to complete              {_hours(summary['median_hours_to_complete'])}")
    if summary["clients_complete"]:
        print(
            f"    fastest {_hours(summary['fastest_hours'])},"
            f" slowest {_hours(summary['slowest_hours'])}"
        )
    print()

    if summary["clients"]:
        print("Per client")
        print("----------")
        width = max(len(item["legal_name"] or item["org_id"]) for item in summary["clients"])
        for item in summary["clients"]:
            name = (item["legal_name"] or item["org_id"]).ljust(width)
            if not item["started_at"]:
                state = "not started"
            elif item["is_complete"]:
                state = f"done in {_hours(item['hours_to_complete'])}"
            else:
                state = f"{item['datapoints_settled']}/{item['datapoints_total']} answered"
            stuck = "  STUCK" if item["got_stuck"] else ""
            waiting = (
                f"  {item['escalations_open']} with us" if item["escalations_open"] else ""
            )
            print(f"  {name}  {state}{waiting}{stuck}")
        print()

    print("Read this with care")
    print("-------------------")
    for note in summary["caveats"]:
        print(f"  - {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
