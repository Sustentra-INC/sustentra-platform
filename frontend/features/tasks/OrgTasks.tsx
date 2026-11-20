"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import styles from "../admin/admin.module.css";
import { listOrgUsers, type OrgUser } from "../admin/orgApi";
import { listEngagements, type BackendEngagement } from "../s1/api/engagements";
import {
  formatDueDate,
  isOverdue,
  listOrgNotifications,
  listOrgTasks,
  type OrgNotification,
  type Task,
  type TaskStatus,
} from "./tasksApi";

const STATUS_WORDS: Record<TaskStatus, string> = { open: "Open", done: "Done", cancelled: "Cancelled" };
const EMAIL_WORDS: Record<string, string> = { sent: "Email sent", failed: "Email failed", pending: "Email not sent yet" };

type PersonRole = "assignee" | "requester";

function personName(user: OrgUser): string {
  const name = `${user.first_name} ${user.last_name}`.trim();
  return name || user.email;
}

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * Org admin › Tasks: every task and notification in the company. Tasks filter by person (as the person
 * assigned or the person who asked), status and engagement; an open task past its due day is shown
 * as overdue. The Notifications tab shows who was told what, and whether the email reached the mail system.
 */
export function OrgTasks({ orgId, slug }: { orgId: string; slug: string }) {
  const [tab, setTab] = useState<"tasks" | "notifications">("tasks");
  const [people, setPeople] = useState<OrgUser[]>([]);
  const [engagements, setEngagements] = useState<BackendEngagement[]>([]);
  const [person, setPerson] = useState("");
  const [personRole, setPersonRole] = useState<PersonRole>("assignee");
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [engagementId, setEngagementId] = useState("");

  useEffect(() => {
    let active = true;
    listOrgUsers(orgId)
      .then((result) => active && setPeople(result.items))
      .catch(() => {
        // The filters just stay empty; the list below still works.
      });
    listEngagements()
      .then((items) => active && setEngagements(items))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [orgId]);

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <Link className={styles.crumbLink} href={`/org/${slug}`}>
          ← Back
        </Link>
      </div>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Tasks</h1>
          <p className={styles.subtitle}>Every task and notification in this organization.</p>
        </div>
      </div>

      <div className={styles.toolbar}>
        <button
          type="button"
          className={`${styles.button} ${tab === "tasks" ? "" : styles.ghost}`}
          aria-pressed={tab === "tasks"}
          onClick={() => setTab("tasks")}
        >
          Tasks
        </button>
        <button
          type="button"
          className={`${styles.button} ${tab === "notifications" ? "" : styles.ghost}`}
          aria-pressed={tab === "notifications"}
          onClick={() => setTab("notifications")}
        >
          Notifications
        </button>
      </div>

      <div className={styles.toolbar}>
        <select className={styles.select} value={person} onChange={(e) => setPerson(e.target.value)} aria-label="Person">
          <option value="">Everyone</option>
          {people.map((user) => (
            <option key={user.id} value={user.id}>
              {personName(user)}
            </option>
          ))}
        </select>
        {tab === "tasks" ? (
          <>
            <select
              className={styles.select}
              value={personRole}
              onChange={(e) => setPersonRole(e.target.value as PersonRole)}
              aria-label="Person is the"
            >
              <option value="assignee">Assigned to them</option>
              <option value="requester">Requested by them</option>
            </select>
            <select
              className={styles.select}
              value={status}
              onChange={(e) => setStatus(e.target.value as TaskStatus | "")}
              aria-label="Status"
            >
              <option value="">Any status</option>
              <option value="open">Open</option>
              <option value="done">Done</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <select
              className={styles.select}
              value={engagementId}
              onChange={(e) => setEngagementId(e.target.value)}
              aria-label="Engagement"
            >
              <option value="">All engagements</option>
              {engagements.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.client_name ? `${e.client_name} · ${e.name}` : e.name}
                </option>
              ))}
            </select>
          </>
        ) : null}
      </div>

      {tab === "tasks" ? (
        <TaskTable
          orgId={orgId}
          assignee={personRole === "assignee" ? person : ""}
          requester={personRole === "requester" ? person : ""}
          status={status}
          engagementId={engagementId}
        />
      ) : (
        <NotificationTable orgId={orgId} userId={person} />
      )}
    </div>
  );
}

