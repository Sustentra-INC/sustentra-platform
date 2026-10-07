from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app import cli
from backend.app.services import s1_ownership_claim as claim

ORG = "aaaaaaaa-0000-4000-8000-00000000000a"
OTHER = "bbbbbbbb-0000-4000-8000-00000000000b"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _write(root: Path, relative: str, records: list[dict]) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def data(tmp_path: Path) -> Path:
    upload = tmp_path / claim.UPLOADS / "ENG-1" / "EV-1" / "DOC-1" / "bill.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"pdf")
    doc = {"document_id": "DOC-1", "engagement_id": "ENG-1", "evidence_id": "EV-1",
           "storage_uri": "local-data/uploads/ENG-1/EV-1/DOC-1/bill.pdf", "processing_status": "not_started"}
    _write(tmp_path, claim.DOCUMENTS, [
        doc,
        {**doc, "processing_status": "completed"},  # append-only log: a second version
        {"document_id": "DOC-2", "engagement_id": "ENG-2", "evidence_id": "EV-2", "storage_uri": "x"},
        {"document_id": "DOC-3", "engagement_id": "ENG-1", "evidence_id": "EV-3", "storage_uri": "y",
         "org_id": OTHER},
    ])
    _write(tmp_path, claim.PIPELINE_RUNS, [{"pipeline_run_id": "R1", "engagement_id": "ENG-1"},
                                           {"pipeline_run_id": "R2", "engagement_id": "ENG-2"}])
    _write(tmp_path, claim.REVIEW_DECISIONS, [{"review_decision_id": "D1", "evidence_id": "EV-1", "document_id": "DOC-1"},
                                              {"review_decision_id": "D2", "evidence_id": "EV-2", "document_id": "DOC-2"}])
    _write(tmp_path, claim.APPROVED_EVIDENCE, [{"approved_evidence_id": "A1", "engagement_id": "ENG-1"}])
    return tmp_path


def test_dry_run_reports_and_changes_nothing(data: Path) -> None:
    before = (data / claim.DOCUMENTS).read_text()
    report = claim.claim_engagement("ENG-1", ORG, data_root=data, dry_run=True, now=NOW)
    assert report.claimed == {"documents": 2, "pipeline_runs": 1, "review_decisions": 1, "approved_evidence": 1}
    assert report.owned_by_other_org["documents"] == 1
    assert (data / claim.DOCUMENTS).read_text() == before
    assert report.backups == []


def test_claim_stamps_only_the_engagements_unowned_records(data: Path) -> None:
    report = claim.claim_engagement("ENG-1", ORG, data_root=data, now=NOW)
    assert report.total_claimed == 5
    docs = {(d["document_id"], d.get("processing_status")): d for d in _read(data / claim.DOCUMENTS)}
    assert docs[("DOC-1", "not_started")]["org_id"] == ORG
    assert docs[("DOC-1", "completed")]["org_id"] == ORG
    assert "org_id" not in docs[("DOC-2", None)]                       # other engagement untouched
    assert docs[("DOC-3", None)]["org_id"] == OTHER                    # already owned: never re-assigned
    runs = {r["pipeline_run_id"]: r for r in _read(data / claim.PIPELINE_RUNS)}
    assert runs["R1"]["org_id"] == ORG and "org_id" not in runs["R2"]
    reviews = {r["review_decision_id"]: r for r in _read(data / claim.REVIEW_DECISIONS)}
    assert reviews["D1"]["org_id"] == ORG and "org_id" not in reviews["D2"]
    assert _read(data / claim.APPROVED_EVIDENCE)[0]["org_id"] == ORG


def test_claim_moves_uploads_into_the_org_folder_and_keeps_backups(data: Path) -> None:
    original = (data / claim.DOCUMENTS).read_text()
    report = claim.claim_engagement("ENG-1", ORG, data_root=data, now=NOW)
    assert report.files_moved == 1
    new_uri = f"local-data/uploads/{ORG}/ENG-1/EV-1/DOC-1/bill.pdf"
    doc_versions = [d for d in _read(data / claim.DOCUMENTS) if d["document_id"] == "DOC-1"]
    assert {d["storage_uri"] for d in doc_versions} == {new_uri}
    assert (data / new_uri).read_bytes() == b"pdf"
    assert not (data / "local-data/uploads/ENG-1/EV-1/DOC-1/bill.pdf").exists()
    backup = data / f"{claim.DOCUMENTS}.bak-20261007T120000Z"
    assert str(backup) in report.backups and backup.read_text() == original


def test_claiming_twice_is_a_no_op(data: Path) -> None:
    claim.claim_engagement("ENG-1", ORG, data_root=data, now=NOW)
    second = claim.claim_engagement("ENG-1", ORG, data_root=data, now=NOW)
    assert second.total_claimed == 0 and second.backups == []


def test_missing_files_are_reported(tmp_path: Path) -> None:
    _write(tmp_path, claim.DOCUMENTS, [{"document_id": "D", "engagement_id": "E",
                                        "storage_uri": "local-data/uploads/E/gone.pdf"}])
    report = claim.claim_engagement("E", ORG, data_root=tmp_path, now=NOW)
    assert report.claimed["documents"] == 1 and report.files_missing == 1


def test_files_of_another_engagement_are_never_moved(tmp_path: Path) -> None:
    other = tmp_path / claim.UPLOADS / "E2" / "bill.pdf"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"e2")
    _write(tmp_path, claim.DOCUMENTS, [{"document_id": "D", "engagement_id": "E1",
                                        "storage_uri": "local-data/uploads/E2/bill.pdf"}])
    report = claim.claim_engagement("E1", ORG, data_root=tmp_path, now=NOW)
    assert report.files_skipped == 1 and report.files_moved == 0
    assert other.read_bytes() == b"e2"


def test_required_arguments() -> None:
    with pytest.raises(ValueError):
        claim.claim_engagement(" ", ORG)
    with pytest.raises(ValueError):
        claim.claim_engagement("E", "")


def test_cli_resolves_the_org_slug(data: Path, monkeypatch, capsys) -> None:
    async def fake_lookup(slug: str) -> str | None:
        return ORG if slug == "acme" else None

    monkeypatch.setattr(cli, "_org_id_for_slug", fake_lookup)
    assert cli.main(["claim-s1-data", "--engagement-id", "ENG-1", "--org-slug", "nope", "--data-root", str(data)]) == 2
    assert cli.main(["claim-s1-data", "--engagement-id", "ENG-1", "--org-slug", "acme", "--data-root", str(data),
                     "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would claim engagement ENG-1 for acme" in out and "documents: 2 (1 already owned by another org" in out
