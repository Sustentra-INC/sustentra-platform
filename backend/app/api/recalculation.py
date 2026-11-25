"""Emissions recalculation for an engagement, and the reference lists its inputs use.

GET /v1/engagements/{engagement_id}/recalculation runs the recalculation on the reviewed
evidence (see services/engagement_recalculation_service.py). The GWP set is the one chosen on
the Methodology review (services/methodology_gwp.py), not an input here. Its inputs (grid
region per facility, fuel choices, certificates, reported totals) are saved through
PATCH /v1/engagements/{engagement_id} under settings["recalculation"].
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api import documents as documents_api
from backend.app.api import reviews as reviews_api
from backend.app.api.engagements import _visible
from backend.app.api.s1_access import can_see, s1_reader
from backend.app.core.auth import CurrentUser
from backend.app.core.config import get_settings
from backend.app.core.db import get_db_session
from backend.app.reference import egrid_zip
from backend.app.reference.emission_factor_loader import (
    DEFAULT_GWP_SET,
    GWP_SETS,
    default_emission_factor_reference,
)
from backend.app.services import emissions_rollup, methodology_gwp, workpaper_export_service, workpaper_item_service
from backend.app.services import workpaper_copy_service
from backend.app.services.audit_log import write_audit_event
from backend.app.services.engagement_recalculation_service import (
    DATA_POINT_CATALOGUE,
    DATA_POINTS,
    EngagementRecalculationService,
)
from backend.app.services.workpaper_copy_store import (
    CopyRecord,
    PostgresWorkpaperCopyStore,
    WorkpaperCopyCorrupt,
    WorkpaperCopyStore,
)

logger = logging.getLogger("sustentra.workpaper_copies")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FILE_NAME_CHARS = 80  # of the engagement's name, in the file name

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
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    engagement = await _visible(db, engagement_id, user)
    decisions = {
        str(item["payload"].get("documentId") or item["item_key"]): item["payload"]
        for item in await workpaper_item_service.list_items(db, engagement["id"], "document")
    }
    engagement = await methodology_gwp.attach_choice(db, engagement)  # the Methodology review's GWP set
    return _service().recalculate(engagement, lambda record: can_see(record, user), decisions)


@router.get("/engagements/{engagement_id}/recalculation/lines/{line_key}/trace")
async def get_line_trace(
    engagement_id: str,
    line_key: str,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    """The step-level working of one calculation line (``services/calc_trace``), fetched when a panel is opened.
    The same engine run as the recalculation, so it agrees with it; the recalculation response itself never
    carries traces. ``trace`` is null when the line cannot be traced."""

    engagement = await _visible(db, engagement_id, user)
    decisions = {
        str(item["payload"].get("documentId") or item["item_key"]): item["payload"]
        for item in await workpaper_item_service.list_items(db, engagement["id"], "document")
    }
    engagement = await methodology_gwp.attach_choice(db, engagement)
    result = _service().recalculate(engagement, lambda record: can_see(record, user), decisions, with_traces=True)
    line = next((ln for ln in result.get("calculation_lines", []) if ln.get("key") == line_key), None)
    if line is None:
        raise HTTPException(status_code=404, detail="No such calculation line.")
    return {"line_key": line_key, "trace": line.get("trace")}


def copy_store(db: AsyncSession) -> WorkpaperCopyStore:
    """Where kept copies live (tests swap it; a later S3 store is returned here)."""

    return PostgresWorkpaperCopyStore(db)


def _file_name(engagement: dict, day: datetime) -> str:
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", str(engagement.get("name") or "engagement"))[:FILE_NAME_CHARS]
    return f"{name.strip(' .-_') or 'engagement'} workpaper {day:%Y-%m-%d}.xlsx"


def _attachment(content: bytes, file_name: str, sha256: str) -> Response:
    return Response(
        content=content, media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"', "ETag": f'"{sha256}"',
                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def _audit(request: Request, user: CurrentUser, engagement: dict, event: str, metadata: dict) -> dict:
    return {
        "event_type": event, "org_id": engagement["org_id"], "actor_user_id": user.id, "actor_role": user.role,
        "target_type": "engagement", "target_id": str(engagement["id"]),
        "request_id": getattr(request.state, "request_id", None),
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"), "metadata": metadata,
    }


@router.get("/engagements/{engagement_id}/export")
async def export_workpaper(
    engagement_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> Response:
    """The workpaper as an Excel file (the same numbers the screens show).

    The exact bytes served are kept first (``workpaper_copies``), in this request's transaction with the
    download record and the audit event. If any of that cannot be saved nothing is sent: 503, retry. A
    download is never served without a record of it. Allowed for an archived engagement, as before.
    """

    engagement = await _visible(db, engagement_id, user)
    items = await workpaper_item_service.list_items(db, engagement["id"])
    decisions = {str(i["payload"].get("documentId") or i["item_key"]): i["payload"]
                 for i in items if i["kind"] == "document"}
    service = _service()
    visible = lambda record: can_see(record, user)  # noqa: E731
    engagement = await methodology_gwp.attach_choice(db, engagement)
    recalculation = service.recalculate(engagement, visible, decisions)
    if recalculation.get("gwp_blocked"):  # the workpaper must not state numbers Results does not show
        raise HTTPException(status_code=409, detail=recalculation["gwp_blocked"])
    register = service.evidence_register(str(engagement["id"]), visible)
    settings = get_settings()
    request_id = getattr(request.state, "request_id", None)
    try:
        kept = await workpaper_copy_service.keep_for_download(
            copy_store(db),
            build=lambda: workpaper_export_service.build_workbook_with_fingerprint(
                engagement=engagement, recalculation=recalculation, register=register, items=items,
                exported_by=user.email),
            org_id=str(engagement["org_id"]), engagement_id=str(engagement["id"]),
            file_name=_file_name(engagement, datetime.now(UTC)), app_version=settings.git_sha,
            user_id=user.id, email=user.email, request_id=request_id, max_bytes=settings.workpaper_copy_max_bytes,
        )
        await write_audit_event(db, **_audit(request, user, engagement, "workpaper_exported", {
            "format": "xlsx", "copy_id": str(kept.copy.id), "sha256": kept.copy.sha256,
            "size_bytes": kept.copy.size_bytes, "copy_reused": kept.reused}))
    except workpaper_copy_service.CopyTooLarge as exc:
        logger.error("workpaper too large to keep: engagement %s, %s", engagement["id"], exc)
        raise HTTPException(
            status_code=413,
            detail=f"This workpaper is larger than the {settings.workpaper_copy_max_mb} MB Sustentra keeps for each "
                   "saved copy, so it was not downloaded. Please contact support.") from exc
    except Exception as exc:
        logger.exception("workpaper download refused: copy or audit event not saved (engagement %s)", engagement["id"])
        raise HTTPException(
            status_code=503, headers={"Retry-After": "5"},
            detail="The workpaper could not be saved, so it was not downloaded. Please try again in a moment."
        ) from exc
    return _attachment(kept.content, kept.copy.file_name, kept.copy.sha256)


def _copy_json(copy: CopyRecord) -> dict:
    return {
        "id": str(copy.id), "created_at": copy.created_at.isoformat() if copy.created_at else None,
        "prepared_by": copy.prepared_by_email, "file_name": copy.file_name, "size_bytes": copy.size_bytes,
        "sha256": copy.sha256, "app_version": copy.app_version, "downloads": copy.downloads,
    }


@router.get("/engagements/{engagement_id}/workpaper-copies")
async def list_workpaper_copies(
    engagement_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> dict:
    """The workpapers kept for this engagement, newest first: when, who, size, SHA-256 and how many times
    each was downloaded."""

    engagement = await _visible(db, engagement_id, user)
    copies, total = await copy_store(db).list(str(engagement["id"]), limit=limit, offset=offset)
    return {"items": [_copy_json(c) for c in copies], "total": total, "limit": limit, "offset": offset}


@router.get("/engagements/{engagement_id}/workpaper-copies/{copy_id}/download")
async def download_workpaper_copy(
    engagement_id: str,
    copy_id: str,
    request: Request,
    user: CurrentUser = Depends(s1_reader),
    db: AsyncSession = Depends(get_db_session, scope="function"),
) -> Response:
    """One kept workpaper, byte for byte. Its SHA-256 is checked on the way out: a copy that no longer
    matches is not sent (500, and an error in the log). The download is recorded, with an audit event,
    before anything is sent (503 if that cannot be saved)."""

    engagement = await _visible(db, engagement_id, user)
    try:
        key = uuid.UUID(copy_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such saved workpaper.") from None
    store = copy_store(db)
    try:
        found = await store.read(str(engagement["id"]), key)
    except WorkpaperCopyCorrupt:
        logger.error("kept workpaper %s of engagement %s does not match its SHA-256 or size", key, engagement["id"])
        raise HTTPException(
            status_code=500,
            detail="This saved workpaper no longer matches its checksum, so it was not sent. "
                   "Support has been notified.") from None
    if found is None:
        raise HTTPException(status_code=404, detail="No such saved workpaper.")
    copy, content = found
    try:
        await store.add_download(copy, kind="saved", user_id=user.id, email=user.email,
                                 request_id=getattr(request.state, "request_id", None))
        await write_audit_event(db, **_audit(request, user, engagement, "workpaper_copy_downloaded", {
            "copy_id": str(copy.id), "sha256": copy.sha256, "size_bytes": copy.size_bytes}))
    except Exception as exc:
        logger.exception("saved workpaper download refused: record not saved (copy %s)", key)
        raise HTTPException(
            status_code=503, headers={"Retry-After": "5"},
            detail="The download could not be recorded, so the workpaper was not sent. Please try again in a moment."
        ) from exc
    return _attachment(content, copy.file_name, copy.sha256)


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
    """Choices for the recalculation inputs (grid regions, EPA fuels, vehicle types, GWP sets, data
    points) and the roll-up layout."""

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
        # The emissions roll-up's structure (no values): sources, Steps 1a/1b/2 and the final outputs.
        "rollup_layout": emissions_rollup.rollup_layout(),
    }
