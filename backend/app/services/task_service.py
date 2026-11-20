"""Tasks and in-app notifications (migrations 0022 + 0023).

A task is work one member of an organization asks another to do ("Debo, please review this line").
Everything runs in the request's DB transaction; ``get_current_user`` has set the RLS scope and every
query also filters on org_id explicitly.

Rules
- Anyone in the org may create a task for any ACTIVE member of the same org (a note to self is allowed).
  An assignee who is not an active member of this org - another org's user, an invited, suspended or
  erased person, or an id that does not exist - is refused the same way (422), so the answer does not
  reveal who exists elsewhere.
- Who sees a task: its assignee, its requester, and the org's admins. Anyone else gets 404.
- Mark done: the assignee or an org admin. Cancel: the requester or an org admin. Only an OPEN task
  can change (409 otherwise), and the row is locked first so two people cannot finish it twice.
- Notifications (the in-app bell) and emails go to the same people:
    assigned  -> the assignee (unless they assigned it to themselves)
    done      -> the requester, plus every active org admin, except the person who completed it.
  A notification row is written in the same transaction as the action; its email is sent AFTER the
  commit (``deliver_task_emails``) and its result recorded in ``notifications.email_status``. An email
  failure is logged and recorded, never raised.
- Emails carry the task title, who, the engagement and an "Open in Sustentra" link - never the note or
  any document content.
- Audit events (DB-003): task_created, task_completed, task_cancelled. Ids only, never text.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.config import get_settings
from ..core.db import set_tenant
from .audit_log import write_audit_event
from .org_user_service import Actor
from .otp_delivery import mask_email

logger = logging.getLogger("sustentra.tasks")

TASK_STATUSES = ("open", "done", "cancelled")
MAX_NOTIFICATION_TITLE = 300

_TASK_NOT_FOUND = HTTPException(status_code=404, detail="Task not found")
_NOTIFICATION_NOT_FOUND = HTTPException(status_code=404, detail="Notification not found")
_NOT_ASSIGNABLE = HTTPException(status_code=422, detail="The assignee must be an active member of this organization")
_NO_ENGAGEMENT = HTTPException(status_code=422, detail="That engagement does not exist in this organization")

__all__ = ["Actor", "PendingEmail", "assignable_members", "cancel_task", "complete_task", "create_task",
           "deliver_task_emails", "list_my_tasks", "list_notifications", "list_org_notifications",
           "list_org_tasks", "mark_all_read", "mark_read", "unread_count"]

_NAME = "NULLIF(TRIM(COALESCE({a}.first_name, '') || ' ' || COALESCE({a}.last_name, '')), '')"
_TASK_SELECT = f"""
    SELECT t.id, t.org_id, t.engagement_id, e.name AS engagement_name, t.title, t.note, t.link,
           t.assignee_user_id, COALESCE({_NAME.format(a='a')}, a.email) AS assignee_name,
           t.requested_by_user_id, COALESCE({_NAME.format(a='r')}, r.email) AS requested_by_name,
           t.status, t.due_date, t.created_at, t.completed_at, t.completed_by,
           COALESCE({_NAME.format(a='c')}, c.email) AS completed_by_name
      FROM tasks t
      JOIN users a ON a.id = t.assignee_user_id
      JOIN users r ON r.id = t.requested_by_user_id
      LEFT JOIN users c ON c.id = t.completed_by
      LEFT JOIN engagements e ON e.id = t.engagement_id
