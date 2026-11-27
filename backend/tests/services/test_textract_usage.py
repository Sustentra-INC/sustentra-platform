"""MVP-245: every Textract call is in the ledger, and the month's AI and scan limit is one limit."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from backend.app.adapters.parsers.aws_textract_parser import AwsTextractParser
from backend.app.core.config import get_settings
from backend.app.repositories.parsed_text_repository import InMemoryParsedTextRepository
from backend.app.services import textract_usage as tu
from backend.app.services.parser_service import ParserService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.services.test_parser_service import _pdf

ORG = "eeeeeeee-0000-0000-0000-0000000000e5"
OTHER_ORG = "ffffffff-0000-0000-0000-0000000000f6"
SCAN = ["Cover letter with enough text to count", "", "Back page text that counts", ""]  # pages 2 and 4 are scans
LINE = {"BlockType": "LINE", "Id": "l1", "Text": "Total kWh Used: 700 kWh", "Confidence": 99.0, "Page": 1,
        "Geometry": {"BoundingBox": {"Left": 0.1, "Top": 0.4, "Width": 0.5, "Height": 0.03}}}


class FakeLedger:
    """What the database ledger does, in memory: AI spend is preset per org, scans are rows."""

    def __init__(self, ai_microusd: dict[str, int] | None = None) -> None:
        self.ai = ai_microusd or {}
        self.rows: list[dict[str, Any]] = []

    def month_spend_microusd(self, org_id: uuid.UUID) -> int:
        return self.ai.get(str(org_id), 0) + sum(r["cost_microusd"] for r in self.rows if r["org_id"] == org_id)

    def record(self, **row: Any) -> None:
        self.rows.append(row)


class Client:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_document(self, **kwargs: Any) -> dict:
        self.calls += 1
        return {"Blocks": [{"BlockType": "PAGE", "Id": "p1", "Page": 1}, LINE]}


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TEXTRACT_ENABLED", "true")
    monkeypatch.setenv("TEXTRACT_FEATURE_TYPES", "FORMS,TABLES")
    get_settings.cache_clear()
    yield


def _setup(ledger: FakeLedger, features: list[str] | None = None) -> tuple[ParserService, Client, Any]:
    client = Client()
    live = AwsTextractParser(client_factory=lambda *a, **k: client, feature_types=features)
    service = ParserService(live_textract_parser=live, parsed_texts=InMemoryParsedTextRepository())
    restore = tu.use_ledger(ledger)
    return service, client, restore


def test_a_call_writes_one_row_with_pages_mode_and_cost(tmp_path: Path) -> None:
    ledger = FakeLedger()
    service, client, restore = _setup(ledger)
    try:
        service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1", org_id=ORG)
    finally:
        restore()
    assert client.calls == 2 and len(ledger.rows) == 2
    row = ledger.rows[0]
    assert row["org_id"] == uuid.UUID(ORG) and row["document_id"] == "DOC-1" and len(row["sha256"]) == 64
    assert row["pages"] == 1 and row["mode"] == "forms_tables" and row["cost_microusd"] == 65_000 and row["ok"]


def test_the_cheaper_modes_are_priced_by_their_features(tmp_path: Path) -> None:
    assert [tu.estimate_microusd(1, tu.price_mode(f)) for f in (["TABLES"], ["FORMS"], ["FORMS", "TABLES"], [])] == [
        15_000, 50_000, 65_000, 1_500]
    assert tu.price_mode(["QUERIES"]) == tu.FORMS_TABLES  # unknown features: the highest price


def test_a_failed_call_is_recorded_at_zero_cost(tmp_path: Path) -> None:
    ledger = FakeLedger()

    class Broken:
        def analyze_document(self, **kwargs: Any) -> dict:
            raise RuntimeError("throttled")

    live = AwsTextractParser(client_factory=lambda *a, **k: Broken())
    service = ParserService(live_textract_parser=live, parsed_texts=InMemoryParsedTextRepository())
    restore = tu.use_ledger(ledger)
    try:
        service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1", org_id=ORG)
    finally:
        restore()
    assert ledger.rows and all(r["ok"] is False and r["cost_microusd"] == 0 for r in ledger.rows)


def test_ai_spend_plus_the_scan_estimate_over_the_cap_blocks_the_scan_and_marks_the_document(tmp_path: Path) -> None:
    cap = get_settings().ai_monthly_cap_usd
    ledger = FakeLedger({ORG: round(cap * 1_000_000) - 10_000})  # 10 000 left: under one page's 65 000
    service, client, restore = _setup(ledger)
    try:
        output = service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1", org_id=ORG)
    finally:
        restore()
    assert client.calls == 0 and ledger.rows == []
    capped = [w for w in output["warnings"] if w["code"] == "scan_cap_reached"]
    assert len(capped) == 1 and "Pages 2, 4 are scans and were not read" in capped[0]["message"]
    assert "limit is reached" in capped[0]["message"]
    assert output["pages"][0]["text"].startswith("Cover letter")  # the typed pages are still read


def test_a_blocked_read_is_not_kept_so_it_can_be_read_later(tmp_path: Path) -> None:
    cap = get_settings().ai_monthly_cap_usd
    ledger = FakeLedger({ORG: round(cap * 1_000_000)})
    service, client, restore = _setup(ledger)
    path = _pdf(tmp_path / "s.pdf", SCAN)
    try:
        service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
        ledger.ai[ORG] = 0  # next month, or the limit raised
        again = service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)
    finally:
        restore()
    assert client.calls == 2 and not any(w["code"] == "scan_cap_reached" for w in again["warnings"])


def test_a_blocked_image_halts_with_the_not_read_sentence(tmp_path: Path) -> None:
    cap = get_settings().ai_monthly_cap_usd
    ledger = FakeLedger({ORG: round(cap * 1_000_000)})
    service, client, restore = _setup(ledger)
    image = tmp_path / "bill.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    try:
        output = service.parse_document(image, "DOC-1", "RUN-1", mime_type="image/png", org_id=ORG)
    finally:
        restore()
    assert client.calls == 0 and output["status"] == "failed"
    halt = PipelineOrchestrationService._unreadable_halt(output)
    assert halt["code"] == "scan_limit_reached"
    assert halt["message"] == "Not read: this month's AI and scan limit is reached. It can be read later."


def test_a_reread_from_stored_text_costs_nothing_and_writes_no_row(tmp_path: Path) -> None:
    ledger = FakeLedger()
    service, client, restore = _setup(ledger)
    path = _pdf(tmp_path / "s.pdf", SCAN)
    try:
        service.parse_document(path, "DOC-1", "RUN-1", org_id=ORG)
        rows, spent = len(ledger.rows), ledger.month_spend_microusd(uuid.UUID(ORG))
        service.parse_document(path, "DOC-1", "RUN-2", org_id=ORG)
    finally:
        restore()
    assert len(ledger.rows) == rows == 2 and ledger.month_spend_microusd(uuid.UUID(ORG)) == spent == 130_000
    assert client.calls == 2


def test_another_orgs_spend_never_counts(tmp_path: Path) -> None:
    cap = get_settings().ai_monthly_cap_usd
    ledger = FakeLedger({OTHER_ORG: round(cap * 1_000_000) * 10})
    service, client, restore = _setup(ledger)
    try:
        service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1", org_id=ORG)
    finally:
        restore()
    assert client.calls == 2 and {r["org_id"] for r in ledger.rows} == {uuid.UUID(ORG)}


@pytest.mark.parametrize("pages", [0, -3, -(10**9), None, "abc", True])
def test_hostile_page_counts_cost_nothing_and_never_block(pages: Any) -> None:
    assert tu.page_count(pages) == 0 and tu.estimate_microusd(pages, tu.FORMS_TABLES) == 0
    assert tu.would_exceed(10**12, 0, 25.0) is False  # nothing to bill: never refused, even over the cap
    ledger = FakeLedger()
    restore = tu.use_ledger(ledger)
    try:
        assert tu._gate({"org_id": ORG, "pages": pages, "feature_types": ["FORMS", "TABLES"]}) is None
        tu._hook({"org_id": ORG, "pages": pages, "feature_types": [], "ok": True})
    finally:
        restore()
    assert ledger.rows == []  # the table requires pages > 0: no row for a call with none


def test_a_5000_page_estimate_is_blocked_under_the_default_cap() -> None:
    estimate = tu.estimate_microusd(5000, tu.FORMS_TABLES)
    assert estimate == 325_000_000
    assert tu.would_exceed(0, estimate, 25.0) is True
    ledger = FakeLedger()
    restore = tu.use_ledger(ledger)
    try:
        assert tu._gate({"org_id": ORG, "pages": 5000, "feature_types": ["FORMS", "TABLES"]}) == "scan_cap_reached"
        assert tu._gate({"org_id": ORG, "pages": 100, "feature_types": ["FORMS", "TABLES"]}) is None  # $6.50
    finally:
        restore()


def test_exactly_reaching_the_cap_is_allowed_one_micro_over_is_not() -> None:
    assert tu.would_exceed(25_000_000 - 65_000, 65_000, 25.0) is False
    assert tu.would_exceed(25_000_000 - 65_000 + 1, 65_000, 25.0) is True


def test_a_ledger_that_cannot_be_read_blocks_the_scan_without_failing_the_read(tmp_path: Path) -> None:
    class Down(FakeLedger):
        def month_spend_microusd(self, org_id: uuid.UUID) -> int:
            raise RuntimeError("db down")

    service, client, restore = _setup(Down())
    try:
        output = service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1", org_id=ORG)
    finally:
        restore()
    assert client.calls == 0
    assert any(w["code"] == "scan_cap_reached" and "could not be checked" in w["message"] for w in output["warnings"])


def test_a_call_with_no_organization_is_not_gated_or_recorded(tmp_path: Path) -> None:
    ledger = FakeLedger()
    service, client, restore = _setup(ledger)
    try:
        service.parse_document(_pdf(tmp_path / "s.pdf", SCAN), "DOC-1", "RUN-1")
    finally:
        restore()
    assert client.calls == 2 and ledger.rows == []
