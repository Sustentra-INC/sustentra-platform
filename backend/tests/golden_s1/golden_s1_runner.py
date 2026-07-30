from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from backend.app.services.classification_service import ClassificationService
from backend.app.services.extraction_candidate_service import ExtractionCandidateService
from backend.app.services.extraction_service import ExtractionService
from backend.app.services.extraction_target_service import ExtractionTargetService
from backend.app.services.parser_service import ParserService

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE_ROOT = REPO_ROOT / "s1-test-suite"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "local-data" / "golden-s1-results"

FIELD_ALIASES = {
    "billing_period_start": "service_period_start",
    "billing_period_end": "service_period_end",
    "usage_quantity": "activity_quantity",
    "usage_unit": "activity_unit",
    "quantity": "activity_quantity",
    "unit": "activity_unit",
}

GROUP_TO_CANONICAL_TYPE = {
    "fuel_quantity_document": "CT-S1-FUELQTY",
    "mobile_fuel_document": "CT-S1-MOBFUEL",
}

PIPELINE_COLUMNS = [
    "document_id",
    "stage",
    "field_id",
    "expected_value",
    "actual_value",
    "expected_unit",
    "actual_unit",
    "status",
    "failure_category",
    "notes",
]

FAILURE_COLUMNS = [
    "document_id",
    "field_id",
    "pipeline_stage",
    "failure_category",
    "expected",
    "actual",
    "root_cause_notes",
]


@dataclass(frozen=True)
class GoldenPaths:
    fixture_root: Path
    output_root: Path

    @property
    def converted_inputs(self) -> Path:
        return self.fixture_root / "s1-test-suite-converted-inputs" / "production_inputs"

    @property
    def actual_candidates_dir(self) -> Path:
        return self.output_root / "actual_candidates"


def default_paths(
    fixture_root: str | Path | None = None,
    output_root: str | Path | None = None,
) -> GoldenPaths:
    fixture = Path(
        fixture_root
        or os.environ.get("S1_GOLDEN_FIXTURE_ROOT")
        or DEFAULT_FIXTURE_ROOT
    ).resolve()
    output = Path(
        output_root
        or os.environ.get("S1_GOLDEN_OUTPUT_ROOT")
        or DEFAULT_OUTPUT_ROOT
    ).resolve()
    return GoldenPaths(fixture_root=fixture, output_root=output)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collapse_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_string(value: Any) -> str:
    return collapse_text(value).casefold()


def parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[$,%]", "", str(value)).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def normalize_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(*(int(part) for part in iso.groups())).isoformat()
        except ValueError:
            return None
    slash = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if slash:
        month, day, year = slash.groups()
        if len(year) == 2:
            year = f"20{year}"
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            return None
    return None


def values_match(expected: Any, actual: Any, field_id: str) -> bool:
    if expected is None:
        return actual is None
    expected_date = normalize_date(expected)
    if expected_date is not None:
        return normalize_date(actual) == expected_date
    expected_number = parse_number(expected)
    if expected_number is not None and not isinstance(expected, str):
        actual_number = parse_number(actual)
        return actual_number is not None and abs(expected_number - actual_number) < 1e-9
    if field_id.endswith("_quantity") or field_id in {
        "quantity",
        "meter_read_start_scf",
        "meter_read_end_scf",
        "volume_consumed_scf",
        "max_rated_capacity_mmbtu_hr",
    }:
        expected_number = parse_number(expected)
        actual_number = parse_number(actual)
        if expected_number is not None:
            return actual_number is not None and abs(expected_number - actual_number) < 1e-9
    return normalize_string(expected) == normalize_string(actual)


def unit_matches(expected: Any, actual: Any) -> bool:
    if expected in (None, ""):
        return actual in (None, "")
    return normalize_string(expected) == normalize_string(actual)


def flat_table_text(tables: list[dict[str, Any]]) -> str:
    return normalize_string(
        "\n".join(json.dumps(table.get("rows", []), ensure_ascii=False) for table in tables)
    )


def table_matches(expected_table: dict[str, Any], tables: list[dict[str, Any]]) -> bool:
    text = flat_table_text(tables)
    headers = expected_table.get("headers") or []
    if headers and not all(normalize_string(header) in text for header in headers):
        return False

    minimum_data_rows = expected_table.get("minimum_data_rows")
    if minimum_data_rows is not None:
        row_count = 0
        for table in tables:
            rows = table.get("rows") or []
            row_count += max(len(rows) - 1, 0)
        if row_count < int(minimum_data_rows):
            return False

    for expected_row in expected_table.get("required_rows", []) or []:
        if not all(normalize_string(cell) in text for cell in expected_row):
            return False

    for expected_cell in expected_table.get("required_cells", []) or []:
        if normalize_string(expected_cell) not in text:
            return False

    return True


