"""S2 gap record emission for Subsystem 2 PR13."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid5, NAMESPACE_URL


class S2GapRecordService:
    """Converts S2 findings into stage-specific gap records for S3."""

    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def from_completeness_result(self, result: dict) -> list[dict]:
        engagement_id = str(result["engagement_id"])
        records: list[dict] = []
        for row in result.get("results", []):
            status = row.get("status")
            if status not in {"missing_required", "provisional_condition_unknown"}:
                continue
            records.append(
                self._record(
                    engagement_id=engagement_id,
                    field_id=str(row["field_id"]),
                    substage="completeness",
                    gap_type=str(status),
                    root_cause_code=str(status),
                    assertion="completeness",
                    severity="high" if status == "missing_required" else "medium",
                    source_reference=None,
                    rule_id=None,
                )
            )
        return records

    def from_verification_result(
        self,
        result: dict,
        *,
        engagement_id: str,
    ) -> list[dict]:
        records: list[dict] = []
        for row in result.get("results", []):
            status = row.get("status")
            if status not in {"failed", "cannot_verify", "provisional", "unsupported"}:
                continue
            field_id = (row.get("applies_to") or ["verification"])[0]
            records.append(
                self._record(
                    engagement_id=engagement_id,
                    field_id=str(field_id),
                    substage="verification",
                    gap_type=f"verification_{status}",
                    root_cause_code=str(status),
                    assertion=row.get("assertion"),
                    severity="high" if status == "failed" else "medium",
                    source_reference=None,
                    rule_id=row.get("rule_id"),
                )
            )
        return records

    def from_derivation_results(
        self,
        results: list[dict],
        *,
        engagement_id: str,
    ) -> list[dict]:
        records: list[dict] = []
        for row in results:
            status = row.get("status")
            if status == "derived":
                continue
            records.append(
                self._record(
                    engagement_id=engagement_id,
                    field_id=str(row["field_id"]),
                    substage="derivation",
                    gap_type=f"derivation_{status}",
                    root_cause_code=str(status),
                    assertion="derivation",
                    severity="medium",
                    source_reference=None,
                    rule_id=None,
                )
            )
        return records

    def from_recompute_result(
        self,
        result: dict,
        *,
        engagement_id: str,
        field_id: str,
    ) -> list[dict]:
        status = result.get("status")
        if status == "matched":
            return []
        return [
            self._record(
                engagement_id=engagement_id,
                field_id=field_id,
                substage="recompute",
                gap_type=f"recompute_{status}",
                root_cause_code=str(status),
                assertion="recompute",
                severity="high" if status == "mismatch" else "medium",
                source_reference=None,
                rule_id=None,
            )
        ]

    def _record(
        self,
        *,
        engagement_id: str,
        field_id: str,
        substage: str,
        gap_type: str,
        root_cause_code: str,
        assertion: str | None,
        severity: str,
        source_reference: dict | None,
        rule_id: str | None,
        evidence_id: str | None = None,
        document_id: str | None = None,
    ) -> dict:
        created_at = self._clock()
        raw_id = "::".join(
            [
                engagement_id,
                field_id,
                substage,
                gap_type,
                rule_id or "",
                created_at,
            ]
        )
        return {
            "gap_record_id": f"s2-gap::{uuid5(NAMESPACE_URL, raw_id).hex}",
            "engagement_id": engagement_id,
            "evidence_id": evidence_id,
            "document_id": document_id,
            "field_id": field_id,
            "stage": "S2",
            "substage": substage,
            "gap_type": gap_type,
            "root_cause_code": root_cause_code,
            "assertion": assertion,
            "severity": severity,
            "source_reference": source_reference,
            "rule_id": rule_id,
            "created_at": created_at,
        }
