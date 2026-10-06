import copy
import json

import pytest

from backend.app.repositories.evidence_repository import InMemoryApprovedEvidenceRepository
from backend.app.repositories.pipeline_repository import InMemoryPipelineRunRepository
from backend.app.repositories.review_repository import InMemoryReviewDecisionRepository
from backend.app.services.approved_evidence_service import ApprovedEvidenceService
from backend.app.services.pipeline_orchestration_service import PipelineOrchestrationService
from backend.app.services.review_decision_service import ReviewDecisionService


class FakeClassificationService:
    def __init__(self, result: dict) -> None:
        self._result = result

    def classify(self, payload: dict) -> dict:
        return copy.deepcopy(self._result)


class FakeParserService:
    def __init__(self, output: dict) -> None:
        self._output = output

    def parse_document(self, file_path: str, document_id: str, processing_run_id: str, mime_type=None) -> dict:
        return copy.deepcopy(self._output)


class FakeTargetService:
    def __init__(self, targets: list[dict]) -> None:
        self._targets = targets

    def get_targets_for_canonical_type(self, canonical_type_id: str, include_optional=True, include_deprecated=False):
        return copy.deepcopy(self._targets)

    def get_targets_for_classification_result(self, classification_result: dict, include_optional=True, include_deprecated=False):
        return copy.deepcopy(self._targets)


class FakeExtractionService:
    def __init__(self, result: dict) -> None:
        self._result = result

    def extract(self, payload: dict) -> dict:
        return copy.deepcopy(self._result)



def _review_decision(evidence_id: str = "EV-1", document_id: str = "DOC-1") -> dict:
    return {
        "review_decision_id": "review-001",
        "candidate_id": f"candidate::{evidence_id}::{document_id}::activity_quantity",
        "evidence_id": evidence_id,
        "document_id": document_id,
        "field_name": "activity_quantity",
        "decision": "accepted",
        "reviewed_value": 28100,
        "reviewed_unit": "MMBtu",
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-01-01T00:00:00+00:00",
        "reviewer_note": None,
        "candidate_snapshot": {
            "candidate_id": f"candidate::{evidence_id}::{document_id}::activity_quantity",
            "display_label": "Activity Quantity",
            "raw_value": "28,100 MMBtu",
            "confidence": 0.9,
            "validation_flags": [],
        },
        "source_reference": {
            "document_id": document_id,
            "text_snippet": "Total Usage 28,100 MMBtu",
        },
    }



def _build_service(
    *,
    parser_service=None,
    classification_service=None,
    target_service=None,
    extraction_service=None,
    pipeline_repository=None,
    review_service=None,
    approved_evidence_service=None,
):
    counter = {"n": 0}

    def id_factory(prefix: str, seed: str) -> str:
        counter["n"] += 1
        return f"{prefix}::{seed}::{counter['n']:02d}"

    return PipelineOrchestrationService(
        parser_service=parser_service,
        classification_service=classification_service,
        target_service=target_service,
        extraction_service=extraction_service,
        pipeline_repository=pipeline_repository or InMemoryPipelineRunRepository(),
        review_service=review_service,
        approved_evidence_service=approved_evidence_service,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=id_factory,
    )



def _write_temp_text_file(tmp_path) -> str:
    text = "\n".join(
        [
            "Facility Name: Demo Plant",
            "Fuel Type: Natural Gas",
            "Total Usage: 28,100 MMBtu",
            "Service Period: 10/01/2023 - 10/31/2023",
            "Supplier: Demo Utility",
            "Account Number: 123456",
        ]
    )
    path = tmp_path / "sample.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)



def test_process_local_document_with_override_generates_targets_and_candidates(tmp_path):
    service = _build_service(pipeline_repository=InMemoryPipelineRunRepository())
    local_file = _write_temp_text_file(tmp_path)

    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=True,
    )

    assert "pipeline_run" in result
    assert "parser_output" in result
    assert "classification_result" in result
    assert "extraction_targets" in result
    assert "extraction_result" in result

    run = result["pipeline_run"]
    assert run["status"] == "completed"
    assert run["canonical_type_id"] == "CT-S1-FUELQTY"
    assert run["canonical_type_source"] == "override"
    assert run["stage_statuses"]["candidate_generation"] == "completed"
    assert run["target_count"] == len(result["extraction_targets"])
    assert run["candidate_count"] == result["extraction_result"]["candidate_count"]



