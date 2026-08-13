"""Org and Site domain models (intake Stage 0/1).

An ``Org`` is one client company; a ``Site`` is one location belonging to it.
Both hold only the raw facts collected by the seed form. Boundary judgments -
notably whether the company has operational control over a leased asset - are
HUMAN class per the mapping and are deliberately NOT decided here; the fields
they would populate are listed in ``deferred_boundary_fields`` and resolved in
the boundary block (BND-2.3) during Phase C.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Ownership = Literal["owned", "leased"]
ProfileStatus = Literal["awaiting_seed_form", "seed_form_complete"]


class ResponsibleParty(BaseModel):
    """The person accountable for the inventory (mapping 1.2, ISO 14064-1)."""

    name: str
    role: str
    email: str


class SiteAddress(BaseModel):
    """Postal address. Feeds FAC-010.location and Scope 2 grid-region matching.

    The grid region (S2-MTR-070) is derived from this address downstream and is
    never asked of the client.
    """

    address_line: str
    city: str
    state_region: str
    postal_code: str
    country_region: str


class Org(BaseModel):
    """A client company (mapping 1.1, 1.2, 1.4, 1.6).

    An org is created before the client signs in, so the seed-form fields start
    empty and ``profile_status`` is ``awaiting_seed_form``. They are filled when
    the seed form is submitted. They are optional rather than placeholder-filled:
    an empty field is honest, a made-up one is not.
    """

    org_id: str
    legal_name: str
    reporting_year: int | None = None
    industry: str | None = None
    industry_overlay_id: str | None = None
    reporting_period_start: str | None = None
    reporting_period_end: str | None = None
    fiscal_year_basis: str | None = None
    responsible_party: ResponsibleParty | None = None
    profile_status: ProfileStatus = "awaiting_seed_form"
    created_at: str
    created_by: str
    updated_at: str
    provisional_fields: list[str] = Field(
        default_factory=list,
        description="Field IDs whose value uses a vocabulary still awaiting expert sign-off.",
    )


class Site(BaseModel):
    """One location belonging to an org (mapping 1.3, 1.5, 1.7)."""

    site_id: str
    org_id: str
    site_name: str
    address: SiteAddress
    operational_status: str
    period_in_scope_start: str
    period_in_scope_end: str
    site_type: str
    ownership: Ownership
    lease_type: str | None = None
    ownership_note: str | None = None
    created_at: str
    updated_at: str
    provisional_fields: list[str] = Field(default_factory=list)
    deferred_boundary_fields: list[dict] = Field(
        default_factory=list,
        description=(
            "Methodology fields intentionally left unset because they require a boundary "
            "judgment (HUMAN class). Each entry names the field and the datapoint that "
            "resolves it."
        ),
    )
