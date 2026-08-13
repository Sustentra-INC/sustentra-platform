"""Seed-form submission record (intake Stage 1).

One record per submission of the seed form. The org and site records hold the
current facts; this record is the immutable submission itself - who submitted
what, when, against which form version, and which values carry a provisional
vocabulary awaiting expert sign-off.

Phase C's state machine back-fills ``datapoint_states`` from these submissions;
Phase B deliberately does not write datapoint states (founder-approved).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProvisionalValue(BaseModel):
    """A submitted value whose permitted vocabulary is not yet agreed."""

    field_id: str
    datapoint_id: str
    value: str | int | float | bool | None
    requires_signoff: str
    reason: str


class SeedProfileSubmission(BaseModel):
    seed_profile_id: str
    org_id: str
    submitted_by: str
    submitted_at: str
    form_version: str
    profile_schema_version: str
    answers: dict
    site_ids: list[str] = Field(default_factory=list)
    datapoint_ids: list[str] = Field(
        default_factory=list,
        description="Seed-form datapoints (SEED-1.x) covered by this submission.",
    )
    provisional_values: list[ProvisionalValue] = Field(default_factory=list)