def test_pipeline_run_is_persisted_when_persist_true(tmp_path):
    repository = InMemoryPipelineRunRepository()
    service = _build_service(pipeline_repository=repository)
    local_file = _write_temp_text_file(tmp_path)

    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=True,
    )

    stored = repository.get_by_id(result["pipeline_run"]["pipeline_run_id"])
    assert stored is not None



def test_pipeline_run_is_not_persisted_when_persist_false(tmp_path):
    repository = InMemoryPipelineRunRepository()
    service = _build_service(pipeline_repository=repository)
    local_file = _write_temp_text_file(tmp_path)

    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=False,
    )

    stored = repository.get_by_id(result["pipeline_run"]["pipeline_run_id"])
    assert stored is None



def test_candidate_metrics_are_computed(tmp_path):
    service = _build_service()
    local_file = _write_temp_text_file(tmp_path)

    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=False,
    )

    run = result["pipeline_run"]
    assert run["candidate_count"] >= 0
    assert run["found_candidate_count"] >= 0
    assert run["missing_candidate_count"] >= 0
    assert run["low_confidence_candidate_count"] >= 0
    assert run["found_candidate_count"] + run["missing_candidate_count"] == run["candidate_count"]



def test_missing_local_file_path_raises_value_error():
    service = _build_service()
    with pytest.raises(ValueError):
        service.process_local_document(
            local_file_path="does-not-exist.txt",
            engagement_id="ENG-1",
            persist_run=False,
        )



def test_no_canonical_type_and_no_override_returns_partial(tmp_path):
    parser_output = {
        "document_id": "DOC-1",
        "processing_run_id": "PROC-1",
        "status": "parsed",
        "pages": [],
        "tables": [],
        "key_value_pairs": [],
        "text_blocks": [],
        "source_references": [],
        "warnings": [],
    }
    service = _build_service(
        parser_service=FakeParserService(parser_output),
        classification_service=FakeClassificationService(
            {
                "status": "unclassified",
                "primary_canonical_type_id": None,
                "candidate_matches": [],
            }
        ),
        target_service=FakeTargetService([]),
        extraction_service=FakeExtractionService(
            {
                "evidence_id": "EV-1",
                "document_id": "DOC-1",
                "candidate_count": 0,
                "items": [],
            }
        ),
    )

    local_file = _write_temp_text_file(tmp_path)
    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        persist_run=False,
    )

    run = result["pipeline_run"]
    assert run["status"] == "partial"
    assert run["canonical_type_id"] is None
    assert run["stage_statuses"]["target_plan"] == "skipped"
    assert run["stage_statuses"]["candidate_generation"] == "skipped"



def test_parser_failed_status_returns_failed_pipeline_run(tmp_path):
    parser_output = {
        "document_id": "DOC-1",
        "processing_run_id": "PROC-1",
        "status": "failed",
        "pages": [],
        "tables": [],
        "key_value_pairs": [],
        "text_blocks": [],
        "source_references": [],
        "warnings": [],
    }
    service = _build_service(
        parser_service=FakeParserService(parser_output),
        classification_service=FakeClassificationService(
            {
                "status": "unclassified",
                "primary_canonical_type_id": None,
                "candidate_matches": [],
            }
        ),
    )

    local_file = _write_temp_text_file(tmp_path)
    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        persist_run=False,
    )

    assert result["pipeline_run"]["status"] == "failed"



def test_get_pipeline_run_and_latest_by_evidence(tmp_path):
    repository = InMemoryPipelineRunRepository()
    service = _build_service(pipeline_repository=repository)
    local_file = _write_temp_text_file(tmp_path)

    result = service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        evidence_id="EV-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=True,
    )

    run_id = result["pipeline_run"]["pipeline_run_id"]
    assert service.get_pipeline_run(run_id) is not None
    latest = service.get_latest_run_by_evidence("EV-1")
    assert latest is not None
    assert latest["pipeline_run_id"] == run_id



