import { api } from "../../lib/api";

/**
 * Tasks and notifications: work one member of an organisation asks another to do, and the
 * in-app bell that tells them. Calls `/api/v1/orgs/{org_id}/tasks` and `.../notifications`.
 */

export type TaskStatus = "open" | "done" | "cancelled";
export type TaskRelation = "assigned" | "requested";

export interface Task {
  id: string;
  org_id: string;
  engagement_id: string | null;
  engagement_name: string | null;
  title: string;
  note: string | null;
  /** An in-app path ("/?view=review&doc=..."), never a full URL. */
  link: string | null;
  assignee_user_id: string;
  assignee_name: string;
  requested_by_user_id: string;
  requested_by_name: string;
  status: TaskStatus;
  /** YYYY-MM-DD */
  due_date: string | null;
  created_at: string;
  completed_at: string | null;
  completed_by: string | null;
  completed_by_name: string | null;
}

export interface Assignee {
  id: string;
  name: string;
  email: string;
  role: string;
}

export interface AppNotification {
  id: string;
  kind: "task_assigned" | "task_completed";
  task_id: string | null;
  title: string;
  link: string | null;
  read_at: string | null;
  email_status: "pending" | "sent" | "failed";
  created_at: string;
}

export interface NewTask {
  title: string;
  assignee_user_id: string;
  note?: string | null;
  link?: string | null;
  engagement_id?: string | null;
  due_date?: string | null;
}

const base = (orgId: string) => `/orgs/${encodeURIComponent(orgId)}`;

export function listAssignees(orgId: string): Promise<{ items: Assignee[] }> {
  return api(`${base(orgId)}/tasks/assignees`);
}

export function createTask(orgId: string, task: NewTask): Promise<Task> {
  return api(`${base(orgId)}/tasks`, { method: "POST", body: task });
}

export function listMyTasks(
  orgId: string,
  params: { relation: TaskRelation; status?: TaskStatus | "" },
): Promise<{ items: Task[] }> {
  const query = new URLSearchParams({ relation: params.relation });
  if (params.status) query.set("status", params.status);
  return api(`${base(orgId)}/tasks/mine?${query}`);
}

export function completeTask(orgId: string, taskId: string): Promise<Task> {
  return api(`${base(orgId)}/tasks/${encodeURIComponent(taskId)}/done`, { method: "POST" });
}

export function cancelTask(orgId: string, taskId: string): Promise<Task> {
  return api(`${base(orgId)}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
}

export function listNotifications(
  orgId: string,
  params: { limit?: number } = {},
): Promise<{ items: AppNotification[]; unread_count: number }> {
  return api(`${base(orgId)}/notifications?limit=${params.limit ?? 10}`);
}

export function getUnreadCount(orgId: string): Promise<{ unread_count: number }> {
  return api(`${base(orgId)}/notifications/unread-count`);
}

export function markNotificationRead(orgId: string, notificationId: string): Promise<AppNotification> {
  return api(`${base(orgId)}/notifications/${encodeURIComponent(notificationId)}/read`, { method: "POST" });
}

export function markAllNotificationsRead(orgId: string): Promise<{ updated: number }> {
  return api(`${base(orgId)}/notifications/read-all`, { method: "POST" });
}

/** Today as YYYY-MM-DD in the viewer's own time zone (a due date is a calendar day, not an instant). */
export function todayIso(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Open and past its due day. */
export function isOverdue(task: Pick<Task, "status" | "due_date">, today: string = todayIso()): boolean {
  return task.status === "open" && task.due_date !== null && task.due_date < today;
}

/** "3 Dec 2026" for a YYYY-MM-DD, whatever the viewer's time zone. */
export function formatDueDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
