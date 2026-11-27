"""MVP-237: Sustentra's AI reads the whole document (type, values, facility, methodology), in parts, with no page or
line cut-off; the monthly limit is checked before every part and a read it stops is marked read in part; the cost of
each part is recorded under its document. Fake clients and ledgers: no network, no database, no live AI call."""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable, Iterator
from typing import Any, get_args

from backend.app.adapters.llm.base import StructuredReply, TokenUsage
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services import ai_usage
from backend.app.services import document_parts as dp
from backend.app.services import methodology_prefill as mp
from backend.app.services.ai_extraction import AiExtraction
from backend.app.services.ai_facility import AiFacility
from backend.app.services.ai_locator import DocumentLine, document_lines, row_lines
from backend.app.services.ai_routing import AiRouting, RoutingResult, combine
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.services.test_ai_extraction import TARGETS, TYPE, candidate, read, result, settings
from backend.tests.services.test_ai_facility import COMPANY, FACILITIES, ITEMS, STATIONARY
from backend.tests.services.test_ai_locator import _pdf_like
from backend.tests.services.test_pipeline_orchestration_service import (
    FakeClassificationService,
    FakeExtractionService,
    FakeParserService,
    _write_temp_text_file,
)

ORG = str(uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000d7"))
COST = 4_000  # micro-USD a call


def parsed(lines: list[tuple[int, str]], document_id: str = "DOC-1") -> dict[str, Any]:
    return {**_pdf_like(lines, document_id), "status": "parsed", "pages": [], "tables": [], "key_value_pairs": [],
            "warnings": []}


def bundle(pages: int, filler: str = "Monthly operations narrative for the site, nothing to read here.",
           at: dict[int, str] | None = None) -> list[tuple[int, str]]:
    """A ``pages``-page document, two lines a page, with ``at[page]`` replacing that page's second line."""

    at = at or {}
    return [line for page in range(1, pages + 1)
            for line in ((page, f"Page {page} of the bundle"), (page, at.get(page, filler)))]


class Scripted:
    """A fake client. ``answer(index, content)`` is the reply's payload for call ``index``; ``fail_at`` raises there."""

    provider = "anthropic"
    model = "claude-sonnet-5-5"

    def __init__(self, answer: Callable[[int, str], dict[str, Any]], fail_at: int | None = None) -> None:
        self.answer, self.fail_at, self.calls = answer, fail_at, []

    def structured(self, *, system: str, content: Any, output_type: Any, max_tokens: int) -> StructuredReply[Any]:
        index = len(self.calls)
        self.calls.append({"system": system, "content": content, "output_type": output_type})
        if index == self.fail_at:
            raise ConnectionError("the network is down")
        payload = self.answer(index, str(content))
        fields = output_type.model_fields
        if isinstance(next(iter(payload.values()), None), list):  # a methodology part: only the items it may carry
            payload = {k: [i for i in v if _fits(output_type, k, i)] for k, v in payload.items() if k in fields}
        output = output_type.model_validate(payload)
        return StructuredReply(outcome="ok", output=output, model=self.model,  # type: ignore[arg-type]
                               usage=TokenUsage(input_tokens=900, output_tokens=60), cost_microusd=COST,
                               request_id=f"req-{index}", stop_reason="end_turn")


def _fits(output_type: Any, name: str, item: Any) -> bool:
    """Whether a methodology part may carry the item: its field_id (if any) is one the part allows."""

    element = get_args(output_type.model_fields[name].annotation)[0]
    if not isinstance(item, dict) or "field_id" not in getattr(element, "model_fields", {}):
        return True
    return item["field_id"] in get_args(element.model_fields["field_id"].annotation)


class Ledger:
    """A ledger whose month's spend grows with what is recorded, as the real one does."""

    def __init__(self, spent: int = 0) -> None:
        self.spent, self.rows = spent, []

    def month_spend_microusd(self, org_id: uuid.UUID) -> int:
        return self.spent + sum(int(r["cost"] or 0) for r in self.rows)

    def record(self, *, org_id: uuid.UUID, engagement_id: uuid.UUID | None, provider: str, reply: Any,
               document_id: str | None = None) -> None:
        self.rows.append({"cost": reply.cost_microusd, "document_id": document_id})


def lines_of(pages: list[tuple[int, str]]) -> list[DocumentLine]:
    return document_lines(parsed(pages))


def own(parts: list[dp.Part]) -> list[str]:
    return [line.alias for part in parts for line in part.own_lines]


# --- 1. the parts ----------------------------------------------------------------------------------------------

def test_parts_cover_every_line_exactly_once_and_keep_page_numbers() -> None:
    lines = lines_of(bundle(30))
    for max_chars, max_pages in ((300, None), (2_000, 5), (100_000, None), (100_000, 1)):
        parts = list(dp.iter_parts(lines, max_chars=max_chars, max_pages=max_pages))
        assert own(parts) == [line.alias for line in lines], (max_chars, max_pages)
        assert all(sum(dp.line_cost(line) for line in p.lines) <= max_chars for p in parts)
        assert all(line.page_number is not None for p in parts for line in p.lines)
        assert [p.index for p in parts] == list(range(1, len(parts) + 1))
        assert all(p.start == q.end for q, p in zip(parts, parts[1:]))  # back to back, no gap
    assert [p.pages for p in dp.iter_parts(lines, max_chars=100_000, max_pages=10)] == [
        tuple(range(1, 11)), tuple(range(11, 21)), tuple(range(21, 31))]


def test_parts_overlap_only_where_a_table_runs_over_a_page_break() -> None:
    prose = [(1, "Narrative text about the boilers."), (1, "More narrative text."),
             (2, "Further narrative on page two."), (2, "The end of the narrative.")]
    table = [(1, "Usage table"), (1, "Jan 2025 1,204 kWh 88.10"), (1, "Feb 2025 1,310 kWh 91.40"),
             (2, "Mar 2025 1,288 kWh 90.20"), (2, "Apr 2025 1,190 kWh 85.00")]
    prose_parts = list(dp.iter_parts(lines_of(prose), max_chars=100_000, max_pages=1))
    assert [p.overlap for p in prose_parts] == [0, 0]
    table_parts = list(dp.iter_parts(lines_of(table), max_chars=100_000, max_pages=1))
    assert [p.overlap for p in table_parts] == [0, 2]  # the two table rows that end page 1 are shown again
    assert [line.text for line in table_parts[1].lines[:2]] == ["Jan 2025 1,204 kWh 88.10", "Feb 2025 1,310 kWh 91.40"]
    assert own(table_parts) == [line.alias for line in lines_of(table)]  # apart from the overlap, once each


def test_an_empty_page_and_an_empty_document() -> None:
    pages = [(1, "Page one text"), (3, "Page three text")]  # page 2 has no text at all
    parts = list(dp.iter_parts(lines_of(pages), max_chars=100_000, max_pages=1))
    assert [p.pages for p in parts] == [(1,), (3,)]
    assert list(dp.iter_parts([], max_chars=100_000)) == []
    assert dp.describe_lines([]) == "nothing"


def test_a_2000_page_document_is_cut_lazily_and_read_whole() -> None:
    lines = lines_of(bundle(2_000))
    consumed = [0]

    def counting() -> Iterator[DocumentLine]:
        for line in lines:
            consumed[0] += 1
            yield line

    parts = dp.iter_parts(counting(), max_chars=50_000, max_pages=5)
    assert inspect.isgenerator(parts)
    first = next(parts)
    assert first.pages == (1, 2, 3, 4, 5) and consumed[0] < 20  # one part made, not the whole document
    rest = list(parts)
    assert len(rest) == 399 and own([first, *rest]) == [line.alias for line in lines]



def _timed_values(seconds_a_call: float, **over: Any) -> tuple[Any, Scripted]:
    """The values read of a 2,000-page bundle on a clock that moves ``seconds_a_call`` with every call."""

    now = [0.0]
    claude = Scripted(lambda i, c: now.__setitem__(0, now[0] + seconds_a_call) or {"readings": []})
    service = AiExtraction(settings=settings(ai_window_pages=5, ai_monthly_cap_usd=100.0, **over),
                           client_factory=lambda s: claude, ledger=Ledger(), clock=lambda: now[0])
    outcome = service.assist(parser_output=parsed(bundle(2_000)), extraction_result=result(candidate("account_number")),
                             extraction_targets=TARGETS, canonical_type_id=TYPE, file_name="bundle.pdf", org_id=ORG,
                             engagement_id="ENG-1", started=0.0)
    return outcome, claude


def test_a_2000_page_document_is_read_whole_when_the_reader_has_the_time() -> None:
    # Queued, a reader run of 7,200 s: 400 parts at 10 s each end well inside 80% of it (5,760 s).
    outcome, claude = _timed_values(10.0, s1_reader_max_run_seconds=7_200)
    assert len(claude.calls) == 400 and outcome.not_read is None and outcome.windows_read == 400


def test_a_2000_page_document_the_time_cuts_short_says_exactly_what_was_not_read() -> None:
    # The default 900 s run: no part starts after 720 s, and none whose worst case (180 s) ends after 900 s.
    outcome, claude = _timed_values(10.0)
    assert len(claude.calls) == 72 and outcome.windows_read == 72  # 72 parts, 5 pages each: pages 1-360
    assert outcome.not_read == "pages 361–2000"
    assert dp.read_in_part("pages 361–2000", dp.TIME_REASON) in outcome.warnings


def test_a_single_200_kb_line_is_cut_into_overlapping_pieces_that_cover_it() -> None:
    text = "".join(f"cell {n:06d}; " for n in range(16_000))[:200_000]
    (line,) = lines_of([(1, text)])
    parts = list(dp.iter_parts([line], max_chars=50_000))
    assert len(parts) == 5 and all(p.piece is not None for p in parts)
    assert all(len(p.lines[0].text) <= 50_000 for p in parts)
    spans = [p.piece for p in parts]
    assert spans[0] == (0, spans[0][1]) and spans[-1][1] == len(text)  # type: ignore[index]
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))  # type: ignore[index]
    for part in parts[1:]:  # each piece repeats the end of the one before
        start = part.piece[0]  # type: ignore[index]
        assert part.lines[0].text.startswith(text[start - dp.PIECE_OVERLAP_CHARS:start])
    assert all(p.lines[0].alias == "L1" and p.lines[0].source_reference == line.source_reference for p in parts)


