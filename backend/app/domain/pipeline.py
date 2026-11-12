from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PipelineStatus = Literal["completed", "partial", "failed"]
PipelineStageStatus = Literal[
    "not_started",
    "completed",
    "skipped",
    "partial",
    "failed",
]
CanonicalTypeSource = Literal["classifier", "content_check", "override", "ai", "none"]


class PipelineStageStatuses(BaseModel):
    parse: PipelineStageStatus = "not_started"
    classify: PipelineStageStatus = "not_started"
    target_plan: PipelineStageStatus = "not_started"
    candidate_generation: PipelineStageStatus = "not_started"


class HaltReason(BaseModel):
    """Why the pipeline stopped before producing reviewable candidates."""

    code: str  # unreadable_document | ocr_required | password_protected | unsupported_document
    message: str


class AiRoutingRecord(BaseModel):
    """What Claude said about the document's type. ``used``: it set the type (source "ai"),
    otherwise it only disagreed with the rules (shadow mode) and changed nothing."""

    canonical_type_id: str
    quote: str
    line: str
    reason_code: str
    page_number: int | None = None
    used: bool
    disagrees: bool = False
    review_required: bool = True


class PipelineRun(BaseModel):
    pipeline_run_id: str
    engagement_id: str
    evidence_id: str
    document_id: str
    processing_run_id: str
    status: PipelineStatus
    stage_statuses: PipelineStageStatuses
    input_file_name: str | None = None
    canonical_type_id: str | None = None
    canonical_type_source: CanonicalTypeSource = "none"
    classification_status: str | None = None
    parser_status: str | None = None
    target_count: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    found_candidate_count: int = Field(default=0, ge=0)
    missing_candidate_count: int = Field(default=0, ge=0)
    low_confidence_candidate_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    halt_reason: HaltReason | None = None
    # Claude's suggested type, with its quote (services/ai_routing.py). Absent unless Claude was asked.
    ai_routing: AiRoutingRecord | None = None
    # Owning organization (SEC-001). None = recorded before org scoping; only a
    # provider_admin can see such records until they are claimed (cli claim-s1-data).
    org_id: str | None = None
    created_at: str
    completed_at: str | None = None
    artifacts: dict[str, str | None] = Field(default_factory=dict)
