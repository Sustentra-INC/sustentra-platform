"""Extract the methodology field index used to validate the intake profile schema seed.

Phase A helper. Reads the authoritative S2 methodology workbooks in
``reference-data/methodology/`` plus the J2 evidence type library, and writes a
machine-readable index to ``intake/config/methodology_field_index.json``.

The index is the executable form of CLAUDE.md rule 3 ("never invent data
fields"): ``intake/scripts/validate_profile_schema.py`` rejects any
``populates`` field ID or ``evidence_triggered`` ID in the profile schema seed
that does not appear here.

The index is committed so that validation, tests and CI never depend on the
binary workbooks. Re-run this script whenever the workbooks change:

    python intake/scripts/extract_methodology_field_index.py

Read-only: this script never modifies the workbooks or any existing file.
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

# (workbook path, sheet name, source key) — sheet names verified against the files.
WORKBOOK_SHEETS: tuple[tuple[str, str, str], ...] = (
    ("reference-data/methodology/S2_General_Methodology_Schema_v.1.xlsx", "1_Schema", "general"),
    ("reference-data/methodology/S2_Scope1_Data_Schema_v.1.xlsx", "1_Schema", "scope1"),
    ("reference-data/methodology/S2_Scope2_Data_Schema_v.1.xlsx", "S2_Schema", "scope2"),
)

EVIDENCE_LIBRARY = "reference-data/config/libraries/evidence_type_library.json"

DEFAULT_OUTPUT = "intake/config/methodology_field_index.json"

FIELD_ID_PATTERN = re.compile(r"^(?:S1|S2)-[A-Z]{3}-\d{3}$|^[A-Z]{3}-\d{3}$")

# Column headers are identical across the three schema sheets.
COL_FIELD_ID = "Field_ID"
COL_SCHEMA_FIELDS = "Data_Schema_Field(s)"
COL_BLOCK = "Block"
COL_GRAIN = "Grain"
COL_CALC_METHOD = "Calculation_Method"

_SPLIT_PATTERN = re.compile(r"[;,\n]")


def _split_schema_fields(raw: Any) -> list[str]:
    """Split a ``Data_Schema_Field(s)`` cell into individual field names."""
    if raw is None:
        return []
    parts = (part.strip() for part in _SPLIT_PATTERN.split(str(raw)))
    return [part for part in parts if part and part not in {"N/A", "—", "-"}]


@contextmanager
def _open_workbook(workbook_path: Path) -> Iterator[Any]:
    """Open a workbook read-only, suppressing openpyxl's extension warning.

    Read-only workbooks parse lazily, so the warning filter has to stay active
    for the whole iteration, not just the ``load_workbook`` call.
    """
    import openpyxl  # imported lazily so --help works without the dependency

    with warnings.catch_warnings():
        # openpyxl warns about an unsupported Data Validation extension in these
        # workbooks; it does not affect the cell values we read.
        warnings.simplefilter("ignore", UserWarning)
        workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            yield workbook
        finally:
            workbook.close()


def _read_sheet(workbook_path: Path, sheet_name: str, source: str) -> dict[str, dict[str, Any]]:
    """Read one schema sheet into ``{field_id: {...}}``."""
    with _open_workbook(workbook_path) as workbook:
        if sheet_name not in workbook.sheetnames:
            raise SystemExit(
                f"{workbook_path}: expected sheet {sheet_name!r}, found {workbook.sheetnames}"
            )
        rows = workbook[sheet_name].iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]

        missing_columns = [
            column
            for column in (COL_FIELD_ID, COL_SCHEMA_FIELDS, COL_BLOCK, COL_GRAIN, COL_CALC_METHOD)
            if column not in header
        ]
        if missing_columns:
            raise SystemExit(f"{workbook_path}:{sheet_name}: missing columns {missing_columns}")

        index_of = {column: header.index(column) for column in header if column}

        def cell(row: tuple[Any, ...], column: str) -> Any:
            position = index_of[column]
            return row[position] if position < len(row) else None

        fields: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not row:
                continue
            raw_field_id = cell(row, COL_FIELD_ID)
            if raw_field_id is None:
                continue
            field_id = str(raw_field_id).strip()
            if not FIELD_ID_PATTERN.match(field_id):
                continue
            fields[field_id] = {
                "field_id": field_id,
                "source": source,
                "block": (str(cell(row, COL_BLOCK)).strip() if cell(row, COL_BLOCK) else None),
                "grain": (str(cell(row, COL_GRAIN)).strip() if cell(row, COL_GRAIN) else None),
                "schema_fields": _split_schema_fields(cell(row, COL_SCHEMA_FIELDS)),
            }
        return fields


def _read_calculation_methods(workbook_path: Path, sheet_name: str) -> set[str]:
    """Collect the controlled ``Calculation_Method`` values from one sheet."""
    with _open_workbook(workbook_path) as workbook:
        rows = workbook[sheet_name].iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows)]
        position = header.index(COL_CALC_METHOD)
        methods: set[str] = set()
        for row in rows:
            if not row or position >= len(row) or row[position] is None:
                continue
            value = str(row[position]).strip()
            if value and value not in {"N/A", "—", "-"}:
                methods.add(value)
        return methods


def _read_evidence_types(library_path: Path) -> list[str]:
    """Return the J2 evidence type IDs from the evidence type library."""
    library = json.loads(library_path.read_text(encoding="utf-8"))
    evidence_types = library.get("evidence_types")
    if not isinstance(evidence_types, list) or not evidence_types:
        raise SystemExit(f"{library_path}: no 'evidence_types' list found")
    return sorted(
        str(entry["evidence_type_id"]).strip()
        for entry in evidence_types
        if entry.get("evidence_type_id")
    )


def build_index(repo_root: Path) -> dict[str, Any]:
    """Build the full methodology field index from the repo's reference data."""
    fields: dict[str, dict[str, Any]] = {}
    methods: set[str] = set()
    sources: list[dict[str, Any]] = []

    for relative_path, sheet_name, source in WORKBOOK_SHEETS:
        workbook_path = repo_root / relative_path
        if not workbook_path.exists():
            raise SystemExit(f"missing workbook: {workbook_path}")
        sheet_fields = _read_sheet(workbook_path, sheet_name, source)
        duplicates = sorted(set(sheet_fields) & set(fields))
        if duplicates:
            raise SystemExit(f"{relative_path}: field IDs already defined elsewhere: {duplicates}")
        fields.update(sheet_fields)
        methods |= _read_calculation_methods(workbook_path, sheet_name)
        sources.append(
            {"path": relative_path, "sheet": sheet_name, "source": source, "field_count": len(sheet_fields)}
        )

    library_path = repo_root / EVIDENCE_LIBRARY
    if not library_path.exists():
        raise SystemExit(f"missing evidence type library: {library_path}")
    evidence_type_ids = _read_evidence_types(library_path)
    library = json.loads(library_path.read_text(encoding="utf-8"))

    return {
        "index_name": "sustentra_intake_methodology_field_index",
        "index_version": "1.0.0",
        "description": (
            "Generated allow-list of methodology field IDs, their data schema field names, "
            "controlled calculation-method values, and J2 evidence type IDs. Used by "
            "intake/scripts/validate_profile_schema.py to prove the intake profile schema "
            "seed invents no data fields (CLAUDE.md rule 3)."
        ),
        "generated_by": "intake/scripts/extract_methodology_field_index.py",
        "sources": sources,
        "evidence_type_library": {
            "path": EVIDENCE_LIBRARY,
            "library_name": library.get("library_name"),
            "version": library.get("version"),
        },
        "counts": {
            "methodology_fields": len(fields),
            "calculation_methods": len(methods),
            "evidence_types": len(evidence_type_ids),
        },
        "calculation_methods": sorted(methods),
        "evidence_type_ids": evidence_type_ids,
        "methodology_fields": {field_id: fields[field_id] for field_id in sorted(fields)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / DEFAULT_OUTPUT,
        help=f"where to write the index (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if the committed index is stale",
    )
    args = parser.parse_args(argv)

    index = build_index(REPO_ROOT)
    rendered = json.dumps(index, indent=2, ensure_ascii=False) + "\n"

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
    counts = index["counts"]
    print(
        f"wrote {args.output.relative_to(REPO_ROOT)}: "
        f"{counts['methodology_fields']} methodology fields, "
        f"{counts['calculation_methods']} calculation methods, "
        f"{counts['evidence_types']} evidence types"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