"""


@dataclass(frozen=True)
class PendingEmail:
    """One email to send once the transaction has committed, for one notification row."""

    notification_id: uuid.UUID
    to: str
    template: str  # task_assigned | task_completed
    variables: dict[str, Any]


def _uuid(value: str | uuid.UUID, not_found: HTTPException) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise not_found from None


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _full_link(path: str) -> str:
    return get_settings().public_base_url.rstrip("/") + path


async def _audit(db: AsyncSession, actor: Actor, event: str, org_id: uuid.UUID, task_id: uuid.UUID,
                 metadata: dict[str, Any]) -> None:
    await write_audit_event(
        db, event, org_id=org_id, actor_user_id=actor.user_id, actor_role=actor.role, target_type="task",
        target_id=str(task_id), request_id=actor.request_id, ip_address=actor.ip_address,
        user_agent=actor.user_agent, metadata=metadata,
    )


async def _task_row(db: AsyncSession, org_id: uuid.UUID, task_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
    if lock:  # lock the bare row first: FOR UPDATE cannot be combined with the outer joins below
        locked = (await db.execute(text("SELECT 1 FROM tasks WHERE id = :id AND org_id = :org FOR UPDATE"),
                                   {"id": task_id, "org": org_id})).first()
        if locked is None:
            raise _TASK_NOT_FOUND
    row = (await db.execute(text(_TASK_SELECT + " WHERE t.id = :id AND t.org_id = :org"),
                            {"id": task_id, "org": org_id})).mappings().first()
    if row is None:
        raise _TASK_NOT_FOUND
    return dict(row)


async def _org_slug(db: AsyncSession, org_id: uuid.UUID) -> str:
    return (await db.execute(text("SELECT slug FROM organizations WHERE id = :id"), {"id": org_id})).scalar() or ""


async def _user_name(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    row = (await db.execute(
        text(f"SELECT COALESCE({_NAME.format(a='u')}, u.email) AS name FROM users u WHERE u.id = :id AND u.org_id = :org"),
        {"id": user_id, "org": org_id})).first()
    return row[0] if row else "A teammate"


async def _is_admin(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (await db.execute(
        text("SELECT 1 FROM users WHERE id = :id AND org_id = :org AND role = 'org_admin' AND status = 'active'"),
        {"id": user_id, "org": org_id})).first() is not None


async def _notify(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, kind: str, task_id: uuid.UUID,
                  title: str, link: str | None) -> uuid.UUID:
    return (await db.execute(
        text("INSERT INTO notifications (org_id, user_id, kind, task_id, title, link) "
             "VALUES (:org, :uid, :kind, :task, :title, :link) RETURNING id"),
        {"org": org_id, "uid": user_id, "kind": kind, "task": task_id, "title": _clip(title, MAX_NOTIFICATION_TITLE),
         "link": link},
    )).scalar_one()


def _due_text(due: date | None) -> str:
    return f"{due.day} {due:%b %Y}" if due else ""


# --- members ------------------------------------------------------------------------------------

async def assignable_members(db: AsyncSession, org_id: str) -> list[dict[str, Any]]:
    """The people a task can be assigned to: the org's active members (name, email), by name."""
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    rows = (await db.execute(
        text(f"SELECT u.id, u.email, COALESCE({_NAME.format(a='u')}, u.email) AS name, u.role FROM users u "
             "WHERE u.org_id = :org AND u.status = 'active' ORDER BY lower(COALESCE(u.first_name, u.email)), u.email "
             "LIMIT 500"),
        {"org": oid})).mappings().all()
    return [dict(r) for r in rows]


# --- create -------------------------------------------------------------------------------------

async def create_task(db: AsyncSession, actor: Actor, org_id: str, *, title: str, note: str | None,
                      link: str | None, assignee_user_id: uuid.UUID, engagement_id: uuid.UUID | None,
                      due_date: date | None) -> tuple[dict[str, Any], list[PendingEmail]]:
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    assignee = (await db.execute(
        text("SELECT id, email FROM users WHERE id = :id AND org_id = :org AND status = 'active'"),
        {"id": assignee_user_id, "org": oid})).mappings().first()
    if assignee is None:
        raise _NOT_ASSIGNABLE
    engagement_name = None
    if engagement_id is not None:
        engagement_name = (await db.execute(
            text("SELECT name FROM engagements WHERE id = :id AND org_id = :org"),
            {"id": engagement_id, "org": oid})).scalar()
        if engagement_name is None:
            raise _NO_ENGAGEMENT

    task_id = (await db.execute(
        text("INSERT INTO tasks (org_id, engagement_id, title, note, link, assignee_user_id, requested_by_user_id, "
             "due_date) VALUES (:org, :eng, :title, :note, :link, :assignee, :requester, :due) RETURNING id"),
        {"org": oid, "eng": engagement_id, "title": title, "note": note, "link": link,
         "assignee": assignee_user_id, "requester": actor.user_id, "due": due_date},
    )).scalar_one()
    await _audit(db, actor, "task_created", oid, task_id,
                 {"assignee_user_id": str(assignee_user_id), "engagement_id": str(engagement_id) if engagement_id else None,
                  "has_due_date": due_date is not None})

    emails: list[PendingEmail] = []
    if assignee_user_id != actor.user_id:  # nobody needs telling about a note to self
        requester = await _user_name(db, oid, actor.user_id)
        notification_id = await _notify(db, oid, assignee_user_id, "task_assigned", task_id,
                                        f"{requester} assigned you: {title}", link)
        path = link or f"/org/{await _org_slug(db, oid)}/tasks"
        emails.append(PendingEmail(notification_id, assignee["email"], "task_assigned", {
            "email_subject": f"{requester} assigned you a task: {title}", "title": title,
            "requested_by": requester, "engagement": engagement_name, "due_date": _due_text(due_date),
            "link": _full_link(path)}))
    return await _task_row(db, oid, task_id), emails


