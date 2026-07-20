"""Local end-to-end extraction smoke harness (PR6.1).

Runs the existing local pipeline against private, git-ignored sample documents:

    sample docs (optional refresh)
    -> parser_output JSON (PR4/PR4.1)
    -> canonical_type_id selection (mapping / embedded / default)
    -> ExtractionTargetService (PR5)
    -> ExtractionService.extract(...) (PR6)
    -> extraction_candidate JSON + completeness report

This is a smoke harness only. It adds no product API, persistence, review
decisions, approved evidence, RAG, S2, OCR, or external calls, and it never
mutates parser outputs or sample documents. All generated outputs are written
under the ignored ``local-samples/`` tree.

Usage::

    python backend/scripts/extraction_smoke.py \
        --parser-output-dir "local-samples/parser-smoke/outputs" \
        --output-dir "local-samples/extraction-smoke/outputs" \
        --default-canonical-type-id "CT-S1-FUELQTY"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the repository root is importable when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.extraction_service import ExtractionService  # noqa: E402
from backend.app.services.extraction_target_service import ExtractionTargetService  # noqa: E402
from backend.scripts.parser_smoke import _safe_stem, run_smoke  # noqa: E402

DEFAULT_INPUT_DOC_DIR = "local-samples/parser-smoke/inputs"
DEFAULT_PARSER_OUTPUT_DIR = "local-samples/parser-smoke/outputs"
DEFAULT_OUTPUT_DIR = "local-samples/extraction-smoke/outputs"
DEFAULT_CANONICAL_TYPE_ID = "CT-S1-FUELQTY"

REPORT_FILE_NAME = "extraction_smoke_report.md"
SUMMARY_FILE_NAME = "extraction_smoke_summary.json"

PARSER_OUTPUT_SUFFIX = ".parser_output.json"
CANDIDATE_SUFFIX = ".extraction_candidates.json"

LOW_CONFIDENCE_THRESHOLD = 0.50
SNIPPET_TRUNCATE_LENGTH = 180

REPORT_DISCLAIMER = (
    "This smoke report evaluates deterministic extraction_candidate generation "
    "from existing parser_output and extraction targets. It is not a human review "
    "result, approved evidence record, regulatory validation, calculation result, "
    "or gap analysis."
)


def _base_stem(file_name: str) -> str:
    if file_name.endswith(PARSER_OUTPUT_SUFFIX):
        return file_name[: -len(PARSER_OUTPUT_SUFFIX)]
    return Path(file_name).stem


def _load_mapping(mapping_file: str | Path | None) -> dict[str, str]:
    if not mapping_file:
        return {}
    path = Path(mapping_file)
    if not path.exists() or not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _select_canonical_type(
    parser_output: dict,
    file_name: str,
    base_stem: str,
    mapping: dict[str, str],
    default_canonical_type_id: str,
) -> tuple[str, str]:
    """Return (canonical_type_id, source) using mapping > embedded > default."""

    for key in (file_name, base_stem):
        if key in mapping:
            return mapping[key], "mapping"

    embedded = parser_output.get("canonical_type_id")
    if isinstance(embedded, str) and embedded.strip():
        return embedded.strip(), "parser_output"

    return default_canonical_type_id, "default"


def _collect_parser_output_files(parser_output_dir: Path) -> list[Path]:
    if not parser_output_dir.exists() or not parser_output_dir.is_dir():
        return []
    return [
        entry
        for entry in sorted(parser_output_dir.iterdir(), key=lambda p: p.name.lower())
        if entry.is_file()
        and not entry.name.startswith(".")
        and entry.name.endswith(PARSER_OUTPUT_SUFFIX)
    ]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _summarize_candidates(items: list[dict], target_count: int) -> dict[str, Any]:
    found_count = sum(1 for item in items if item.get("raw_value") is not None)
    missing_count = sum(
        1
        for item in items
        if item.get("raw_value") is None
        or "field_not_found" in (item.get("validation_flags") or [])
    )
    unsupported_count = sum(
        1
        for item in items
        if "unsupported_extraction_method" in (item.get("validation_flags") or [])
    )
    low_confidence_count = sum(
        1 for item in items if float(item.get("confidence", 0.0)) < LOW_CONFIDENCE_THRESHOLD
    )
    if items:
        average_confidence = round(
            sum(float(item.get("confidence", 0.0)) for item in items) / len(items), 3
        )
    else:
        average_confidence = 0.0

    return {
        "target_count": target_count,
        "candidate_count": len(items),
        "found_count": found_count,
        "missing_count": missing_count,
        "unsupported_count": unsupported_count,
        "low_confidence_count": low_confidence_count,
        "average_confidence": average_confidence,
        "found_rate": _rate(found_count, target_count),
        "missing_rate": _rate(missing_count, target_count),
    }


def run_extraction_smoke(
    parser_output_dir: str | Path = DEFAULT_PARSER_OUTPUT_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    default_canonical_type_id: str = DEFAULT_CANONICAL_TYPE_ID,
    mapping_file: str | Path | None = None,
    include_optional: bool = True,
    include_deprecated: bool = False,
    input_doc_dir: str | Path = DEFAULT_INPUT_DOC_DIR,
    refresh_parser_outputs: bool = False,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run the extraction smoke pass and write outputs. Returns a summary dict."""

    parser_output_path = Path(parser_output_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if refresh_parser_outputs:
        run_smoke(input_doc_dir, parser_output_path)

    mapping = _load_mapping(mapping_file)

    target_service = ExtractionTargetService(repo_root=repo_root)
    extraction_service = ExtractionService()

    files = _collect_parser_output_files(parser_output_path)
    per_file: list[dict[str, Any]] = []
    canonical_type_coverage: dict[str, int] = {}

    for index, file_path in enumerate(files, start=1):
        with file_path.open("r", encoding="utf-8") as handle:
            parser_output = json.load(handle)

        base_stem = _base_stem(file_path.name)
        document_id = str(parser_output.get("document_id") or base_stem)
        canonical_type_id, canonical_type_source = _select_canonical_type(
            parser_output, file_path.name, base_stem, mapping, default_canonical_type_id
        )

        targets = target_service.get_targets_for_canonical_type(
            canonical_type_id,
            include_optional=include_optional,
            include_deprecated=include_deprecated,
        )

        evidence_id = f"SMOKE-EVIDENCE-{index:04d}"
        result = extraction_service.extract(
            {
                "parser_output": parser_output,
                "extraction_targets": targets,
                "evidence_id": evidence_id,
            }
        )
        items = result["items"]
        metrics = _summarize_candidates(items, len(targets))

        candidate_stem = _safe_stem(base_stem)
        candidate_file = output_path / f"{candidate_stem}{CANDIDATE_SUFFIX}"
        try:
            candidate_display = str(
                candidate_file.resolve().relative_to(_REPO_ROOT)
            ).replace("\\", "/")
        except ValueError:
            candidate_display = candidate_file.name

        document_record = {
            "source_parser_output": file_path.name,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "canonical_type_id": canonical_type_id,
            "canonical_type_source": canonical_type_source,
            "target_count": metrics["target_count"],
            "candidate_count": metrics["candidate_count"],
            "found_count": metrics["found_count"],
            "missing_count": metrics["missing_count"],
            "unsupported_count": metrics["unsupported_count"],
            "low_confidence_count": metrics["low_confidence_count"],
            "average_confidence": metrics["average_confidence"],
            "items": items,
        }
        with candidate_file.open("w", encoding="utf-8") as handle:
            json.dump(document_record, handle, indent=2, ensure_ascii=False)

        canonical_type_coverage[canonical_type_id] = (
            canonical_type_coverage.get(canonical_type_id, 0) + 1
        )
        per_file.append(
            {
                "file": file_path.name,
                "document_id": document_id,
                "canonical_type_id": canonical_type_id,
                "canonical_type_source": canonical_type_source,
                **metrics,
                "output_json_path": candidate_display,
                "items": items,
            }
        )

    summary = _build_summary(
        per_file=per_file,
        parser_output_path=parser_output_path,
        output_path=output_path,
        canonical_type_coverage=canonical_type_coverage,
    )

    _write_report(output_path / REPORT_FILE_NAME, summary, per_file)
    with (output_path / SUMMARY_FILE_NAME).open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    return summary


def _build_summary(
    *,
    per_file: list[dict[str, Any]],
    parser_output_path: Path,
    output_path: Path,
    canonical_type_coverage: dict[str, int],
) -> dict[str, Any]:
    total_target_count = sum(entry["target_count"] for entry in per_file)
    total_candidate_count = sum(entry["candidate_count"] for entry in per_file)
    total_found = sum(entry["found_count"] for entry in per_file)
    total_missing = sum(entry["missing_count"] for entry in per_file)
    total_unsupported = sum(entry["unsupported_count"] for entry in per_file)
    total_low_confidence = sum(entry["low_confidence_count"] for entry in per_file)

    if total_candidate_count > 0:
        average_confidence = round(
            sum(entry["average_confidence"] * entry["candidate_count"] for entry in per_file)
            / total_candidate_count,
            3,
        )
    else:
        average_confidence = 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parser_output_dir": str(parser_output_path).replace("\\", "/"),
        "output_dir": str(output_path).replace("\\", "/"),
        "file_count": len(per_file),
        "canonical_type_coverage": canonical_type_coverage,
        "total_target_count": total_target_count,
        "total_candidate_count": total_candidate_count,
        "found_count": total_found,
        "missing_count": total_missing,
        "unsupported_count": total_unsupported,
        "low_confidence_count": total_low_confidence,
        "average_confidence": average_confidence,
        "files": [
            {key: value for key, value in entry.items() if key != "items"}
            for entry in per_file
        ],
        "note": REPORT_DISCLAIMER,
    }