def test_get_evidence_status_returns_pipeline_review_and_approved_summary(tmp_path):
    pipeline_repository = InMemoryPipelineRunRepository()
    review_repo = InMemoryReviewDecisionRepository()
    approved_repo = InMemoryApprovedEvidenceRepository()

    review_service = ReviewDecisionService(
        repository=review_repo,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda candidate: "review-fixed",
    )
    approved_service = ApprovedEvidenceService(
        review_repository=review_repo,
        approved_repository=approved_repo,
        clock=lambda: "2026-01-01T00:00:00+00:00",
        id_factory=lambda engagement_id, evidence_id: f"approved::{engagement_id}::{evidence_id}::01",
    )

    service = _build_service(
        pipeline_repository=pipeline_repository,
        review_service=review_service,
        approved_evidence_service=approved_service,
    )
    local_file = _write_temp_text_file(tmp_path)

    service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        evidence_id="EV-1",
        document_id="DOC-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=True,
    )

    review_repo.save(_review_decision(evidence_id="EV-1", document_id="DOC-1"))
    approved_service.project_by_evidence(
        evidence_id="EV-1",
        engagement_id="ENG-1",
        evidence_type="CT-S1-FUELQTY",
    )

    status = service.get_evidence_status("EV-1")
    assert status["evidence_id"] == "EV-1"
    assert status["latest_pipeline_run"] is not None
    assert status["review_decision_count"] == 1
    assert status["latest_approved_evidence"] is not None
    assert status["approved_field_count"] == 1



def test_pipeline_run_summary_does_not_persist_input_document_text(tmp_path):
    service = _build_service()
    local_file = tmp_path / "sensitive.txt"
    secret_text = "Private line should not be in pipeline summary"
    local_file.write_text(secret_text, encoding="utf-8")

    result = service.process_local_document(
        local_file_path=str(local_file),
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=False,
    )

    serialized = json.dumps(result["pipeline_run"])
    assert secret_text not in serialized
    assert "pages" not in result["pipeline_run"]
    assert "text_blocks" not in result["pipeline_run"]



def test_service_does_not_mutate_stage_object_outputs(tmp_path):
    parser_output = {
        "document_id": "DOC-1",
        "processing_run_id": "PROC-1",
        "status": "parsed",
        "pages": [{"page_number": 1, "text": "hello"}],
        "tables": [],
        "key_value_pairs": [],
        "text_blocks": [],
        "source_references": [],
        "warnings": [],
    }
    classification = {
        "status": "classified",
        "primary_canonical_type_id": "CT-S1-FUELQTY",
        "candidate_matches": [],
    }
    targets = [
        {
            "target_id": "target::CT-S1-FUELQTY::activity_quantity",
            "field_id": "activity_quantity",
            "field_label": "Activity Quantity",
        }
    ]
    extraction_result = {
        "evidence_id": "EV-1",
        "document_id": "DOC-1",
        "candidate_count": 1,
        "items": [
            {
                "candidate_id": "candidate::EV-1::DOC-1::activity_quantity",
                "evidence_id": "EV-1",
                "document_id": "DOC-1",
                "field_name": "activity_quantity",
                "display_label": "Activity Quantity",
                "raw_value": "28,100 MMBtu",
                "normalized_value": 28100,
                "unit": "MMBtu",
                "confidence": 0.9,
                "source_reference": {"document_id": "DOC-1"},
                "validation_flags": [],
            }
        ],
    }

    parser_snapshot = copy.deepcopy(parser_output)
    target_snapshot = copy.deepcopy(targets)
    extraction_snapshot = copy.deepcopy(extraction_result)

    service = _build_service(
        parser_service=FakeParserService(parser_output),
        classification_service=FakeClassificationService(classification),
        target_service=FakeTargetService(targets),
        extraction_service=FakeExtractionService(extraction_result),
    )

    local_file = _write_temp_text_file(tmp_path)
    service.process_local_document(
        local_file_path=local_file,
        engagement_id="ENG-1",
        canonical_type_id_override="CT-S1-FUELQTY",
        persist_run=False,
    )

    assert parser_output == parser_snapshot
    assert targets == target_snapshot
    assert extraction_result == extraction_snapshot


# --- EXT-001: halt reasons and the stationary-combustion content check -------------------
def _parser_output(text: str, status: str = "parsed") -> dict:
    return {
        "parser_output_id": "PO-1",
        "document_id": "DOC-1",
        "processing_run_id": "RUN-1",
        "parser_name": "text",
        "parser_version": "v0",
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"page_number": 1, "text": text}] if text else [],
        "text_blocks": [{"block_id": "b1", "page_number": 1, "text": text, "confidence": None,
                         "bounding_box": None, "source_reference_id": None}] if text else [],
        "tables": [],
        "key_value_pairs": [],
        "source_references": [],
        "warnings": [] if text else [{"code": "empty_page_text", "message": "Page 1 had no extractable text.",
                                      "severity": "warning"}],
        "raw_artifact_uri": None,
    }


