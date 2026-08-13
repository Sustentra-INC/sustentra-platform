"""Seed form: definition, validation and persistence (intake Stage 1).

The form is driven by config, not code. ``intake/config/seed_form.json`` names
the inputs and the methodology/legacy/intake field each one feeds; this service
resolves option lists, validates a submission and writes the resulting org, site
and submission records.

Two deliberate restraints, both from the mapping and CLAUDE.md:

* Values whose vocabulary is not yet agreed (``operational_status``,
  ``fiscal_year_basis``, general-overlay ``site_type``) are accepted as free text
  and recorded as provisional, never validated against invented values.
* Boundary judgments are not made here. Own/lease is captured as a raw fact;
  ``operational_control_over_asset_flag`` and ``party_role`` are left unset and
  recorded as deferred to BND-2.3.

Phase B does not write ``datapoint_states``; Phase C's state machine back-fills
them from these submissions (founder-approved).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from intake.backend.config import (
    IntakeSettings,
    load_profile_schema,
    load_seed_form,
    load_settings,
    vocabulary_is_open,
    vocabulary_values,
)
from intake.backend.domain.org import Site, SiteAddress
from intake.backend.domain.seed_profile import ProvisionalValue, SeedProfileSubmission
from intake.backend.repositories.org_repository import OrgRepository
from intake.backend.repositories.seed_profile_repository import SeedProfileRepository
from intake.backend.repositories.site_repository import SiteRepository

COMPANY_STEP = "company"
SITES_STEP = "sites"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SeedFormValidationError(Exception):
    """Carries every field-level problem so the form can show them all at once."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(errors)} validation error(s)")
        self.errors = errors


