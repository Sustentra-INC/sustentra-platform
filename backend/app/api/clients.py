from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.api.identity_deps import CurrentActor, get_identity_service, map_identity_error
from backend.app.services.identity_service import IdentityError

router = APIRouter(prefix="/v1", tags=["sustentra-clients"])


class CreateClientRequest(BaseModel):
    name: str
    code: str
    contact_email: str | None = None
    notes: str | None = None


class UpdateClientRequest(BaseModel):
    name: str | None = None
    code: str | None = None
    contact_email: str | None = None
    notes: str | None = None
    status: str | None = None


class CreateClientUserRequest(BaseModel):
    username: str
    email: str
    password: str


class UpdateClientUserRequest(BaseModel):
    email: str | None = None
    status: str | None = None
    password: str | None = None


@router.post("/clients")
def create_client(payload: CreateClientRequest, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().create_client(
            name=payload.name,
            code=payload.code,
            contact_email=payload.contact_email,
            notes=payload.notes,
            actor=actor,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.get("/clients")
def list_clients(actor: dict = CurrentActor) -> list[dict]:
    try:
        return get_identity_service().list_clients(actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.get("/clients/{client_id}")
def get_client(client_id: str, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().get_client(client_id, actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.patch("/clients/{client_id}")
def update_client(client_id: str, payload: UpdateClientRequest, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().update_client(
            client_id,
            actor,
            name=payload.name,
            code=payload.code,
            contact_email=payload.contact_email,
            notes=payload.notes,
            status=payload.status,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.delete("/clients/{client_id}")
def delete_client(client_id: str, actor: dict = CurrentActor) -> dict:
    try:
        return get_identity_service().delete_client(client_id, actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.post("/clients/{client_id}/users")
def create_client_user(
    client_id: str, payload: CreateClientUserRequest, actor: dict = CurrentActor
) -> dict:
    try:
        return get_identity_service().create_client_user(
            client_id=client_id,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            actor=actor,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.get("/clients/{client_id}/users")
def list_client_users(client_id: str, actor: dict = CurrentActor) -> list[dict]:
    try:
        return get_identity_service().list_client_users(client_id, actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.patch("/clients/{client_id}/users/{client_user_id}")
def update_client_user(
    client_id: str,
    client_user_id: str,
    payload: UpdateClientUserRequest,
    actor: dict = CurrentActor,
) -> dict:
    try:
        return get_identity_service().update_client_user(
            client_id,
            client_user_id,
            actor,
            email=payload.email,
            status=payload.status,
            password=payload.password,
        )
    except IdentityError as exc:
        raise map_identity_error(exc) from exc


@router.delete("/clients/{client_id}/users/{client_user_id}")
def delete_client_user(
    client_id: str, client_user_id: str, actor: dict = CurrentActor
) -> dict:
    try:
        return get_identity_service().delete_client_user(client_id, client_user_id, actor)
    except IdentityError as exc:
        raise map_identity_error(exc) from exc
