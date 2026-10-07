"""EXT-001 / EXT-002 golden tests: every stationary- and mobile-combustion sample must
pass end to end (classification, halts, records, normalization, traceability)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.tests.golden_s1.stationary_combustion_golden import (
    REPO_ROOT,
    SUITES,
    DocumentResult,
    expected_files,
    render_report,
    run_document,
    suite_root,
)

EXPECTED = {path.name.split(".")[0]: (suite, path) for suite in SUITES for path in expected_files(suite_root(suite))}
IDS = sorted(EXPECTED)


@pytest.fixture(scope="module")
def results() -> dict[str, DocumentResult]:
    return {doc_id: run_document(path, suite_root(suite)) for doc_id, (suite, path) in EXPECTED.items()}


@pytest.mark.parametrize("suite", SUITES)
def test_golden_set_has_samples(suite: str) -> None:
    paths = expected_files(suite_root(suite))
    assert len(paths) >= 5
    for path in paths:
        expected = json.loads(path.read_text(encoding="utf-8"))
        assert (suite_root(suite) / "documents" / expected["file"]).is_file(), expected["file"]


@pytest.mark.parametrize("document_id", IDS)
def test_stage_classification(results: dict[str, DocumentResult], document_id: str) -> None:
    result = results[document_id]
    assert result.classification_ok, (result.classification_expected, result.classification_actual)


@pytest.mark.parametrize("document_id", IDS)
def test_stage_halt_reason(results: dict[str, DocumentResult], document_id: str) -> None:
    result = results[document_id]
    assert result.halt_actual == result.halt_expected
    run = result.payload["pipeline_run"]
    if result.halt_expected:
        assert run["halt_reason"]["message"]
        assert run["status"] == "partial"
        assert result.payload["extraction_result"]["items"] == []
    else:
        assert run["halt_reason"] is None


@pytest.mark.parametrize("document_id", IDS)
def test_stage_candidates_one_record_per_meter_period_or_transaction(results: dict[str, DocumentResult], document_id: str) -> None:
    result = results[document_id]
    assert result.records_actual == result.records_expected


@pytest.mark.parametrize("document_id", IDS)
def test_stage_candidates_and_normalization(results: dict[str, DocumentResult], document_id: str) -> None:
    result = results[document_id]
    mismatches = [(c.record, c.field_id, c.expected, c.actual) for c in result.checks if not c.ok]
    assert mismatches == []
    assert result.core_accuracy == 1.0


@pytest.mark.parametrize("document_id", IDS)
def test_stage_traceability(results: dict[str, DocumentResult], document_id: str) -> None:
    result = results[document_id]
    untraceable = [(c.record, c.field_id) for c in result.checks if not c.traceable]
    assert untraceable == []


@pytest.mark.parametrize("document_id", IDS)
def test_raw_quantity_and_unit_are_kept(results: dict[str, DocumentResult], document_id: str) -> None:
    suite, path = EXPECTED[document_id]
    expected = json.loads(path.read_text(encoding="utf-8"))
    records = expected.get("records") or []
    items = results[document_id].payload["extraction_result"]["items"]
    for position, record in enumerate(records):
        record_index = None if len(records) == 1 else position + 1
        quantity = next(c for c in items if c["field_name"] == "activity_quantity" and c["record_index"] == record_index)
        unit = next(c for c in items if c["field_name"] == "activity_unit" and c["record_index"] == record_index)
        assert quantity["raw_value"] == record["raw_quantity"]
        assert unit["raw_value"] == record["raw_unit"]
        assert ("unit_converted" in quantity["validation_flags"]) == (record["raw_unit"] != record["activity_unit"])


def test_candidates_match_the_contract(results: dict[str, DocumentResult]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPO_ROOT / "contracts" / "extraction_candidate.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for result in results.values():
        items = result.payload["extraction_result"]["items"]
        assert len({c["candidate_id"] for c in items}) == len(items), "candidate ids must be unique"
        for candidate in items:
            errors = sorted(validator.iter_errors(candidate), key=str)
            assert not errors, (candidate["candidate_id"], [e.message for e in errors])


def test_report_lists_core_accuracy_per_document(results: dict[str, DocumentResult], tmp_path: Path) -> None:
    report = render_report(list(results.values()))
    (tmp_path / "ext001_report.md").write_text(report, encoding="utf-8")
    for document_id in IDS:
        assert f"| {document_id} |" in report
    assert "FAIL" not in report