class SeedFormService:
    def __init__(
        self,
        org_repository: OrgRepository,
        site_repository: SiteRepository,
        seed_profile_repository: SeedProfileRepository,
        email_service: Any | None = None,
        settings: IntakeSettings | None = None,
        clock: Callable[[], datetime] = _utcnow,
        profile_audit: Any | None = None,
        profile_states: Any | None = None,
    ) -> None:
        self._orgs = org_repository
        self._sites = site_repository
        self._submissions = seed_profile_repository
        self._email = email_service
        self._settings = settings or load_settings()
        self._clock = clock
        # Phase E. Optional so the seed form still works with no audit wired up,
        # but the runtime always wires it: resubmitting must leave a trace.
        self._profile_audit = profile_audit
        # Phase E. Also optional: used only to re-run the seed back-fill when a
        # client edits facts after the interview has already started.
        self._profile_states = profile_states

    # -- form definition ----------------------------------------------------

    def get_form(self, overlay_id: str | None = None) -> dict[str, Any]:
        """The form definition with option lists resolved for the UI."""
        form = load_seed_form()
        steps = []
        for step in form["steps"]:
            fields = [self._resolve_field(field, overlay_id) for field in step["fields"]]
            steps.append({**step, "fields": fields})
        return {
            "form_name": form["form_name"],
            "form_version": form["form_version"],
            "copy_status": form["copy_status"],
            "copy_note": form["copy_note"],
            "overlay_id": overlay_id,
            "steps": steps,
        }

    def _resolve_field(self, field: dict[str, Any], overlay_id: str | None) -> dict[str, Any]:
        resolved = dict(field)
        ref = field.get("options_ref")
        if ref == "settings:industries":
            resolved["options"] = self._settings.industries
        elif ref == "settings:site_types":
            resolved.update(self._site_type_options(overlay_id))
        elif isinstance(ref, str) and ref.startswith("vocabulary:"):
            name = ref.split(":", 1)[1]
            resolved["options"] = [
                {"value": value, "label": value.replace("_", " ")}
                for value in vocabulary_values(name)
            ]
            resolved["vocabulary_open"] = vocabulary_is_open(name)
        return resolved

    def _site_type_options(self, overlay_id: str | None) -> dict[str, Any]:
        overlay = overlay_id or "general"
        config = self._settings.site_types.get(overlay) or self._settings.site_types["general"]
        return {
            "input": config["input"],
            "options": config.get("options", []),
            "provisional": bool(config.get("provisional")),
            "requires_signoff": config.get("requires_signoff"),
            "provisional_reason": config.get("reason"),
        }

    # -- submission ---------------------------------------------------------

    def latest_submission(self, org_id: str) -> dict[str, Any] | None:
        """The most recent seed-form submission for an org, if any."""
        return self._submissions.latest_for_org(org_id)

    def current_answers(self, org_id: str) -> dict[str, Any]:
        """Existing answers shaped for the form, so it can be prefilled.

        Each site carries its ``site_id``, which is what makes a second
        submission update the existing sites instead of creating duplicates.
        """
        org = self._orgs.get(org_id)
        if org is None:
            return {"company": {}, "sites": []}

        responsible = org.get("responsible_party") or {}
        company = {
            "legal_name": org.get("legal_name"),
            "reporting_year": org.get("reporting_year"),
            "responsible_party_name": responsible.get("name"),
            "responsible_party_role": responsible.get("role"),
            "responsible_party_email": responsible.get("email"),
            "industry": org.get("industry"),
            "reporting_period_start": org.get("reporting_period_start"),
            "reporting_period_end": org.get("reporting_period_end"),
            "fiscal_year_basis": org.get("fiscal_year_basis"),
        }

        sites = []
        for site in self._sites.list_by_org(org_id):
            address = site.get("address") or {}
            sites.append(
                {
                    "site_id": site["site_id"],
                    "site_name": site.get("site_name"),
                    "address_line": address.get("address_line"),
                    "city": address.get("city"),
                    "state_region": address.get("state_region"),
                    "postal_code": address.get("postal_code"),
                    "country_region": address.get("country_region"),
                    "operational_status": site.get("operational_status"),
                    "site_type": site.get("site_type"),
                    "ownership": site.get("ownership"),
                    "lease_type": site.get("lease_type"),
                    "ownership_note": site.get("ownership_note"),
                }
            )

        return {
            "profile_status": org.get("profile_status"),
            "company": {key: value for key, value in company.items() if value is not None},
            "sites": sites,
        }

    def submit(
        self, org_id: str, submitted_by: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        org = self._orgs.get(org_id)
        if org is None:
            raise SeedFormValidationError([{"field": "org_id", "message": f"Unknown org {org_id}."}])

        company = payload.get(COMPANY_STEP) or {}
        sites = payload.get(SITES_STEP) or []
        errors: list[dict[str, Any]] = []

        if not isinstance(company, dict):
            raise SeedFormValidationError([{"field": COMPANY_STEP, "message": "Expected an object."}])
        if not isinstance(sites, list):
            raise SeedFormValidationError([{"field": SITES_STEP, "message": "Expected a list."}])

        overlay_id = self._validate_company(company, errors)
        if not sites:
            errors.append({"field": SITES_STEP, "message": "At least one site is required."})
        for index, site in enumerate(sites):
            if not isinstance(site, dict):
                errors.append({"field": SITES_STEP, "index": index, "message": "Expected an object."})
                continue
            self._validate_site(site, index, overlay_id, errors)

        if errors:
            raise SeedFormValidationError(errors)

        return self._persist(org, company, sites, overlay_id, submitted_by)

    # -- validation helpers -------------------------------------------------

    def _validate_company(self, company: dict[str, Any], errors: list[dict[str, Any]]) -> str:
        for field_id in (
            "legal_name",
            "responsible_party_name",
            "responsible_party_role",
            "responsible_party_email",
        ):
            if not str(company.get(field_id) or "").strip():
                errors.append({"field": field_id, "message": "This field is required."})

        email = str(company.get("responsible_party_email") or "").strip()
        if email and not self._looks_like_email(email):
            errors.append(
                {"field": "responsible_party_email", "message": "Enter a valid email address."}
            )

        year = company.get("reporting_year")
        if year is None or str(year).strip() == "":
            errors.append({"field": "reporting_year", "message": "This field is required."})
        else:
            try:
                year_value = int(year)
            except (TypeError, ValueError):
                errors.append({"field": "reporting_year", "message": "Enter a four-digit year."})
            else:
                if not 1990 <= year_value <= 2100:
                    errors.append(
                        {"field": "reporting_year", "message": "Enter a year between 1990 and 2100."}
                    )

        industry = str(company.get("industry") or "").strip()
        known = {item["value"] for item in self._settings.industries}
        if not industry:
            errors.append({"field": "industry", "message": "This field is required."})
        elif industry not in known:
            errors.append(
                {"field": "industry", "message": f"Choose one of: {', '.join(sorted(known))}."}
            )

        start = self._validate_date(company.get("reporting_period_start"), "reporting_period_start", errors)
        end = self._validate_date(company.get("reporting_period_end"), "reporting_period_end", errors)
        if start and end and start > end:
            errors.append(
                {
                    "field": "reporting_period_end",
                    "message": "The reporting period must end on or after it starts.",
                }
            )

        entry = self._settings.industry(industry) if industry else None
        return (entry or {}).get("overlay_id", "general")

    def _validate_site(
        self, site: dict[str, Any], index: int, overlay_id: str, errors: list[dict[str, Any]]
    ) -> None:
        def fail(field: str, message: str) -> None:
            errors.append({"field": field, "index": index, "message": message})

        for field_id in (
            "site_name",
            "address_line",
            "city",
            "state_region",
            "postal_code",
            "country_region",
            "operational_status",
            "site_type",
        ):
            if not str(site.get(field_id) or "").strip():
                fail(field_id, "This field is required.")

        ownership = str(site.get("ownership") or "").strip()
        if ownership not in {"owned", "leased"}:
            fail("ownership", "Choose whether you own or lease this site.")

        lease_type = str(site.get("lease_type") or "").strip()
        if lease_type:
            permitted = vocabulary_values("lease_type")
            if lease_type not in permitted:
                fail("lease_type", f"Choose one of: {', '.join(permitted)}.")
            if ownership == "owned":
                fail("lease_type", "Lease type only applies to leased sites.")

        site_type = str(site.get("site_type") or "").strip()
        overlay_config = self._settings.site_types.get(overlay_id)
        if site_type and overlay_config and overlay_config.get("input") == "select":
            permitted = {option["value"] for option in overlay_config.get("options", [])}
            if site_type not in permitted:
                fail("site_type", f"Choose one of: {', '.join(sorted(permitted))}.")

    def _validate_date(
        self, value: Any, field_id: str, errors: list[dict[str, Any]]
    ) -> date | None:
        raw = str(value or "").strip()
        if not raw:
            errors.append({"field": field_id, "message": "This field is required."})
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            errors.append({"field": field_id, "message": "Use the format YYYY-MM-DD."})
            return None

    @staticmethod
    def _looks_like_email(value: str) -> bool:
        if value.count("@") != 1:
            return False
        local, _, domain = value.partition("@")
        return bool(local) and "." in domain and not domain.startswith(".")

    # -- persistence --------------------------------------------------------

    def _persist(
        self,
        org: dict[str, Any],
        company: dict[str, Any],
        sites: list[dict[str, Any]],
        overlay_id: str,
        submitted_by: str,
    ) -> dict[str, Any]:
        now = self._clock().isoformat()
        provisional: list[ProvisionalValue] = []

        fiscal_basis = str(company.get("fiscal_year_basis") or "").strip() or None
        if fiscal_basis:
            provisional.append(
                ProvisionalValue(
                    field_id="fiscal_year_basis",
                    datapoint_id="SEED-1.6",
                    value=fiscal_basis,
                    requires_signoff="Todd",
                    reason=self._provisional_reason("fiscal_year_basis"),
                )
            )

        updated_org = dict(org)
        updated_org.update(
            {
                "legal_name": str(company["legal_name"]).strip(),
                "reporting_year": int(company["reporting_year"]),
                "industry": str(company["industry"]).strip(),
                "industry_overlay_id": overlay_id,
                "reporting_period_start": str(company["reporting_period_start"]).strip(),
                "reporting_period_end": str(company["reporting_period_end"]).strip(),
                "fiscal_year_basis": fiscal_basis,
                "responsible_party": {
                    "name": str(company["responsible_party_name"]).strip(),
                    "role": str(company["responsible_party_role"]).strip(),
                    "email": str(company["responsible_party_email"]).strip(),
                },
                "profile_status": "seed_form_complete",
                "updated_at": now,
                "provisional_fields": ["fiscal_year_basis"] if fiscal_basis else [],
            }
        )
        self._orgs.save(updated_org)
        if self._profile_audit is not None:
            self._profile_audit.record_org_change(
                before=org,
                after=updated_org,
                actor_id=submitted_by,
                reason="seed form submitted",
            )

        deferred = load_seed_form()["steps"][1]["deferred_fields"]
        site_ids: list[str] = []
        for site_payload in sites:
            site_id = str(site_payload.get("site_id") or "").strip() or f"ste_{uuid.uuid4().hex[:12]}"
            existing = self._sites.get(site_id)
            site_provisional = ["operational_status"]
            site_type = str(site_payload["site_type"]).strip()
            if (self._settings.site_types.get(overlay_id) or {}).get("provisional"):
                site_provisional.append("site_type")

            record = Site(
                site_id=site_id,
                org_id=updated_org["org_id"],
                site_name=str(site_payload["site_name"]).strip(),
                address=SiteAddress(
                    address_line=str(site_payload["address_line"]).strip(),
                    city=str(site_payload["city"]).strip(),
                    state_region=str(site_payload["state_region"]).strip(),
                    postal_code=str(site_payload["postal_code"]).strip(),
                    country_region=str(site_payload["country_region"]).strip(),
                ),
                operational_status=str(site_payload["operational_status"]).strip(),
                # Derived, never asked: sites default to the company reporting period.
                period_in_scope_start=updated_org["reporting_period_start"],
                period_in_scope_end=updated_org["reporting_period_end"],
                site_type=site_type,
                ownership=str(site_payload["ownership"]).strip(),  # type: ignore[arg-type]
                lease_type=str(site_payload.get("lease_type") or "").strip() or None,
                ownership_note=str(site_payload.get("ownership_note") or "").strip() or None,
                created_at=(existing or {}).get("created_at", now),
                updated_at=now,
                provisional_fields=site_provisional,
                deferred_boundary_fields=deferred,
            )
            self._sites.save(record)
            if self._profile_audit is not None:
                self._profile_audit.record_site_change(
                    before=existing,
                    after=record.model_dump(),
                    actor_id=submitted_by,
                    reason="seed form submitted",
                )
            site_ids.append(site_id)

            provisional.append(
                ProvisionalValue(
                    field_id="operational_status",
                    datapoint_id="SEED-1.3",
                    value=record.operational_status,
                    requires_signoff="Todd",
                    reason=self._provisional_reason("operational_status"),
                )
            )
            if "site_type" in site_provisional:
                provisional.append(
                    ProvisionalValue(
                        field_id="site_type",
                        datapoint_id="SEED-1.5",
                        value=site_type,
                        requires_signoff="Todd",
                        reason=str(self._settings.site_types["general"].get("reason", "")),
                    )
                )

        submission = SeedProfileSubmission(
            seed_profile_id=f"sfp_{uuid.uuid4().hex[:12]}",
            org_id=updated_org["org_id"],
            submitted_by=submitted_by,
            submitted_at=now,
            form_version=load_seed_form()["form_version"],
            profile_schema_version=load_profile_schema()["schema_version"],
            answers={COMPANY_STEP: company, SITES_STEP: sites},
            site_ids=site_ids,
            datapoint_ids=self._seed_datapoint_ids(),
            provisional_values=provisional,
        )
        self._submissions.save(submission)
        self._refresh_seed_answers(updated_org["org_id"], submitted_by)

        if self._email is not None:
            self._email.send_template(
                "seed_form_received",
                to=updated_org["responsible_party"]["email"],
                context={
                    "name": updated_org["responsible_party"]["name"],
                    "legal_name": updated_org["legal_name"],
                    "reporting_period_start": updated_org["reporting_period_start"],
                    "reporting_period_end": updated_org["reporting_period_end"],
                    "site_count": len(site_ids),
                },
            )

        return {
            "org": updated_org,
            "sites": [self._sites.get(site_id) for site_id in site_ids],
            "submission": submission.model_dump(),
        }

    def _refresh_seed_answers(self, org_id: str, actor_id: str) -> None:
        """Push edited facts back into the answers derived from them (Phase E).

        The seed form's answers are back-filled into datapoint states when the
        interview starts. Editing a fact afterwards used to change the company
        record and leave the derived answer behind, so the profile page could
        show one reporting period in the company block and a different one in
        the seed-form answers - two truths on the page an auditor reads.

        Only runs once the interview has begun; before that there is nothing to
        refresh, and creating states early would start the interview by surprise.
        """
        if self._profile_states is None or not self._profile_states.has_states(org_id):
            return
        self._profile_states.initialise(org_id, actor_id=actor_id)

    def _provisional_reason(self, field_id: str) -> str:
        fields = self._settings.provisional_vocabularies.get("fields", {})
        return str(fields.get(field_id, {}).get("reason", "Awaiting expert sign-off."))

    @staticmethod
    def _seed_datapoint_ids() -> list[str]:
        return [
            datapoint["datapoint_id"]
            for datapoint in load_profile_schema()["datapoints"]
            if datapoint["section"] == "seed_form"
        ]
