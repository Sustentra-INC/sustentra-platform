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
CanonicalTypeSource = Literal["classifier", "override", "none"]


class PipelineStageStatuses(BaseModel):
    parse: PipelineStageStatus = "not_started"
    classify: PipelineStageStatus = "not_started"
    target_plan: PipelineStageStatus = "not_started"
    candidate_generation: PipelineStageStatus = "not_started"


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
    created_at: str
    completed_at: str | None = None
    artifacts: dict[str, str | None] = Field(default_factory=dict)
