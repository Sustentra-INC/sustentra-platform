"""Build reference-data/emission-factors/egrid_zip_subregions_2023.json.

Reads the US EPA Power Profiler ZIP Code Tool (Excel, eGRID2023 rev 1), sheet
"Zip-subregion", and writes ZIP code -> possible eGRID subregions. Most ZIP codes
have one subregion; EPA lists up to three where a ZIP code is served by utilities in
different subregions, and says to choose by the facility's utility in that case.

Usage:
    python backend/scripts/build_egrid_zip_reference.py [path/to/tool.xlsx] [out.json]

Defaults: reference-data/emission-factors/source/power_profiler_zipcode_tool_v14.2.xlsx
       -> reference-data/emission-factors/egrid_zip_subregions_2023.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "reference-data" / "emission-factors" / "source" / "power_profiler_zipcode_tool_v14.2.xlsx"
DEFAULT_OUT = REPO_ROOT / "reference-data" / "emission-factors" / "egrid_zip_subregions_2023.json"
SHEET = "Zip-subregion"


def build(source: Path) -> dict[str, Any]:
    ws = openpyxl.load_workbook(source, data_only=True, read_only=True)[SHEET]
    rows = ws.iter_rows(values_only=True)
    header = [str(c or "").strip().lower() for c in next(rows)]
    if header[:2] != ["zip", "subregion 1"]:
        raise ValueError(f"Unexpected header in {SHEET!r}: {header[:4]}")
    zips: dict[str, str] = {}
    for raw in rows:
        if not raw or raw[0] in (None, ""):
            continue
        zip_code = str(raw[0]).strip()
        if zip_code.isdigit():
            zip_code = zip_code.zfill(5)  # a ZIP code stored as a number loses its leading zeros
        if not re.fullmatch(r"\d{5}", zip_code):
            raise ValueError(f"Bad ZIP code {raw[0]!r}")
        subregions = [str(c).strip() for c in raw[1:4] if c not in (None, "") and str(c).strip()]
        if not subregions:
            continue
        zips[zip_code] = "|".join(dict.fromkeys(subregions))  # keep EPA's order, drop repeats
    return {
        "dataset": "EPA Power Profiler ZIP Code Tool v14.2 (eGRID2023 rev 1)",
        "source_file": source.name,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "sheet": SHEET,
        "note": "ZIP code -> possible eGRID subregions, '|'-separated in EPA's order. Where a ZIP code has "
                "more than one, EPA says to choose by the facility's electric utility (Power Profiler).",
        "zips": dict(sorted(zips.items())),
    }


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    out = Path(argv[2]) if len(argv) > 2 else DEFAULT_OUT
    data = build(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    multi = sum(1 for v in data["zips"].values() if "|" in v)
    print(f"wrote {out}: {len(data['zips'])} ZIP codes, {multi} with more than one subregion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
