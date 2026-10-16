"""Textract before-and-after check: does a Textract model update change what we read?

AWS updates Textract's text detection model from time to time (one starts 2026-10-30) and
the model cannot be pinned. This script runs the same scanned samples through live
Textract and our normal pipeline, and compares the values we extract with a recorded
baseline, field by field.

    record    call Textract now and save the raw responses and the extracted values
    compare   call Textract now and report every field (and model version) that changed
    reread    no AWS call: read the saved responses again with the current code and save
              the values, after a change to our own reading rules (prints what changed)

Credentials: the AWS profile's session, exported first:

    eval "$(aws configure export-credentials --profile sustentra --format env)"
    python -m backend.scripts.textract_regression compare

Each run calls AnalyzeDocument (FORMS, TABLES) once per sample page: three pages, a few
cents. The saved responses also back a CI test that replays them offline
(backend/tests/services/test_textract_regression_baseline.py).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.parser_service import ParserService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "backend" / "tests" / "services" / "data" / "textract_regression"
BASELINE = DATA_DIR / "baseline.json"
GAS_BILL_SCAN = REPO_ROOT / "s1-test-suite" / "raw_documents" / "ocr_png" / "EV-NG-2023-001" / "page-1.png"

# name -> how to get the file: a path, or "pdf_from:<path>" for a scanned PDF with no text
# layer made from that image (the pipeline renders its page and sends it to Textract).
SAMPLES: dict[str, str] = {
    "scanned_gas_bill_png": str(GAS_BILL_SCAN),
    "scanned_gas_bill_pdf_no_text_layer": f"pdf_from:{GAS_BILL_SCAN}",
    "electric_bill_photo_png": str(DATA_DIR / "electric_bill_photo.png"),
}


@contextmanager
def sample_file(spec: str) -> Iterator[Path]:
    if not spec.startswith("pdf_from:"):
        yield Path(spec)
        return
    import fitz  # PyMuPDF, already the PDF parser

    image = fitz.open(spec.removeprefix("pdf_from:"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scan_no_text_layer.pdf"
        fitz.open("pdf", image.convert_to_pdf()).save(path)
        yield path


class RecordingClient:
    """Calls the real Textract client and keeps every raw response."""

    def __init__(self, client: Any, responses: list[dict[str, Any]]) -> None:
        self._client = client
        self._responses = responses

    def analyze_document(self, **kwargs: Any) -> dict[str, Any]:
        response = self._client.analyze_document(**kwargs)
        response.pop("ResponseMetadata", None)
        self._responses.append(response)
        return response


class ReplayClient:
    """Returns recorded responses in order, without calling AWS."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)

    def analyze_document(self, **_: Any) -> dict[str, Any]:
        if not self._responses:
            raise RuntimeError("more Textract calls than recorded responses")
        return self._responses.pop(0)


def extract(path: Path, client_factory: Callable[..., Any]) -> dict[str, Any]:
    """Our normal pipeline with Textract on: the document type and every value read."""

    previous = os.environ.get("TEXTRACT_ENABLED")
    os.environ["TEXTRACT_ENABLED"] = "true"
    try:
        service = PipelineOrchestrationService(
            parser_service=ParserService(live_textract_parser=AwsTextractParser(client_factory=client_factory)),
            pipeline_repository=InMemoryPipelineRunRepository(),
            extraction_result_repository=InMemoryExtractionResultRepository(),
        )
        out = service.process_local_document(str(path), engagement_id="TEXTRACT-REGRESSION", persist_run=False)
    finally:
        if previous is None:
            os.environ.pop("TEXTRACT_ENABLED", None)
        else:
            os.environ["TEXTRACT_ENABLED"] = previous
    run = out["pipeline_run"]
    values: dict[str, dict[str, Any]] = {}
    for item in (out.get("extraction_result") or {}).get("items") or []:
        if item.get("normalized_value") is None:
            continue
        record = "" if item.get("record_index") is None else f"#{item['record_index']} "
        values[f"{record}{item['field_name']}"] = {"value": item["normalized_value"], "unit": item.get("unit")}
    return {
        "type": run.get("canonical_type_id"),
        "halt": (run.get("halt_reason") or {}).get("code"),
        "values": dict(sorted(values.items())),
    }


def run_live(region: str) -> dict[str, Any]:
    import boto3

    samples: dict[str, Any] = {}
    for name, spec in SAMPLES.items():
        responses: list[dict[str, Any]] = []

        def factory(service_name: str, _responses: list[dict[str, Any]] = responses, **kwargs: Any) -> Any:
            return RecordingClient(boto3.client(service_name, **{"region_name": region, **kwargs}), _responses)

        with sample_file(spec) as path:
            result = extract(path, factory)
        samples[name] = {
            "file": spec.replace(str(REPO_ROOT) + "/", ""),
            "model_versions": sorted({str(r.get("AnalyzeDocumentModelVersion")) for r in responses}),
            **result,
            "responses": responses,
        }
    return samples


def compare(baseline: dict[str, Any], now: dict[str, Any]) -> list[tuple[str, str, Any, Any]]:
    """(sample, what, baseline, now) for everything that differs."""

    changes: list[tuple[str, str, Any, Any]] = []
    for name, before in baseline["samples"].items():
        after = now.get(name)
        if after is None:
            changes.append((name, "sample", "present", "missing"))
            continue
        if before["model_versions"] != after["model_versions"]:
            changes.append((name, "Textract model version", before["model_versions"], after["model_versions"]))
        for key in ("type", "halt"):
            if before[key] != after[key]:
                changes.append((name, key, before[key], after[key]))
        for field in sorted(set(before["values"]) | set(after["values"])):
            if before["values"].get(field) != after["values"].get(field):
                changes.append((name, field, before["values"].get(field), after["values"].get(field)))
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("record", "compare", "reread"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = parser.parse_args(argv)

    if args.mode == "reread":
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        before = json.loads(json.dumps(baseline))
        for name, sample in baseline["samples"].items():
            replay = ReplayClient(sample["responses"])
            with sample_file(SAMPLES[name]) as path:
                sample.update(extract(path, lambda *_args, **_kwargs: replay))
        for name, what, old, new in compare(before, baseline["samples"]):
            print(f"CHANGED  {name}  {what}:  {json.dumps(old)}  ->  {json.dumps(new)}")
        BASELINE.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Values re-read from the saved responses into {BASELINE.relative_to(REPO_ROOT)}")
        return 0

    now = run_live(args.region)
    if args.mode == "record":
        BASELINE.write_text(json.dumps({
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "region": args.region,
            "feature_types": ["FORMS", "TABLES"],
            "samples": now,
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        for name, sample in now.items():
            print(f"{name}: {sample['type']} · {len(sample['values'])} values · model {', '.join(sample['model_versions'])}")
        print(f"Baseline saved to {BASELINE.relative_to(REPO_ROOT)}")
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changes = compare(baseline, now)
    print(f"Baseline recorded {baseline['recorded_at']}; compared now.")
    if not changes:
        print("No change: every sample reads the same values as the baseline.")
        return 0
    for name, what, before, after in changes:
        print(f"CHANGED  {name}  {what}:  {json.dumps(before)}  ->  {json.dumps(after)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
