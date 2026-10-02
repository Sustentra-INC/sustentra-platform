from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.api.identity_deps import CurrentActor, get_identity_service, map_identity_error
from backend.app.services.identity_service import IdentityError

router = APIRouter(prefix="/v1", tags=["audit"])


@router.get("/audit-events")
def list_audit_events(
    actor: dict = CurrentActor,
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    try:
        return get_identity_service().list_audit_events(
            actor,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc
