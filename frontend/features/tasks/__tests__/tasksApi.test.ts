import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => [] as { path: string; options?: { method?: string; body?: unknown } }[]);
vi.mock("../../../lib/api", () => ({
  api: vi.fn((path: string, options?: { method?: string; body?: unknown }) => {
    calls.push({ path, options });
    return Promise.resolve({});
  }),
}));

import {
  cancelTask,
  completeTask,
  createTask,
  formatDueDate,
  getUnreadCount,
  isOverdue,
  listAssignees,
  listMyTasks,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  todayIso,
} from "../tasksApi";

beforeEach(() => {
  calls.length = 0;
});

describe("tasks API paths", () => {
  it("calls the org-scoped task and notification routes", async () => {
    await listAssignees("o1");
    await createTask("o1", { title: "Review", assignee_user_id: "u2" });
    await listMyTasks("o1", { relation: "requested", status: "open" });
    await listMyTasks("o1", { relation: "assigned", status: "" });
    await completeTask("o1", "t1");
    await cancelTask("o1", "t1");
    await listNotifications("o1");
    await listNotifications("o1", { limit: 3 });
    await getUnreadCount("o1");
    await markNotificationRead("o1", "n1");
    await markAllNotificationsRead("o1");
    expect(calls.map((c) => `${c.options?.method ?? "GET"} ${c.path}`)).toEqual([
      "GET /orgs/o1/tasks/assignees",
      "POST /orgs/o1/tasks",
      "GET /orgs/o1/tasks/mine?relation=requested&status=open",
      "GET /orgs/o1/tasks/mine?relation=assigned",
      "POST /orgs/o1/tasks/t1/done",
      "POST /orgs/o1/tasks/t1/cancel",
      "GET /orgs/o1/notifications?limit=10",
      "GET /orgs/o1/notifications?limit=3",
      "GET /orgs/o1/notifications/unread-count",
      "POST /orgs/o1/notifications/n1/read",
      "POST /orgs/o1/notifications/read-all",
    ]);
    expect(calls[1].options?.body).toEqual({ title: "Review", assignee_user_id: "u2" });
  });

  it("encodes ids in the path", async () => {
    await completeTask("o/1", "t 1");
    expect(calls[0].path).toBe("/orgs/o%2F1/tasks/t%201/done");
  });
});

describe("due dates", () => {
  it("todayIso is the viewer's calendar day, zero padded", () => {
    expect(todayIso(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });

  it("only an open task past its due day is overdue", () => {
    const today = "2026-12-01";
    expect(isOverdue({ status: "open", due_date: "2026-11-30" }, today)).toBe(true);
    expect(isOverdue({ status: "open", due_date: "2026-12-01" }, today)).toBe(false);
    expect(isOverdue({ status: "open", due_date: null }, today)).toBe(false);
    expect(isOverdue({ status: "done", due_date: "2026-01-01" }, today)).toBe(false);
    expect(isOverdue({ status: "cancelled", due_date: "2026-01-01" }, today)).toBe(false);
  });

  it("formats a date without a time-zone shift", () => {
    expect(formatDueDate("2026-12-03")).toBe("3 Dec 2026");
    expect(formatDueDate("nonsense")).toBe("nonsense");
  });
});
