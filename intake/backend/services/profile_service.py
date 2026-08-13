"""The profile page: the client's living record (intake Stage 6, Phase E).

intake/SPEC.md section 3, Stage 6: company and sites, boundary decisions with
their rationale, every data point with status and who answered it, "screened,
not present" completeness records kept separate from genuine exclusions,
uncertainty ratings, coverage state - and versioned, because for a verification
company the edit history is itself evidence.

This service decides nothing. Every field it returns is read from a record that
already exists: orgs, sites, datapoint_states, escalations, the audit log and
the profile schema. It assembles and labels; it never computes a new fact about
a client's emissions.

Two distinctions are load-bearing and are kept apart on purpose:

* **"Screened, not present"** (status ``not_present``) means we looked and the
  source is not there. It is a completeness record.
* **An exclusion** (EXC-010, via BND-2.7) means the source exists and was left
  out on materiality grounds. It requires a reviewer and carries a rationale.

Collapsing them would misrepresent the inventory to a verifier, so they are
separate blocks in the response and are never counted together.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from intake.backend.config import IntakeSettings, load_profile_schema, load_settings
from intake.backend.services.coverage_service import is_complete_for_client
from intake.backend.services.question_content import load_question_content

EXCLUSION_DATAPOINT = "BND-2.7"
BOUNDARY_SECTION = "boundary"

# How a status reads to a client, and to a verifier reading over their shoulder.
STATUS_LABELS = {
    "unasked": "Not asked yet",
    "asked": "Asked, not answered",
    "answered": "Answered",
    "unknown": "Answer not known",
    "not_present": "Screened - not present here",
    "pending_documents": "Waiting on a document",
    "escalated": "With the Sustentra team",
    "resolved": "Answered by the Sustentra team",
}

ANSWERED_BY_LABELS = {
    "user": "the client",
    "document": "a document",
    "team": "the Sustentra team",
    "system": "derived automatically",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProfileService:
    def __init__(
        self,
        org_repository: Any,
        site_repository: Any,
        state_repository: Any,
        escalation_repository: Any,
        audit_repository: Any,
        coverage_service: Any,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._orgs = org_repository
        self._sites = site_repository
        self._states = state_repository
        self._escalations = escalation_repository
        self._audit = audit_repository
        self._coverage = coverage_service
        self._settings = settings or load_settings()
        self._clock = clock

        schema = load_profile_schema()
        self._sections = {section["section_id"]: section for section in schema["sections"]}
        self._datapoints = {item["datapoint_id"]: item for item in schema["datapoints"]}
        self._content = load_question_content()

    # -- the page -----------------------------------------------------------

    def profile(self, org_id: str) -> dict[str, Any] | None:
        org = self._orgs.get(org_id)
        if org is None:
            return None

        sites = self._sites.list_by_org(org_id)
        site_names = {site["site_id"]: site["site_name"] for site in sites}
        states = self._states.list_by_org(org_id)
        open_escalations = {
            (record["datapoint_id"], record.get("scope_ref")): record
            for record in self._escalations.list_open(org_id)
        }

        entries = [self._entry(state, site_names, open_escalations) for state in states]

        return {
            "org_id": org_id,
            "generated_at": self._clock().isoformat(),
            "company": self._company(org),
            "sites": [self._site(site) for site in sites],
            "coverage": self._coverage.coverage(org_id),
            "sections": self._by_section(entries),
            "boundary_decisions": [
                entry for entry in entries if entry["section"] == BOUNDARY_SECTION
            ],
            "completeness_records": [
                entry for entry in entries if entry["status"] == "not_present"
            ],
            "exclusions": self._exclusions(entries),
            "uncertainty": self._uncertainty(entries),
            "with_the_team": [
                entry for entry in entries if entry["status"] == "escalated"
            ],
            "provisional_values": self._provisional(org, sites),
        }

    def history(self, org_id: str, limit: int | None = None) -> dict[str, Any]:
        """Every recorded change, oldest first - the story, not a stack.

        A verifier reads this forwards: what was said, what changed, who changed
        it. Newest-first would put the conclusion before the evidence.
        """
        entries = self._audit.list_by_org(org_id)
        entries = sorted(entries, key=lambda entry: entry["at"])
        total = len(entries)
        if limit is not None:
            entries = entries[-limit:]

        site_names = {
            site["site_id"]: site["site_name"] for site in self._sites.list_by_org(org_id)
        }
        return {
            "org_id": org_id,
            "count": total,
            "returned": len(entries),
            "entries": [self._audit_entry(entry, site_names) for entry in entries],
        }

    # -- blocks -------------------------------------------------------------

    def _company(self, org: dict[str, Any]) -> dict[str, Any]:
        return {
            "legal_name": org.get("legal_name"),
            "reporting_year": org.get("reporting_year"),
            "reporting_period_start": org.get("reporting_period_start"),
            "reporting_period_end": org.get("reporting_period_end"),
            "fiscal_year_basis": org.get("fiscal_year_basis"),
            "industry": org.get("industry"),
            "industry_overlay_id": org.get("industry_overlay_id"),
            "responsible_party": org.get("responsible_party"),
            "profile_status": org.get("profile_status"),
            "provisional_fields": org.get("provisional_fields") or [],
            "updated_at": org.get("updated_at"),
        }

    def _site(self, site: dict[str, Any]) -> dict[str, Any]:
        return {
            "site_id": site["site_id"],
            "site_name": site.get("site_name"),
            "address": site.get("address"),
            "site_type": site.get("site_type"),
            "operational_status": site.get("operational_status"),
            "ownership": site.get("ownership"),
            "lease_type": site.get("lease_type"),
            "ownership_note": site.get("ownership_note"),
            "period_in_scope_start": site.get("period_in_scope_start"),
            "period_in_scope_end": site.get("period_in_scope_end"),
            "provisional_fields": site.get("provisional_fields") or [],
            # Fields left unset on purpose because they need a boundary call.
            "deferred_boundary_fields": site.get("deferred_boundary_fields") or [],
            "updated_at": site.get("updated_at"),
        }

    def _entry(
        self,
        state: dict[str, Any],
        site_names: dict[str, str],
        open_escalations: dict[tuple[str, str | None], dict[str, Any]],
    ) -> dict[str, Any]:
        datapoint = self._datapoints.get(state["datapoint_id"], {})
        content = self._content.get(state["datapoint_id"], {})
        provenance = state.get("provenance") or {}
        answered_by = provenance.get("answered_by")
        scope_ref = state.get("scope_ref")
        escalation = open_escalations.get((state["datapoint_id"], scope_ref))

        return {
            "datapoint_id": state["datapoint_id"],
            "label": datapoint.get("label"),
            "question": content.get("question"),
            "section": datapoint.get("section"),
            "class": datapoint.get("class"),
            "grain": state.get("grain"),
            "scope_ref": scope_ref,
            "scope_label": site_names.get(scope_ref) if scope_ref else None,
            "status": state["status"],
            "status_label": STATUS_LABELS.get(state["status"], state["status"]),
            "complete_for_client": is_complete_for_client(state),
            "value": state.get("value"),
            "answered_by": answered_by,
            "answered_by_label": ANSWERED_BY_LABELS.get(answered_by) if answered_by else None,
            "actor_id": provenance.get("actor_id"),
            "value_basis": provenance.get("value_basis"),
            "note": provenance.get("note"),
            "uncertainty_tier": state.get("uncertainty_tier"),
            "ai_assisted": bool(state.get("ai_assisted")),
            "provisional_fields": state.get("provisional_fields") or [],
            "evidence_triggered": datapoint.get("evidence_triggered") or [],
            "escalation_id": state.get("escalation_id"),
            "with_team_since": escalation.get("created_at") if escalation else None,
            "updated_at": state.get("updated_at"),
        }

    def _by_section(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            grouped.setdefault(entry["section"], []).append(entry)

        sections = []
        for section_id, items in grouped.items():
            section = self._sections.get(section_id, {})
            sections.append(
                {
                    "section_id": section_id,
                    "label": section.get("label", section_id),
                    "order": section.get("order", 99),
                    "complete": sum(1 for item in items if item["complete_for_client"]),
                    "total": len(items),
                    "datapoints": sorted(
                        items,
                        key=lambda item: (item["scope_label"] or "", item["datapoint_id"]),
                    ),
                }
            )
        return sorted(sections, key=lambda section: section["order"])

    def _exclusions(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Genuine EXC-010 exclusions - never the screened-out sources.

        A source excluded on materiality grounds still exists. Presenting it
        alongside "we looked and it is not here" would misstate the inventory.
        """
        out = []
        for entry in entries:
            if entry["datapoint_id"] != EXCLUSION_DATAPOINT:
                continue
            value = entry.get("value") or {}
            if not value:
                continue
            out.append(
                {
                    "datapoint_id": entry["datapoint_id"],
                    "scope_ref": entry["scope_ref"],
                    "scope_label": entry["scope_label"],
                    "status": entry["status"],
                    "value": value,
                    "confirmed_by": entry["answered_by_label"],
                    "actor_id": entry["actor_id"],
                    "methodology_field": "EXC-010",
                    "updated_at": entry["updated_at"],
                }
            )
        return out

    def _uncertainty(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The ISO 14064-1 section 8.3 roll-up input, as far as it exists today.

        Reported per answered data point rather than rolled up to a category
        rating: the roll-up rule itself is a methodology judgment (PRV-8.2,
        HUMAN class) and is not ours to invent.
        """
        return [
            {
                "datapoint_id": entry["datapoint_id"],
                "label": entry["label"],
                "scope_label": entry["scope_label"],
                "value_basis": entry["value_basis"],
                "uncertainty_tier": entry["uncertainty_tier"],
            }
            for entry in entries
            if entry["value_basis"] or entry["uncertainty_tier"]
        ]

    def _provisional(
        self, org: dict[str, Any], sites: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Values using a vocabulary nobody has signed off yet."""
        out = [
            {"scope": "company", "scope_label": org.get("legal_name"), "field_id": field}
            for field in (org.get("provisional_fields") or [])
        ]
        for site in sites:
            out.extend(
                {
                    "scope": "site",
                    "scope_label": site.get("site_name"),
                    "field_id": field,
                }
                for field in (site.get("provisional_fields") or [])
            )
        signoff = self._settings.provisional_vocabularies
        for item in out:
            item["requires_signoff"] = (signoff.get(item["field_id"]) or {}).get(
                "requires_signoff", "Todd"
            )
        return out

    def _audit_entry(
        self, entry: dict[str, Any], site_names: dict[str, str]
    ) -> dict[str, Any]:
        datapoint = self._datapoints.get(entry.get("datapoint_id") or "", {})
        scope_ref = entry.get("scope_ref")
        return {
            "at": entry["at"],
            "action": entry["action"],
            "entity_type": entry["entity_type"],
            "entity_id": entry["entity_id"],
            "datapoint_id": entry.get("datapoint_id"),
            "label": datapoint.get("label"),
            "scope_ref": scope_ref,
            "scope_label": site_names.get(scope_ref) if scope_ref else None,
            "field": entry.get("field"),
            "old_value": entry.get("old_value"),
            "new_value": entry.get("new_value"),
            "actor_id": entry["actor_id"],
            "actor_role": entry.get("actor_role"),
            "reason": entry.get("reason"),
        }
