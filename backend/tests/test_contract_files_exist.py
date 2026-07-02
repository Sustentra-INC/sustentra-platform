from pathlib import Path


REQUIRED_CONTRACT_FILES = [
    "document.schema.json",
    "processing_run.schema.json",
    "source_reference.schema.json",
    "extraction_candidate.schema.json",
    "review_decision.schema.json",
    "approved_evidence.schema.json",
    "validation_result.schema.json",
    "calculation_result.schema.json",
    "gap_ticket.schema.json"
]


def test_required_contract_files_exist() -> None:
    contracts_dir = Path(__file__).resolve().parents[2] / "contracts"
    missing = [name for name in REQUIRED_CONTRACT_FILES if not (contracts_dir / name).exists()]
    assert not missing, f"Missing contract files: {missing}"
