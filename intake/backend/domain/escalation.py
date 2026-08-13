"""Escalation record.

intake/SPEC.md section 5 says to reuse the shape of
``reference-data/config/libraries/gap_ticket_schema.json`` "where sensible". Most
of that schema is not sensible here: it is a verification-side artifact with
forty-odd fields built around audit findings, assertions, materiality and
workbook locations. Forcing an intake escalation - "the client does not know the
answer to a question" - into it would mean inventing values for a dozen required
fields.

What IS reused, deliberately:

* ``ticket_type: clarification_request`` - an existing member of that schema's
  enum, and exactly what an intake escalation is.
* ``status`` values ``pending_auditor_review`` and ``resolved``, taken from the
  gap ticket status enum.
* ``detection_origin``, ``ticket_version``, ``audit_trail``, and the
  created/updated/resolved timestamp trio.

What is deliberately NOT reused: assertions, materiality, calculation impact,
workbook locations, library references. Those describe findings against a
prepared inventory, which is not what this is.

Phase C writes these records. Phase D adds the reviewer queue and the emails; no
email is sent from here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EscalationStatus = Literal["pending_auditor_review", "resolved", "superseded"]

EscalationTrigger = Literal[
    "human_class_datapoint",
    "failed_clarification",
    "user_requested_help",
    "contradiction",
    "condition_met",
]


class EscalationAuditEntry(BaseModel):
    at: str
    actor_id: str
    action: str
    note: str | None = None


class Escalation(BaseModel):
    escalation_id: str
    ticket_version: int = 1
    org_id: str
    datapoint_id: str
    scope_ref: str | None = None
    title: str
    ticket_type: Literal["clarification_request"] = "clarification_request"
    status: EscalationStatus = "pending_auditor_review"
    detection_origin: Literal["system_detected", "user_requested"] = "system_detected"
    trigger: EscalationTrigger
    question_label: str
    answer_attempts: list[dict] = Field(default_factory=list)
    seed_context: dict = Field(
        default_factory=dict,
        description="Company and site facts the reviewer needs to answer without digging.",
    )
    resolution_value: dict | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    audit_trail: list[EscalationAuditEntry] = Field(default_factory=list)
    created_by: str
    created_at: str
    updated_at: str
    resolved_at: str | None = None
    notified_at: str | None = Field(
        default=None,
        description="When the team was emailed about this. Unset means it is waiting for the next digest.",
    )
    reminded_at: str | None = Field(
        default=None,
        description="When the reminder went out. Set once, so re-running the job sends nothing.",
    )
