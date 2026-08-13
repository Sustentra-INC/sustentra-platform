"""Extract controlled vocabularies from the S2 methodology workbooks.

Phase B helper. The seed form needs dropdown values (lease type, party role,
consolidation approach, ...). CLAUDE.md rule 3 forbids inventing them, so they
are extracted from the workbooks' own vocabulary sheets and committed to
``intake/config/controlled_vocabularies.json``. The seed form config is then
validated against this file.

Sheets parsed:

* ``S2_General_Methodology_Schema_v.1.xlsx`` / ``2_Vocab`` - three columns:
  ``field (FIELD-ID)`` | pipe-separated permitted values | definitions.
* ``S2_Scope2_Data_Schema_v.1.xlsx`` / ``Controlled_Vocabularies`` - four
  columns, one row per permitted value: ``Column`` | value | meaning | source.

``S2_Scope1_Data_Schema_v.1.xlsx`` / ``4_Vocab`` is deliberately NOT parsed: it
is a wide paired (heading, meaning) layout rather than a vocabulary list, and
nothing in the intake seed form draws from it. Extend this script if a later
phase needs it.

A vocabulary marked ``"open": true`` carries an ``[OPEN ...]`` annotation in the
workbook, meaning the listed values are indicative and must not be enforced as a
closed set.

Run:

    python intake/scripts/extract_controlled_vocabularies.py
    python intake/scripts/extract_controlled_vocabularies.py --check

Read-only with respect to the workbooks; writes only its own output file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

GENERAL_WORKBOOK = "reference-data/methodology/S2_General_Methodology_Schema_v.1.xlsx"
GENERAL_SHEET = "2_Vocab"
SCOPE2_WORKBOOK = "reference-data/methodology/S2_Scope2_Data_Schema_v.1.xlsx"
SCOPE2_SHEET = "Controlled_Vocabularies"

DEFAULT_OUTPUT = "intake/config/controlled_vocabularies.json"

# "lease_type (ORG-050)" or "scope2_method (RUP-010, RUP-020)" or "Grain"
NAME_PATTERN = re.compile(r"^(?P<name>[A-Za-z_][\w ]*?)\s*(?:\((?P<ids>[^)]*)\))?$")
FIELD_ID_PATTERN = re.compile(r"(?:S1|S2)-[A-Z]{3}-\d{3}|[A-Z]{3}-\d{3}")
# Trailing bracketed annotation, e.g. "a | b   [OPEN - regulatory overlay narrows]"
NOTE_PATTERN = re.compile(r"\[(?P<note>[^\]]*)\]")

PLACEHOLDER_VALUES = {"...", "-", "—", "N/A", ""}


@contextmanager
def _open_workbook(workbook_path: Path) -> Iterator[Any]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            yield workbook
        finally:
            workbook.close()


def _parse_name(raw: str) -> tuple[str, list[str]]:
    """Split "lease_type (ORG-050)" into ("lease_type", ["ORG-050"])."""
    match = NAME_PATTERN.match(raw.strip())
    if not match:
        return raw.strip(), []
    name = match.group("name").strip()
    ids = FIELD_ID_PATTERN.findall(match.group("ids") or "")
    return name, ids


def _parse_values(raw: str) -> tuple[list[str], str | None, bool]:
    """Split a permitted-values cell into (values, note, is_open)."""
    text = str(raw)
    notes = NOTE_PATTERN.findall(text)
    note = " ".join(part.strip() for part in notes) or None
    body = NOTE_PATTERN.sub("", text)

    values = []
    for part in body.split("|"):
        candidate = part.strip()
        if candidate and candidate not in PLACEHOLDER_VALUES:
            values.append(candidate)

    is_open = "OPEN" in text.upper() or "..." in body
    return values, note, is_open


def _read_general(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = repo_root / GENERAL_WORKBOOK
    if not path.exists():
        raise SystemExit(f"missing workbook: {path}")

    vocabularies: dict[str, dict[str, Any]] = {}
    with _open_workbook(path) as workbook:
        if GENERAL_SHEET not in workbook.sheetnames:
            raise SystemExit(f"{path}: expected sheet {GENERAL_SHEET!r}")
        rows = workbook[GENERAL_SHEET].iter_rows(values_only=True)
        for row in rows:
            if not row or row[0] is None:
                continue
            raw_name = str(row[0]).strip()
            if not raw_name or raw_name.lower().startswith("controlled vocabular"):
                continue
            if raw_name.lower().startswith("column"):
                continue
            if len(row) < 2 or row[1] is None:
                continue
            name, field_ids = _parse_name(raw_name)
            values, note, is_open = _parse_values(row[1])
            if not values and not is_open:
                continue
            vocabularies[name] = {
                "vocabulary": name,
                "field_ids": field_ids,
                "values": values,
                "open": is_open,
                "note": note,
                "source": {"workbook": GENERAL_WORKBOOK, "sheet": GENERAL_SHEET},
            }
    return vocabularies


def _read_scope2(repo_root: Path) -> dict[str, dict[str, Any]]:
    path = repo_root / SCOPE2_WORKBOOK
    if not path.exists():
        raise SystemExit(f"missing workbook: {path}")

    grouped: dict[str, dict[str, Any]] = {}
    with _open_workbook(path) as workbook:
        if SCOPE2_SHEET not in workbook.sheetnames:
            raise SystemExit(f"{path}: expected sheet {SCOPE2_SHEET!r}")
        rows = workbook[SCOPE2_SHEET].iter_rows(values_only=True)
        header = next(rows, None)
        if not header or str(header[0]).strip().lower() != "column":
            raise SystemExit(f"{path}:{SCOPE2_SHEET}: unexpected header {header!r}")
        for row in rows:
            if not row or row[0] is None or len(row) < 2 or row[1] is None:
                continue
            name, field_ids = _parse_name(str(row[0]).strip())
            value = str(row[1]).strip()
            if not value or value in PLACEHOLDER_VALUES:
                continue
            entry = grouped.setdefault(
                name,
                {
                    "vocabulary": name,
                    "field_ids": field_ids,
                    "values": [],
                    "open": False,
                    "note": None,
                    "source": {"workbook": SCOPE2_WORKBOOK, "sheet": SCOPE2_SHEET},
                },
            )
            if value not in entry["values"]:
                entry["values"].append(value)
    return grouped


def build_vocabularies(repo_root: Path) -> dict[str, Any]:
    general = _read_general(repo_root)
    scope2 = _read_scope2(repo_root)

    merged: dict[str, dict[str, Any]] = {}
    for source in (general, scope2):
        for name, entry in source.items():
            if name in merged:
                # Same vocabulary name in two workbooks: keep both under distinct keys.
                merged[f"{name} ({entry['source']['sheet']})"] = entry
            else:
                merged[name] = entry

    return {
        "config_name": "sustentra_intake_controlled_vocabularies",
        "config_version": "1.0.0",
        "description": (
            "Controlled vocabularies extracted from the S2 methodology workbooks. Source of "
            "truth for intake dropdown options (CLAUDE.md rule 3). Vocabularies marked "
            "'open': true are indicative per the workbook and must not be enforced as closed sets."
        ),
        "generated_by": "intake/scripts/extract_controlled_vocabularies.py",
        "not_parsed": [
            {
                "workbook": "reference-data/methodology/S2_Scope1_Data_Schema_v.1.xlsx",
                "sheet": "4_Vocab",
                "reason": (
                    "Wide paired (heading, meaning) layout rather than a vocabulary list; "
                    "no intake seed-form field draws from it."
                ),
            }
        ],
        "counts": {"vocabularies": len(merged)},
        "vocabularies": {name: merged[name] for name in sorted(merged)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="do not write; fail if the committed file is stale"
    )
    args = parser.parse_args(argv)

    vocabularies = build_vocabularies(REPO_ROOT)
    rendered = json.dumps(vocabularies, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not args.output.exists():
            print(f"FAIL: {args.output} does not exist", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(f"FAIL: {args.output} is stale; re-run this script", file=sys.stderr)
            return 1
        print(f"OK: {args.output} is up to date")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {args.output.relative_to(REPO_ROOT)}: "
        f"{vocabularies['counts']['vocabularies']} vocabularies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
