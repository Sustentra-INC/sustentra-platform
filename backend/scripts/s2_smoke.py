"""Subsystem 2 orchestration smoke test.

This script starts from a synthetic ApprovedEvidence object and runs the PR14
backend flow. It does not parse raw documents and does not call S1 extraction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.s2_orchestration_service import (  # noqa: E402
    build_default_s2_orchestration_service,
)


def run_smoke(output_json: str | Path | None = None) -> dict:
    service = build_default_s2_orchestration_service()
    result = service.run(_approved_evidence())
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _approved_evidence() -> dict:
    fields = [
        _field("fuel_type", "Natural Gas", None, "review-fuel"),
        _field("activity_quantity", 28100, "MMBtu", "review-quantity"),
        _field("activity_unit", "MMBtu", None, "review-unit"),
    ]
    return {
        "approved_evidence_id": "approved-smoke-001",
        "evidence_id": "EV-SMOKE-001",
        "engagement_id": "ENG-SMOKE-001",
        "document_id": "DOC-SMOKE-001",
        "evidence_type": "CT-S1-FUELQTY",
        "review_status": "approved",
        "field_count": len(fields),
        "approved_field_count": len(fields),
        "fields": fields,
        "created_at": "2026-01-01T00:00:00+00:00",
        "source_review_decision_ids": [
            "review-fuel",
            "review-quantity",
            "review-unit",
        ],
    }


def _field(
    field_name: str,
    approved_value: str | float | int | None,
    approved_unit: str | None,
    review_decision_id: str,
) -> dict:
    return {
        "field_name": field_name,
        "display_label": field_name.replace("_", " ").title(),
        "extracted_value": approved_value,
        "approved_value": approved_value,
        "approved_unit": approved_unit,
        "decision": "accepted",
        "source_reference": {
            "document_id": "DOC-SMOKE-001",
            "text_snippet": "Total Usage 28,100 MMBtu",
        },
        "review_decision_id": review_decision_id,
        "candidate_id": f"candidate-{review_decision_id}",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "confidence": 0.91,
        "validation_flags": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the S2 orchestration smoke flow.")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    result = run_smoke(args.output_json)
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
