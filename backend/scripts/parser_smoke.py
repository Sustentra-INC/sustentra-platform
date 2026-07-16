"""Local parser smoke-test harness (PR4.1).

Runs the PR4 parser runtime against local sample documents and writes one
``parser_output`` JSON per input file plus a completeness report. This exercises
the parser layer only; it performs no field extraction, no ``extraction_candidate``
generation, and no external calls (AWS, OpenAI, OCR, or network).

Usage::

    python backend/scripts/parser_smoke.py \
        --input-dir "local-samples/parser-smoke/inputs" \
        --output-dir "local-samples/parser-smoke/outputs"

Both directories default to the ``local-samples/parser-smoke`` tree, which is
git-ignored. Sample documents are private and are never committed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the repository root is importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.parser_service import ParserService  # noqa: E402

DEFAULT_INPUT_DIR = "local-samples/parser-smoke/inputs"
DEFAULT_OUTPUT_DIR = "local-samples/parser-smoke/outputs"

REPORT_FILE_NAME = "parser_smoke_report.md"
SUMMARY_FILE_NAME = "parser_smoke_summary.json"

REPORT_DISCLAIMER = (
    "This smoke report evaluates parser_output completeness only. It does not "
    "validate field extraction, ESG values, extraction_candidate generation, "
    "review decisions, or approved evidence."
)


def _safe_stem(file_name: str) -> str:
    """Return a filesystem-safe stem for an output file name."""

    stem = Path(file_name).stem
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_")
    return safe or "document"


def _is_hidden(path: Path) -> bool:
    return path.name.startswith(".")


def _usable_for_extraction_later(summary: dict[str, Any]) -> bool:
    """Parser-completeness signal (not ESG extraction completeness)."""

    if summary["status"] not in {"parsed", "partial"}:
        return False
    content_count = (
        summary["text_block_count"]
        + summary["table_count"]
        + summary["key_value_pair_count"]
    )
    return content_count > 0


def _summarize(output: dict[str, Any], file_name: str, output_json_path: str) -> dict[str, Any]:
    warnings = output.get("warnings", []) or []
    summary = {
        "file_name": file_name,
        "extension": Path(file_name).suffix.lower(),
        "parser_name": output.get("parser_name"),
        "status": output.get("status"),
        "page_count": len(output.get("pages", []) or []),
        "text_block_count": len(output.get("text_blocks", []) or []),
        "table_count": len(output.get("tables", []) or []),
        "key_value_pair_count": len(output.get("key_value_pairs", []) or []),
        "source_reference_count": len(output.get("source_references", []) or []),
        "warning_count": len(warnings),
        "warnings": [
            {
                "code": warning.get("code"),
                "message": warning.get("message"),
                "severity": warning.get("severity"),
            }
            for warning in warnings
        ],
        "output_json_path": output_json_path,
    }
    summary["usable_for_extraction_later"] = _usable_for_extraction_later(summary)
    return summary


def _collect_input_files(input_dir: Path) -> list[Path]:
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    files = [
        entry
        for entry in sorted(input_dir.iterdir(), key=lambda p: p.name.lower())
        if entry.is_file() and not _is_hidden(entry)
    ]
    return files


def run_smoke(input_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Parse every file in ``input_dir`` and write outputs to ``output_dir``.

    Returns a machine-readable summary dictionary. Never raises on individual
    parser problems: the parser runtime already normalizes failures into
    ``failed``/``empty`` outputs with warnings.
    """

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    parser_service = ParserService()
    files = _collect_input_files(input_path)

    per_file: list[dict[str, Any]] = []
    used_stems: set[str] = set()

    for index, file_path in enumerate(files, start=1):
        stem = _safe_stem(file_path.name)
        unique_stem = stem
        suffix_counter = 1
        while unique_stem in used_stems:
            suffix_counter += 1
            unique_stem = f"{stem}_{suffix_counter}"
        used_stems.add(unique_stem)

        json_file = output_path / f"{unique_stem}.parser_output.json"

        document_id = f"SMOKE-DOC-{index:04d}"
        processing_run_id = f"SMOKE-RUN-{index:04d}"

        output = parser_service.parse_document(
            file_path=file_path,
            document_id=document_id,
            processing_run_id=processing_run_id,
            mime_type=None,
        )

        with json_file.open("w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2, ensure_ascii=False)

        # Store a workspace-relative path when possible for portability.
        try:
            json_rel = json_file.resolve().relative_to(_REPO_ROOT)
            json_display = str(json_rel).replace("\\", "/")
        except ValueError:
            json_display = json_file.name

        per_file.append(_summarize(output, file_path.name, json_display))

    status_counts = {"parsed": 0, "partial": 0, "empty": 0, "failed": 0}
    for entry in per_file:
        status = entry["status"]
        if status in status_counts:
            status_counts[status] += 1

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path).replace("\\", "/"),
        "output_dir": str(output_path).replace("\\", "/"),
        "file_count": len(per_file),
        "status_counts": status_counts,
        "usable_for_extraction_later_count": sum(
            1 for entry in per_file if entry["usable_for_extraction_later"]
        ),
        "files": per_file,
        "note": REPORT_DISCLAIMER,
    }

    _write_report(output_path / REPORT_FILE_NAME, summary)
    with (output_path / SUMMARY_FILE_NAME).open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    return summary