# --- read ---------------------------------------------------------------------------------------

async def list_my_tasks(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, *, relation: str,
                        status: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    column = "t.assignee_user_id" if relation == "assigned" else "t.requested_by_user_id"
    rows = (await db.execute(
        text(_TASK_SELECT + f" WHERE t.org_id = :org AND {column} = :uid AND (CAST(:status AS text) IS NULL OR t.status = :status) "
             "ORDER BY (t.status = 'open') DESC, t.due_date ASC NULLS LAST, t.created_at DESC, t.id LIMIT :limit OFFSET :offset"),
        {"org": org_id, "uid": user_id, "status": status, "limit": limit, "offset": offset})).mappings().all()
    return [dict(r) for r in rows]


async def list_org_tasks(db: AsyncSession, org_id: str, *, assignee: uuid.UUID | None, requester: uuid.UUID | None,
                         status: str | None, engagement_id: uuid.UUID | None, limit: int,
                         offset: int) -> tuple[list[dict[str, Any]], int]:
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    where = ("t.org_id = :org AND (CAST(:assignee AS uuid) IS NULL OR t.assignee_user_id = :assignee) "
             "AND (CAST(:requester AS uuid) IS NULL OR t.requested_by_user_id = :requester) "
             "AND (CAST(:status AS text) IS NULL OR t.status = :status) "
             "AND (CAST(:eng AS uuid) IS NULL OR t.engagement_id = :eng)")
    params = {"org": oid, "assignee": assignee, "requester": requester, "status": status, "eng": engagement_id}
    total = (await db.execute(text(f"SELECT count(*) FROM tasks t WHERE {where}"), params)).scalar_one()
    rows = (await db.execute(
        text(_TASK_SELECT + f" WHERE {where} ORDER BY t.created_at DESC, t.id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset})).mappings().all()
    return [dict(r) for r in rows], int(total)


# --- done / cancel ------------------------------------------------------------------------------

async def _visible_locked(db: AsyncSession, actor: Actor, oid: uuid.UUID, task_id: str) -> tuple[dict[str, Any], bool]:
    tid = _uuid(task_id, _TASK_NOT_FOUND)
    task = await _task_row(db, oid, tid, lock=True)
    is_admin = await _is_admin(db, oid, actor.user_id)
    if actor.user_id not in (task["assignee_user_id"], task["requested_by_user_id"]) and not is_admin:
        raise _TASK_NOT_FOUND  # not yours and you are not an admin: it does not exist for you
    return task, is_admin


def _must_be_open(task: dict[str, Any]) -> None:
    if task["status"] != "open":
        raise HTTPException(status_code=409, detail=f"This task is already {task['status']}")


async def complete_task(db: AsyncSession, actor: Actor, org_id: str, task_id: str) -> tuple[dict[str, Any], list[PendingEmail]]:
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    task, is_admin = await _visible_locked(db, actor, oid, task_id)
    if actor.user_id != task["assignee_user_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Only the person it is assigned to, or an admin, can complete a task")
    _must_be_open(task)
    await db.execute(
        text("UPDATE tasks SET status = 'done', completed_at = now(), completed_by = :uid WHERE id = :id"),
        {"uid": actor.user_id, "id": task["id"]})
    await _audit(db, actor, "task_completed", oid, task["id"],
                 {"assignee_user_id": str(task["assignee_user_id"]),
                  "requested_by_user_id": str(task["requested_by_user_id"])})

    # The requester, plus every active admin who is neither the requester nor the person who finished it.
    recipients = (await db.execute(
        text("SELECT id, email FROM users WHERE org_id = :org AND status = 'active' AND id <> :completer "
             "AND (id = :requester OR role = 'org_admin') ORDER BY email"),
        {"org": oid, "completer": actor.user_id, "requester": task["requested_by_user_id"]})).mappings().all()
    completer = await _user_name(db, oid, actor.user_id)
    path = task["link"] or f"/org/{await _org_slug(db, oid)}/tasks"
    emails = []
    for person in recipients:
        notification_id = await _notify(db, oid, person["id"], "task_completed", task["id"],
                                        f"{completer} completed: {task['title']}", task["link"])
        emails.append(PendingEmail(notification_id, person["email"], "task_completed", {
            "email_subject": f"{completer} completed a task: {task['title']}", "title": task["title"],
            "completed_by": completer, "requested_by": task["requested_by_name"],
            "engagement": task["engagement_name"], "link": _full_link(path)}))
    return await _task_row(db, oid, task["id"]), emails


async def cancel_task(db: AsyncSession, actor: Actor, org_id: str, task_id: str) -> dict[str, Any]:
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    task, is_admin = await _visible_locked(db, actor, oid, task_id)
    if actor.user_id != task["requested_by_user_id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Only the person who asked, or an admin, can cancel a task")
    _must_be_open(task)
    await db.execute(
        text("UPDATE tasks SET status = 'cancelled', completed_at = now(), completed_by = :uid WHERE id = :id"),
        {"uid": actor.user_id, "id": task["id"]})
    await _audit(db, actor, "task_cancelled", oid, task["id"], {"assignee_user_id": str(task["assignee_user_id"])})
    return await _task_row(db, oid, task["id"])


# --- email after commit -------------------------------------------------------------------------

async def deliver_task_emails(sessionmaker: async_sessionmaker[AsyncSession], sender: Callable[..., bool],
                              org_id: uuid.UUID, emails: list[PendingEmail]) -> None:
    """Background task: send each email, then record sent / failed on its notification. Never raises."""
    for email in emails:
        try:
            delivered = bool(await asyncio.to_thread(sender, email.template, email.to, email.variables))
        except Exception:  # noqa: BLE001 - an email problem must never break the action it follows
            logger.error("task email failed", extra={"template": email.template, "recipient": mask_email(email.to)})
            delivered = False
        try:
            async with sessionmaker() as session, session.begin():
                await set_tenant(session, org_id)
                await session.execute(
                    text("UPDATE notifications SET email_status = :s WHERE id = :id AND org_id = :org"),
                    {"s": "sent" if delivered else "failed", "id": email.notification_id, "org": org_id})
        except Exception:  # noqa: BLE001
            logger.error("could not record the task email result", extra={"template": email.template})


# --- notifications ------------------------------------------------------------------------------

_NOTIFICATION_SELECT = ("SELECT n.id, n.kind, n.task_id, n.title, n.link, n.read_at, n.email_status, n.created_at "
                        "FROM notifications n")


async def list_notifications(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, *, unread_only: bool,
                             limit: int, offset: int) -> list[dict[str, Any]]:
    rows = (await db.execute(
        text(_NOTIFICATION_SELECT + " WHERE n.org_id = :org AND n.user_id = :uid AND (NOT :unread OR n.read_at IS NULL) "
             "ORDER BY n.created_at DESC, n.id LIMIT :limit OFFSET :offset"),
        {"org": org_id, "uid": user_id, "unread": unread_only, "limit": limit, "offset": offset})).mappings().all()
    return [dict(r) for r in rows]


async def unread_count(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int((await db.execute(
        text("SELECT count(*) FROM notifications WHERE org_id = :org AND user_id = :uid AND read_at IS NULL"),
        {"org": org_id, "uid": user_id})).scalar_one())


async def mark_read(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, notification_id: str) -> dict[str, Any]:
    nid = _uuid(notification_id, _NOTIFICATION_NOT_FOUND)
    row = (await db.execute(
        text("UPDATE notifications SET read_at = COALESCE(read_at, now()) WHERE id = :id AND org_id = :org "
             "AND user_id = :uid RETURNING id"),
        {"id": nid, "org": org_id, "uid": user_id})).first()
    if row is None:
        raise _NOTIFICATION_NOT_FOUND
    return dict((await db.execute(text(_NOTIFICATION_SELECT + " WHERE n.id = :id"), {"id": nid})).mappings().one())


async def mark_all_read(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    result = await db.execute(
        text("UPDATE notifications SET read_at = now() WHERE org_id = :org AND user_id = :uid AND read_at IS NULL"),
        {"org": org_id, "uid": user_id})
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def list_org_notifications(db: AsyncSession, org_id: str, *, user_id: uuid.UUID | None, limit: int,
                                 offset: int) -> tuple[list[dict[str, Any]], int]:
    """Admins: every notification in the company, with who it went to and what happened to its email."""
    oid = _uuid(org_id, HTTPException(status_code=404, detail="Organization not found"))
    where = "n.org_id = :org AND (CAST(:uid AS uuid) IS NULL OR n.user_id = :uid)"
    total = (await db.execute(text(f"SELECT count(*) FROM notifications n WHERE {where}"),
                              {"org": oid, "uid": user_id})).scalar_one()
    rows = (await db.execute(
        text("SELECT n.id, n.kind, n.task_id, n.title, n.link, n.read_at, n.email_status, n.created_at, n.user_id, "
             f"COALESCE({_NAME.format(a='u')}, u.email) AS user_name FROM notifications n JOIN users u ON u.id = n.user_id "
             f"WHERE {where} ORDER BY n.created_at DESC, n.id LIMIT :limit OFFSET :offset"),
        {"org": oid, "uid": user_id, "limit": limit, "offset": offset})).mappings().all()
    return [dict(r) for r in rows], int(total)
