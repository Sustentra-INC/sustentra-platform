"""No type id, classifier score, parser output or exception text reaches a client through a pipeline run:
the run endpoints answer the halt's code with its plain sentence, and each warning and error with its
code and a plain sentence. The stored record keeps the pipeline's own text."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.api import pipeline as pipeline_api
from backend.app.main import app
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.halt_text import (
    GENERIC_NOTE,
    PIPELINE_FAILED,
    plain_halt_reason,
    plain_note,
    plain_pipeline_run,
)
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService

# What must never appear in a client body: a type id, a score, a parser's or the classifier's own words.
LEAK = re.compile(r"CT-S\d|\b0\.\d{2}\b|Parser said|Textract|classifier chose|closest match|confidence \d", re.IGNORECASE)
# Not part of the run itself: the dev tool's debug payloads (parser output, classification result, targets).
RUN_KEYS = ("pipeline_run",)

UNSUPPORTED = "Rechnung für Müller Käserei – Zürich 電気\nDear customer, thank you for your order.\nNothing about energy."


@pytest.fixture
def ctx(tmp_path):
    original = pipeline_api._service
    repo = InMemoryPipelineRunRepository()
    service = PipelineOrchestrationService(pipeline_repository=repo, clock=lambda: "2026-01-01T00:00:00+00:00")
    pipeline_api.configure_service(service)
    path = tmp_path / "Rechnung März 電気.txt"
    path.write_text(UNSUPPORTED, encoding="utf-8")
    try:
        with TestClient(app) as client:
            yield {"client": client, "path": str(path), "repo": repo}
    finally:
        pipeline_api.configure_service(original)


def _process(ctx: dict, evidence_id: str, **extra: Any):
    body = {"local_file_path": ctx["path"], "engagement_id": "ENG-1", "evidence_id": evidence_id,
            "persist_run": True, **extra}
    return ctx["client"].post("/v1/pipeline/local/process-document", json=body)


def test_a_real_unsupported_halt_is_plain_on_every_run_endpoint(ctx: dict) -> None:
    created = _process(ctx, "EV-U")
    # Whether the halt makes the run partial (200) or failed (422), no body carries the raw text.
    body = created.json()
    if created.status_code == 200:  # the debug payloads (parser output, classification result) are not the run
        assert not LEAK.search(json.dumps({k: body[k] for k in ("pipeline_run", "extraction_result")})), created.text[:400]
    else:
        assert not LEAK.search(created.text), created.text[:400]
    stored = ctx["repo"].get_latest_by_evidence("EV-U")
    assert stored is not None
    raw = (stored.get("halt_reason") or {}).get("message", "")
    assert re.search(r"CT-S|closest match|does not match", raw) or stored.get("halt_reason") is None  # the record is raw

    run_id = stored["pipeline_run_id"]
    for path in (f"/v1/pipeline/runs/{run_id}", "/v1/pipeline/evidence/EV-U/latest-run"):
        response = ctx["client"].get(path)
        assert response.status_code == 200, response.text
        assert not LEAK.search(response.text), (path, response.text[:400])
        halt = response.json().get("halt_reason")
        if halt:
            assert halt["code"] == "unsupported_document"
            assert halt["message"] == "We couldn't tell what kind of document this is. Choose its type in Evidence."
    status = ctx["client"].get("/v1/pipeline/evidence/EV-U/status")
    assert status.status_code == 200 and not LEAK.search(json.dumps(status.json()["latest_pipeline_run"]))


def test_the_stored_record_is_not_changed_by_reading_it(ctx: dict) -> None:
    _process(ctx, "EV-S")
    before = json.dumps(ctx["repo"].get_latest_by_evidence("EV-S"), sort_keys=True, default=str)
    ctx["client"].get("/v1/pipeline/evidence/EV-S/latest-run")
    after = json.dumps(ctx["repo"].get_latest_by_evidence("EV-S"), sort_keys=True, default=str)
    assert before == after


# --- the mapping, over every warning the pipeline writes --------------------------------------

RAW_UNSUPPORTED = ("Unsupported document type: the closest match was CT-S1-ONSGEN with confidence 0.41, below the "
                   "0.55 needed to extract automatically. Set the document type manually if it is a supported "
                   "type. It reads as stationary fuel use (natural gas): CT-S1-FUELQTY is likely.")

WARNINGS = [
    "pages_unread: Pages 11-20, 51 could not be read, so any values on them are missing.",
    "The classifier chose CT-S1-MOBFUEL, but the document reads as stationary fuel use (boiler); using CT-S1-FUELQTY.",
    "The classifier chose CT-S1-FUELQTY, but the document's quantities are electricity (kWh/MWh) and it names no "
    "combusted fuel; using CT-S2-ELEC (purchased electricity, Scope 2).",
    "The classifier chose CT-S1-FUELQTY, but the document is a steam, hot water or chilled water bill and names no "
    "combusted fuel; using CT-S2-THERMAL (purchased steam, heat or cooling, Scope 2).",
    "The classifier chose CT-S1-FUELQTY; the document names a refrigerant and an amount added or recovered, so it is "
    "read as CT-S1-REFRSVC (refrigerant service record).",
    "Classifier confidence 0.42 was below its threshold; accepted CT-S1-FUELQTY because the document names a fuel",
    "Claude suggested CT-S2-ELEC from the first pages; the rules could not place this document. Confirm the type.",
    "No confident canonical_type_id available; target planning and candidate generation were skipped.",
    "ai_type_disagrees: the rules chose CT-S1-FUELQTY, Claude read the first pages as CT-S2-ELEC. The type was not "
    "changed.",
    "ai_routing_ignored: quote 0.30 not found on the page CT-S1-X",
    "ai_unavailable: Claude could not be reached.",
    "ai_cap_reached: this month's limit on Claude suggestions is reached, so the type was not read by Claude.",
    "ai_pages_skipped: Pages 4-9 were not read by Claude.",
    "ai_extraction: ai_suggested 3, ai_disagrees 1, ai_conflict 0, dropped 2, cost $0.0123, windows 2 of 2.",
    "No extraction targets were generated for the resolved canonical type.",
    "Pipeline orchestration failed: KeyError('CT-S1-X') in /srv/app/pipeline.py",
    RAW_UNSUPPORTED,
]


def test_every_known_warning_is_plain_and_keeps_its_code() -> None:
    halt = {"code": "unsupported_document", "message": RAW_UNSUPPORTED}
    for warning in WARNINGS:
        plain = plain_note(warning, halt)
        assert not LEAK.search(plain), (warning, plain)
        assert plain != GENERIC_NOTE, f"unmapped: {warning}"
    assert plain_note(WARNINGS[0]) == WARNINGS[0]  # the frontend reads the pages from this one, as written
    assert plain_note(RAW_UNSUPPORTED, halt).startswith("unsupported_document: We couldn't tell")
    assert plain_note(WARNINGS[-2]) == PIPELINE_FAILED
    assert "cost" not in plain_note(WARNINGS[13]) and "ai_suggested 3" in plain_note(WARNINGS[13])


def test_a_note_nobody_mapped_never_leaks_and_is_logged_by_its_code_only(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="sustentra.halt_text"):
        plain = plain_note("new_check: the closest match was CT-S1-NEW with confidence 0.31 (Müller 電気)")
    assert plain == GENERIC_NOTE
    assert any("new_check" in r.getMessage() and "CT-S1" not in r.getMessage() for r in caplog.records)
    # Plain text with no internal wording is kept, non-ASCII included.
    assert plain_note("Zählerstand für Käserei Zürich 電気 fehlt.") == "Zählerstand für Käserei Zürich 電気 fehlt."


def test_a_run_record_is_cleaned_without_touching_the_original() -> None:
    run = {"pipeline_run_id": "p1", "halt_reason": {"code": "unreadable_document",
                                                     "message": "Unreadable document: Parser said: 電気 page 3"},
           "warnings": ["Unreadable document: Parser said: 電気 page 3", WARNINGS[1]],
           "errors": ["Pipeline orchestration failed: boom"], "canonical_type_id": "CT-S1-FUELQTY"}
    snapshot = json.dumps(run, sort_keys=True)
    cleaned = plain_pipeline_run(run)
    assert cleaned is not None and json.dumps(run, sort_keys=True) == snapshot
    assert cleaned["halt_reason"] == {"code": "unreadable_document", "message": "File could not be read."}
    assert cleaned["warnings"][0] == "unreadable_document: File could not be read."
    assert not LEAK.search(json.dumps({k: v for k, v in cleaned.items() if k != "canonical_type_id"}))
    assert cleaned["canonical_type_id"] == "CT-S1-FUELQTY"  # data the screens use is kept
    assert plain_halt_reason(None) is None
    assert plain_pipeline_run(None) is None


def test_an_unmapped_halt_code_gets_a_generic_sentence() -> None:
    cleaned = plain_halt_reason({"code": "new_halt", "message": RAW_UNSUPPORTED})
    assert cleaned is not None and cleaned["code"] == "new_halt" and not LEAK.search(cleaned["message"])
