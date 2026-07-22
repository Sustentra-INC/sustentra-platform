from pathlib import Path

from backend.scripts.backend_s1_smoke import main, run_backend_s1_smoke
from backend.scripts.generate_synthetic_evidence import generate_synthetic_evidence


def test_runs_end_to_end_with_temp_paths(tmp_path: Path) -> None:
    sample_dir = tmp_path / "samples"
    sample_file = generate_synthetic_evidence(
        output_dir=sample_dir,
        file_name="synthetic.txt",
    )

    runtime_root = tmp_path / "runtime-data"
    result = run_backend_s1_smoke(
        sample_file=sample_file,
        generate_sample=False,
        engagement_id="eng-test-001",
        canonical_type_id="CT-S1-FUELQTY",
        reviewer_id="tester@example.com",
        clean_run=True,
        local_data_root=runtime_root,
    )

    summary = result["summary"]
    assert summary["sample_file"].endswith("synthetic.txt")
    assert summary["pipeline_status"] in {"completed", "partial"}
    assert summary["target_count"] >= 0
    assert summary["candidate_count"] >= 0
    assert summary["review_decision_count"] >= 0
    assert summary["approved_field_count"] >= 0
    assert Path(summary["local_data_root"]).resolve() == runtime_root.resolve()

    pipeline_result = result["pipeline_result"]
    assert "pipeline_run" in pipeline_result
    assert "parser_output" in pipeline_result
    assert "classification_result" in pipeline_result
    assert "extraction_targets" in pipeline_result
    assert "extraction_result" in pipeline_result
    assert pipeline_result["pipeline_run"]["canonical_type_source"] == "override"
    assert pipeline_result["pipeline_run"]["canonical_type_id"] == "CT-S1-FUELQTY"

    assert "document_id" in result["uploaded_document"]
    assert "evidence_id" in result["uploaded_document"]
    assert isinstance(result["review_decisions"], list)
    assert "approved_evidence_id" in result["approved_evidence"]


def test_generate_sample_option_creates_missing_file(tmp_path: Path) -> None:
    sample_file = tmp_path / "generated" / "synthetic-smoke.txt"
    runtime_root = tmp_path / "runtime"

    result = run_backend_s1_smoke(
        sample_file=sample_file,
        generate_sample=True,
        clean_run=True,
        local_data_root=runtime_root,
    )

    assert sample_file.exists()
    assert result["summary"]["sample_file"].endswith("synthetic-smoke.txt")


def test_smoke_writes_only_to_temp_runtime_when_clean_run(tmp_path: Path) -> None:
    sample_file = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
    )
    runtime_root = tmp_path / "temp-local-data"

    result = run_backend_s1_smoke(
        sample_file=sample_file,
        clean_run=True,
        local_data_root=runtime_root,
    )

    local_data_root = Path(result["summary"]["local_data_root"]).resolve()
    assert local_data_root == runtime_root.resolve()
    assert (local_data_root / "uploads").exists()


def test_cli_main_prints_summary(tmp_path: Path, capsys) -> None:
    sample_file = generate_synthetic_evidence(
        output_dir=tmp_path,
        file_name="synthetic.txt",
    )

    exit_code = main(
        [
            "--sample-file",
            str(sample_file),
            "--clean-run",
            "--engagement-id",
            "eng-cli-001",
            "--canonical-type-id",
            "CT-S1-FUELQTY",
            "--reviewer-id",
            "cli@example.com",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Backend S1 smoke summary" in captured.out
    assert "pipeline_run_id" in captured.out
    assert "approved_evidence_id" in captured.out