def test_a_value_at_the_end_of_a_200_kb_line_is_found() -> None:
    text = ("x" * 199_950) + " Account Number 5521-8890"

    def answer(index: int, content: str) -> dict[str, Any]:
        found = "Account Number 5521-8890" in content
        return {"readings": [read("account_number", "5521-8890", "Account Number 5521-8890", "L1")] if found else []}

    claude = Scripted(answer)
    service = AiExtraction(settings=settings(ai_part_tokens=20_000), client_factory=lambda s: claude, ledger=Ledger(),
                           clock=lambda: 0.0)
    outcome = service.assist(parser_output=parsed([(1, text)]), extraction_result=result(candidate("account_number")),
                             extraction_targets=TARGETS, canonical_type_id=TYPE, file_name="wide.pdf", org_id=ORG,
                             engagement_id="ENG-1", started=0.0)
    (item,) = [i for i in outcome.result["items"] if i["field_name"] == "account_number"]
    assert item["normalized_value"] == "5521-8890" and len(claude.calls) > 1 and outcome.not_read is None


# --- 2. values -------------------------------------------------------------------------------------------------

def _values(lines: list[tuple[int, str]], answer: Callable[[int, str], dict[str, Any]], ledger: Ledger | None = None,
            **over: Any) -> tuple[Any, Scripted, Ledger]:
    claude = Scripted(answer)
    ledger = ledger or Ledger()
    service = AiExtraction(settings=settings(**over), client_factory=lambda s: claude, ledger=ledger, clock=lambda: 0.0)
    outcome = service.assist(parser_output=parsed(lines), extraction_result=result(candidate("activity_quantity")),
                             extraction_targets=TARGETS, canonical_type_id=TYPE, file_name="bundle.pdf", org_id=ORG,
                             engagement_id="ENG-1", started=0.0)
    return outcome, claude, ledger