def _write_report(report_path: Path, summary: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Parser Smoke Report")
    lines.append("")
    lines.append(f"- Generated at: {summary['generated_at']}")
    lines.append(f"- Input dir: `{summary['input_dir']}`")
    lines.append(f"- Output dir: `{summary['output_dir']}`")
    lines.append(f"- Files processed: {summary['file_count']}")
    counts = summary["status_counts"]
    lines.append(
        "- Status counts: "
        f"parsed={counts['parsed']}, partial={counts['partial']}, "
        f"empty={counts['empty']}, failed={counts['failed']}"
    )
    lines.append(
        f"- Usable for extraction later: {summary['usable_for_extraction_later_count']}"
    )
    lines.append("")
    lines.append(f"> {summary['note']}")
    lines.append("")

    if not summary["files"]:
        lines.append("_No input files were found._")
        lines.append("")
    else:
        header = (
            "| file_name | extension | parser_name | status | pages | text_blocks | "
            "tables | key_value_pairs | source_refs | warnings | usable_for_extraction_later | output_json_path |"
        )
        divider = "|" + "|".join(["---"] * 12) + "|"
        lines.append(header)
        lines.append(divider)
        for entry in summary["files"]:
            lines.append(
                "| {file_name} | {extension} | {parser_name} | {status} | {pages} | "
                "{text_blocks} | {tables} | {kv} | {refs} | {warnings} | {usable} | `{path}` |".format(
                    file_name=entry["file_name"],
                    extension=entry["extension"] or "",
                    parser_name=entry["parser_name"],
                    status=entry["status"],
                    pages=entry["page_count"],
                    text_blocks=entry["text_block_count"],
                    tables=entry["table_count"],
                    kv=entry["key_value_pair_count"],
                    refs=entry["source_reference_count"],
                    warnings=entry["warning_count"],
                    usable=str(entry["usable_for_extraction_later"]).lower(),
                    path=entry["output_json_path"],
                )
            )
        lines.append("")

        # Per-file warning details.
        warned = [entry for entry in summary["files"] if entry["warnings"]]
        if warned:
            lines.append("## Warnings")
            lines.append("")
            for entry in warned:
                lines.append(f"### {entry['file_name']}")
                for warning in entry["warnings"]:
                    lines.append(
                        f"- `{warning['code']}` ({warning['severity']}): {warning['message']}"
                    )
                lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PR4 parser runtime against local sample documents.",
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_smoke(args.input_dir, args.output_dir)

    counts = summary["status_counts"]
    print(f"Processed {summary['file_count']} file(s) from {summary['input_dir']}")
    print(
        "Status: "
        f"parsed={counts['parsed']}, partial={counts['partial']}, "
        f"empty={counts['empty']}, failed={counts['failed']}"
    )
    print(f"Report: {Path(summary['output_dir']) / REPORT_FILE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
