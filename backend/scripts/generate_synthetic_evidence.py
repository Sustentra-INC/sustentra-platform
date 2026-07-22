"""Generate fake evidence documents for local S1 backend testing.

This script creates synthetic, non-customer evidence text for smoke testing.
By default it writes under local-samples/generated, which is git-ignored.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = "local-samples/generated"
DEFAULT_FILE_NAME = "synthetic_fuel_bill.txt"

DEFAULT_LINES = [
    "Facility Name: Demo Plant",
    "Service Address: 100 Demo Way, Example City, NY 10001",
    "Fuel Type: Natural Gas",
    "Total Usage: 28,100 MMBtu",
    "Service Period: 10/01/2023 - 10/31/2023",
    "Supplier: Demo Utility",
    "Account Number: 123456",
]


def generate_synthetic_evidence(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    file_name: str = DEFAULT_FILE_NAME,
    *,
    overwrite: bool = False,
    lines: list[str] | None = None,
) -> Path:
    """Create a synthetic evidence file and return its path."""

    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name is required.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    target = output_path / file_name.strip()
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing file: {target}. Use --overwrite to replace it."
        )

    content_lines = lines if lines is not None else DEFAULT_LINES
    text = "\n".join(content_lines).strip() + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic evidence text file for local S1 testing.",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--file-name", default=DEFAULT_FILE_NAME)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = generate_synthetic_evidence(
        output_dir=args.output_dir,
        file_name=args.file_name,
        overwrite=args.overwrite,
    )
    print(str(path).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