def _reads_page(page_text: str, alias: str, value: str) -> Callable[[int, str], dict[str, Any]]:
    def answer(index: int, content: str) -> dict[str, Any]:
        if f"{alias}: {page_text}" in content:
            return {"readings": [read("activity_quantity", value, page_text, alias, "kWh")]}
        return {"readings": []}

    return answer


def test_a_60_page_bundle_whose_page_45_has_the_value_is_read_to_the_end() -> None:
    usage = "Total usage 48,200 kWh this period"
    lines = bundle(60, at={45: usage})  # page 45's second line is L90
    outcome, claude, ledger = _values(lines, _reads_page(usage, "L90", "48,200"))
    (item,) = [i for i in outcome.result["items"] if i["field_name"] == "activity_quantity"]
    assert item["normalized_value"] == 48200 and item["source_reference"]["page_number"] == 45
    assert len(claude.calls) == 12 and outcome.not_read is None  # 60 pages, 5 a part: all 12 parts
    assert [r["document_id"] for r in ledger.rows] == ["DOC-1"] * 12 and outcome.cost_microusd == 12 * COST


def test_the_value_in_the_last_part_is_found() -> None:
    usage = "Total usage 9,950 kWh this period"
    outcome, claude, _ = _values(bundle(23, at={23: usage}), _reads_page(usage, "L46", "9,950"))
    (item,) = [i for i in outcome.result["items"] if i["field_name"] == "activity_quantity"]
    assert item["normalized_value"] == 9950 and "Part 5 of 5: pages 21–23" in claude.calls[-1]["content"]


def test_a_value_repeated_on_a_summary_page_counts_once() -> None:
    usage, summary = "Total usage 48,200 kWh this period", "Summary: total usage 48,200 kWh"
    lines = bundle(20, at={3: usage, 20: summary})

    def answer(index: int, content: str) -> dict[str, Any]:
        readings = []
        if f"L6: {usage}" in content:
            readings.append(read("activity_quantity", "48,200", usage, "L6", "kWh"))
        if f"L40: {summary}" in content:
            readings.append(read("activity_quantity", "48,200", "total usage 48,200 kWh", "L40", "kWh"))
        return {"readings": readings}

    outcome, _, _ = _values(lines, answer)
    found = [i for i in outcome.result["items"] if i["field_name"] == "activity_quantity"]
    assert len(found) == 1 and found[0]["validation_flags"] == ["ai_suggested"]  # no double count, no conflict
    assert found[0]["source_reference"]["page_number"] == 3


