"""Seed-form endpoints (intake Stage 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from intake.backend.api.context import get_context, require_user
from intake.backend.domain.auth import AuthenticatedUser
from intake.backend.services.seed_form_service import SeedFormValidationError

router = APIRouter(prefix="/v1/intake/seed-form", tags=["intake-seed-form"])


class SeedFormSubmission(BaseModel):
    company: dict = Field(default_factory=dict)
    sites: list[dict] = Field(default_factory=list)


@router.get("/schema")
def get_schema(
    overlay_id: str | None = None, user: AuthenticatedUser = Depends(require_user)
) -> dict:
    """The form definition, with option lists resolved for the caller's overlay."""
    context = get_context()
    if overlay_id is None:
        org = context.org_service.get_org(user.org_id)
        overlay_id = org.get("industry_overlay_id")
    return context.seed_form_service.get_form(overlay_id)


@router.post("")
def submit(
    payload: SeedFormSubmission, user: AuthenticatedUser = Depends(require_user)
) -> dict:
    context = get_context()
    if not context.org_service.can_submit_seed_form(user.role):
        raise HTTPException(status_code=403, detail="Your role cannot submit the seed form.")
    try:
        return context.seed_form_service.submit(
            org_id=user.org_id,
            submitted_by=user.user_id,
            payload=payload.model_dump(),
        )
    except SeedFormValidationError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors}) from exc


@router.get("/submissions/latest")
def latest_submission(user: AuthenticatedUser = Depends(require_user)) -> dict:
    submission = get_context().seed_form_service.latest_submission(user.org_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="No seed form submitted yet.")
    return submission