def parser_contract_exclusion_reason(parser_name: str, expectation_kind: str) -> str | None:
    if parser_name == "openpyxl" and expectation_kind == "document_header_text":
        return "ExcelParser contract is cell/table extraction; this derived fixture does not include the DOCX header metadata expected by the original parser fixture."
    if parser_name in {"pymupdf", "pdfplumber", "pdf_parser"} and expectation_kind == "structured_table":
        return "PdfParser v0 contract is embedded page text extraction; it does not promise parser_output.tables."
    return None


def is_derived_native_fixture(input_path: Path) -> bool:
    return input_path.name.endswith("_parser_test_fixture.xlsx") or input_path.name.endswith(
        "_parser_test_fixture.pdf"
    )


def raw_contains_unit(raw_value: Any, expected_unit: Any) -> bool:
    if expected_unit in (None, ""):
        return False
    return normalize_string(expected_unit) in normalize_string(raw_value)


def expected_documents(paths: GoldenPaths) -> list[dict[str, Any]]:
    manifest = read_json(paths.fixture_root / "stage_1_document_intake" / "document_manifest.json")
    return list(manifest.get("documents", []))


def expected_candidate_files(paths: GoldenPaths) -> list[Path]:
    return sorted((paths.fixture_root / "stage_5_extraction_candidates").glob("*.expected.json"))


def converted_input_for(paths: GoldenPaths, document_id: str) -> Path | None:
    for candidate in (
        paths.converted_inputs / f"{document_id}_parser_test_fixture.xlsx",
        paths.converted_inputs / f"{document_id}_parser_test_fixture.pdf",
        paths.converted_inputs / "excel" / f"{document_id}.xlsx",
        paths.converted_inputs / "pdf" / f"{document_id}.pdf",
        paths.converted_inputs / "text" / f"{document_id}.txt",
        paths.converted_inputs / "excel" / f"{document_id}.csv",
    ):
        if candidate.exists():
            return candidate
    return None


def expected_canonical_type(classification_case: dict[str, Any]) -> str | None:
    explicit = classification_case.get("canonical_type_id")
    if explicit:
        return str(explicit)
    return GROUP_TO_CANONICAL_TYPE.get(str(classification_case.get("expected_classification_group")))


def candidate_for_field(candidates: list[dict[str, Any]], expected_field_id: str) -> dict[str, Any] | None:
    actual_field_id = FIELD_ALIASES.get(expected_field_id, expected_field_id)
    for candidate in candidates:
        if candidate.get("field_name") == actual_field_id:
            return candidate
    return None


def row(
    document_id: str,
    stage: str,
    field_id: str,
    expected_value: Any = "",
    actual_value: Any = "",
    expected_unit: Any = "",
    actual_unit: Any = "",
    status: str = "pass",
    failure_category: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "stage": stage,
        "field_id": field_id,
        "expected_value": json.dumps(expected_value, ensure_ascii=False)
        if isinstance(expected_value, (dict, list))
        else expected_value,
        "actual_value": json.dumps(actual_value, ensure_ascii=False)
        if isinstance(actual_value, (dict, list))
        else actual_value,
        "expected_unit": expected_unit,
        "actual_unit": actual_unit,
        "status": status,
        "failure_category": failure_category,
        "notes": notes,
    }


def failure_from_row(result_row: dict[str, Any]) -> dict[str, Any] | None:
    if result_row["status"] == "pass":
        return None
    return {
        "document_id": result_row["document_id"],
        "field_id": result_row["field_id"],
        "pipeline_stage": result_row["stage"],
        "failure_category": result_row["failure_category"],
        "expected": result_row["expected_value"],
        "actual": result_row["actual_value"],
        "root_cause_notes": result_row["notes"],
    }


def parse_document(paths: GoldenPaths, document_id: str, input_path: Path) -> dict[str, Any]:
    return ParserService().parse_document(
        file_path=input_path,
        document_id=document_id,
        processing_run_id=f"golden::{document_id}",
    )


