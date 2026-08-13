"""Datapoint state: the DB-owned status of one question for one client.

One row per (org, datapoint, scope). ``scope_ref`` names the instance the state
belongs to - a site id for site-grain questions, a vehicle-group id for
vehicle-grain questions, and None for org-grain questions. A client with three
sites therefore has three copies of every site-grain question, which is what
intake/SPEC.md section 3 means by "each site instantiates its own copy of the
applicable screening tree".

Status vocabulary and the transition rules come from SPEC section 4. Two of them
matter more than the rest:

* ``not_present`` is a completeness record - "we screened for this and it isn't
  here" - and is NOT an exclusion. Genuine exclusions use the EXC-010 pattern and
  require a sustentra_reviewer.
* ``escalated`` blocks only the things that depend on this answer. It never
  blocks the interview.

Only :mod:`intake.backend.services.state_machine` may change ``status``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DatapointStatus = Literal[
    "unasked",
    "asked",
    "answered",
    "unknown",
    "not_present",
    "pending_documents",
    "escalated",
    "resolved",
]

# Mirrors the grain enum in intake/contracts/profile_schema.schema.json.
Grain = Literal[
    "org",
    "site",
    "entity",
    "vehicle_group",
    "meter",
    "source_category",
    "category",
    "datapoint",
]

AnsweredBy = Literal["user", "document", "team", "system"]

# ISO 14064-1 section 8.3: metered / invoiced / estimated feeds the category-level
# uncertainty roll-up (PRV-8.1 / PRV-8.2).
ValueBasis = Literal["metered", "invoiced", "estimated", "asserted", "derived"]


class Provenance(BaseModel):
    """Where an answer came from. Feeds the uncertainty roll-up in PRV-8.2."""

    answered_by: AnsweredBy
    actor_id: str | None = None
    value_basis: ValueBasis | None = None
    source_document_id: str | None = None
    period_covered_start: str | None = None
    period_covered_end: str | None = None
    note: str | None = None


class DatapointState(BaseModel):
    state_id: str
    org_id: str
    datapoint_id: str
    grain: Grain
    scope_ref: str | None = Field(
        default=None,
        description="Site id, vehicle-group id, etc. None for org-grain questions.",
    )
    status: DatapointStatus = "unasked"
    value: dict | None = None
    provenance: Provenance | None = None
    uncertainty_tier: str | None = None
    escalation_id: str | None = None
    provisional_fields: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    updated_by: str

    @property
    def key(self) -> tuple[str, str, str | None]:
        """Identity of the state within an org."""
        return (self.org_id, self.datapoint_id, self.scope_ref)
