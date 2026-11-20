"""Tasks and notifications, at /api/v1/orgs/{org_id}/tasks and /api/v1/orgs/{org_id}/notifications.

Any signed-in user of the org (another org's id -> 404) can create a task for an active member, see
the tasks assigned to or requested by them, complete a task assigned to them and read their own
notifications. Org admins also see every task and notification of the company (provider admins may
read them too, but have no tasks or notifications of their own). Rules: services/task_service.py.

No `from __future__ import annotations`: FastAPI resolves these annotations at runtime, and slowapi
wraps the create endpoint.
"""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...core.db import get_db_session, get_sessionmaker_dependency
from ...core.rate_limit import session_rate_limit
from ...services import task_service as tasks
from ...services.otp_delivery import TaskEmailSender, get_task_email_sender
from .deps import Principal, require_org_admin, require_org_member
from .task_targets import TargetKind, resolve_link

router = APIRouter(prefix="/orgs/{org_id}/tasks", tags=["org-tasks"])
notifications_router = APIRouter(prefix="/orgs/{org_id}/notifications", tags=["org-notifications"])

Member = Annotated[Principal, Depends(require_org_member)]
OrgAdmin = Annotated[Principal, Depends(require_org_admin)]
Db = Annotated[AsyncSession, Depends(get_db_session, scope="function")]
Sessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker_dependency)]
Sender = Annotated[TaskEmailSender, Depends(get_task_email_sender)]
TaskStatus = Literal["open", "done", "cancelled"]


class TaskTarget(BaseModel):
    """What the task is about. The server checks it exists and builds the link; the client sends no link."""

    model_config = ConfigDict(extra="forbid")

    kind: TargetKind
    # document id, line key or methodology field id; not used for the engagement itself.
    item_id: str | None = Field(default=None, min_length=1, max_length=300)


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    assignee_user_id: UUID
    engagement_id: UUID | None = None
    target: TaskTarget | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _target_needs_engagement(self) -> "CreateTaskRequest":
        if self.target is not None:
            if self.engagement_id is None:
                raise ValueError("a target needs an engagement_id")
            if self.target.kind != "engagement" and not self.target.item_id:
                raise ValueError("this kind of target needs an item_id")
        return self

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())  # one line: it ends up in an email subject
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class TaskResponse(BaseModel):
    id: UUID
    org_id: UUID
    engagement_id: UUID | None
    engagement_name: str | None
    title: str
    note: str | None
    link: str | None
    assignee_user_id: UUID
    assignee_name: str
    requested_by_user_id: UUID
    requested_by_name: str
    status: str
    due_date: date | None
    created_at: datetime
    completed_at: datetime | None
    completed_by: UUID | None
    completed_by_name: str | None


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int | None = None


class AssigneeResponse(BaseModel):
    id: UUID
    name: str
    email: str
    role: str


class AssigneeListResponse(BaseModel):
    items: list[AssigneeResponse]


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    task_id: UUID | None
    title: str
    link: str | None
    read_at: datetime | None
    email_status: str
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkAllReadResponse(BaseModel):
    updated: int


class OrgNotificationResponse(NotificationResponse):
    user_id: UUID
    user_name: str


class OrgNotificationListResponse(BaseModel):
    items: list[OrgNotificationResponse]
    total: int


def _actor(principal: Principal, request: Request) -> tasks.Actor:
    return tasks.Actor(
        user_id=principal.id,
        role=principal.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def _person(principal: Principal, org_id: str) -> UUID:
    """The org this person belongs to. Provider admins belong to none: they have no tasks of their own."""
    if principal.is_provider or principal.org_id is None:
        raise HTTPException(status_code=403, detail="Platform admins do not have tasks or notifications")
    return UUID(str(principal.org_id))


# --- tasks --------------------------------------------------------------------------------------

@router.get("/assignees", response_model=AssigneeListResponse)
async def list_assignees(org_id: str, principal: Member, db: Db) -> AssigneeListResponse:
    """Who a task can be assigned to: the org's active members."""
    return AssigneeListResponse(items=[AssigneeResponse(**m) for m in await tasks.assignable_members(db, org_id)])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    org_id: str,
    payload: CreateTaskRequest,
    principal: Member,
    db: Db,
    request: Request,
    background: BackgroundTasks,
    sessions: Sessions,
    send_email: Sender,
) -> TaskResponse:
    _person(principal, org_id)
    link = None
    if payload.target is not None and payload.engagement_id is not None:
        link = await resolve_link(db, principal, str(payload.engagement_id), payload.target.kind, payload.target.item_id)
    row, emails = await tasks.create_task(
        db, _actor(principal, request), org_id, title=payload.title, note=payload.note, link=link,
        assignee_user_id=payload.assignee_user_id, engagement_id=payload.engagement_id, due_date=payload.due_date,
    )
    if emails:  # after the response = after the commit
        background.add_task(tasks.deliver_task_emails, sessions, send_email, UUID(str(row["org_id"])), emails)
    return TaskResponse(**row)