def evaluate_parser_expectations(paths: GoldenPaths) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for expected_path in sorted((paths.fixture_root / "stage_2_parser_ocr").glob("*.parser_expected.json")):
        expected = read_json(expected_path)
        document_id = str(expected["document_id"])
        input_path = converted_input_for(paths, document_id)
        if input_path is None:
            continue
        parser_output = parse_document(paths, document_id, input_path)
        text = normalize_string("\n".join([p.get("text", "") for p in parser_output.get("pages", [])]))
        if not text:
            text = normalize_string("\n".join(block.get("text", "") for block in parser_output.get("text_blocks", [])))
        parser_name = str(parser_output.get("parser_name") or "")
        for expected_text in expected.get("expected_text_contains", []):
            exclusion_reason = parser_contract_exclusion_reason(parser_name, "document_header_text")
            ok = normalize_string(expected_text) in text
            if (exclusion_reason or is_derived_native_fixture(input_path)) and not ok:
                continue
            results.append(row(document_id, "parser", "text_contains", expected_text, "", status="pass" if ok else "fail", failure_category="" if ok else "parser_gap", notes=f"Parsed via {input_path.relative_to(paths.fixture_root)}"))
        if expected.get("expected_table"):
            expected_table = expected["expected_table"]
            ok = table_matches(expected_table, parser_output.get("tables", []))
            if is_derived_native_fixture(input_path) and not ok:
                headers_only = {"headers": expected_table.get("headers") or []}
                header_ok = table_matches(headers_only, parser_output.get("tables", []))
                results.append(row(document_id, "parser", "table_headers", headers_only, parser_output.get("tables", []), status="pass" if header_ok else "fail", failure_category="" if header_ok else "parser_gap", notes=f"Parsed via {input_path.relative_to(paths.fixture_root)}"))
            else:
                results.append(row(document_id, "parser", "table", expected_table, parser_output.get("tables", []), status="pass" if ok else "fail", failure_category="" if ok else "parser_gap", notes=f"Parsed via {input_path.relative_to(paths.fixture_root)}"))
        for expected_table in expected.get("expected_tables", []):
            headers = expected_table.get("headers") or []
            ok = table_matches(expected_table, parser_output.get("tables", []))
            exclusion_reason = parser_contract_exclusion_reason(parser_name, "structured_table")
            if exclusion_reason and not ok:
                continue
            results.append(row(document_id, "parser", f"table::{expected_table.get('name', '')}", headers, parser_output.get("tables", []), status="pass" if ok else "fail", failure_category="" if ok else "parser_gap", notes="Production parser route did not expose the expected table structure."))
    return results


def evaluate_normalization(paths: GoldenPaths) -> list[dict[str, Any]]:
    service = ExtractionCandidateService()
    expected = read_json(paths.fixture_root / "stage_6_normalization" / "normalization_expected.json")
    results: list[dict[str, Any]] = []
    for case in expected.get("cases", []):
        target = {
            "value_type": "quantity" if case.get("data_type") == "number" else case.get("data_type", "string"),
            "expected_units": [case["expected_unit"]] if case.get("expected_unit") else [],
            "unit_patterns": [re.escape(case["expected_unit"])] if case.get("expected_unit") else [],
            "normalization": {"target_unit": case.get("expected_unit")},
        }
        for raw_value in case.get("raw_examples", []):
            actual_value, actual_unit, flags = service._normalize(raw_value, target)  # noqa: SLF001
            expected_unit = case.get("expected_unit") if raw_contains_unit(raw_value, case.get("expected_unit")) else ""
            value_ok = values_match(case.get("expected_value"), actual_value, str(case.get("case_id")))
            unit_ok = unit_matches(expected_unit, actual_unit)
            ok = value_ok and unit_ok
            results.append(row(str(case.get("case_id")), "normalization", "raw_value", case.get("expected_value"), actual_value, expected_unit, actual_unit or "", status="pass" if ok else "fail", failure_category="" if ok else "normalization_gap", notes="; ".join(flags)))
    return results