def test_the_limit_reached_mid_document_stops_with_the_read_in_part_state(tmp_path: Any) -> None:
    usage = "Total usage 12,400 kWh this period"
    cap_after_three = 1_000_000 - 3 * COST  # three parts' cost reaches the 1 USD cap
    outcome, claude, ledger = _values(bundle(60, at={2: usage}), _reads_page(usage, "L4", "12,400"),
                                      ledger=Ledger(spent=cap_after_three))
    assert len(claude.calls) == 3 and len(ledger.rows) == 3
    assert outcome.not_read == "pages 16–60"
    assert ("ai_read_in_part: Read in part: pages 16–60 not read because this month's limit on Sustentra's AI and "
            "scans is reached.") in outcome.warnings
    (item,) = [i for i in outcome.result["items"] if i["field_name"] == "activity_quantity"]
    assert item["normalized_value"] == 12400  # what was read is kept
    # The pipeline never shows it as read whole: the run is partial and carries the sentence as written.
    claude = Scripted(_reads_page(usage, "L4", "12,400"))
    extraction = AiExtraction(settings=settings(), client_factory=lambda s: claude,
                              ledger=Ledger(spent=cap_after_three), clock=lambda: 0.0)
    service = PipelineOrchestrationService(
        parser_service=FakeParserService(parsed(bundle(60, at={2: usage}))),
        classification_service=FakeClassificationService({"status": "classified", "primary_canonical_type_id": TYPE,
                                                          "candidate_matches": [], "confidence": 0.9,
                                                          "threshold": 0.5}),
        target_service=_Targets(), extraction_service=FakeExtractionService(result(candidate("activity_quantity"))),
        pipeline_repository=InMemoryPipelineRunRepository(), clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda prefix, seed: f"{prefix}::{seed}", ai_extraction=extraction,
        ai_routing=_NoRouting(), ai_facility=_NoFacility())
    run = service.process_local_document(local_file_path=_write_temp_text_file(tmp_path), engagement_id="ENG-1",
                                         org_id=ORG, persist_run=False)["pipeline_run"]
    assert run["status"] == "partial" and any(w.startswith("ai_read_in_part: Read in part: pages 16–60")
                                              for w in run["warnings"])
    from backend.app.services.halt_text import plain_note

    assert plain_note(dp.read_in_part("pages 16–60")) == dp.read_in_part("pages 16–60")  # shown as written


class _Targets:
    def get_targets_for_canonical_type(self, canonical_type_id: str, include_optional: bool = True,
                                       include_deprecated: bool = False, include_ai_only: bool = False) -> list[dict]:
        return [dict(t) for t in TARGETS]

    def get_targets_for_classification_result(self, classification_result: dict, include_optional: bool = True,
                                              include_deprecated: bool = False) -> list[dict]:
        return [dict(t) for t in TARGETS]


class _NoRouting:
    shadow = False

    def suggest(self, *args: Any, **kwargs: Any) -> RoutingResult:
        return RoutingResult("off")


class _NoFacility:
    def suggest(self, **kwargs: Any) -> None:
        return None


# --- 3. type ---------------------------------------------------------------------------------------------------

def _verdict(type_id: str, confidence: str, page: int) -> RoutingResult:
    return RoutingResult("suggested", canonical_type_id=type_id, quote="q" * 10, line="L1", reason_code="title",
                         page_number=page, confidence=confidence)


def test_part_verdicts_combine_by_evidence_weight_and_flag_several_types() -> None:
    elec, gas = "CT-S2-ELEC", "CT-S1-FUELQTY"
    one = combine([_verdict(elec, "low", 1), _verdict(gas, "high", 9)])
    assert one.canonical_type_id == gas and one.other_types == (elec,) and one.page_number == 9  # 2 beats 1
    two = combine([_verdict(elec, "low", 1), _verdict(gas, "low", 9), _verdict(elec, "low", 20)])
    assert two.canonical_type_id == elec and two.other_types == (gas,) and two.page_number == 1  # 2 beats 1
    tie = combine([_verdict(elec, "low", 1), _verdict(gas, "low", 9)])
    assert tie.canonical_type_id == elec and tie.other_types == (gas,)  # a tie: the type read first
    agree = combine([_verdict(elec, "low", 1), RoutingResult("none"), _verdict(elec, "high", 30)])
    assert agree.canonical_type_id == elec and agree.other_types == () and agree.page_number == 30
    assert combine([RoutingResult("none"), RoutingResult("ignored", ignored_reason="unknown_line",
                                                         drops={"unknown_line": 1})]).status == "none"
    assert any(n.startswith("ai_several_types:") for n in one.notes()) and "CT-" not in " ".join(one.notes())


def _routing(answer: Callable[[int, str], dict[str, Any]], ledger: Ledger | None = None, **over: Any
             ) -> tuple[RoutingResult, Scripted, Ledger]:
    claude = Scripted(answer)
    ledger = ledger or Ledger()
    service = AiRouting(settings=settings(ai_part_tokens=10_000, **over), client_factory=lambda s: claude,
                        ledger=ledger)
    found = service.suggest(parsed(_typed_bundle()), org_id=ORG, engagement_id="ENG-1", has_targets=lambda t: True)
    return found, claude, ledger


