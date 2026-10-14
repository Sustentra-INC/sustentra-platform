"""Emissions recalculation for an engagement, and the reference lists its inputs use.

GET /v1/engagements/{engagement_id}/recalculation runs the recalculation on the reviewed
evidence (see services/engagement_recalculation_service.py). Its inputs (GWP set, grid
region per facility, fuel choices, certificates, reported totals) are saved through
PATCH /v1/engagements/{engagement_id} under settings["recalculation"].
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.api import reviews as reviews_api
from backend.app.api.engagements import _visible
from backend.app.api.s1_access import can_see, s1_reader
from backend.app.core.auth import CurrentUser
from backend.app.core.db import get_db_session
from backend.app.reference import egrid_zip
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    GWP_SETS,
    default_emission_factor_reference,
)
from backend.app.services import workpaper_export_service, workpaper_item_service
from backend.app.services.audit_log import write_audit_event
from backend.app.services.engagement_recalculation_service import (
    DATA_POINT_CATALOGUE,
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
    decisions = {
        str(item["payload"].get("documentId") or item["item_key"]): item["payload"]
        for item in await workpaper_item_service.list_items(db, engagement["id"], "document")
    }
    return _service().recalculate(engagement, lambda record: can_see(record, user), decisions)


@router.get("/engagements/{engagement_id}/export")
async def export_workpaper(
    engagement_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """The workpaper as an Excel file (the same numbers the screens show)."""

    engagement = await _visible(db, engagement_id, user)
    items = await workpaper_item_service.list_items(db, engagement["id"])
    decisions = {str(i["payload"].get("documentId") or i["item_key"]): i["payload"]
                 for i in items if i["kind"] == "document"}
    service = _service()
    visible = lambda record: can_see(record, user)  # noqa: E731
    recalculation = service.recalculate(engagement, visible, decisions)
    register = service.evidence_register(str(engagement["id"]), visible)
    content = workpaper_export_service.build_workbook(
        engagement=engagement, recalculation=recalculation, register=register, items=items,
        exported_by=user.email,
    )
    await write_audit_event(
        db, "workpaper_exported", org_id=engagement["org_id"], actor_user_id=user.id, actor_role=user.role,
        target_type="engagement", target_id=str(engagement["id"]),
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"), metadata={"format": "xlsx"},
    )
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", str(engagement.get("name") or "engagement")).strip() or "engagement"
    filename = f"{name} workpaper {datetime.now(UTC):%Y-%m-%d}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/reference/egrid-zip/{zip_code}")
def egrid_zip_lookup(zip_code: str, user: CurrentUser = Depends(s1_reader)) -> dict:
    """eGRID subregion(s) for a US ZIP code (EPA Power Profiler, eGRID2023): one is
    definitive; several mean the facility's utility decides."""

    if not re.fullmatch(r"\d{5}", zip_code):
        raise HTTPException(status_code=422, detail="A ZIP code is 5 digits.")
    subregions = egrid_zip.subregions_for_zip(zip_code)
    if not subregions:
        raise HTTPException(status_code=404, detail=f"ZIP code {zip_code} is not in the EPA lookup.")
    return {"zip": zip_code, "subregions": subregions, "dataset": egrid_zip.DATASET}


@router.get("/reference/recalculation")
def recalculation_reference(user: CurrentUser = Depends(s1_reader)) -> dict:
    """Choices for the recalculation inputs: grid regions, EPA fuels, vehicle types, GWP sets, data points."""

    ref = default_emission_factor_reference()
    return {
        "dataset": ref.dataset,
        "gwp_sets": list(GWP_SETS),
        "default_gwp_set": DEFAULT_GWP_SET,
        "egrid_subregions": ref.egrid_subregions(),
        "stationary_fuels": ref.stationary_fuel_types(),
        "mobile_fuels": [row["fuel_type"] for row in ref.data["mobile_co2"]],
        "vehicle_types": ref.vehicle_types(),
        "reported_data_points": [
            {"key": key, "label": label, "workbook_row": row, "unit": unit} for key, label, row, unit in DATA_POINTS
        ],
        # Every reported data point in the workbook, for Setup's in-scope list.
        "data_points": [
            {"key": key, "label": label, "workbook_row": row, "unit": unit, "layer": layer,
             "requirement": requirement, "check": check}
            for key, label, row, unit, layer, requirement, check in DATA_POINT_CATALOGUE
        ],
    }