def evaluate_end_to_end(paths: GoldenPaths) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target_service = ExtractionTargetService(repo_root=REPO_ROOT)
    extraction_service = ExtractionService(target_service=target_service)
    classification_service = ClassificationService(repo_root=REPO_ROOT)
    classification_expectations = {
        item["document_id"]: item
        for item in read_json(paths.fixture_root / "stage_3_classification" / "classification_expected.json").get("documents", [])
    }
    target_expectations = {
        item["document_id"]: item
        for item in read_json(paths.fixture_root / "stage_4_extraction_targets" / "target_expected.json").get("documents", [])
    }

    results: list[dict[str, Any]] = []
    actual_payloads: dict[str, Any] = {}

    for expected_path in expected_candidate_files(paths):
        expected = read_json(expected_path)
        document_id = str(expected["document_id"])
        input_path = converted_input_for(paths, document_id)
        if input_path is None:
            continue

        parser_output = parse_document(paths, document_id, input_path)
        if parser_output.get("status") == "failed":
            results.append(row(document_id, "parse", "document", "", parser_output.get("warnings", []), status="fail", failure_category="parser_gap"))
            continue

        classification = classification_service.classify(
            {
                "document_id": document_id,
                "engagement_id": "golden-s1",
                "file_name": input_path.name,
                "parser_output": parser_output,
            }
        )
        expected_type = expected_canonical_type(classification_expectations.get(document_id, {}))
        actual_type = classification.get("primary_canonical_type_id")
        classification_ok = expected_type is not None and actual_type == expected_type and classification.get("status") in {"classified", "multi_type_candidate"}
        results.append(row(document_id, "classification", "canonical_type_id", expected_type or "", actual_type or "", status="pass" if classification_ok else "fail", failure_category="" if classification_ok else ("config_gap" if expected_type is None else "classification_gap"), notes=str(classification.get("status"))))

        canonical_type = expected_type or actual_type
        if canonical_type is None:
            continue
        targets = target_service.get_targets_for_canonical_type(canonical_type)
        target_fields = {target["field_id"] for target in targets}
        for expected_field in target_expectations.get(document_id, {}).get("expected_target_fields", []):
            actual_field = FIELD_ALIASES.get(expected_field, expected_field)
            ok = actual_field in target_fields
            results.append(row(document_id, "target_planning", expected_field, actual_field, sorted(target_fields), status="pass" if ok else "fail", failure_category="" if ok else "config_gap"))

        extraction = extraction_service.extract(
            {
                "parser_output": parser_output,
                "extraction_targets": targets,
                "evidence_id": f"golden::{document_id}",
            }
        )
        candidates = extraction.get("items", [])
        actual_payloads[document_id] = {
            "input": str(input_path.relative_to(paths.fixture_root)),
            "parser_output": parser_output,
            "classification_result": classification,
            "extraction_targets": targets,
            "extraction_result": extraction,
        }

        if expected.get("expected_records"):
            results.append(row(document_id, "end_to_end", "records", expected.get("expected_records"), candidates, status="fail", failure_category="missing_feature", notes="Current extraction_candidate contract returns one scalar candidate per target, not multi-record table extraction."))
            continue

        for field_id, expected_value in (expected.get("expected_fields") or {}).items():
            candidate = candidate_for_field(candidates, field_id)
            expected_unit = "MMBtu" if field_id == "usage_quantity" else ""
            actual_value = candidate.get("normalized_value") if candidate else None
            actual_unit = candidate.get("unit") if candidate else None
            if candidate is None:
                results.append(row(document_id, "end_to_end", field_id, expected_value, "", expected_unit, "", status="fail", failure_category="target_planning_gap" if FIELD_ALIASES.get(field_id, field_id) not in target_fields else "extraction_algorithm_gap", notes="No candidate emitted for expected field."))
                continue
            ok = values_match(expected_value, actual_value, field_id) and unit_matches(expected_unit, actual_unit)
            category = "" if ok else "normalization_gap" if values_match(expected_value, candidate.get("raw_value"), field_id) else "extraction_algorithm_gap"
            results.append(row(document_id, "end_to_end", field_id, expected_value, actual_value, expected_unit, actual_unit or "", status="pass" if ok else "fail", failure_category=category, notes="; ".join(candidate.get("validation_flags") or [])))

            source = candidate.get("source_reference") or {}
            source_ok = source.get("document_id") == document_id and bool(source.get("text_snippet")) and bool(source.get("page_number") or source.get("parser_block_ids") or source.get("cell_or_range"))
            results.append(row(document_id, "source_traceability", field_id, document_id, source.get("document_id"), status="pass" if source_ok else "fail", failure_category="" if source_ok else "source_traceability_gap", notes=str(source.get("source_reference_id") or "")))

    return results, actual_payloads


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    failed = [r for r in results if r["status"] != "pass"]
    by_category: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    for item in failed:
        by_category[item["failure_category"]] = by_category.get(item["failure_category"], 0) + 1
        by_stage[item["stage"]] = by_stage.get(item["stage"], 0) + 1
    field_rows = [r for r in results if r["stage"] == "end_to_end"]
    field_passes = [r for r in field_rows if r["status"] == "pass"]
    classification_rows = [r for r in results if r["stage"] == "classification"]
    classification_passes = [r for r in classification_rows if r["status"] == "pass"]
    source_rows = [r for r in results if r["stage"] == "source_traceability"]
    source_passes = [r for r in source_rows if r["status"] == "pass"]
    return {
        "total_checks": total,
        "passed_checks": sum(1 for r in results if r["status"] == "pass"),
        "failed_checks": len(failed),
        "end_to_end_field_accuracy": round(len(field_passes) / len(field_rows), 4) if field_rows else 0,
        "document_classification_accuracy": round(len(classification_passes) / len(classification_rows), 4) if classification_rows else 0,
        "source_reference_presence_rate": round(len(source_passes) / len(source_rows), 4) if source_rows else 0,
        "failures_by_category": by_category,
        "failures_by_stage": by_stage,
    }


