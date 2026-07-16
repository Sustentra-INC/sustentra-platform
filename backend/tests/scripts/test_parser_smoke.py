import json
from pathlib import Path

import pytest

from backend.scripts.parser_smoke import run_smoke


def test_smoke_run_processes_text_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "note.txt").write_text(
        "Total Usage 28,100 MMBtu\nService address: 1 Main St\n", encoding="utf-8"
    )

    summary = run_smoke(input_dir, output_dir)

    assert summary["file_count"] == 1
    entry = summary["files"][0]
    assert entry["file_name"] == "note.txt"
    assert entry["parser_name"] == "text_parser"
    assert entry["status"] == "parsed"
    assert entry["text_block_count"] == 2
    assert entry["source_reference_count"] == 2
    assert entry["usable_for_extraction_later"] is True

    output_json = output_dir / "note.parser_output.json"
    assert output_json.exists()
    parsed = json.loads(output_json.read_text(encoding="utf-8"))
    assert parsed["parser_name"] == "text_parser"

    report = output_dir / "parser_smoke_report.md"
    assert report.exists()
    report_text = report.read_text(encoding="utf-8")
    assert "note.txt" in report_text
    assert "parser_output completeness only" in report_text

    summary_json = output_dir / "parser_smoke_summary.json"
    assert summary_json.exists()


def test_smoke_run_processes_excel_file(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")

    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet["A1"] = "Metric"
    worksheet["B1"] = "Value"
    workbook.save(input_dir / "data.xlsx")

    summary = run_smoke(input_dir, output_dir)

    names = {entry["file_name"]: entry for entry in summary["files"]}
    assert "data.xlsx" in names
    excel_entry = names["data.xlsx"]
    assert excel_entry["parser_name"] == "openpyxl"
    assert excel_entry["status"] == "parsed"
    assert excel_entry["source_reference_count"] >= 2
    assert (output_dir / "data.parser_output.json").exists()


def test_smoke_run_skips_hidden_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / ".hidden.txt").write_text("secret", encoding="utf-8")
    (input_dir / "visible.txt").write_text("content", encoding="utf-8")

    summary = run_smoke(input_dir, output_dir)

    processed = {entry["file_name"] for entry in summary["files"]}
    assert processed == {"visible.txt"}


def test_smoke_run_reports_status_counts(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "good.txt").write_text("line", encoding="utf-8")
    (input_dir / "unsupported.zip").write_bytes(b"not a real zip")

    summary = run_smoke(input_dir, output_dir)

    assert summary["file_count"] == 2
    assert summary["status_counts"]["parsed"] == 1
    assert summary["status_counts"]["failed"] == 1


def test_smoke_run_empty_input_dir(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()

    summary = run_smoke(input_dir, output_dir)

    assert summary["file_count"] == 0
    assert (output_dir / "parser_smoke_report.md").exists()