def _typed_bundle() -> list[tuple[int, str]]:
    """20 pages of about 1,000 characters: page 1 an electricity bill, page 15 a gas invoice."""

    pages = [(page, f"Page {page} " + "narrative " * 100) for page in range(1, 21)]
    pages[0] = (1, "Electric Statement for March " + "narrative " * 100)
    pages[14] = (15, "Natural Gas Invoice for March " + "narrative " * 100)
    return pages


def _says(index: int, content: str) -> dict[str, Any]:
    if "L1: Electric Statement" in content:
        return {"canonical_type_id": "CT-S2-ELEC", "quote": "Electric Statement for March", "line": "L1",
                "reason_code": "title", "confidence": "low"}
    if "L15: Natural Gas Invoice" in content:
        return {"canonical_type_id": "CT-S1-FUELQTY", "quote": "Natural Gas Invoice for March", "line": "L15",
                "reason_code": "title", "confidence": "low"}
    return {"canonical_type_id": "none", "quote": "", "line": "", "reason_code": "other", "confidence": "low"}


def test_the_type_read_reads_every_part_and_a_bundle_is_flagged() -> None:
    found, claude, ledger = _routing(_says)
    # (10,000 - 8,000) x 3 = 6,000 characters a part: five pages each, four parts, every one read.
    assert len(claude.calls) == 4 and found.parts_read == 4 and found.not_read is None
    assert found.canonical_type_id == "CT-S2-ELEC" and found.other_types == ("CT-S1-FUELQTY",)
    assert found.as_record(used=True, disagrees=False)["other_types"] == ["CT-S1-FUELQTY"]
    assert [r["document_id"] for r in ledger.rows] == ["DOC-1"] * 4


def test_the_type_read_stopped_by_the_limit_says_what_it_did_not_read() -> None:
    found, claude, _ = _routing(_says, ledger=Ledger(spent=1_000_000 - COST))
    assert len(claude.calls) == 1 and found.status == "suggested" and found.not_read == "pages 6–20"
    assert found.notes() == ["ai_read_in_part: Read in part: pages 6–20 not read because this month's limit on "
                             "Sustentra's AI and scans is reached."]


def test_a_failed_later_part_keeps_the_earlier_verdict_and_says_the_rest_was_not_read() -> None:
    claude = Scripted(_says, fail_at=1)
    service = AiRouting(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude, ledger=Ledger())
    found = service.suggest(parsed(_typed_bundle()), org_id=ORG, engagement_id="ENG-1", has_targets=lambda t: True)
    assert found.status == "suggested" and found.canonical_type_id == "CT-S2-ELEC" and found.not_read == "pages 6–20"
    assert found.warning and found.warning.startswith("ai_unavailable")


# --- 4. facility -----------------------------------------------------------------------------------------------

def _facility(lines: list[tuple[int, str]], answer: Callable[[int, str], dict[str, Any]], ledger: Ledger | None = None
              ) -> tuple[Any, Scripted, list[str]]:
    claude = Scripted(answer)
    service = AiFacility(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude,
                         ledger=ledger or Ledger(), facilities_for=lambda org, eng: (FACILITIES, COMPANY),
                         decided_for=lambda org, eng, doc: None)
    warnings: list[str] = []
    found = service.suggest(parser_output=parsed(lines), extraction_result={"items": ITEMS},
                            canonical_type_id=STATIONARY, file_name="generator-log.csv", org_id=ORG,
                            engagement_id=str(uuid.uuid4()), document_id="DOC-1", warnings=warnings)
    return found, claude, warnings


def _log(at: dict[int, str]) -> list[tuple[int, str]]:
    return [(page, at.get(page, f"Generator run log page {page} " + "hours " * 160)) for page in range(1, 21)]


def _names(index: int, content: str) -> dict[str, Any]:
    for alias, quote, facility in (("L14", "Fresno Plant", "fac-fr"), ("L18", "Tacoma Distribution Center", "fac-tac")):
        if f"{alias}: Site: {quote}" in content:
            return {"facility_id": facility, "quote": quote, "source": "line", "line": alias, "reason": ""}
    return {"facility_id": "none", "quote": "", "source": "file_name", "line": "", "reason": ""}


def test_the_facility_read_considers_every_part_and_decides_once() -> None:
    lines = _log({14: "Site: Fresno Plant"})
    found, claude, warnings = _facility(lines, _names)
    parts = list(dp.iter_parts(lines_of(lines), max_chars=dp.part_chars(10_000, 8_000)))
    assert len(parts) > 2 and len(claude.calls) == len(parts) and found is not None and found.facility_id == "fac-fr" and found.page_number == 14
    assert warnings == [] and found.read_in_part is None