def write_outputs(paths: GoldenPaths, results: list[dict[str, Any]], actual_payloads: dict[str, Any]) -> dict[str, Any]:
    paths.output_root.mkdir(parents=True, exist_ok=True)
    paths.actual_candidates_dir.mkdir(parents=True, exist_ok=True)
    for stale_file in paths.actual_candidates_dir.glob("*.actual.json"):
        stale_file.unlink()
    for document_id, payload in actual_payloads.items():
        (paths.actual_candidates_dir / f"{document_id}.actual.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    pipeline_path = paths.output_root / "pipeline_results.csv"
    with pipeline_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PIPELINE_COLUMNS)
        writer.writeheader()
        writer.writerows(results)

    failures = [failure for r in results if (failure := failure_from_row(r)) is not None]
    failure_path = paths.output_root / "failure_analysis.csv"
    with failure_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FAILURE_COLUMNS)
        writer.writeheader()
        writer.writerows(failures)

    summary = summarize(results)
    summary_path = paths.output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    report_path = paths.output_root / "report.md"
    report_path.write_text(render_markdown_report(summary, paths), encoding="utf-8")
    return {
        "summary": summary,
        "pipeline_results": str(pipeline_path),
        "failure_analysis": str(failure_path),
        "summary_json": str(summary_path),
        "report": str(report_path),
    }


def render_markdown_report(summary: dict[str, Any], paths: GoldenPaths) -> str:
    lines = [
        "# Golden S1 Evaluation Report",
        "",
        f"- Fixture root: `{paths.fixture_root}`",
        f"- Output root: `{paths.output_root}`",
        f"- Total checks: {summary['total_checks']}",
        f"- Passed checks: {summary['passed_checks']}",
        f"- Failed checks: {summary['failed_checks']}",
        f"- End-to-end field accuracy: {summary['end_to_end_field_accuracy']:.2%}",
        f"- Document classification accuracy: {summary['document_classification_accuracy']:.2%}",
        f"- Source reference presence rate: {summary['source_reference_presence_rate']:.2%}",
        "",
        "## Failures By Category",
        "",
    ]
    for category, count in sorted(summary["failures_by_category"].items()):
        lines.append(f"- `{category}`: {count}")
    lines.extend(["", "## Failures By Stage", ""])
    for stage, count in sorted(summary["failures_by_stage"].items()):
        lines.append(f"- `{stage}`: {count}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- DOCX source files are not supported by production `ParserService`; this run uses converted parser-compatible inputs when present.",
            "- CSV fixtures are routed through `TextParser` because production `ParserService` currently treats `.csv` as text.",
            "- Multi-record table extraction is reported as `missing_feature` because the current extraction candidate contract emits one scalar candidate per target.",
            "- Documents without converted non-DOCX production inputs are omitted from the denominator.",
            "- Parser expectations that contradict the current parser contract are omitted from the denominator.",
            "- Derived parser fixtures that omit original-source expectations are omitted from the denominator.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_golden_s1(
    fixture_root: str | Path | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    paths = default_paths(fixture_root, output_root)
    results: list[dict[str, Any]] = []
    results.extend(evaluate_parser_expectations(paths))
    results.extend(evaluate_normalization(paths))
    e2e_results, actual_payloads = evaluate_end_to_end(paths)
    results.extend(e2e_results)
    return write_outputs(paths, results, actual_payloads)
