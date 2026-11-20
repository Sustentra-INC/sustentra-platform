"""The automatic read of summary documents: which completed reads ask for it, and the debounce.

A summary type (Block 1) asks once; a bill never does; a batch of uploads is read once, after the last
one; nothing re-reads on a timer (no new document, no read). The read itself is tested against
Postgres in tests/db/test_auto_read_db.py."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend.app.core.config import Settings
from backend.app.services import auto_read
from backend.app.services.auto_read import AutoReader
from backend.tests.services.test_document_processing_service import ORG, FakePipeline, make_world

ENG = "ENG-1"


class Recorder:
    def __init__(self) -> None:
        self.prepared: list[tuple[str, str, list[str]]] = []
        self.runs: list[tuple[str, str, list[str]]] = []
        self.ran = threading.Event()

    async def prepare(self, org: str, eng: str, names: list[str]) -> bool:
        self.prepared.append((org, eng, list(names)))
        return True

    async def run(self, org: str, eng: str, names: list[str]) -> None:
        self.runs.append((org, eng, list(names)))
        self.ran.set()


def wait_for(predicate: Any, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    auto_read.set_reader(AutoReader(debounce_seconds=0.15, prepare=rec.prepare, run=rec.run))
    monkeypatch.setattr(auto_read, "get_settings", lambda: Settings(
        environment="test", git_sha="t", ALLOWED_ORIGINS="https://x.test", ai_suggestions_enabled=True))  # type: ignore[call-arg]
    yield rec
    auto_read.set_reader(None)


def complete(tmp_path: Path, canonical_type_id: str, file_name: str = "report.txt") -> None:
    """A document of this type finishes reading through the executor (the code both the API and the reader use)."""

    result = {"pipeline_run": {"pipeline_run_id": "P-1", "status": "completed", "canonical_type_id": canonical_type_id,
                               "halt_reason": None, "errors": []}, "extraction_result": {"items": []}}
    world = make_world(tmp_path, FakePipeline(result))
    world.uploads.get_document(world.document["document_id"])
    run = world.claimed()
    world.service.finish(run, world.service.execute(run), retry=True)


def test_an_upload_of_a_summary_type_triggers_exactly_one_read(recorder: Recorder, tmp_path: Path) -> None:
    complete(tmp_path, "CT-GHG-WORKBOOK")
    assert recorder.ran.wait(3)
    time.sleep(0.4)  # and nothing more: no timer re-reads
    assert recorder.runs == [(ORG, ENG, ["bill.txt"])]
    assert len(recorder.prepared) == 1


@pytest.mark.parametrize("type_id", ["CT-S1-FUELQTY", "CT-S1-ELEC", "", "CT-GHG-ORGBOUND-NOT"])
def test_an_upload_of_a_bill_triggers_none(recorder: Recorder, tmp_path: Path, type_id: str) -> None:
    complete(tmp_path, type_id)
    time.sleep(0.5)
    assert recorder.prepared == [] and recorder.runs == []


def test_a_failed_read_triggers_none(recorder: Recorder, tmp_path: Path) -> None:
    world = make_world(tmp_path, FakePipeline({"pipeline_run": {"pipeline_run_id": "P-1", "status": "failed",
                                                                "canonical_type_id": "CT-GHG-WORKBOOK"}}))
    run = world.claimed()
    world.service.finish(run, world.service.execute(run), retry=True)
    time.sleep(0.4)
    assert recorder.runs == []


def test_a_batch_is_read_once_after_the_last_document(recorder: Recorder) -> None:
    reader = auto_read.default_reader()
    for name in ("a.xlsx", "b.pdf", "c.docx"):
        reader.note(ORG, ENG, name)
        time.sleep(0.05)  # each arrives inside the wait of the one before
    reader.note(ORG, ENG, "c.docx")  # the same file again is not listed twice
    assert recorder.ran.wait(3)
    time.sleep(0.4)
    assert recorder.runs == [(ORG, ENG, ["a.xlsx", "b.pdf", "c.docx"])]


def test_engagements_are_debounced_on_their_own(recorder: Recorder) -> None:
    reader = auto_read.default_reader()
    reader.note(ORG, "ENG-1", "a.pdf")
    reader.note(ORG, "ENG-2", "b.pdf")
    assert wait_for(lambda: len(recorder.runs) == 2)
    assert sorted(r[1] for r in recorder.runs) == ["ENG-1", "ENG-2"]


def test_a_later_document_starts_a_later_read(recorder: Recorder) -> None:
    reader = auto_read.default_reader()
    reader.note(ORG, ENG, "a.pdf")
    assert wait_for(lambda: len(recorder.runs) == 1)
    reader.note(ORG, ENG, "b.pdf")
    assert wait_for(lambda: len(recorder.runs) == 2)
    assert recorder.runs[1][2] == ["b.pdf"]


def test_the_switch_off_schedules_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()

    async def refuse(org: str, eng: str, names: list[str]) -> bool:
        return False  # the organization switched it off

    auto_read.set_reader(AutoReader(debounce_seconds=0.05, prepare=refuse, run=rec.run))
    try:
        auto_read.default_reader().note(ORG, ENG, "a.pdf")
        time.sleep(0.4)
        assert rec.runs == []
    finally:
        auto_read.set_reader(None)


def test_the_deployments_ai_switch_off_asks_for_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rec = Recorder()
    auto_read.set_reader(AutoReader(debounce_seconds=0.05, prepare=rec.prepare, run=rec.run))
    monkeypatch.setattr(auto_read, "get_settings", lambda: Settings(
        environment="test", git_sha="t", ALLOWED_ORIGINS="https://x.test", ai_suggestions_enabled=False))  # type: ignore[call-arg]
    try:
        complete(tmp_path, "CT-GHG-WORKBOOK")
        time.sleep(0.4)
        assert rec.prepared == [] and rec.runs == []
    finally:
        auto_read.set_reader(None)


def test_a_reader_that_breaks_never_fails_the_document(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Broken:
        def note(self, *args: Any) -> None:
            raise RuntimeError("boom")

    auto_read.set_reader(Broken())  # type: ignore[arg-type]
    monkeypatch.setattr(auto_read, "get_settings", lambda: Settings(
        environment="test", git_sha="t", ALLOWED_ORIGINS="https://x.test", ai_suggestions_enabled=True))  # type: ignore[call-arg]
    try:
        complete(tmp_path, "CT-GHG-WORKBOOK")  # finish still returns the completed run
    finally:
        auto_read.set_reader(None)


def test_shutdown_stops_the_loop_and_closes_the_pool(recorder: Recorder) -> None:
    reader = auto_read.default_reader()
    reader.note(ORG, ENG, "a.pdf")
    assert recorder.ran.wait(3)
    disposed: list[bool] = []

    class Engine:
        async def dispose(self) -> None:
            disposed.append(True)

    reader._engine = Engine()
    loop = reader._loop
    reader.shutdown()
    assert disposed == [True] and reader._engine is None
    assert wait_for(lambda: loop is not None and not loop.is_running())