function TaskTable({
  orgId,
  assignee,
  requester,
  status,
  engagementId,
}: {
  orgId: string;
  assignee: string;
  requester: string;
  status: TaskStatus | "";
  engagementId: string;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestKey = JSON.stringify([orgId, assignee, requester, status, engagementId]);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    listOrgTasks(orgId, { assignee, requester, status, engagementId })
      .then((result) => {
        if (!active) return;
        setTasks(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch(() => active && setError("Could not load tasks."))
      .finally(() => active && setLoadedKey(requestKey));
    return () => {
      active = false;
    };
    // requestKey captures every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const result = await listOrgTasks(orgId, { assignee, requester, status, engagementId, offset: tasks.length });
      setTasks((all) => [...all, ...result.items]);
      setTotal(result.total);
    } catch {
      setError("Could not load more tasks.");
    } finally {
      setLoadingMore(false);
    }
  }

  const overdueCount = tasks.filter((task) => isOverdue(task)).length;

  return (
    <>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {!loading && tasks.length > 0 ? (
        <p className={styles.muted}>
          {total} {total === 1 ? "task" : "tasks"}
          {overdueCount > 0 ? <span className={styles.overdue}> · {overdueCount} overdue</span> : null}
        </p>
      ) : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Task</th>
              <th>Assigned to</th>
              <th>Requested by</th>
              <th>Engagement</th>
              <th>Due</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : tasks.length === 0 ? (
              <tr>
                <td colSpan={6} className={styles.muted}>
                  No tasks match.
                </td>
              </tr>
            ) : (
              tasks.map((task) => {
                const overdue = isOverdue(task);
                return (
                  <tr key={task.id} className={overdue ? styles.overdueRow : undefined} data-overdue={overdue || undefined}>
                    <td>
                      {task.link ? <a href={task.link}>{task.title}</a> : task.title}
                      {task.note ? <div className={styles.muted}>{task.note}</div> : null}
                    </td>
                    <td>{task.assignee_name}</td>
                    <td>{task.requested_by_name}</td>
                    <td className={styles.muted}>{task.engagement_name ?? "—"}</td>
                    <td className={styles.muted}>
                      {task.due_date ? formatDueDate(task.due_date) : "—"}
                      {overdue ? <span className={styles.overdue}> · Overdue</span> : null}
                    </td>
                    <td>
                      {STATUS_WORDS[task.status]}
                      {task.status === "done" && task.completed_by_name ? (
                        <div className={styles.muted}>by {task.completed_by_name}</div>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {!loading && tasks.length < total ? (
        <div className={styles.toolbar}>
          <button type="button" className={styles.button} onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      ) : null}
    </>
  );
}

function NotificationTable({ orgId, userId }: { orgId: string; userId: string }) {
  const [items, setItems] = useState<OrgNotification[]>([]);
  const [total, setTotal] = useState(0);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestKey = JSON.stringify([orgId, userId]);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    listOrgNotifications(orgId, { userId })
      .then((result) => {
        if (!active) return;
        setItems(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch(() => active && setError("Could not load notifications."))
      .finally(() => active && setLoadedKey(requestKey));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const result = await listOrgNotifications(orgId, { userId, offset: items.length });
      setItems((all) => [...all, ...result.items]);
      setTotal(result.total);
    } catch {
      setError("Could not load more notifications.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>When</th>
              <th>Sent to</th>
              <th>Notification</th>
              <th>Email</th>
              <th>Read</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className={styles.muted}>
                  No notifications yet.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id}>
                  <td className={styles.muted}>{when(item.created_at)}</td>
                  <td>{item.user_name}</td>
                  <td>{item.link ? <a href={item.link}>{item.title}</a> : item.title}</td>
                  <td className={item.email_status === "failed" ? styles.overdue : styles.muted}>
                    {EMAIL_WORDS[item.email_status] ?? item.email_status}
                  </td>
                  <td className={styles.muted}>{item.read_at ? "Read" : "Unread"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {!loading && items.length < total ? (
        <div className={styles.toolbar}>
          <button type="button" className={styles.button} onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      ) : null}
    </>
  );
}