def test_a_facility_read_naming_two_facilities_keeps_both_with_their_quotes() -> None:
    lines = _log({2: "Site: Fresno Plant", 18: "Site: Tacoma Distribution Center"})

    def answer(index: int, content: str) -> dict[str, Any]:
        if "L2: Site: Fresno Plant" in content:
            return {"facility_id": "fac-fr", "quote": "Fresno Plant", "source": "line", "line": "L2", "reason": ""}
        return _names(index, content)

    found, _, _ = _facility(lines, answer)
    assert found is not None and found.facility_id == "fac-fr" and [o.facility_id for o in found.others] == ["fac-tac"]
    record = found.as_record()
    assert record["several"] is True
    assert [(c["facility_id"], c["quote"], c["page_number"]) for c in record["candidates"]] == [
        ("fac-fr", "Fresno Plant", 2), ("fac-tac", "Tacoma Distribution Center", 18)]
    from backend.app.services.ai_facility import explanation

    shown = explanation(record, "Fresno Plant", "generator-log.csv", "DOC-1")
    assert [c["facility_id"] for c in shown["candidates"]] == ["fac-fr", "fac-tac"]


def test_the_type_and_facility_reads_stop_at_the_time_budget_and_say_so() -> None:
    now = [0.0]
    deadline = dp.Deadline(stop_starting=60.0, hard_limit=900.0, clock=lambda: now[0])

    def slow_says(index: int, content: str) -> dict[str, Any]:
        now[0] += 40.0  # each part takes 40 s: the second part starts at 40 s, the third would start at 80 s
        return _says(index, content)

    claude = Scripted(slow_says)
    service = AiRouting(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude, ledger=Ledger())
    found = service.suggest(parsed(_typed_bundle()), org_id=ORG, engagement_id="ENG-1", has_targets=lambda t: True,
                            deadline=deadline)
    assert len(claude.calls) == 2 and found.not_read == "pages 11–20"
    assert found.notes()[-1] == dp.read_in_part("pages 11–20", dp.TIME_REASON)
    now[0] = 0.0
    lines = _log({2: "Site: Fresno Plant"})

    def slow_names(index: int, content: str) -> dict[str, Any]:
        now[0] += 40.0
        if "L2: Site: Fresno Plant" in content:
            return {"facility_id": "fac-fr", "quote": "Fresno Plant", "source": "line", "line": "L2", "reason": ""}
        return _names(index, content)

    claude = Scripted(slow_names)
    facility = AiFacility(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude, ledger=Ledger(),
                          facilities_for=lambda org, eng: (FACILITIES, COMPANY), decided_for=lambda org, eng, doc: None)
    warnings: list[str] = []
    suggestion = facility.suggest(parser_output=parsed(lines), extraction_result={"items": ITEMS},
                                  canonical_type_id=STATIONARY, file_name="generator-log.csv", org_id=ORG,
                                  engagement_id=str(uuid.uuid4()), document_id="DOC-1", warnings=warnings,
                                  deadline=deadline)
    assert len(claude.calls) == 2 and suggestion is not None and suggestion.read_in_part
    assert warnings and warnings[0].endswith(f"not read because {dp.TIME_REASON}.")


def test_the_facility_read_stopped_by_the_limit_is_marked_read_in_part() -> None:
    def early(index: int, content: str) -> dict[str, Any]:
        if "L2: Site: Fresno Plant" in content:
            return {"facility_id": "fac-fr", "quote": "Fresno Plant", "source": "line", "line": "L2", "reason": ""}
        return _names(index, content)

    found, claude, warnings = _facility(_log({2: "Site: Fresno Plant"}), early, ledger=Ledger(spent=1_000_000 - COST))
    assert len(claude.calls) == 1 and found is not None and found.facility_id == "fac-fr"
    assert found.read_in_part and found.read_in_part.endswith("–20")  # what was read is kept, and says so
    assert found.as_record()["read_in_part"] == found.read_in_part
    assert warnings == [dp.read_in_part(found.read_in_part)]


# --- 5. methodology --------------------------------------------------------------------------------------------

def _report(alias: str, document_id: str, pages: int, at: dict[int, str]) -> mp.PrefillDocument:
    lines = [(page, at.get(page, f"Narrative page {page} of the inventory report " + "text " * 4_000))
             for page in range(1, pages + 1)]
    return mp.PrefillDocument(alias, document_id, f"{document_id}.pdf", document_lines(parsed(lines, document_id)),
                              False)


EMPTY = {"choices": [], "gases": [], "texts": [], "estimations": [], "selections": [], "periods": [], "gwp": [],
         "entities": [], "factors": []}


def _prefill_answer(index: int, content: str) -> dict[str, Any]:
    out: dict[str, Any] = {k: [] for k in EMPTY}
    if "L12: We consolidate using the operational control approach." in content:
        out["choices"] = [{"field_id": "consolidation_approach", "value": "Operational Control", "document": "D1",
                           "line": "L12", "quote": "operational control approach", "reason": ""}]
    if "L3: Scope 1 stationary combustion is included." in content:
        out["choices"].append({"field_id": "category:scope1:stationary", "value": "Yes", "document": "D7",
                               "line": "L3", "quote": "stationary combustion is included", "reason": ""})
    elif "=== Document D1, part 1" in content:
        out["choices"].append({"field_id": "category:scope1:stationary", "value": "Not detected", "document": "D1",
                               "line": "", "quote": "", "reason": ""})
    return out


