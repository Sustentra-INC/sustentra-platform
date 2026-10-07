"""Golden sets for Scope 1 fuel extraction: EXT-001 (CT-S1-FUELQTY, stationary) and
EXT-002 (CT-S1-MOBFUEL, mobile).

Runs each sample in ``s1-test-suite/<suite>`` through the production pipeline
(ParserService -> ClassificationService -> targets -> extraction) and scores the
candidates against ``expected/<id>.expected.json``.

    python -m backend.tests.golden_s1.stationary_combustion_golden [stationary_combustion|mobile_combustion]
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITES = ("stationary_combustion", "mobile_combustion")
SUITE_ROOT = REPO_ROOT / "s1-test-suite" / "stationary_combustion"
# Core fields per canonical type; a core field is always checked (expected None if absent).
CORE_FIELDS = {
    "CT-S1-FUELQTY": ("fuel_type", "activity_quantity", "activity_unit", "service_period_start",
                      "service_period_end", "facility_name"),
    "CT-S1-MOBFUEL": ("fuel_type", "activity_quantity", "activity_unit", "transaction_date"),
}
NOT_FIELDS = {"record_hint", "raw_quantity", "raw_unit"}


def suite_root(suite: str) -> Path:
    return REPO_ROOT / "s1-test-suite" / suite


@dataclass
class FieldCheck:
    record: int | None
    field_id: str
    expected: Any
    actual: Any
    core: bool
    ok: bool
    traceable: bool


@dataclass
class DocumentResult:
    document_id: str
    file: str
    classification_expected: str | None
    classification_actual: str | None
    halt_expected: str | None
    halt_actual: str | None
    records_expected: int
    records_actual: int
    checks: list[FieldCheck] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    unattended_halt_expected: str | None = None
    unattended_halt_actual: str | None = None

    @property
    def core_checks(self) -> list[FieldCheck]:
        return [c for c in self.checks if c.core]

    @property
    def core_accuracy(self) -> float:
        core = self.core_checks
        return sum(c.ok for c in core) / len(core) if core else 1.0

    @property
    def field_accuracy(self) -> float:
        return sum(c.ok for c in self.checks) / len(self.checks) if self.checks else 1.0

    @property
    def classification_ok(self) -> bool:
        return self.classification_expected is None or self.classification_actual == self.classification_expected

    @property
    def halt_ok(self) -> bool:
        return (
            self.halt_actual == self.halt_expected
            and self.unattended_halt_actual == self.unattended_halt_expected
        )

    @property
    def traceability_ok(self) -> bool:
        return all(c.traceable for c in self.checks if c.actual is not None)

    @property
    def passed(self) -> bool:
        return (
            self.classification_ok
            and self.halt_ok
            and self.records_actual == self.records_expected
            and all(c.ok for c in self.checks)
            and self.traceability_ok
        )


def expected_files(root: Path = SUITE_ROOT) -> list[Path]:
    return sorted((root / "expected").glob("*.expected.json"))


def _same(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(float(expected) - float(actual)) < 1e-6
    return " ".join(str(expected).split()).casefold() == " ".join(str(actual or "").split()).casefold()


def _traceable(candidate: dict, document_id: str) -> bool:
    ref = candidate.get("source_reference") or {}
    box = ref.get("bounding_box") or {}
    return (
        ref.get("document_id") == document_id
        and bool(ref.get("text_snippet"))
        and ref.get("page_number") is not None
        and bool(ref.get("parser_block_ids"))
        and all(isinstance(box.get(k), (int, float)) for k in ("x", "y", "width", "height"))
        and 0 <= box["x"] <= 1 and 0 <= box["y"] <= 1 and box["width"] > 0 and box["height"] > 0
    )


def _process(root: Path, expected: dict, override: str | None) -> dict:
    document_id = expected["document_id"]
    service = PipelineOrchestrationService(pipeline_repository=_NullRepository())
    return service.process_local_document(
        local_file_path=str(root / "documents" / expected["file"]),
        engagement_id="golden-ext001",
        evidence_id=f"golden::{document_id}",
        document_id=document_id,
        processing_run_id=f"golden::{document_id}",
        canonical_type_id_override=override,
        persist_run=False,
    )


def run_document(expected_path: Path, root: Path = SUITE_ROOT) -> DocumentResult:
    """Score one sample.

    A sample with ``reviewer_override`` is one the classifier must NOT decide on its own
    (e.g. diesel: stationary vs mobile). It is run twice: without the override it must
    halt with ``expected_halt_without_override``; the fields are scored on the run with
    the reviewer's override applied.
    """

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    document_id = expected["document_id"]
    override = expected.get("reviewer_override")
    unattended_halt: str | None = None
    if override:
        unattended = _process(root, expected, None)["pipeline_run"]
        unattended_halt = (unattended.get("halt_reason") or {}).get("code")
    output = _process(root, expected, override)
    run = output["pipeline_run"]
    halt = (run.get("halt_reason") or {}).get("code")
    candidates = output["extraction_result"].get("items") or []
    by_record: dict[int | None, dict[str, dict]] = {}
    for candidate in candidates:
        by_record.setdefault(candidate.get("record_index"), {})[candidate["field_name"]] = candidate

    expected_records = expected.get("records") or []
    actual_record_keys = sorted(by_record, key=lambda k: (k is None, k or 0))
    result = DocumentResult(
        document_id=document_id,
        file=expected["file"],
        classification_expected=expected.get("expected_classification"),
        classification_actual=run.get("canonical_type_id"),
        halt_expected=expected.get("expected_halt"),
        halt_actual=halt,
        records_expected=len(expected_records),
        records_actual=len(actual_record_keys),
        payload=output,
        unattended_halt_expected=expected.get("expected_halt_without_override"),
        unattended_halt_actual=unattended_halt,
    )
    for position, expected_record in enumerate(expected_records):
        record_index = None if len(expected_records) == 1 else position + 1
        actual = by_record.get(record_index, {})
        canonical = expected.get("reviewer_override") or expected.get("expected_classification")
        core = CORE_FIELDS.get(str(canonical), ())
        record_fields = [f for f in core if f not in (expected.get("document_fields") or {})]
        record_fields += [f for f in expected_record if f not in NOT_FIELDS and f not in record_fields]
        for field_id in record_fields:
            _check(result, actual.get(field_id), record_index, field_id, expected_record.get(field_id),
                   field_id in core, document_id)
        for field_id, value in (expected.get("document_fields") or {}).items():
            _check(result, actual.get(field_id), record_index, field_id, value, field_id in core, document_id)
    return result


def _check(result: DocumentResult, candidate: dict | None, record: int | None, field_id: str, expected: Any,
           core: bool, document_id: str) -> None:
    actual = candidate.get("normalized_value") if candidate else None
    result.checks.append(FieldCheck(
        record=record, field_id=field_id, expected=expected, actual=actual, core=core,
        ok=_same(expected, actual),
        traceable=candidate is None or actual is None or _traceable(candidate, document_id),
    ))


class _NullRepository:
    def save(self, run: dict) -> dict:
        return run

    def get_by_id(self, _: str) -> None:
        return None

    def get_latest_by_evidence(self, _: str) -> None:
        return None


def run_all(root: Path = SUITE_ROOT) -> list[DocumentResult]:
    return [run_document(path, root) for path in expected_files(root)]


def render_report(results: list[DocumentResult]) -> str:
    lines = [
        "# Scope 1 fuel extraction - golden report",
        "",
        "| Document | Classified | Halt | Records | Core-field accuracy | All-field accuracy | Traceable | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.document_id} | {r.classification_actual or '-'}{'' if r.classification_ok else ' (expected ' + str(r.classification_expected) + ')'} "
            f"| {r.halt_actual or ('needs reviewer type: ' + str(r.unattended_halt_actual) if r.unattended_halt_actual else '-')}"
            f"{'' if r.halt_ok else ' (expected ' + str(r.halt_expected or r.unattended_halt_expected) + ')'} "
            f"| {r.records_actual}/{r.records_expected} | {r.core_accuracy:.0%} | {r.field_accuracy:.0%} "
            f"| {'yes' if r.traceability_ok else 'NO'} | {'PASS' if r.passed else 'FAIL'} |"
        )
    failures = [(r.document_id, c) for r in results for c in r.checks if not c.ok or not c.traceable]
    if failures:
        lines += ["", "## Mismatches", ""]
        for document_id, c in failures:
            where = f" record {c.record}" if c.record else ""
            lines.append(f"- {document_id}{where} `{c.field_id}`: expected {c.expected!r}, got {c.actual!r}"
                         + ("" if c.traceable else " (no bounding box / snippet)"))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover - manual report
    suites = sys.argv[1:] or list(SUITES)
    for name in suites:
        sys.stdout.write(f"\n## {name}\n\n" + render_report(run_all(suite_root(name))))