@router.get("/mine", response_model=TaskListResponse)
async def list_my_tasks(
    org_id: str,
    principal: Member,
    db: Db,
    relation: Annotated[Literal["assigned", "requested"], Query(description="assigned to me, or requested by me")] = "assigned",
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> TaskListResponse:
    org = _person(principal, org_id)
    rows = await tasks.list_my_tasks(db, org, principal.id, relation=relation, status=task_status, limit=limit, offset=offset)
    return TaskListResponse(items=[TaskResponse(**r) for r in rows])


@router.get("", response_model=TaskListResponse)
async def list_org_tasks(
    org_id: str,
    principal: OrgAdmin,
    db: Db,
    assignee_user_id: Annotated[UUID | None, Query()] = None,
    requested_by_user_id: Annotated[UUID | None, Query()] = None,
    engagement_id: Annotated[UUID | None, Query()] = None,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> TaskListResponse:
    """Every task in the company (org admins; provider admins read-only)."""
    rows, total = await tasks.list_org_tasks(
        db, org_id, assignee=assignee_user_id, requester=requested_by_user_id, status=task_status,
        engagement_id=engagement_id, limit=limit, offset=offset)
    return TaskListResponse(items=[TaskResponse(**r) for r in rows], total=total)


@router.post("/{task_id}/done", response_model=TaskResponse)
async def mark_done(
    org_id: str,
    task_id: str,
    principal: Member,
    db: Db,
    request: Request,
    background: BackgroundTasks,
    sessions: Sessions,
    send_email: Sender,
) -> TaskResponse:
    _person(principal, org_id)
    row, emails = await tasks.complete_task(db, _actor(principal, request), org_id, task_id)
    if emails:
        background.add_task(tasks.deliver_task_emails, sessions, send_email, UUID(str(row["org_id"])), emails)
    return TaskResponse(**row)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel(org_id: str, task_id: str, principal: Member, db: Db, request: Request) -> TaskResponse:
    _person(principal, org_id)
    return TaskResponse(**await tasks.cancel_task(db, _actor(principal, request), org_id, task_id))


# --- notifications ------------------------------------------------------------------------------

@notifications_router.get("", response_model=NotificationListResponse)
async def list_notifications(
    org_id: str,
    principal: Member,
    db: Db,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> NotificationListResponse:
    """My notifications, newest first, with the unread count for the bell."""
    org = _person(principal, org_id)
    rows = await tasks.list_notifications(db, org, principal.id, unread_only=unread_only, limit=limit, offset=offset)
    return NotificationListResponse(
        items=[NotificationResponse(**r) for r in rows], unread_count=await tasks.unread_count(db, org, principal.id))


@notifications_router.get("/unread-count", response_model=UnreadCountResponse)
@session_rate_limit
async def get_unread_count(org_id: str, principal: Member, db: Db, request: Request, response: Response) -> UnreadCountResponse:
    """Polled by the bell every minute."""
    return UnreadCountResponse(unread_count=await tasks.unread_count(db, _person(principal, org_id), principal.id))


@notifications_router.post("/read-all", response_model=MarkAllReadResponse)
async def read_all(org_id: str, principal: Member, db: Db) -> MarkAllReadResponse:
    return MarkAllReadResponse(updated=await tasks.mark_all_read(db, _person(principal, org_id), principal.id))


@notifications_router.get("/org", response_model=OrgNotificationListResponse)
async def list_org_notifications(
    org_id: str,
    principal: OrgAdmin,
    db: Db,
    user_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> OrgNotificationListResponse:
    """Every notification in the company, with who got it and what happened to its email (org admins)."""
    rows, total = await tasks.list_org_notifications(db, org_id, user_id=user_id, limit=limit, offset=offset)
    return OrgNotificationListResponse(items=[OrgNotificationResponse(**r) for r in rows], total=total)


@notifications_router.post("/{notification_id}/read", response_model=NotificationResponse)
async def read_one(org_id: str, notification_id: str, principal: Member, db: Db) -> NotificationResponse:
    org = _person(principal, org_id)
    return NotificationResponse(**await tasks.mark_read(db, org, principal.id, notification_id))
