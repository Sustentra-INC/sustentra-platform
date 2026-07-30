from pathlib import Path

from backend.app.adapters.parsers.csv_parser import CsvParser
from backend.tests.adapters.parsers._parser_output_asserts import (
    assert_parser_output_shape,
)


def test_csv_file_produces_table_and_text_blocks(tmp_path: Path) -> None:
    file_path = tmp_path / "usage.csv"
    file_path.write_text(
        "Month,Usage,Unit\nJanuary,32400,MMBtu\n",
        encoding="utf-8",
    )

    output = CsvParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "parsed"
    assert output["parser_name"] == "csv_parser"
    assert output["tables"][0]["rows"] == [
        ["Month", "Usage", "Unit"],
        ["January", "32400", "MMBtu"],
    ]
    assert output["text_blocks"][1]["text"] == "January | 32400 | MMBtu"


def test_csv_parser_handles_quoted_commas(tmp_path: Path) -> None:
    file_path = tmp_path / "usage.csv"
    file_path.write_text(
        'Unit ID,Description,Capacity\nBLR-001,"Natural Gas Boiler, North",25\n',
        encoding="utf-8",
    )

    output = CsvParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert output["tables"][0]["rows"][1] == [
        "BLR-001",
        "Natural Gas Boiler, North",
        "25",
    ]


def test_empty_csv_file_is_empty_status_with_warning(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.csv"
    file_path.write_text(",,\n\n", encoding="utf-8")

    output = CsvParser().parse(file_path, document_id="DOC-1", processing_run_id="RUN-1")

    assert_parser_output_shape(output)
    assert output["status"] == "empty"
    assert output["tables"] == []
    assert any(w["code"] == "empty_document" for w in output["warnings"])
