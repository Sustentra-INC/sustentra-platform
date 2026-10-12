"""Emissions recalculation for an engagement, and the reference lists its inputs use.

GET /v1/engagements/{engagement_id}/recalculation runs the recalculation on the reviewed
evidence (see services/engagement_recalculation_service.py). Its inputs (GWP set, grid
region per facility, fuel choices, certificates, reported totals) are saved through
PATCH /v1/engagements/{engagement_id} under settings["recalculation"].
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.api import reviews as reviews_api
from backend.app.api.engagements import _visible
from backend.app.api.s1_access import can_see, s1_reader
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    GWP_SETS,
    default_emission_factor_reference,
)
from backend.app.services.engagement_recalculation_service import (
    DATA_POINTS,
    EngagementRecalculationService,
)

router = APIRouter(prefix="/v1", tags=["recalculation"])


def _service() -> EngagementRecalculationService:
    return EngagementRecalculationService(
        upload_service=documents_api.current_upload_service(),
        pipeline_service=documents_api.current_pipeline_service(),
        review_service=reviews_api.current_service(),
    )


@router.get("/engagements/{engagement_id}/recalculation")
async def get_recalculation(
    engagement_id: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    return _service().recalculate(engagement, lambda record: can_see(record, user))


@router.get("/reference/recalculation")
def recalculation_reference(user: CurrentUser = Depends(s1_reader)) -> dict:
    """Choices for the recalculation inputs: grid regions, EPA fuels, GWP sets, data points."""

    ref = default_emission_factor_reference()
    return {
        "dataset": ref.dataset,
        "gwp_sets": list(GWP_SETS),
        "default_gwp_set": DEFAULT_GWP_SET,
        "egrid_subregions": ref.egrid_subregions(),
        "stationary_fuels": ref.stationary_fuel_types(),
        "mobile_fuels": [row["fuel_type"] for row in ref.data["mobile_co2"]],
        "reported_data_points": [
            {"key": key, "label": label, "workbook_row": row, "unit": unit} for key, label, row, unit in DATA_POINTS
        ],
    }
