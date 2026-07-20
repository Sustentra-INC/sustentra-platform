import json
from pathlib import Path

from backend.scripts.extraction_smoke import run_extraction_smoke

_SYNTHETIC_TEXT_LINES = [
    "Facility Name: Demo Plant",
    "Fuel Type: Natural Gas",
    "Total Usage: 28,100 MMBtu",
    "Service Period: 10/01/2023 - 10/31/2023",
    "Supplier: Demo Utility",
    "Account Number: 123456",
]


def _write_parser_output(
    directory: Path,
    file_stem: str,
    *,
    lines: list[str] | None = None,
    document_id: str = "DOC-SMOKE-1",
    long_snippet: bool = False,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    text_lines = lines if lines is not None else _SYNTHETIC_TEXT_LINES
    text_blocks = []
    source_references = []
    for index, line in enumerate(text_lines, start=1):
        block_id = f"text_parser-p1-b{index}"
        source_reference_id = f"SRC-text_parser-p1-{index}"
        snippet = line if not long_snippet else line + " " + ("x" * 400)
        text_blocks.append(
            {
                "block_id": block_id,
                "page_number": 1,
                "text": line,
                "confidence": None,
                "bounding_box": None,
                "source_reference_id": source_reference_id,
            }
        )
        source_references.append(
            {
                "source_reference_id": source_reference_id,
                "document_id": document_id,
                "page_number": 1,
                "sheet_name": None,
                "cell_or_range": None,
                "text_snippet": snippet,
                "bounding_box": None,
                "parser_block_ids": [block_id],
                "source_kind": "page_text",
            }
        )

    parser_output = {
        "parser_output_id": "PO-SMOKE-1",
        "document_id": document_id,
        "processing_run_id": "RUN-SMOKE-1",
        "parser_name": "text_parser",
        "parser_version": "v0",
        "status": "parsed",
        "created_at": "2026-07-18T00:00:00+00:00",
        "pages": [{"page_number": 1, "text": "\n".join(text_lines)}],
        "text_blocks": text_blocks,
        "tables": [],
        "key_value_pairs": [],
        "source_references": source_references,
        "warnings": [],
    }
    path = directory / f"{file_stem}.parser_output.json"
    path.write_text(json.dumps(parser_output), encoding="utf-8")
    return path


def test_run_with_default_canonical_type(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "Demo-Bill")

    summary = run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    assert summary["file_count"] == 1
    entry = summary["files"][0]
    assert entry["canonical_type_id"] == "CT-S1-FUELQTY"
    assert entry["canonical_type_source"] == "default"
    assert entry["target_count"] >= 6
    assert entry["candidate_count"] == entry["target_count"]
    assert entry["found_count"] >= 1


def test_candidate_json_report_and_summary_created(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "Demo-Bill")

    run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    assert (output_dir / "Demo-Bill.extraction_candidates.json").exists()
    assert (output_dir / "extraction_smoke_report.md").exists()
    assert (output_dir / "extraction_smoke_summary.json").exists()

    record = json.loads(
        (output_dir / "Demo-Bill.extraction_candidates.json").read_text(encoding="utf-8")
    )
    assert record["canonical_type_id"] == "CT-S1-FUELQTY"
    assert record["items"]
    assert record["source_parser_output"] == "Demo-Bill.parser_output.json"


def test_mapping_file_overrides_default(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "Fuel-Purchase")

    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(
        json.dumps({"Fuel-Purchase.parser_output.json": "CT-S1-MOBFUEL"}), encoding="utf-8"
    )

    summary = run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
        mapping_file=mapping_file,
    )

    entry = summary["files"][0]
    assert entry["canonical_type_id"] == "CT-S1-MOBFUEL"
    assert entry["canonical_type_source"] == "mapping"


def test_mapping_by_stem_overrides_default(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "sample-bill")

    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps({"sample-bill": "CT-S1-MOBFUEL"}), encoding="utf-8")

    summary = run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
        mapping_file=mapping_file,
    )

    assert summary["files"][0]["canonical_type_id"] == "CT-S1-MOBFUEL"
    assert summary["files"][0]["canonical_type_source"] == "mapping"


def test_summary_includes_expected_metrics(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "Demo-Bill")

    summary = run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    for key in (
        "file_count",
        "total_target_count",
        "total_candidate_count",
        "found_count",
        "missing_count",
    ):
        assert key in summary
    assert summary["total_candidate_count"] == summary["total_target_count"]


def test_long_snippets_are_truncated_in_report(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    _write_parser_output(parser_dir, "Demo-Bill", long_snippet=True)

    run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    report_text = (output_dir / "extraction_smoke_report.md").read_text(encoding="utf-8")
    assert "\u2026" in report_text
    assert ("x" * 400) not in report_text


def test_empty_parser_output_dir_writes_empty_report(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    parser_dir.mkdir()
    output_dir = tmp_path / "extract"

    summary = run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    assert summary["file_count"] == 0
    assert summary["total_candidate_count"] == 0
    report = output_dir / "extraction_smoke_report.md"
    assert report.exists()
    assert "No parser_output files were found" in report.read_text(encoding="utf-8")


def test_parser_output_is_not_mutated(tmp_path: Path) -> None:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "extract"
    path = _write_parser_output(parser_dir, "Demo-Bill")
    before = path.read_text(encoding="utf-8")

    run_extraction_smoke(
        parser_output_dir=parser_dir,
        output_dir=output_dir,
        default_canonical_type_id="CT-S1-FUELQTY",
    )

    assert path.read_text(encoding="utf-8") == before