def _low_confidence(matches: list[tuple[str, float]]) -> dict:
    return {
        "status": "low_confidence",
        "primary_canonical_type_id": matches[0][0],
        "primary_variant_id": "VR-1",
        "confidence": matches[0][1],
        "threshold": 0.8,
        "candidate_matches": [
            {"canonical_type_id": ct, "variant_id": f"VR-{i}", "confidence": c, "threshold": 0.8}
            for i, (ct, c) in enumerate(matches)
        ],
    }


GAS_BILL_TEXT = "Lakeside Gas Co.\nFuel Type: Natural Gas\nTotal Usage: 1,240 therms\nService Period: 01/01/2024 - 01/31/2024\n"


def test_empty_parser_output_halts_as_unreadable(tmp_path):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(parser_service=FakeParserService(_parser_output("", status="empty")))
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["status"] == "partial"
    assert run["halt_reason"]["code"] == "unreadable_document"
    assert "Page 1 had no extractable text" in run["halt_reason"]["message"]
    assert run["stage_statuses"]["classify"] == "skipped"


def test_parser_failure_halts_as_unreadable(tmp_path):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(parser_service=FakeParserService(_parser_output("", status="failed")))
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["status"] == "failed"
    assert run["halt_reason"]["code"] == "unreadable_document"


def test_unrecognized_document_halts_as_unsupported_with_best_match(tmp_path):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output("Lease agreement between landlord and tenant")),
        classification_service=FakeClassificationService(_low_confidence([("CT-LEASE", 0.31)])),
    )
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["halt_reason"]["code"] == "unsupported_document"
    assert "CT-LEASE" in run["halt_reason"]["message"] and "0.31" in run["halt_reason"]["message"]


def test_low_confidence_fuel_bill_is_accepted_by_content_check(tmp_path):
    from backend.app.services.extraction_target_service import ExtractionTargetService

    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output(GAS_BILL_TEXT)),
        classification_service=FakeClassificationService(
            _low_confidence([("CT-S2-ELEC", 0.77), ("CT-S1-FUELQTY", 0.77), ("CT-S1-MOBFUEL", 0.4)])),
        target_service=ExtractionTargetService(),
    )
    output = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)
    run = output["pipeline_run"]
    assert run["canonical_type_id"] == "CT-S1-FUELQTY"
    assert run["canonical_type_source"] == "content_check"
    assert run["halt_reason"] is None
    quantity = next(c for c in output["extraction_result"]["items"] if c["field_name"] == "activity_quantity")
    assert quantity["normalized_value"] == 124 and quantity["unit"] == "MMBtu"


@pytest.mark.parametrize(
    "matches",
    [
        [("CT-S1-MOBFUEL", 0.62), ("CT-S1-FUELQTY", 0.5)],  # mobile leads but a therm bill has no vehicle cue
        [("CT-S1-FUELQTY", 0.35)],  # below the content-check floor
        [("CT-S1-MOBFUEL", 0.77), ("CT-S1-FUELQTY", 0.7)],  # mobile leads
    ],
)
def test_content_check_does_not_override_ambiguous_or_weak_matches(tmp_path, matches):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output(GAS_BILL_TEXT)),
        classification_service=FakeClassificationService(_low_confidence(matches)),
    )
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["canonical_type_id"] is None
    assert run["halt_reason"]["code"] == "unsupported_document"


def test_content_check_needs_fuel_content(tmp_path):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output("City Water\nTotal Usage: 118 CCF\n")),
        classification_service=FakeClassificationService(_low_confidence([("CT-S1-FUELQTY", 0.77)])),
    )
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["canonical_type_id"] is None


def test_extraction_halt_is_recorded(tmp_path):
    path = _write_temp_text_file(tmp_path)
    halted = {"evidence_id": "EV", "document_id": "DOC-1", "candidate_count": 0, "items": [],
              "halt_reason": {"code": "unsupported_document", "message": "No combusted fuel."}}
    service = _build_service(
        parser_service=FakeParserService(_parser_output("Water bill")),
        target_service=FakeTargetService([{"field_id": "activity_quantity"}]),
        extraction_service=FakeExtractionService(halted),
    )
    run = service.process_local_document(
        local_file_path=path, engagement_id="ENG-1", canonical_type_id_override="CT-S1-FUELQTY", persist_run=False,
    )["pipeline_run"]
    assert run["status"] == "partial"
    assert run["stage_statuses"]["candidate_generation"] == "skipped"
    assert run["halt_reason"] == {"code": "unsupported_document", "message": "No combusted fuel."}


