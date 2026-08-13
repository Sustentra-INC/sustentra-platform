"""Evidence request: one document we expect from a client (intake Stage 4).

intake/SPEC.md section 5 lists ``evidence_requests`` as J2 type x site x period
x status. A request exists only because the client's own answers imply the
source exists - "yes, we have generators" produces generator records, "no, we
have none" produces a completeness record and no request at all.

Two things this deliberately does not do:

* **Invent an expected count.** Where the cadence is unknown (most types - see
  ``intake/config/evidence_cadence.json``) the request covers the whole period
  and ``expected_count_known`` is False. A completeness gate must treat that as
  unknown, never as zero.
* **Handle files.** Uploading, parsing and extracting belong to the existing S1
  pipeline. This is the list of what should arrive, not a second pipeline.

The ID is derived from the request's identity rather than randomly generated, so
recompiling after further answers updates the same record and its status
survives. See :func:`request_id`.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from intake.backend.domain.datapoint_state import Grain

EvidenceRequestStatus = Literal["expected", "received", "accepted", "waived", "superseded"]

Cadence = Literal["monthly", "annual", "as_available"]

DatapointClass = Literal["AUTO", "HUMAN", "SYSTEM"]


def request_id(
    org_id: str,
    evidence_type_id: str,
    scope_ref: str | None,
    period_start: str,
    unit_index: int,
) -> str:
    """A stable ID for one request.

    Derived, not random: the same client, evidence type, scope, period and unit
    always produce the same ID. That is what lets the compiler run again after
    every answer without duplicating rows or resetting a status someone set.
    """
    identity = "|".join(
        [org_id, evidence_type_id, scope_ref or "org", period_start, str(unit_index)]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"evr_{digest}"


class RequestedBy(BaseModel):
    """An answer that caused this request to exist."""

    datapoint_id: str
    scope_ref: str | None = None
    datapoint_class: DatapointClass = Field(alias="class")

    model_config = {"populate_by_name": True}


class BlockedBy(BaseModel):
    """Why S1 must not start on this document yet (SPEC section 5, Stage 5)."""

    datapoint_id: str
    scope_ref: str | None = None
    reason: str


class EvidenceRequest(BaseModel):
    evidence_request_id: str
    org_id: str
    evidence_type_id: str
    evidence_type_name: str
    grain: Grain
    scope_ref: str | None = None
    scope_label: str
    period_start: str
    period_end: str
    period_label: str
    unit_index: int = 1
    unit_label: str = "all"
    cadence: Cadence = "as_available"
    cadence_provisional: bool = True
    expected_count_known: bool = False
    status: EvidenceRequestStatus = "expected"
    requested_by: list[RequestedBy] = Field(default_factory=list)
    safe_to_parse: bool = False
    blocked_by: list[BlockedBy] = Field(default_factory=list)
    created_at: str
    updated_at: str
