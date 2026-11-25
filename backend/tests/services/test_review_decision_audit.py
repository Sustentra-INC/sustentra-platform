"""Every review decision written through the service adds one audit event, with ids only.

Postgres writes the event in the decision's transaction (see tests/db/test_review_decisions_add_only.py);
the file stores write the decision first and the event after, and log an error when the event fails.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest

from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository, JsonlReviewDecisionRepository
from backend.app.repositories.s1_stores import MirroredRepository
from backend.app.services.review_decision_service import AUDIT_EVENT_TYPES, AuditContext, ReviewDecisionService

USER = uuid.UUID("11111111-0000-0000-0000-000000000001")
SECRET_NOTE = "client said the meter was swapped"
SECRET_VALUE = 987654321
SECRET_FILE = "acme-march-gas-bill.pdf"


def _candidate() -> dict[str, Any]:
    return {
        "candidate_id": "candidate::EV-1::DOC-1::activity_quantity",
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "field_name": "activity_quantity",
        "display_label": "Activity quantity",
        "raw_value": "28,100 MMBtu",
        "normalized_value": 28100,
        "unit": "MMBtu",
        "confidence": 0.9,
        "source_reference": {"document_id": "DOC-1", "text_snippet": "Total Usage 28,100 MMBtu", "file_name": SECRET_FILE},
        "validation_flags": [],
    }


def _context() -> AuditContext:
    return AuditContext(org_id="org-1", actor_user_id=USER, actor_role="org_member", engagement_id="ENG-1",
                        pipeline_run_id="RUN-1", request_id="req-1", ip_address="10.0.0.1", user_agent="pytest")


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _service(repository: Any, writer: Any = None) -> ReviewDecisionService:
    return ReviewDecisionService(repository=repository, audit_writer=writer)


@pytest.mark.parametrize(
    ("decision", "kwargs", "event_type"),
    [
        ("accepted", {}, "review_value_accepted"),
        ("edited", {"reviewed_value": SECRET_VALUE, "reviewed_unit": "kWh"}, "review_value_edited"),
        ("rejected", {"reviewer_note": SECRET_NOTE}, "review_value_rejected"),
        ("needs_more_evidence", {"reviewer_note": SECRET_NOTE}, "review_value_more_evidence_requested"),
    ],
)
def test_each_decision_adds_one_event_with_ids_only(decision: str, kwargs: dict[str, Any], event_type: str) -> None:
    recorder = _Recorder()
    service = _service(InMemoryReviewDecisionRepository(), recorder)
    saved = service.submit_decision(_candidate(), decision, "rev@example.com", org_id="org-1", audit=_context(), **kwargs)

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["event_type"] == event_type == AUDIT_EVENT_TYPES[decision]
    assert (event["org_id"], event["actor_user_id"], event["actor_role"]) == ("org-1", USER, "org_member")
    assert (event["target_type"], event["target_id"]) == ("engagement", "ENG-1")
    assert event["metadata"] == {
        "review_decision_id": saved["review_decision_id"],
        "candidate_id": "candidate::EV-1::DOC-1::activity_quantity",
        "field_name": "activity_quantity",
        "document_id": "DOC-1",
        "evidence_id": "EV-1",
        "engagement_id": "ENG-1",
        "pipeline_run_id": "RUN-1",
        "decision": decision,
    }
    text = json.dumps(event, default=str)
    for secret in (SECRET_NOTE, str(SECRET_VALUE), SECRET_FILE, "MMBtu", "28100", "28,100", "kWh"):
        assert secret not in text


def test_without_an_engagement_the_event_is_about_the_document() -> None:
    recorder = _Recorder()
    context = AuditContext(org_id="org-1", actor_user_id=USER, actor_role="org_member")
    _service(InMemoryReviewDecisionRepository(), recorder).submit_decision(
        _candidate(), "accepted", "r", audit=context)
    assert (recorder.events[0]["target_type"], recorder.events[0]["target_id"]) == ("document", "DOC-1")
    assert "engagement_id" not in recorder.events[0]["metadata"]


def test_a_rejected_request_writes_no_event() -> None:
    recorder = _Recorder()
    service = _service(InMemoryReviewDecisionRepository(), recorder)
    with pytest.raises(ValueError):
        service.submit_decision(_candidate(), "edited", "r", audit=_context())  # edited needs a value
    assert recorder.events == []


def test_a_failed_event_after_a_file_decision_is_logged_and_the_decision_stays(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    repository = JsonlReviewDecisionRepository(tmp_path / "decisions.jsonl")

    def failing(_event: dict[str, Any]) -> None:
        raise RuntimeError("audit database down")

    with caplog.at_level(logging.ERROR, logger="sustentra.review_audit"):
        saved = _service(repository, failing).submit_decision(_candidate(), "accepted", "r", audit=_context())

    assert [r["review_decision_id"] for r in repository.list_all()] == [saved["review_decision_id"]]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert saved["review_decision_id"] in errors[0].getMessage() and "review_value_accepted" in errors[0].getMessage()


def test_no_audit_writer_is_an_error_not_a_silent_skip(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="sustentra.review_audit"):
        _service(InMemoryReviewDecisionRepository()).submit_decision(_candidate(), "accepted", "r", audit=_context())
    assert any("missing" in r.getMessage() for r in caplog.records)


def test_a_failed_decision_write_writes_no_event(tmp_path: Any) -> None:
    class Broken(InMemoryReviewDecisionRepository):
        def save(self, decision: Any, audit: Any = None) -> dict:
            raise OSError("disk full")

    recorder = _Recorder()
    with pytest.raises(OSError):
        _service(Broken(), recorder).submit_decision(_candidate(), "accepted", "r", audit=_context())
    assert recorder.events == []


def test_an_atomic_repository_gets_the_event_and_the_service_does_not_write_it_again() -> None:
    class Atomic(InMemoryReviewDecisionRepository):
        audits_atomically = True
        seen: list[Any] = []

        def save(self, decision: Any, audit: Any = None) -> dict:
            self.seen.append(audit)
            return super().save(decision)

    repository = Atomic()
    recorder = _Recorder()
    _service(repository, recorder).submit_decision(_candidate(), "accepted", "r", audit=_context())
    assert len(repository.seen) == 1 and repository.seen[0]["event_type"] == "review_value_accepted"
    assert recorder.events == []


def test_a_failed_atomic_save_is_raised_so_it_is_never_reported_saved() -> None:
    class Atomic(InMemoryReviewDecisionRepository):
        audits_atomically = True

        def save(self, decision: Any, audit: Any = None) -> dict:
            raise RuntimeError("audit insert failed, transaction rolled back")

    with pytest.raises(RuntimeError):
        _service(Atomic()).submit_decision(_candidate(), "accepted", "r", audit=_context())


def test_the_mirrored_store_passes_the_event_to_postgres_and_mirrors_the_decision(tmp_path: Any) -> None:
    class Primary(InMemoryReviewDecisionRepository):
        audits_atomically = True
        seen: list[Any] = []

        def save(self, decision: Any, audit: Any = None) -> dict:
            self.seen.append(audit)
            return super().save(decision)

    mirror = JsonlReviewDecisionRepository(tmp_path / "m.jsonl")
    repository = MirroredRepository(Primary(), mirror)
    assert repository.audits_atomically is True
    recorder = _Recorder()
    saved = _service(repository, recorder).submit_decision(_candidate(), "accepted", "r", audit=_context())
    assert repository._primary.seen[0]["event_type"] == "review_value_accepted"
    assert recorder.events == []
    assert [r["review_decision_id"] for r in mirror.list_all()] == [saved["review_decision_id"]]


def test_a_duplicate_submit_adds_a_second_decision_and_a_second_event_as_before() -> None:
    repository = InMemoryReviewDecisionRepository()
    recorder = _Recorder()
    service = _service(repository, recorder)
    for _ in range(2):
        service.submit_decision(_candidate(), "accepted", "r", audit=_context())
    assert len(repository.list_all()) == 2 and len(recorder.events) == 2
    assert repository.get_latest_by_candidate("candidate::EV-1::DOC-1::activity_quantity") == repository.list_all()[-1]


def test_the_api_service_has_an_audit_writer() -> None:
    from backend.app.api import reviews

    assert reviews._service._audit_writer is not None


def test_every_event_type_matches_the_audit_log_format() -> None:
    import re

    assert all(re.fullmatch(r"[a-z][a-z0-9_]{1,63}", t) for t in AUDIT_EVENT_TYPES.values())
