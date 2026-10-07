"""SEC-001 - assign S1 records written before org scoping to an organization.

Records created before SEC-001 have no ``org_id``, so org users cannot see them
(only a provider_admin can). ``claim_engagement`` stamps one engagement's unowned
records with an org: documents, pipeline runs, review decisions and approved
evidence. Uploaded files are moved into the org's storage folder so they can be
processed again. Records that already have an owner are never changed.

The JSONL stores are append-only logs; claiming rewrites each file in place after
copying it to ``<file>.bak-<timestamp>`` and swaps the new content in atomically.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.repositories import document_repository, evidence_repository, pipeline_repository, review_repository
from backend.app.services.local_storage_service import LocalStorageService

DOCUMENTS = document_repository.DEFAULT_JSONL_PATH
PIPELINE_RUNS = pipeline_repository.DEFAULT_JSONL_PATH
REVIEW_DECISIONS = review_repository.DEFAULT_JSONL_PATH
APPROVED_EVIDENCE = evidence_repository.DEFAULT_JSONL_PATH
UPLOADS = "local-data/uploads"


@dataclass
class ClaimReport:
    engagement_id: str
    org_id: str
    dry_run: bool
    claimed: dict[str, int] = field(default_factory=dict)
    owned_by_other_org: dict[str, int] = field(default_factory=dict)
    files_moved: int = 0
    files_missing: int = 0
    files_skipped: int = 0
    backups: list[str] = field(default_factory=list)

    @property
    def total_claimed(self) -> int:
        return sum(self.claimed.values())


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write(path: Path, records: list[dict[str, Any]], report: ClaimReport, stamp: str) -> None:
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    report.backups.append(str(backup))
    tmp = path.with_name(f".{path.name}.claim-tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(tmp, path)


def claim_engagement(
    engagement_id: str,
    org_id: str,
    *,
    data_root: str | Path = ".",
    dry_run: bool = False,
    now: datetime | None = None,
) -> ClaimReport:
    if not engagement_id.strip():
        raise ValueError("engagement_id is required")
    if not org_id.strip():
        raise ValueError("org_id is required")
    root = Path(data_root)
    report = ClaimReport(engagement_id=engagement_id, org_id=org_id, dry_run=dry_run)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")

    def claim_file(name: str, relative: str, belongs: Any, mutate: Any = None) -> list[dict[str, Any]]:
        path = root / relative
        records = _read(path)
        changed = False
        claimed = other = 0
        for record in records:
            if not belongs(record):
                continue
            owner = record.get("org_id")
            if owner is None:
                claimed += 1
                if not dry_run:
                    record["org_id"] = org_id
                    if mutate is not None:
                        mutate(record)
                    changed = True
            elif str(owner) != org_id:
                other += 1
        report.claimed[name] = claimed
        report.owned_by_other_org[name] = other
        if changed:
            _write(path, records, report, stamp)
        return records

    moved: dict[str, str] = {}
    uploads_root = (root / UPLOADS).resolve()
    engagement_folder = LocalStorageService._sanitize_component(engagement_id, "engagement_id")
    prefix = Path(UPLOADS).parts

    def move_upload(record: dict[str, Any]) -> None:
        """Move the stored file under ``<uploads>/<org_id>/`` and rewrite its storage_uri."""

        uri = str(record.get("storage_uri") or "")
        if uri in moved:
            record["storage_uri"] = moved[uri]
            return
        parts = Path(uri).parts
        if not parts or Path(uri).is_absolute():
            report.files_missing += 1
            return
        suffix = parts[len(prefix):] if parts[: len(prefix)] == prefix else parts
        if suffix and suffix[0] == org_id:
            return  # already in the org's folder
        if not suffix or suffix[0] != engagement_folder:
            report.files_skipped += 1  # not this engagement's folder: never move another engagement's file
            return
        source = uploads_root.joinpath(*suffix).resolve()
        if not source.is_relative_to(uploads_root) or not source.is_file():
            report.files_missing += 1
            return
        target = uploads_root.joinpath(org_id, *suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        new_uri = Path(UPLOADS, org_id, *suffix).as_posix()
        moved[uri] = new_uri
        record["storage_uri"] = new_uri
        report.files_moved += 1

    documents = claim_file("documents", DOCUMENTS, lambda r: r.get("engagement_id") == engagement_id, move_upload)
    document_ids = {r.get("document_id") for r in documents if r.get("engagement_id") == engagement_id}
    evidence_ids = {r.get("evidence_id") for r in documents if r.get("engagement_id") == engagement_id}
    evidence_ids.discard(None)
    claim_file("pipeline_runs", PIPELINE_RUNS, lambda r: r.get("engagement_id") == engagement_id)
    claim_file(
        "review_decisions",
        REVIEW_DECISIONS,
        lambda r: r.get("document_id") in document_ids or r.get("evidence_id") in evidence_ids,
    )
    claim_file("approved_evidence", APPROVED_EVIDENCE, lambda r: r.get("engagement_id") == engagement_id)
    return report
