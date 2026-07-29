from __future__ import annotations

from backend.tests.golden_s1.golden_s1_runner import converted_input_for, evaluate_parser_expectations


def test_converted_inputs_are_usable_for_parser_smoke(golden_paths) -> None:
    converted_text_dir = golden_paths.converted_inputs / "text"
    assert converted_text_dir.exists()
    assert list(converted_text_dir.glob("*.txt"))


def test_parser_expectation_evaluator_runs(golden_paths) -> None:
    results = evaluate_parser_expectations(golden_paths)
    assert results
    assert any(result["stage"] == "parser" for result in results)


def test_native_parser_fixture_priority_when_available(golden_paths, tmp_path) -> None:
    fixture_root = tmp_path / "suite"
    production_inputs = fixture_root / "s1-test-suite-converted-inputs" / "production_inputs"
    for folder in ("text", "pdf", "excel"):
        (production_inputs / folder).mkdir(parents=True, exist_ok=True)

    (production_inputs / "text" / "EV-NG-2023-001.txt").write_text("text", encoding="utf-8")
    (production_inputs / "pdf" / "EV-NG-2023-001.pdf").write_bytes(b"%PDF-1.4\n")
    (production_inputs / "excel" / "EV-INV-2023-001.csv").write_text("csv", encoding="utf-8")
    (production_inputs / "excel" / "EV-INV-2023-001.xlsx").write_bytes(b"xlsx")
    (production_inputs / "EV-BIO-2023-003_parser_test_fixture.xlsx").write_bytes(b"xlsx")

    pdf_paths = type(golden_paths)(fixture_root=fixture_root, output_root=tmp_path / "out")
    assert converted_input_for(pdf_paths, "EV-NG-2023-001").suffix == ".pdf"
    assert converted_input_for(pdf_paths, "EV-INV-2023-001").suffix == ".xlsx"
    assert converted_input_for(pdf_paths, "EV-BIO-2023-003").name.endswith("_parser_test_fixture.xlsx")
