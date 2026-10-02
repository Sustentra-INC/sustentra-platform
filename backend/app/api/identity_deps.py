from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from backend.app.observability import set_request_actor
from backend.app.repositories.identity_repository import IdentityRepository
from backend.app.services.identity_service import IdentityError, IdentityService

_service = IdentityService(repository=IdentityRepository.jsonl())


def get_identity_service() -> IdentityService:
    return _service


def configure_identity_service(service: IdentityService) -> None:
    global _service
    _service = service


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def get_current_actor(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    token = _bearer_token(authorization)
    actor = get_identity_service().resolve_session(token or "")
    if actor is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    set_request_actor(request, actor)
    return actor


def get_optional_actor(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict | None:
    token = _bearer_token(authorization)
    if not token:
        return None
    actor = get_identity_service().resolve_session(token)
    if actor is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    set_request_actor(request, actor)
    return actor


def map_identity_error(exc: IdentityError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


CurrentActor = Depends(get_current_actor)
OptionalActor = Depends(get_optional_actor)
