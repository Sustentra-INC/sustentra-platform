from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from backend.app.adapters.parsers.excel_parser import ExcelParser  # noqa: E402
from backend.tests.adapters.parsers._parser_output_asserts import (  # noqa: E402
    assert_parser_output_shape,
)


def _write_workbook(path: Path, rows: list[list]) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    return path


def test_workbook_with_cells_parses_successfully(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "data.xlsx",
        rows=[["Metric", "Value"], ["Natural Gas", 28100]],
    )

    output = ExcelParser().parse(workbook_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "parsed"
    assert output["parser_name"] == "openpyxl"
    assert len(output["text_blocks"]) == 4


def test_source_references_include_sheet_and_cell(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "data.xlsx",
        rows=[["Metric", "Value"]],
    )

    output = ExcelParser().parse(workbook_path, document_id="DOC-7", processing_run_id="RUN-7")

    references = output["source_references"]
    assert references, "expected source references for non-empty cells"
    first = references[0]
    assert first["sheet_name"] == "Sheet1"
    assert first["cell_or_range"] == "A1"
    assert first["source_kind"] == "excel_cell"


def test_text_blocks_include_cell_text(tmp_path: Path) -> None:
    workbook_path = _write_workbook(
        tmp_path / "data.xlsx",
        rows=[["Natural Gas", 28100]],
    )

    output = ExcelParser().parse(workbook_path, document_id="DOC-1", processing_run_id="RUN-1")

    block_texts = {block["text"] for block in output["text_blocks"]}
    assert "Natural Gas" in block_texts
    assert "28100" in block_texts


def test_empty_workbook_returns_empty_with_warning(tmp_path: Path) -> None:
    workbook_path = tmp_path / "empty.xlsx"
    workbook = openpyxl.Workbook()
    workbook.save(workbook_path)

    output = ExcelParser().parse(workbook_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "empty"
    assert output["text_blocks"] == []
    assert any(w["code"] == "empty_document" for w in output["warnings"])
