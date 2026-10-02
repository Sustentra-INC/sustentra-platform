from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.api.identity_deps import CurrentActor, OptionalActor, get_identity_service, map_identity_error
from backend.app.services.identity_service import IdentityError

router = APIRouter(prefix="/v1", tags=["sustentra-users"])


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = Field(default="operator")


@router.post("/users")
def create_user(payload: CreateUserRequest, actor: dict | None = OptionalActor) -> dict:
    try:
        return get_identity_service().create_sustentra_user(
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            actor=actor,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.get("/users")
def list_users(actor: dict = CurrentActor) -> list[dict]:
    try:
        return get_identity_service().list_sustentra_users(actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.get("/users/{user_id}")
def get_user(user_id: str, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().get_sustentra_user(user_id, actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc
