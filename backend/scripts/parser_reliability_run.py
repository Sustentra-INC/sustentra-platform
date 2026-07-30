"""Run parser reliability checks against parser_reliability_test_set.

The fixture set supplies raw documents plus parser-level expected-answer JSON
sidecars. This script evaluates parser_output shape, expected content
preservation, table/key-value containment, warning codes, and basic
traceability. Live AWS Textract cases are skipped unless ``--include-aws`` is
provided.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.parser_service import ParserService  # noqa: E402

DEFAULT_FIXTURE_ROOT = _REPO_ROOT / "parser_reliability_test_set"
DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "local-data" / "parser-reliability-results"

AWS_MODES = {"aws_textract_image", "aws_textract_pdf"}
OFFLINE_TEXTRACT_MODE = "offline_textract_json"
LOCAL_MODES = {"text", "csv_text", "excel", "local_pdf"}

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

SOURCE_KIND_ALIASES = {
    "document_text": "page_text",
    "sheet_cell": "excel_cell",
    "table_cell": "excel_cell",
    "ocr_line": "page_text",
    "ocr_word": "page_text",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collapse(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize(value: Any) -> str:
    return collapse(value).casefold()


def compact_alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize(value))


def contains_expected_text(haystack: str, expected_text: Any) -> bool:
    normalized_expected = normalize(expected_text)
    if normalized_expected in haystack:
        return True
    compact_expected = compact_alnum(expected_text)
    return bool(compact_expected) and compact_expected in compact_alnum(haystack)


def parser_output_candidates(parser_output: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for block in parser_output.get("text_blocks", []) or []:
        if isinstance(block, dict) and block.get("text"):
            candidates.append(str(block["text"]))
    for page in parser_output.get("pages", []) or []:
        if not isinstance(page, dict):
            continue
        for line in str(page.get("text") or "").splitlines():
            if line.strip():
                candidates.append(line.strip())
    for pair in parser_output.get("key_value_pairs", []) or []:
        if isinstance(pair, dict):
            key = str(pair.get("key") or "").strip()
            value = str(pair.get("value") or "").strip()
            if key or value:
                candidates.append(f"{key}: {value}".strip(": "))
                if value:
                    candidates.append(value)
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        collapsed = collapse(candidate)
        if collapsed and collapsed not in seen:
            seen.add(collapsed)
            unique.append(collapsed)
    return unique


def closest_actual_text(parser_output: dict[str, Any], expected_text: Any) -> str:
    expected_compact = compact_alnum(expected_text)
    if not expected_compact:
        return "missing; no comparable expected text"

    scored: list[tuple[float, str]] = []
    for candidate in parser_output_candidates(parser_output):
        candidate_compact = compact_alnum(candidate)
        if not candidate_compact:
            continue
        score = SequenceMatcher(None, expected_compact, candidate_compact).ratio()
        scored.append((score, candidate))

    if not scored:
        return "missing; parser output contained no comparable text"

    scored.sort(key=lambda item: item[0], reverse=True)
    closest = "; ".join(
        f"{collapse(candidate)[:140]} (similarity={score:.2f})"
        for score, candidate in scored[:3]
    )
    return f"missing; closest OCR/parser text: {closest}"


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


def load_manifest(fixture_root: Path) -> list[dict[str, Any]]:
    manifest_path = fixture_root / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if isinstance(manifest, list):
            return manifest
        if isinstance(manifest, dict):
            return list(manifest.get("fixtures", []))
    raise FileNotFoundError(f"Parser reliability manifest not found: {manifest_path}")


def validate_fixture_set(fixture_root: Path, manifest: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for item in manifest:
        document_id = str(item.get("document_id") or "")
        if not document_id:
            issues.append("manifest row missing document_id")
            continue
        if document_id in seen:
            issues.append(f"duplicate document_id: {document_id}")
        seen.add(document_id)
        for field in ("document_style", "parser_mode", "file_path", "complexity_level", "expected_file"):
            if not item.get(field):
                issues.append(f"{document_id}: manifest missing {field}")
        raw_path = fixture_root / str(item.get("file_path") or "")
        expected_path = fixture_root / str(item.get("expected_file") or "")
        if not raw_path.exists():
            issues.append(f"{document_id}: raw file missing: {raw_path}")
        if not expected_path.exists():
            issues.append(f"{document_id}: expected sidecar missing: {expected_path}")
            continue
        try:
            expected = read_json(expected_path)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"{document_id}: expected sidecar is invalid JSON: {type(exc).__name__}")
            continue
        for field in (
            "document_id",
            "document_style",
            "parser_modes",
            "raw_files",
            "complexity_level",
            "expected_parser_output",
            "traceability_expectations",
        ):
            if field not in expected:
                issues.append(f"{document_id}: sidecar missing {field}")
        if expected.get("document_id") != document_id:
            issues.append(
                f"{document_id}: sidecar document_id mismatch: {expected.get('document_id')}"
            )
    return issues


def parse_fixture(
    fixture_root: Path,
    item: dict[str, Any],
    expected: dict[str, Any],
    *,
    include_aws: bool,
) -> tuple[dict[str, Any] | None, str]:
    document_id = str(item["document_id"])
    mode = str(item["parser_mode"])
    raw_path = fixture_root / str(item["file_path"])
    if mode in AWS_MODES and not include_aws:
        return None, "aws_skipped"
    if mode in AWS_MODES:
        with temporary_env(TEXTRACT_ENABLED="true"):
            return (
                ParserService().parse_document(
                    raw_path,
                    document_id=document_id,
                    processing_run_id=f"parser-reliability::aws::{document_id}",
                ),
                "parsed",
            )
    if mode == OFFLINE_TEXTRACT_MODE:
        return (
            ParserService().parse_textract_json(
                raw_path,
                document_id=document_id,
                processing_run_id=f"parser-reliability::offline-textract::{document_id}",
            ),
            "parsed",
        )
    with temporary_env(TEXTRACT_ENABLED="false"):
        return (
            ParserService().parse_document(
                raw_path,
                document_id=document_id,
                processing_run_id=f"parser-reliability::local::{document_id}",
            ),
            "parsed",
        )


def load_saved_parser_output(
    parser_outputs_dir: Path,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    pattern = f"{item['document_id']}__{item['parser_mode']}__*.parser_output.json"
    matches = sorted(parser_outputs_dir.glob(pattern))
    if not matches:
        return None
    return read_json(matches[0])


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
        if isinstance(table, dict):
            pieces.append(json.dumps(table.get("rows", []), ensure_ascii=False))
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


def expected_status_ok(expected_status: str, actual_status: str | None) -> bool:
    if expected_status == "succeeded":
        return actual_status in {"parsed", "partial"}
    if expected_status == "failed":
        return actual_status == "failed"
    if expected_status:
        return actual_status == expected_status
    return actual_status in VALID_STATUSES


def row(
    item: dict[str, Any],
    *,
    check: str,
    expected: Any,
    actual: Any,
    status: str,
    failure_category: str = "",
    parser_name: str = "",
) -> dict[str, Any]:
    return {
        "document_id": item.get("document_id"),
        "document_style": item.get("document_style"),
        "parser_mode": item.get("parser_mode"),
        "complexity_level": item.get("complexity_level"),
        "file_path": item.get("file_path"),
        "parser_name": parser_name,
        "check": check,
        "expected": json.dumps(expected, ensure_ascii=False) if isinstance(expected, (dict, list)) else expected,
        "actual": json.dumps(actual, ensure_ascii=False) if isinstance(actual, (dict, list)) else actual,
        "status": status,
        "failure_category": failure_category,
    }


def evaluate_output(item: dict[str, Any], expected: dict[str, Any], parser_output: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    parser_name = str(parser_output.get("parser_name") or "")
    expected_parser = expected.get("expected_parser_output") or {}

    errors = shape_errors(parser_output)
    rows.append(
        row(
            item,
            check="parser_output_shape",
            expected="valid parser_output contract",
            actual="; ".join(errors) if errors else "valid",
            status="fail" if errors else "pass",
            failure_category="parser_contract_gap" if errors else "",
            parser_name=parser_name,
        )
    )

    expected_status = str(expected.get("expected_status") or "")
    actual_status = parser_output.get("status")
    ok_status = expected_status_ok(expected_status, str(actual_status))
    rows.append(
        row(
            item,
            check="status",
            expected=expected_status or "any valid status",
            actual=actual_status,
            status="pass" if ok_status else "fail",
            failure_category="" if ok_status else "parser_status_gap",
            parser_name=parser_name,
        )
    )

    haystack = output_text(parser_output)
    for expected_text in expected_parser.get("text_contains", []) or []:
        ok = contains_expected_text(haystack, expected_text)
        rows.append(
            row(
                item,
                check="text_contains",
                expected=expected_text,
                actual="present" if ok else closest_actual_text(parser_output, expected_text),
                status="pass" if ok else "fail",
                failure_category="" if ok else "parser_content_gap",
                parser_name=parser_name,
            )
        )

    tables_haystack = table_text(parser_output)
    for index, table in enumerate(expected_parser.get("table_expectations", []) or [], start=1):
        expected_values = [
            *(table.get("headers") or []),
            *[cell for required_row in (table.get("required_rows") or []) for cell in required_row],
            *(table.get("required_cells") or []),
        ]
        missing = [value for value in expected_values if normalize(value) not in tables_haystack]
        required = bool(table.get("required", True))
        ok = not missing
        rows.append(
            row(
                item,
                check=f"table::{index}",
                expected=table,
                actual="present" if ok else "missing: " + ", ".join(missing),
                status="pass" if ok else ("fail" if required else "skipped"),
                failure_category="" if ok else "parser_table_gap",
                parser_name=parser_name,
            )
        )

    pair_texts = [
        (normalize(pair.get("key")), normalize(pair.get("value")))
        for pair in parser_output.get("key_value_pairs", []) or []
        if isinstance(pair, dict)
    ]
    for index, pair in enumerate(expected_parser.get("key_value_expectations", []) or [], start=1):
        expected_key = normalize(pair.get("key"))
        expected_value = normalize(pair.get("value"))
        required = bool(pair.get("required", True))
        ok = any(expected_key in key and expected_value in value for key, value in pair_texts)
        rows.append(
            row(
                item,
                check=f"key_value::{index}",
                expected=pair,
                actual="present" if ok else "missing",
                status="pass" if ok else ("fail" if required else "skipped"),
                failure_category="" if ok else "parser_key_value_gap",
                parser_name=parser_name,
            )
        )

    traceability = expected.get("traceability_expectations") or {}
    refs = [
        ref
        for ref in parser_output.get("source_references", []) or []
        if isinstance(ref, dict)
    ]
    if traceability.get("requires_source_references"):
        ok = bool(refs)
        rows.append(
            row(
                item,
                check="source_references_present",
                expected="at least one source reference",
                actual=len(refs),
                status="pass" if ok else "fail",
                failure_category="" if ok else "parser_traceability_gap",
                parser_name=parser_name,
            )
        )
    expected_kinds = {
        SOURCE_KIND_ALIASES.get(str(kind), str(kind))
        for kind in (traceability.get("expected_source_kinds") or [])
    }
    actual_kinds = {str(ref.get("source_kind")) for ref in refs if ref.get("source_kind")}
    if expected_kinds:
        ok = bool(expected_kinds & actual_kinds)
        rows.append(
            row(
                item,
                check="source_kind",
                expected=sorted(expected_kinds),
                actual=sorted(actual_kinds),
                status="pass" if ok else "fail",
                failure_category="" if ok else "parser_traceability_gap",
                parser_name=parser_name,
            )
        )

    expected_warning_codes = set(expected.get("expected_warning_codes") or [])
    actual_warning_codes = {
        str(warning.get("code"))
        for warning in parser_output.get("warnings", []) or []
        if isinstance(warning, dict) and warning.get("code")
    }
    if expected_warning_codes:
        missing = expected_warning_codes - actual_warning_codes
        rows.append(
            row(
                item,
                check="warning_codes",
                expected=sorted(expected_warning_codes),
                actual=sorted(actual_warning_codes),
                status="fail" if missing else "pass",
                failure_category="parser_warning_gap" if missing else "",
                parser_name=parser_name,
            )
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "document_id",
        "document_style",
        "parser_mode",
        "complexity_level",
        "file_path",
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


def grouped_counts(rows: list[dict[str, Any]], key: str) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for result in rows:
        grouped[str(result.get(key) or "")][str(result["status"])] += 1
    return dict(grouped)


def markdown_table_counts(grouped: dict[str, Counter[str]], label: str) -> list[str]:
    lines = [f"| {label} | Passed | Failed | Skipped |", "|---|---:|---:|---:|"]
    for key in sorted(grouped):
        counts = grouped[key]
        lines.append(
            f"| `{key}` | {counts.get('pass', 0)} | {counts.get('fail', 0)} | {counts.get('skipped', 0)} |"
        )
    return lines


def write_report(
    path: Path,
    *,
    fixture_root: Path,
    output_root: Path,
    manifest: list[dict[str, Any]],
    fixture_issues: list[str],
    rows: list[dict[str, Any]],
    include_aws: bool,
) -> None:
    status_counts = Counter(row["status"] for row in rows)
    fixture_counts = Counter(str(item.get("parser_mode")) for item in manifest)
    style_counts = Counter(str(item.get("document_style")) for item in manifest)
    complexity_counts = Counter(str(item.get("complexity_level")) for item in manifest)
    failures = [row for row in rows if row["status"] == "fail"]
    skipped = [row for row in rows if row["status"] == "skipped"]
    failure_category_counts = Counter(row["failure_category"] for row in failures)

    lines = [
        "# Parser Reliability Test Report",
        "",
        "## Purpose",
        "",
        "This report evaluates parser reliability only: raw fixture -> parser -> parser_output. It checks output shape, status, expected content preservation, table/key-value containment, warning codes, and source-reference readiness for downstream S1 stages.",
        "",
        "It does not evaluate classification, target planning, deterministic extraction, normalization, review, approved evidence, or calculations.",
        "",
        "## Fixture Set Check",
        "",
        f"- Fixture root: `{fixture_root}`",
        f"- Output root: `{output_root}`",
        f"- Manifest fixtures: **{len(manifest)}**",
        f"- Fixture integrity issues: **{len(fixture_issues)}**",
        f"- Live AWS Textract included: **{'yes' if include_aws else 'no'}**",
        "- Source-kind calibration: expected `document_text`, `ocr_line`, `ocr_word`, `sheet_cell`, and `table_cell` are normalized to the parser contract kinds used by the repo.",
        "- Text-containment calibration: `text_contains` checks allow OCR-safe punctuation and spacing differences while still requiring the same alphanumeric content in order.",
        "",
    ]
    if fixture_issues:
        lines.extend(["Fixture issues:", ""])
        lines.extend(f"- {issue}" for issue in fixture_issues)
        lines.append("")
    else:
        lines.append("The folder contains the required manifest, raw files, expected sidecars, parser metadata, and expectation sections.")
        lines.append("")

    lines.extend(["## Fixture Coverage", ""])
    lines.extend(["Parser-mode fixture counts:", ""])
    lines.extend(f"- `{mode}`: {count}" for mode, count in sorted(fixture_counts.items()))
    lines.extend(["", "Document-style fixture counts:", ""])
    lines.extend(f"- `{style}`: {count}" for style, count in sorted(style_counts.items()))
    lines.extend(["", "Complexity fixture counts:", ""])
    lines.extend(f"- `{level}`: {count}" for level, count in sorted(complexity_counts.items()))

    total = len(rows)
    lines.extend(
        [
            "",
            "## Results Summary",
            "",
            f"- Total checks: **{total}**",
            f"- Passed: **{status_counts.get('pass', 0)}**",
            f"- Failed: **{status_counts.get('fail', 0)}**",
            f"- Skipped: **{status_counts.get('skipped', 0)}**",
            "",
            "Skipped checks are expected when live AWS fixtures are present but `--include-aws` was not used.",
            "",
            "### By Parser Mode",
            "",
        ]
    )
    lines.extend(markdown_table_counts(grouped_counts(rows, "parser_mode"), "Parser mode"))
    lines.extend(["", "### By Document Style", ""])
    lines.extend(markdown_table_counts(grouped_counts(rows, "document_style"), "Document style"))
    lines.extend(["", "### By Complexity", ""])
    lines.extend(markdown_table_counts(grouped_counts(rows, "complexity_level"), "Complexity"))
    lines.extend(["", "### By Failure Category", ""])
    if failure_category_counts:
        lines.extend(["| Category | Count |", "|---|---:|"])
        lines.extend(
            f"| `{category}` | {count} |"
            for category, count in sorted(failure_category_counts.items())
        )
    else:
        lines.append("No failed checks.")

    lines.extend(["", "## Failure Details", ""])
    if not failures:
        lines.append("No failed checks.")
    else:
        lines.extend(
            [
                "| Document | Style | Mode | Complexity | Parser | Check | Expected | Actual | Category |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for failure in failures:
            expected = collapse(failure["expected"])[:180]
            actual = collapse(failure["actual"])[:180]
            lines.append(
                f"| `{failure['document_id']}` | `{failure['document_style']}` | `{failure['parser_mode']}` | `{failure['complexity_level']}` | `{failure['parser_name']}` | `{failure['check']}` | {expected} | {actual} | `{failure['failure_category']}` |"
            )

    lines.extend(["", "## Gap Analysis", ""])
    if failures:
        csv_table_failures = [
            failure
            for failure in failures
            if failure["parser_mode"] == "csv_text" and failure["check"].startswith("table::")
        ]
        non_csv_failures = [failure for failure in failures if failure not in csv_table_failures]
        if csv_table_failures:
            lines.append(
                f"- **CSV structured tables:** {len(csv_table_failures)} CSV fixtures preserved text but failed table checks because `.csv` currently routes to `TextParser`, which emits `pages`, `text_blocks`, and `source_references`, but does not populate `parser_output.tables`. If downstream S1 logic needs row binding from CSV files, this is a parser implementation/contract gap. If CSV-as-text is intentional, the CSV sidecars should use only `text_contains` expectations."
            )
        if non_csv_failures:
            lines.append(
                f"- **Other parser gaps:** {len(non_csv_failures)} non-CSV failures remain. Inspect the detailed CSV and saved parser outputs for exact snippets."
            )
        if csv_table_failures and not non_csv_failures:
            lines.append(
                "- No text, Excel, local embedded-text PDF, or offline Textract JSON parser-output contract failures remain after expectation calibration."
            )
    else:
        lines.append("- No parser reliability gaps were detected for the executed fixtures.")
    if skipped:
        lines.append(
            f"- **Live AWS Textract:** {len(skipped)} checks were skipped. These fixtures require `--include-aws`, valid AWS credentials/region, and explicit approval because the run uploads fixture PDFs/images to AWS Textract."
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `parser_output_shape=valid` means the output has the top-level fields and list structures the downstream pipeline expects.",
            "- `text_contains=present` means an expected parser-level snippet was found somewhere in pages, text blocks, key-value pairs, or tables.",
            "- `missing` means the parser output was structurally usable but did not preserve that expected content.",
            "- Table checks compare headers and required rows/cells against `parser_output.tables`.",
            "- Source-reference checks confirm the parser output has traceability objects, not that final extraction candidates are correct.",
            "",
            "## Output Artifacts",
            "",
            f"- Detailed CSV: `{output_root / 'parser_reliability_results.csv'}`",
            f"- Parser outputs: `{output_root / 'parser_outputs'}`",
        ]
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    fixture_root: Path,
    output_root: Path,
    include_aws: bool,
    *,
    reuse_parser_outputs: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    manifest = load_manifest(fixture_root)
    fixture_issues = validate_fixture_set(fixture_root, manifest)
    output_root.mkdir(parents=True, exist_ok=True)
    parser_outputs_dir = output_root / "parser_outputs"
    parser_outputs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for item in manifest:
        expected_path = fixture_root / str(item["expected_file"])
        expected = read_json(expected_path)
        parser_output = (
            load_saved_parser_output(parser_outputs_dir, item)
            if reuse_parser_outputs and item["parser_mode"] in AWS_MODES
            else None
        )
        parse_status = "parsed" if parser_output is not None else ""
        if parser_output is None:
            parser_output, parse_status = parse_fixture(
                fixture_root,
                item,
                expected,
                include_aws=include_aws,
            )
        if parse_status == "aws_skipped":
            rows.append(
                row(
                    item,
                    check="aws_textract_live_run",
                    expected="live AWS Textract parser output",
                    actual="skipped; rerun with --include-aws",
                    status="skipped",
                    failure_category="aws_not_run",
                )
            )
            continue

        assert parser_output is not None
        parser_name = str(parser_output.get("parser_name") or "")
        output_file = parser_outputs_dir / f"{item['document_id']}__{item['parser_mode']}__{safe_stem(parser_name)}.parser_output.json"
        output_file.write_text(
            json.dumps(parser_output, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        rows.extend(evaluate_output(item, expected, parser_output))

    write_csv(output_root / "parser_reliability_results.csv", rows)
    write_report(
        output_root / "parser_reliability_report.md",
        fixture_root=fixture_root,
        output_root=output_root,
        manifest=manifest,
        fixture_issues=fixture_issues,
        rows=rows,
        include_aws=include_aws,
    )
    return rows, fixture_issues


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run parser reliability checks.")
    parser.add_argument("--fixture-root", default=str(DEFAULT_FIXTURE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--include-aws", action="store_true", help="Run live AWS Textract fixtures.")
    parser.add_argument(
        "--reuse-parser-outputs",
        action="store_true",
        help="Evaluate already-saved parser_outputs files when present instead of reparsing those fixtures.",
    )
    parser.add_argument(
        "--fail-on-parser-gaps",
        action="store_true",
        help="Exit nonzero when parser checks fail. By default the script writes the report and exits 0.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, fixture_issues = run(
        fixture_root=Path(args.fixture_root).resolve(),
        output_root=Path(args.output_root).resolve(),
        include_aws=args.include_aws,
        reuse_parser_outputs=args.reuse_parser_outputs,
    )
    failures = sum(1 for result in rows if result["status"] == "fail")
    print(
        f"Wrote parser reliability report with {len(rows)} checks; "
        f"fixture_issues={len(fixture_issues)}; failures={failures}."
    )
    print(Path(args.output_root).resolve() / "parser_reliability_report.md")
    return 1 if args.fail_on_parser_gaps and (failures or fixture_issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