def test_the_methodology_read_uses_every_document_and_every_part() -> None:
    documents = [_report("D1", "DOC-A", 12, {12: "We consolidate using the operational control approach."})]
    documents += [_report(f"D{i}", f"DOC-{i}", 1, {}) for i in range(2, 7)]
    documents.append(_report("D7", "DOC-7", 3, {3: "Scope 1 stationary combustion is included."}))
    claude = Scripted(_prefill_answer)
    whole = mp.run_chunks(claude, documents, spent_microusd=0, cap_usd=100.0)
    parts_of = {d.document_id: len(list(mp.chunks(d))) for d in documents}
    assert parts_of["DOC-A"] == 2 and parts_of["DOC-7"] == 1  # 12 pages of 20,000 characters: two parts
    assert len(claude.calls) == 4 * sum(parts_of.values()) and whole.not_read == {}  # seven documents, no cap
    assert {r.document_id for r in whole.results} == {d.document_id for d in documents}
    assert any("=== Document D7, part 1: pages 1–3 ===" in c["content"] for c in claude.calls)
    merged = mp.merge_parts([r.reply.output for r in whole.results if r.reply and r.reply.output is not None])
    verified, _ = mp.verify(merged, documents, model="m", request_id="r", now_iso="2026-11-26T00:00:00.000Z")
    by_field = {v.field_id: v.suggestion for v in verified if v.field_id}
    assert by_field["consolidation_approach"]["document_id"] == "DOC-A"
    assert by_field["consolidation_approach"]["source_reference"]["page_number"] == 12  # from the last part
    # D1 part 1 said "Not detected"; D7 states it: the stated answer stands, with its document.
    assert by_field["category:scope1:stationary"]["value"] == "Yes"
    assert by_field["category:scope1:stationary"]["document_id"] == "DOC-7"


class PrefillLedger:
    """The methodology read's ledger: rows written as calls come back; the spend read fresh before each part."""

    def __init__(self, spent: int = 0) -> None:
        self.spent, self.rows, self.reads = spent, [], 0

    def month_spend_microusd(self) -> int:
        self.reads += 1
        return self.spent + sum(int(r["cost"]) for r in self.rows)

    def record(self, reply: Any, document_id: str | None) -> None:
        self.rows.append({"cost": reply.cost_microusd or 0, "document_id": document_id})


def test_the_methodology_read_records_each_call_and_checks_a_fresh_spend_and_estimate_before_each_part(
        monkeypatch: Any) -> None:
    documents = [_report("D1", "DOC-A", 12, {}), _report("D2", "DOC-B", 2, {})]
    claude = Scripted(_prefill_answer)
    monkeypatch.setattr(mp, "estimate_microusd", lambda *a, **k: 10_000)  # 40,000 for a part's four calls
    ledger = PrefillLedger(spent=1_000_000 - 4 * COST - 40_000)  # room for the first part only
    whole = mp.run_chunks(claude, documents, spent_microusd=0, cap_usd=1.0, ledger=ledger)
    assert len(claude.calls) == 4  # the first part's four questions, then the limit
    assert [r["document_id"] for r in ledger.rows] == ["DOC-A"] * 4  # each recorded as it came back
    assert ledger.reads == 2  # this month's spend read again before each part
    assert whole.not_read == {"DOC-A": "pages 8–12", "DOC-B": "pages 1–2"}
    assert {r.document_id for r in whole.results} == {"DOC-A"}
    # Spend from elsewhere (a scan) while the read runs counts at once: with no room left, no part is sent.
    claude = Scripted(_prefill_answer)
    whole = mp.run_chunks(claude, documents, spent_microusd=0, cap_usd=1.0, ledger=PrefillLedger(spent=1_000_000 - 39_999))
    assert claude.calls == [] and set(whole.not_read) == {"DOC-A", "DOC-B"}


def test_parts_that_disagree_keep_the_suggestion_marked_conflicting_with_both_quotes() -> None:
    document = _report("D1", "DOC-A", 40, {4: "Scope 1 stationary combustion is included.",
                                            31: "Scope 1 stationary combustion is not included."})

    def answer(index: int, content: str) -> dict[str, Any]:
        out: dict[str, Any] = {k: [] for k in EMPTY}
        if "L4: Scope 1 stationary combustion is included." in content:
            out["choices"] = [{"field_id": "category:scope1:stationary", "value": "Yes", "document": "D1",
                               "line": "L4", "quote": "stationary combustion is included", "reason": ""}]
        if "L31: Scope 1 stationary combustion is not included." in content:
            out["choices"] = [{"field_id": "category:scope1:stationary", "value": "No", "document": "D1",
                               "line": "L31", "quote": "stationary combustion is not included", "reason": ""}]
        return out

    claude = Scripted(answer)
    whole = mp.run_chunks(claude, [document], spent_microusd=0, cap_usd=100.0)
    merged = mp.merge_parts([r.reply.output for r in whole.results if r.reply and r.reply.output is not None])
    verified, _ = mp.verify(merged, [document], model="m", request_id="r", now_iso="2026-11-26T00:00:00.000Z")
    (kept,) = [v.suggestion for v in verified if v.field_id == "category:scope1:stationary"]
    assert kept["value"] == "Yes" and kept["conflicting"] is True  # kept, never picked silently
    assert kept["conflict_note"] == "Part 1 says Yes (p. 4); part 5 says No (p. 31)"
    (other,) = kept["conflicts"]
    assert (other["value"], other["page"], other["part"]) == ("No", 31, 5)
    assert other["quote"] == "stationary combustion is not included"
    from backend.app.services import methodology_review as rules

    stored = rules.bound_suggestion(rules.catalog_field("category:scope1:stationary") or {}, kept)
    assert stored["conflicting"] is True and stored["conflicts"][0]["page"] == 31
    assert stored["conflict_note"] == kept["conflict_note"] and "_answer" not in kept


