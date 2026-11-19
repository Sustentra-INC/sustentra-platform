"""A note from a person is not a bill, and a company's own summary is not a fuel record.

Synthetic text in the shape of the staging set's client note and company inventory workbook. The
note quotes every month's therms in sentences; those are what someone says, not evidence."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.services.document_shape import NOT_EVIDENCE_MESSAGE, looks_like_a_note
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.tests.services.test_ai_routing import FakeClaude, said, router
from backend.tests.services.test_pipeline_orchestration_service import (
    FakeClassificationService,
    FakeExtractionService,
    FakeParserService,
    FakeTargetService,
    _write_temp_text_file,
)

NOTE = """To: GHG assurance team
From: Dana Whitfield-Moreno, Facilities Manager
Date: 01/14/2026
Re: Harbor Warehouse natural gas, 2025

Hi all,

You asked for the Harbor Warehouse gas numbers for last year. I don't have every bill handy, so here is what I pulled from the online account.
January was our heaviest month at 4,480 therms. In February we used 4,120 therms (I sent you a photo of that bill).
In March we used about 3,900 therms; the portal shows 3,905. April dropped to 3,010 therms once the dock heaters were switched off.
Every month is a calendar month. The meter is CG-6620193. Let me know if you need the actual bills.

Thanks,
Dana
"""


def parser_output(text: str, **extra: Any) -> dict[str, Any]:
    return {"document_id": "DOC-1", "status": "parsed", "pages": [{"page_number": 1, "text": text}],
            "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                             "bounding_box": None, "source_reference_id": None}],
            "tables": [], "key_value_pairs": [], "source_references": [], "warnings": [], **extra}


# --- the shape test ----------------------------------------------------------------------------
def test_a_client_note_that_quotes_every_months_therms_in_sentences_is_a_note() -> None:
    assert looks_like_a_note(parser_output(NOTE)) is True


def test_a_note_that_quotes_one_quantity_in_a_sentence_is_a_note() -> None:
    text = ("Hello,\n\nThank you for the reminder about the audit.\n"
            "Last winter the boiler at the warehouse burned roughly 1,200 therms in the coldest month, I think.\n"
            "I will send the bills as soon as I find them, probably early next week, if the office is open.\n"
            "Best regards,\nPat\n")
    assert looks_like_a_note(parser_output(text)) is True


@pytest.mark.parametrize("text", [
    # a German note and a Japanese note, with non-ASCII names and units
    "Hallo zusammen,\n\nanbei die Zahlen für das Lager Müller Käserei – Zürich, soweit ich sie gefunden habe.\n"
    "Im Januar haben wir 4.480 therms verbraucht, im Februar waren es 4.120 therms, im März etwa 3.900 therms.\n"
    "Die Zähler stehen im Keller, und ich kann Ihnen gerne Fotos davon schicken, wenn Sie möchten.\n"
    "Danke und viele Grüße,\nJürgen\n",
    "お世話になっております。\n\n東京工場の天然ガスの使用量をお知らせします、手元にある分だけですが。\n"
    "1月は4,480サーム、2月は4,120サームを使用しました、請求書は後ほどお送りします。\n"
    "メーターは地下にありますので、写真が必要でしたらお知らせください、よろしくお願いいたします。\n"
    "Thanks,\n田中\n",
])
def test_a_note_in_another_language_is_a_note(text: str) -> None:
    assert looks_like_a_note(parser_output(text)) is True


BILL = """Cedarline Gas & Power
Account Number: 3305-778-1102
Meter Number: CG-6620193
Service Period: 10/01/2025 - 10/31/2025
Fuel: Natural gas
Usage: 1,486 therms
Amount Due: $1,474.33
"""


def test_a_bill_with_labelled_rows_is_not_a_note() -> None:
    assert looks_like_a_note(parser_output(BILL)) is False


def test_a_bill_with_a_friendly_paragraph_but_labelled_rows_is_not_a_note() -> None:
    text = ("Hello, Staging-Test Foods Inc.\nThank you for being a customer, and we hope the winter is kind to you this year.\n"
            "Your usage was lower than last month, which is good news for the budget, and we are pleased to report it.\n"
            + BILL + "Thanks,\nCedarline\n")
    assert looks_like_a_note(parser_output(text)) is False


def test_a_note_with_a_table_a_sheet_or_a_laid_out_page_is_not_a_note() -> None:
    assert looks_like_a_note(parser_output(NOTE, tables=[{"rows": [["a", "b"]]}])) is False
    assert looks_like_a_note(parser_output(NOTE, key_value_pairs=[{"key": "k", "value": "v"}])) is False
    assert looks_like_a_note(parser_output(NOTE, source_references=[{"sheet_name": "Log", "cell_or_range": "A1"}])) is False
    laid_out = parser_output(NOTE)
    laid_out["text_blocks"][0]["bounding_box"] = {"left": 0.1, "top": 0.1, "width": 0.5, "height": 0.1}
    assert looks_like_a_note(laid_out) is False


def test_prose_without_a_greeting_or_memo_header_and_tiny_text_are_not_notes() -> None:
    prose = "\n".join(["The boiler burned about 1,200 therms in January, and the dock heaters ran all month long."] * 4)
    assert looks_like_a_note(parser_output(prose)) is False
    assert looks_like_a_note(parser_output("Hi,\nThanks,\nPat")) is False
    assert looks_like_a_note(parser_output("")) is False


# --- the pipeline ------------------------------------------------------------------------------
TARGETS = [{"field_id": "activity_quantity", "display_label": "Activity Quantity"}]


def service(text: str, classified: dict[str, Any], *, ai: Any = None, targets: Any = None) -> PipelineOrchestrationService:
    return PipelineOrchestrationService(
        parser_service=FakeParserService(parser_output(text)),
        classification_service=FakeClassificationService(classified),
        target_service=targets or FakeTargetService(TARGETS),
        extraction_service=FakeExtractionService({"evidence_id": "EV-1", "document_id": "DOC-1", "candidate_count": 0, "items": []}),
        pipeline_repository=InMemoryPipelineRunRepository(), clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda prefix, seed: f"{prefix}::{seed}", ai_routing=ai)


def read(svc: PipelineOrchestrationService, tmp_path: Any) -> dict[str, Any]:
    out: dict[str, Any] = svc.process_local_document(
        local_file_path=_write_temp_text_file(tmp_path), engagement_id="ENG-1",
        org_id="aaaaaaaa-0000-0000-0000-0000000000c3", persist_run=False)
    return out


def assert_stopped_as_a_note(result: dict[str, Any]) -> None:
    run = result["pipeline_run"]
    assert run["canonical_type_id"] is None and run["canonical_type_source"] == "none"
    assert run["halt_reason"] == {"code": "unsupported_document", "message": NOT_EVIDENCE_MESSAGE}
    assert run.get("ai_routing") is None and result["extraction_targets"] == []
    assert (result["extraction_result"] or {}).get("items", []) == []
    assert not any("closest match" in w for w in run["warnings"])  # no stale, contradicting reason


@pytest.mark.parametrize("canonical", ["CT-S1-FUELQTY", "CT-S1-MOBFUEL", "CT-S2-ELEC", "CT-S1-REFRSVC", "CT-S2-THERMAL"])
def test_a_note_the_rules_classified_as_a_quantity_type_stops_with_a_plain_reason(tmp_path: Any, canonical: str) -> None:
    classified = {"status": "classified", "primary_canonical_type_id": canonical, "candidate_matches": [],
                  "confidence": 0.9, "threshold": 0.5}
    assert_stopped_as_a_note(read(service(NOTE, classified), tmp_path))


def test_a_note_claude_suggests_as_fuel_stops_too(tmp_path: Any) -> None:
    routing, _ = router(FakeClaude(said("CT-S1-FUELQTY", "January was our heaviest month at 4,480 therms.", line="L9")))
    classified = {"status": "low_confidence", "primary_canonical_type_id": "CT-S1-REFRSVC", "candidate_matches": [],
                  "confidence": 0.4, "threshold": 0.55}
    result = read(service(NOTE, classified, ai=routing), tmp_path)
    assert_stopped_as_a_note(result)
    assert result["pipeline_run"]["status"] == "partial"


def test_a_note_nothing_classified_stops_with_the_note_reason_not_a_closest_match(tmp_path: Any) -> None:
    classified = {"status": "low_confidence", "primary_canonical_type_id": "CT-S1-REFRSVC",
                  "candidate_matches": [{"canonical_type_id": "CT-S1-REFRSVC", "confidence": 0.4}],
                  "confidence": 0.4, "threshold": 0.55}
    assert_stopped_as_a_note(read(service(NOTE, classified), tmp_path))


def test_the_same_figures_in_a_bill_are_still_read_as_fuel(tmp_path: Any) -> None:
    classified = {"status": "classified", "primary_canonical_type_id": "CT-S1-FUELQTY", "candidate_matches": [],
                  "confidence": 0.9, "threshold": 0.5}
    svc = PipelineOrchestrationService(
        parser_service=FakeParserService(parser_output(BILL)), classification_service=FakeClassificationService(classified),
        target_service=FakeTargetService(TARGETS),
        extraction_service=FakeExtractionService({"evidence_id": "EV-1", "document_id": "DOC-1", "candidate_count": 0, "items": []}),
        pipeline_repository=InMemoryPipelineRunRepository(), clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda prefix, seed: f"{prefix}::{seed}")
    run = read(svc, tmp_path)["pipeline_run"]
    assert run["canonical_type_id"] == "CT-S1-FUELQTY" and run["halt_reason"] is None


class RecordingTargets(FakeTargetService):
    def __init__(self) -> None:
        super().__init__(TARGETS)
        self.calls: list[tuple[str, str]] = []

    def get_targets_for_canonical_type(self, canonical_type_id: str, include_optional: bool = True,
                                       include_deprecated: bool = False) -> list[dict]:
        self.calls.append(("type", canonical_type_id))
        return [] if canonical_type_id == "CT-GHG-WORKBOOK" else copy.deepcopy(TARGETS)

    def get_targets_for_classification_result(self, classification_result: dict, include_optional: bool = True,
                                              include_deprecated: bool = False) -> list[dict]:
        self.calls.append(("result", str(classification_result.get("primary_canonical_type_id"))))
        return copy.deepcopy(TARGETS)


@pytest.mark.parametrize("runner_up", ["CT-S1-MOBFUEL", "CT-S1-FUELQTY"])
def test_a_summary_workbook_is_read_as_itself_and_never_with_a_runner_up_types_fuel_fields(tmp_path: Any, runner_up: str) -> None:
    classified = {"status": "multi_type_candidate", "primary_canonical_type_id": "CT-GHG-WORKBOOK",
                  "candidate_matches": [{"canonical_type_id": "CT-GHG-WORKBOOK", "confidence": 0.75},
                                        {"canonical_type_id": runner_up, "confidence": 0.7}],
                  "confidence": 0.75, "threshold": 0.5}
    targets = RecordingTargets()
    text = "Company GHG inventory 2025\nScope\tSource\ttCO2e\nScope 1\tStationary combustion\t874.6\n"
    run = read(service(text, classified, targets=targets), tmp_path)["pipeline_run"]
    assert run["canonical_type_id"] == "CT-GHG-WORKBOOK" and run["target_count"] == 0
    assert ("type", "CT-GHG-WORKBOOK") in targets.calls
    assert not any(kind == "result" for kind, _ in targets.calls)  # no merged multi-type targets
    assert not any(kind == "type" and type_id == runner_up for kind, type_id in targets.calls)


def test_other_multi_type_documents_still_merge_their_candidates_targets(tmp_path: Any) -> None:
    classified = {"status": "multi_type_candidate", "primary_canonical_type_id": "CT-OTHER",
                  "candidate_matches": [{"canonical_type_id": "CT-OTHER", "confidence": 0.75},
                                        {"canonical_type_id": "CT-ANOTHER", "confidence": 0.7}],
                  "confidence": 0.75, "threshold": 0.5}
    targets = RecordingTargets()
    read(service("Some document\nwith lines\n", classified, targets=targets), tmp_path)
    assert ("result", "CT-OTHER") in targets.calls