def _truncate_snippet(snippet: Any) -> str:
    if snippet is None:
        return ""
    text = " ".join(str(snippet).split())
    if len(text) <= SNIPPET_TRUNCATE_LENGTH:
        return text
    return text[: SNIPPET_TRUNCATE_LENGTH - 1].rstrip() + "\u2026"


def _write_report(
    report_path: Path, summary: dict[str, Any], per_file: list[dict[str, Any]]
) -> None:
    lines: list[str] = []
    lines.append("# Extraction Smoke Report")
    lines.append("")
    lines.append(f"- Generated at: {summary['generated_at']}")
    lines.append(f"- Parser output dir: `{summary['parser_output_dir']}`")
    lines.append(f"- Output dir: `{summary['output_dir']}`")
    lines.append(f"- Files processed: {summary['file_count']}")
    coverage = ", ".join(
        f"{ctid}={count}" for ctid, count in sorted(summary["canonical_type_coverage"].items())
    )
    lines.append(f"- Canonical type coverage: {coverage or 'none'}")
    lines.append(f"- Total targets: {summary['total_target_count']}")
    lines.append(f"- Total candidates: {summary['total_candidate_count']}")
    lines.append(f"- Total found candidates: {summary['found_count']}")
    lines.append(f"- Total missing candidates: {summary['missing_count']}")
    lines.append(f"- Total unsupported-method candidates: {summary['unsupported_count']}")
    lines.append(f"- Average confidence: {summary['average_confidence']}")
    lines.append("")
    lines.append(f"> {summary['note']}")
    lines.append("")

    if not per_file:
        lines.append("_No parser_output files were found._")
        lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return

    header = (
        "| file | document_id | canonical_type_id | source | targets | candidates | "
        "found | missing | unsupported | low_conf | avg_conf | output_json_path |"
    )
    divider = "|" + "|".join(["---"] * 12) + "|"
    lines.append(header)
    lines.append(divider)
    for entry in per_file:
        lines.append(
            "| {file} | {document_id} | {ctid} | {source} | {targets} | {candidates} | "
            "{found} | {missing} | {unsupported} | {low} | {avg} | `{path}` |".format(
                file=entry["file"],
                document_id=entry["document_id"],
                ctid=entry["canonical_type_id"],
                source=entry["canonical_type_source"],
                targets=entry["target_count"],
                candidates=entry["candidate_count"],
                found=entry["found_count"],
                missing=entry["missing_count"],
                unsupported=entry["unsupported_count"],
                low=entry["low_confidence_count"],
                avg=entry["average_confidence"],
                path=entry["output_json_path"],
            )
        )
    lines.append("")

    lines.append("## Per-field candidate details")
    lines.append("")
    for entry in per_file:
        lines.append(f"### {entry['file']} ({entry['canonical_type_id']})")
        lines.append("")
        lines.append(
            "| field_name | display_label | raw_value | normalized_value | unit | "
            "confidence | validation_flags | source_snippet |"
        )
        lines.append("|" + "|".join(["---"] * 8) + "|")
        for item in entry["items"]:
            source_reference = item.get("source_reference") or {}
            snippet = _truncate_snippet(source_reference.get("text_snippet"))
            flags = ", ".join(item.get("validation_flags") or [])
            lines.append(
                "| {field} | {label} | {raw} | {norm} | {unit} | {conf} | {flags} | {snippet} |".format(
                    field=item.get("field_name"),
                    label=item.get("display_label"),
                    raw=_cell(item.get("raw_value")),
                    norm=_cell(item.get("normalized_value")),
                    unit=_cell(item.get("unit")),
                    conf=item.get("confidence"),
                    flags=flags,
                    snippet=snippet,
                )
            )
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local end-to-end extraction smoke pass (PR6.1).",
    )
    parser.add_argument("--input-doc-dir", default=DEFAULT_INPUT_DOC_DIR)
    parser.add_argument("--parser-output-dir", default=DEFAULT_PARSER_OUTPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mapping-file", default=None)
    parser.add_argument("--default-canonical-type-id", default=DEFAULT_CANONICAL_TYPE_ID)
    parser.add_argument("--refresh-parser-outputs", action="store_true")
    parser.add_argument("--include-optional", dest="include_optional", action="store_true", default=True)
    parser.add_argument("--no-include-optional", dest="include_optional", action="store_false")
    parser.add_argument("--include-deprecated", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_extraction_smoke(
        parser_output_dir=args.parser_output_dir,
        output_dir=args.output_dir,
        default_canonical_type_id=args.default_canonical_type_id,
        mapping_file=args.mapping_file,
        include_optional=args.include_optional,
        include_deprecated=args.include_deprecated,
        input_doc_dir=args.input_doc_dir,
        refresh_parser_outputs=args.refresh_parser_outputs,
    )
    print(
        f"Processed {summary['file_count']} parser_output file(s) from "
        f"{summary['parser_output_dir']}"
    )
    print(
        "Targets={targets} candidates={candidates} found={found} missing={missing} "
        "unsupported={unsupported} avg_conf={avg}".format(
            targets=summary["total_target_count"],
            candidates=summary["total_candidate_count"],
            found=summary["found_count"],
            missing=summary["missing_count"],
            unsupported=summary["unsupported_count"],
            avg=summary["average_confidence"],
        )
    )
    print(f"Report: {Path(summary['output_dir']) / REPORT_FILE_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
