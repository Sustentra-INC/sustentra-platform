"""Compare local parser outputs with optional live AWS Textract outputs.

This is a parser-layer harness only. It validates that parser outputs have the
shape the downstream S1 pipeline expects and checks expected text/table content
from ``s1-test-suite/stage_2_parser_ocr``. AWS Textract is opt-in via
``--include-aws`` to avoid accidental network calls and charges.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.parser_service import ParserService  # noqa: E402

DEFAULT_FIXTURE_ROOT = _REPO_ROOT / "s1-test-suite"
DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "local-data" / "parser-comparison-results"

REQUIRED_TOP_LEVEL_FIELDS = {
    "parser_output_id",
    "document_id",
    "processing_run_id",
    "parser_name",
    "parser_version",
    "status",
    "created_at",
    "pages",
    "tables",
    "key_value_pairs",
    "text_blocks",
    "source_references",
    "warnings",
}

VALID_STATUSES = {"parsed", "partial", "empty", "failed"}


def collapse(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize(value: Any) -> str:
    return collapse(value).casefold()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "document"


@contextmanager
def temporary_env(**updates: str | None) -> Iterator[None]:
    old_values = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def converted_inputs(fixture_root: Path, document_id: str) -> list[Path]:
    base = fixture_root / "s1-test-suite-converted-inputs" / "production_inputs"
    candidates = [
        base / f"{document_id}_parser_test_fixture.xlsx",
        base / f"{document_id}_parser_test_fixture.pdf",
        base / "text" / f"{document_id}.txt",
        base / "excel" / f"{document_id}.xlsx",
        base / "excel" / f"{document_id}.csv",
        base / "pdf" / f"{document_id}.pdf",
    ]
    return [path for path in candidates if path.exists()]


def aws_inputs(fixture_root: Path, document_id: str, input_kind: str) -> list[Path]:
    base = fixture_root / "raw_documents" / "ocr_png" / document_id
    candidates: list[Path] = []
    if input_kind in {"png", "both"}:
        candidates.extend(sorted(base.glob("page-*.png")))
    if input_kind in {"pdf", "both"}:
        candidates.append(base / f"{document_id}.pdf")
    return [path for path in candidates if path.exists()]


def output_text(parser_output: dict[str, Any]) -> str:
    pieces: list[str] = []
    for page in parser_output.get("pages", []) or []:
        if isinstance(page, dict):
            pieces.append(str(page.get("text") or ""))
    for block in parser_output.get("text_blocks", []) or []:
        if isinstance(block, dict):
            pieces.append(str(block.get("text") or ""))
    for pair in parser_output.get("key_value_pairs", []) or []:
        if isinstance(pair, dict):
            pieces.append(f"{pair.get('key')}: {pair.get('value')}")
    for table in parser_output.get("tables", []) or []:
        rows = table.get("rows") if isinstance(table, dict) else None
        if isinstance(rows, list):
            pieces.append(json.dumps(rows, ensure_ascii=False))
    return normalize("\n".join(pieces))


def table_text(parser_output: dict[str, Any]) -> str:
    return normalize(
        "\n".join(
            json.dumps(table.get("rows", []), ensure_ascii=False)
            for table in parser_output.get("tables", []) or []
            if isinstance(table, dict)
        )
    )


def shape_errors(parser_output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL_FIELDS - parser_output.keys())
    if missing:
        errors.append(f"missing top-level fields: {', '.join(missing)}")
    if parser_output.get("status") not in VALID_STATUSES:
        errors.append(f"invalid status: {parser_output.get('status')}")
    for field in ("pages", "tables", "key_value_pairs", "text_blocks", "source_references", "warnings"):
        if not isinstance(parser_output.get(field), list):
            errors.append(f"{field} must be a list")
    return errors


def table_expected_for_mode(mode: str, parser_name: str, input_path: Path) -> bool:
    if mode == "aws":
        return True
    if parser_name == "openpyxl":
        return True
    return False


def evaluate_parser_output(
    *,
    mode: str,
    input_path: Path,
    expected: dict[str, Any],
    parser_output: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    document_id = str(expected["document_id"])
    parser_name = str(parser_output.get("parser_name") or "")
    shape = shape_errors(parser_output)
    rows.append(
        result_row(
            document_id=document_id,
            mode=mode,
            input_path=input_path,
            parser_name=parser_name,
            check="parser_output_shape",
            expected="valid parser_output contract",
            actual="; ".join(shape) if shape else "valid",
            status="fail" if shape else "pass",
            failure_category="parser_contract_gap" if shape else "",
        )
    )

    text = output_text(parser_output)
    for expected_text in expected.get("expected_text_contains", []) or []:
        ok = normalize(expected_text) in text
        rows.append(
            result_row(
                document_id=document_id,
                mode=mode,
                input_path=input_path,
                parser_name=parser_name,
                check="text_contains",
                expected=expected_text,
                actual="present" if ok else "missing",
                status="pass" if ok else "fail",
                failure_category="" if ok else "parser_content_gap",
            )
        )

    expected_tables = list(expected.get("expected_tables", []) or [])
    if expected.get("expected_table"):
        expected_tables.append(expected["expected_table"])
    for index, expected_table in enumerate(expected_tables, start=1):
        headers = expected_table.get("headers") or []
        required_rows = expected_table.get("required_rows") or []
        required_cells = expected_table.get("required_cells") or []
        table_required = table_expected_for_mode(mode, parser_name, input_path)
        if not table_required:
            rows.append(
                result_row(
                    document_id=document_id,
                    mode=mode,
                    input_path=input_path,
                    parser_name=parser_name,
                    check=f"table::{index}",
                    expected=expected_table.get("name") or headers,
                    actual="not required for this parser contract",
                    status="skipped",
                    failure_category="parser_contract_exclusion",
                )
            )
            continue
        haystack = table_text(parser_output)
        expected_values = [*headers, *[cell for row in required_rows for cell in row], *required_cells]
        missing = [value for value in expected_values if normalize(value) not in haystack]
        rows.append(
            result_row(
                document_id=document_id,
                mode=mode,
                input_path=input_path,
                parser_name=parser_name,
                check=f"table::{index}",
                expected=expected_table.get("name") or headers,
                actual="missing: " + ", ".join(missing) if missing else "present",
                status="fail" if missing else "pass",
                failure_category="parser_table_gap" if missing else "",
            )
        )
    return rows


def result_row(
    *,
    document_id: str,
    mode: str,
    input_path: Path,
    parser_name: str,
    check: str,
    expected: Any,
    actual: Any,
    status: str,
    failure_category: str = "",
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "mode": mode,
        "input_file": str(input_path),
        "parser_name": parser_name,
        "check": check,
        "expected": json.dumps(expected, ensure_ascii=False) if isinstance(expected, (dict, list)) else expected,
        "actual": json.dumps(actual, ensure_ascii=False) if isinstance(actual, (dict, list)) else actual,
        "status": status,
        "failure_category": failure_category,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "document_id",
        "mode",
        "input_file",
        "parser_name",
        "check",
        "expected",
        "actual",
        "status",
        "failure_category",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, rows: list[dict[str, Any]], output_root: Path) -> None:
    total = len(rows)
    passed = sum(1 for row in rows if row["status"] == "pass")
    failed = sum(1 for row in rows if row["status"] == "fail")
    skipped = sum(1 for row in rows if row["status"] == "skipped")
    lines = [
        "# Parser Comparison Smoke Report",
        "",
        "This report evaluates parser-layer output only. It checks whether local parser and optional live AWS Textract outputs preserve expected content and conform to the parser_output shape needed by downstream S1 pipeline stages.",
        "",
        "## Summary",
        "",
        f"- Total checks: **{total}**",
        f"- Passed: **{passed}**",
        f"- Failed: **{failed}**",
        f"- Skipped: **{skipped}**",
        f"- Output root: `{output_root}`",
        "",
        "## Results",
        "",
        "| Document | Mode | Parser | Check | Status | Expected | Actual |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        expected = collapse(row["expected"])[:140]
        actual = collapse(row["actual"])[:140]
        lines.append(
            f"| `{row['document_id']}` | `{row['mode']}` | `{row['parser_name']}` | `{row['check']}` | {row['status']} | {expected} | {actual} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(fixture_root: Path, output_root: Path, include_aws: bool, aws_input_kind: str) -> list[dict[str, Any]]:
    expected_files = sorted((fixture_root / "stage_2_parser_ocr").glob("*.parser_expected.json"))
    output_root.mkdir(parents=True, exist_ok=True)
    parser_outputs_dir = output_root / "parser_outputs"
    parser_outputs_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for expected_path in expected_files:
        expected = read_json(expected_path)
        document_id = str(expected["document_id"])

        for input_path in converted_inputs(fixture_root, document_id):
            with temporary_env(TEXTRACT_ENABLED="false"):
                parser_output = ParserService().parse_document(
                    input_path,
                    document_id=document_id,
                    processing_run_id=f"parser-comparison::local::{document_id}",
                )
            output_file = parser_outputs_dir / f"{document_id}__local__{safe_stem(input_path.name)}.parser_output.json"
            output_file.write_text(json.dumps(parser_output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            rows.extend(
                evaluate_parser_output(
                    mode="local",
                    input_path=input_path,
                    expected=expected,
                    parser_output=parser_output,
                )
            )

        if include_aws:
            for input_path in aws_inputs(fixture_root, document_id, aws_input_kind):
                with temporary_env(TEXTRACT_ENABLED="true"):
                    parser_output = ParserService().parse_document(
                        input_path,
                        document_id=document_id,
                        processing_run_id=f"parser-comparison::aws::{document_id}",
                    )
                output_file = parser_outputs_dir / f"{document_id}__aws__{safe_stem(input_path.name)}.parser_output.json"
                output_file.write_text(json.dumps(parser_output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                rows.extend(
                    evaluate_parser_output(
                        mode="aws",
                        input_path=input_path,
                        expected=expected,
                        parser_output=parser_output,
                    )
                )
    write_csv(output_root / "parser_comparison_results.csv", rows)
    write_report(output_root / "parser_comparison_report.md", rows, output_root)
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-vs-AWS parser comparison smoke checks.")
    parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--include-aws", action="store_true", help="Run live AWS Textract on OCR PNG/PDF fixtures.")
    parser.add_argument(
        "--fail-on-parser-gaps",
        action="store_true",
        help="Exit nonzero when parser content/contract checks fail. By default the script reports gaps but exits 0.",
    )
    parser.add_argument(
        "--aws-input-kind",
        choices=("png", "pdf", "both"),
        default="png",
        help="Which OCR fixtures to send to live Textract when --include-aws is set.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = run(
        fixture_root=Path(args.fixture_root).resolve(),
        output_root=Path(args.output_root).resolve(),
        include_aws=args.include_aws,
        aws_input_kind=args.aws_input_kind,
    )
    failed = sum(1 for row in rows if row["status"] == "fail")
    print(f"Wrote parser comparison report with {len(rows)} checks; failures={failed}.")
    print(Path(args.output_root).resolve() / "parser_comparison_report.md")
    return 1 if args.fail_on_parser_gaps and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
