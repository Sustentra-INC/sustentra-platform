"""Try one scanned PDF (or image) in each of Textract's three modes and compare what they cost and what we get.

    python -m backend.tools.textract_modes /path/to/scan.pdf --yes [--region us-east-1]

Modes (prices per page from ``textract_usage.PRICE_MICROUSD_PER_PAGE``):

    forms_tables   AnalyzeDocument FORMS + TABLES   $0.065   what the app uses today
    tables         AnalyzeDocument TABLES           $0.015
    detect_text    DetectDocumentText               $0.0015  plain lines, no forms or tables

For each mode it prints the pages sent, the cost, the document type our classifier chose, and how many values
our extractors read. Run it on our own sample scans, by hand. It calls AWS, which is billed, so it needs ``--yes``
and refuses to run when ``CI`` is set. It reads the file and prints; it writes nothing (no files, no database, no
ledger rows), and the app's default mode is not changed by it.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.repositories.extraction_result_repository import InMemoryExtractionResultRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.parser_service import ParserService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.textract_usage import DETECT_TEXT, FORMS_TABLES, TABLES, estimate_microusd

MODES: dict[str, list[str]] = {FORMS_TABLES: ["FORMS", "TABLES"], TABLES: ["TABLES"], DETECT_TEXT: []}


class CountingClient:
    """The real Textract client, counting the pages it is asked to read. With no feature types it makes the
    DetectDocumentText call instead of AnalyzeDocument."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.pages = 0

    def analyze_document(self, **kwargs: Any) -> dict[str, Any]:
        self.pages += 1
        if not kwargs.get("FeatureTypes"):
            return dict(self._client.detect_document_text(Document=kwargs["Document"]))
        return dict(self._client.analyze_document(**kwargs))


def run_mode(path: Path, features: list[str], region: str) -> tuple[int, dict[str, Any]]:
    import boto3

    client = CountingClient(boto3.client("textract", region_name=region))
    previous = os.environ.get("TEXTRACT_ENABLED")
    os.environ["TEXTRACT_ENABLED"] = "true"
    try:
        service = PipelineOrchestrationService(
            parser_service=ParserService(live_textract_parser=AwsTextractParser(
                client_factory=lambda *_a, **_k: client, feature_types=features)),
            pipeline_repository=InMemoryPipelineRunRepository(),
            extraction_result_repository=InMemoryExtractionResultRepository(),
        )
        # No org_id: the call is neither checked against the monthly limit nor written to the ledger.
        out = service.process_local_document(str(path), engagement_id="TEXTRACT-MODES", persist_run=False)
    finally:
        if previous is None:
            os.environ.pop("TEXTRACT_ENABLED", None)
        else:
            os.environ["TEXTRACT_ENABLED"] = previous
    return client.pages, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path, help="a local scanned PDF or image")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--yes", action="store_true", help="confirm that AWS Textract is called and billed")
    args = parser.parse_args(argv)

    if os.environ.get("CI"):
        print("Refusing to run in CI: this calls AWS Textract.", file=sys.stderr)
        return 2
    if not args.yes:
        print("This calls AWS Textract three times over the file (billed). Run again with --yes.", file=sys.stderr)
        return 2
    if not args.file.is_file():
        print(f"Not a file: {args.file}", file=sys.stderr)
        return 2

    print(f"{'mode':<14}{'pages':>6}{'cost':>10}  {'type':<34}{'values':>7}")
    for mode, features in MODES.items():
        try:
            pages, out = run_mode(args.file, features, args.region)
        except Exception as exc:  # noqa: BLE001 - one mode failing should not hide the others
            print(f"{mode:<14}  failed: {type(exc).__name__}")
            continue
        items = (out.get("extraction_result") or {}).get("items") or []
        values = sum(1 for item in items if item.get("normalized_value") is not None)
        run = out["pipeline_run"]
        kind = str(run.get("canonical_type_id") or (run.get("halt_reason") or {}).get("code") or "-")
        cost = estimate_microusd(pages, mode) / 1_000_000
        print(f"{mode:<14}{pages:>6}{'$' + format(cost, '.4f'):>10}  {kind:<34}{values:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
