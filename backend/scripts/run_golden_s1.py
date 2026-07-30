from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.tests.golden_s1.golden_s1_runner import run_golden_s1  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden S1 evaluation report.")
    parser.add_argument(
        "--fixture-root",
        default=None,
        help="Path to s1-test-suite. Defaults to S1_GOLDEN_FIXTURE_ROOT or ./s1-test-suite.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Directory for generated report files. Defaults to local-data/golden-s1-results.",
    )
    args = parser.parse_args()

    result = run_golden_s1(args.fixture_root, args.output_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