def test_the_fingerprint_covers_every_document_and_matches_when_nothing_changed() -> None:
    class Storage:
        def is_owned_by(self, uri: str, owner: str) -> bool:
            return True

    seven = [{"document_id": f"DOC-{i}", "sha256": f"hash-{i}", "org_id": "org"} for i in range(7)]
    first = mp.read_fingerprint(seven, storage=Storage(), provider="anthropic", model="m")
    assert first is not None
    assert mp.read_fingerprint(list(reversed(seven)), storage=Storage(), provider="anthropic", model="m") == first
    changed = [*seven[:6], {**seven[6], "sha256": "hash-new"}]  # the seventh document (past the old cap of five)
    assert mp.read_fingerprint(changed, storage=Storage(), provider="anthropic", model="m") != first
    assert mp.PREFILL_PROMPT_VERSION == "2"


# --- 6. the ledger ---------------------------------------------------------------------------------------------

def test_a_usage_row_carries_the_document_id() -> None:
    reply = StructuredReply(outcome="ok", output=None, model="m", usage=TokenUsage(input_tokens=1, output_tokens=1),
                            cost_microusd=7, request_id="r", stop_reason="end_turn")
    row = ai_usage._row(uuid.uuid4(), None, "extraction", "anthropic", reply, None, "DOC-9")
    assert row["document_id"] == "DOC-9" and row["cost_microusd"] == 7
    assert ai_usage._row(uuid.uuid4(), None, "extraction", "anthropic", reply, None)["document_id"] is None
    assert ":document_id" in str(ai_usage._INSERT)


def test_sheet_rows_are_read_in_parts_of_a_hundred_rows() -> None:
    cells = {("S", n): [f"Row label {n}", f"{n}.5"] for n in range(1, 251)}
    from backend.tests.services.test_ai_extraction import _sheet

    lines = row_lines(_sheet(cells))
    parts = list(dp.iter_parts(lines, max_chars=1_000_000, max_pages=5))
    assert len(parts) == 1  # 250 rows are three "pages" of 100, under five
    parts = list(dp.iter_parts(lines, max_chars=1_000_000, max_pages=1))
    assert [len(p.own_lines) for p in parts] == [100, 100, 50] and parts[0].label() == "lines L1–L100"


def test_the_type_and_facility_reads_check_the_time_budget_before_the_first_part_too() -> None:
    spent = dp.Deadline(stop_starting=60.0, hard_limit=900.0, clock=lambda: 61.0)  # out of time already
    claude = Scripted(_says)
    service = AiRouting(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude, ledger=Ledger())
    found = service.suggest(parsed(_typed_bundle()), org_id=ORG, engagement_id="ENG-1", has_targets=lambda t: True,
                            deadline=spent)
    assert claude.calls == [] and found.status == "off"
    assert found.warning == dp.read_in_part("pages 1–20", dp.TIME_REASON)  # said, never silent
    claude = Scripted(_names)
    facility = AiFacility(settings=settings(ai_part_tokens=10_000), client_factory=lambda s: claude, ledger=Ledger(),
                          facilities_for=lambda org, eng: (FACILITIES, COMPANY), decided_for=lambda org, eng, doc: None)
    warnings: list[str] = []
    assert facility.suggest(parser_output=parsed(_log({})), extraction_result={"items": ITEMS},
                            canonical_type_id=STATIONARY, file_name="generator-log.csv", org_id=ORG,
                            engagement_id=str(uuid.uuid4()), document_id="DOC-1", warnings=warnings,
                            deadline=spent) is None
    assert claude.calls == [] and warnings == [dp.read_in_part("pages 1–20", dp.TIME_REASON)]


def test_the_methodology_read_stops_between_parts_when_told_without_spending() -> None:
    documents = [_report("D1", "DOC-A", 12, {}), _report("D2", "DOC-B", 2, {})]
    claude = Scripted(_prefill_answer)
    asked = {"n": 0}

    def stop() -> str | None:
        asked["n"] += 1
        return "the service restarted" if asked["n"] > 1 else None

    whole = mp.run_chunks(claude, documents, spent_microusd=0, cap_usd=100.0, stop=stop)
    assert len(claude.calls) == 4 and whole.reason == "the service restarted"
    assert whole.not_read == {"DOC-A": "pages 8–12", "DOC-B": "pages 1–2"}