def test_content_check_does_not_override_a_leading_non_fuel_type(tmp_path):
    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output(GAS_BILL_TEXT)),
        classification_service=FakeClassificationService(
            _low_confidence([("CT-S2-ELEC", 0.77), ("CT-S1-FUELQTY", 0.65)])),
    )
    run = service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)["pipeline_run"]
    assert run["canonical_type_id"] is None
    assert run["halt_reason"]["code"] == "unsupported_document"


# --- EXT-002: stationary vs mobile ------------------------------------------------------------
NO_CUE_DIESEL = "Valley Fuels\nProduct: Diesel\nQuantity: 300 gal\nDate: 04/01/2024\n"
FLEET_DIESEL = "Valley Fuels fleet card\nVehicle: T-9\nProduct: Diesel\nQuantity: 300 gal\nDate: 04/01/2024\n"
GENERATOR_DIESEL = "Valley Fuels\nDelivered to standby generator day tank\nProduct: Diesel\nQuantity: 300 gal\nDate: 04/01/2024\n"


def _run_with(tmp_path, text, classification):
    from backend.app.services.extraction_target_service import ExtractionTargetService

    path = _write_temp_text_file(tmp_path)
    service = _build_service(
        parser_service=FakeParserService(_parser_output(text)),
        classification_service=FakeClassificationService(classification),
        target_service=ExtractionTargetService(),
    )
    return service.process_local_document(local_file_path=path, engagement_id="ENG-1", persist_run=False)


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        (FLEET_DIESEL, "CT-S1-MOBFUEL"),        # vehicle/fleet cues break the tie
        (GENERATOR_DIESEL, "CT-S1-FUELQTY"),    # generator/day-tank cues break the tie
        (NO_CUE_DIESEL, None),                  # no cues: a reviewer decides
    ],
)
def test_stationary_mobile_tie_is_broken_only_by_explicit_cues(tmp_path, text, expected_type):
    output = _run_with(tmp_path, text, _low_confidence([("CT-S1-FUELQTY", 0.5), ("CT-S1-MOBFUEL", 0.5)]))
    run = output["pipeline_run"]
    assert run["canonical_type_id"] == expected_type
    if expected_type is None:
        assert "nothing says whether it was burned in vehicles or on site" in run["halt_reason"]["message"]
    else:
        assert run["canonical_type_source"] == "content_check"


def test_mobfuel_content_check_extracts_transactions(tmp_path):
    output = _run_with(tmp_path, FLEET_DIESEL, _low_confidence([("CT-S1-MOBFUEL", 0.5)]))
    fields = {c["field_name"]: c for c in output["extraction_result"]["items"]}
    assert output["pipeline_run"]["canonical_type_id"] == "CT-S1-MOBFUEL"
    assert fields["activity_quantity"]["normalized_value"] == 300
    assert fields["vehicle_or_equipment_id"]["normalized_value"] == "T-9"


def test_confident_classification_contradicted_by_content_halts(tmp_path):
    classified = {"status": "classified", "primary_canonical_type_id": "CT-S1-FUELQTY", "primary_variant_id": "VR-1",
                  "confidence": 0.85, "threshold": 0.8,
                  "candidate_matches": [{"canonical_type_id": "CT-S1-FUELQTY", "variant_id": "VR-1",
                                         "confidence": 0.85, "threshold": 0.8}]}
    run = _run_with(tmp_path, FLEET_DIESEL, classified)["pipeline_run"]
    assert run["canonical_type_id"] is None
    assert run["halt_reason"]["code"] == "unsupported_document"
    assert "reads as mobile" in run["halt_reason"]["message"] and "vehicle" in run["halt_reason"]["message"]


def test_confident_classification_with_both_cues_is_kept(tmp_path):
    classified = {"status": "classified", "primary_canonical_type_id": "CT-S1-MOBFUEL", "primary_variant_id": "VR-1",
                  "confidence": 0.85, "threshold": 0.8, "candidate_matches": []}
    text = FLEET_DIESEL + "Also delivered to the standby generator\n"
    run = _run_with(tmp_path, text, classified)["pipeline_run"]
    assert run["canonical_type_id"] == "CT-S1-MOBFUEL" and run["halt_reason"] is None
