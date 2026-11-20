/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  tasks: [] as unknown[],
  total: null as number | null,
  notifications: [] as unknown[],
  failTasks: false,
  calls: [] as string[],
}));
vi.mock("../../../lib/api", () => ({
  api: vi.fn((path: string) => {
    mock.calls.push(path);
    if (path.startsWith("/orgs/o1/users")) {
      return Promise.resolve({
        items: [
          { id: "u-debo", email: "debo@acme.test", first_name: "Debo", last_name: "Okafor", role: "org_member", status: "active" },
          { id: "u-gone", email: "gone@acme.test", first_name: "", last_name: "", role: "org_member", status: "suspended" },
        ],
        total: 2, max_users: 5, seats_used: 2,
      });
    }
    if (path === "/engagements") {
      return Promise.resolve({ items: [{ id: "E1", name: "FY25 Footprint", client_name: "Acme Foods" }, { id: "E2", name: "FY24", client_name: null }] });
    }
    if (path.startsWith("/orgs/o1/tasks?")) {
      if (mock.failTasks) return Promise.reject(new Error("x"));
      const offset = Number(new URLSearchParams(path.split("?")[1]).get("offset") ?? 0);
      const items = mock.tasks.slice(offset, offset + 2);
      return Promise.resolve({ items, total: mock.total ?? mock.tasks.length });
    }
    if (path.startsWith("/orgs/o1/notifications/org?")) {
      return Promise.resolve({ items: mock.notifications, total: mock.notifications.length });
    }
    return Promise.resolve({});
  }),
}));

import { OrgTasks } from "../OrgTasks";
import type { Task } from "../tasksApi";

const task = (over: Partial<Task> = {}): Task => ({
  id: "t1",
  org_id: "o1",
  engagement_id: "E1",
  engagement_name: "FY25 Footprint",
  title: "Review Rechnung März 電気.pdf",
  note: null,
  link: "/?view=review&doc=D1&e=E1",
  assignee_user_id: "u-debo",
  assignee_name: "Debo Okafor",
  requested_by_user_id: "u-ann",
  requested_by_name: "Ann Admin",
  status: "open",
  due_date: null,
  created_at: "2026-11-01T10:00:00Z",
  completed_at: null,
  completed_by: null,
  completed_by_name: null,
  ...over,
});

const lastTasksCall = () => mock.calls.filter((c) => c.startsWith("/orgs/o1/tasks?")).at(-1) ?? "";

beforeEach(() => {
  mock.tasks = [
    task(),
    task({ id: "t2", title: "Late one", due_date: "2020-01-01", assignee_name: "Vivian Reyes" }),
  ];
  mock.total = null;
  mock.notifications = [];
  mock.failTasks = false;
  mock.calls = [];
});
afterEach(cleanup);

describe("Org admin > Tasks", () => {
  it("lists every task with who, engagement, due date and status", async () => {
    render(<OrgTasks orgId="o1" slug="acme" />);
    expect(await screen.findByRole("link", { name: "Review Rechnung März 電気.pdf" })).toHaveAttribute("href", "/?view=review&doc=D1&e=E1");
    const row = screen.getByText("Review Rechnung März 電気.pdf").closest("tr") as HTMLElement;
    expect(within(row).getByText("Debo Okafor")).toBeInTheDocument();
    expect(within(row).getByText("Ann Admin")).toBeInTheDocument();
    expect(within(row).getByText("FY25 Footprint")).toBeInTheDocument();
    expect(within(row).getByText("Open")).toBeInTheDocument();
    expect(screen.getByText(/2 tasks/)).toBeInTheDocument();
    expect(lastTasksCall()).toBe("/orgs/o1/tasks?limit=100");
  });

  it("highlights an overdue open task, in words as well as colour, and counts them", async () => {
    render(<OrgTasks orgId="o1" slug="acme" />);
    const late = (await screen.findByText("Late one")).closest("tr") as HTMLElement;
    expect(late).toHaveAttribute("data-overdue", "true");
    expect(within(late).getByText(/Overdue/)).toBeInTheDocument();
    expect(screen.getByText(/1 overdue/)).toBeInTheDocument();
    const fine = screen.getByText("Review Rechnung März 電気.pdf").closest("tr") as HTMLElement;
    expect(fine).not.toHaveAttribute("data-overdue");
  });

  it("does not call a done or cancelled task overdue", async () => {
    mock.tasks = [task({ id: "t3", title: "Old but done", status: "done", due_date: "2020-01-01", completed_by_name: "Debo Okafor" })];
    render(<OrgTasks orgId="o1" slug="acme" />);
    const row = (await screen.findByText("Old but done")).closest("tr") as HTMLElement;
    expect(within(row).queryByText(/Overdue/)).toBeNull();
    expect(within(row).getByText("by Debo Okafor")).toBeInTheDocument();
  });

  it("filters by person (as assignee or requester), status and engagement", async () => {
    render(<OrgTasks orgId="o1" slug="acme" />);
    await screen.findByText("Late one");
    await screen.findByRole("option", { name: "Debo Okafor" });
    expect(screen.getByRole("option", { name: "gone@acme.test" })).toBeInTheDocument(); // no name: shows the email

    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "u-debo" } });
    await waitFor(() => expect(lastTasksCall()).toContain("assignee_user_id=u-debo"));
    expect(lastTasksCall()).not.toContain("requested_by_user_id");

    fireEvent.change(screen.getByLabelText("Person is the"), { target: { value: "requester" } });
    await waitFor(() => expect(lastTasksCall()).toContain("requested_by_user_id=u-debo"));
    expect(lastTasksCall()).not.toContain("assignee_user_id");

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "open" } });
    await waitFor(() => expect(lastTasksCall()).toContain("status=open"));

    await screen.findByRole("option", { name: "Acme Foods · FY25 Footprint" });
    expect(screen.getByRole("option", { name: "FY24" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Engagement"), { target: { value: "E1" } });
    await waitFor(() => expect(lastTasksCall()).toContain("engagement_id=E1"));
  });

  it("loads more when there are more than one page", async () => {
    mock.tasks = [task({ id: "a", title: "A" }), task({ id: "b", title: "B" }), task({ id: "c", title: "C" })];
    render(<OrgTasks orgId="o1" slug="acme" />);
    await screen.findByText("A");
    expect(screen.queryByText("C")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("C")).toBeInTheDocument();
    expect(lastTasksCall()).toContain("offset=2");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("says when nothing matches, and when it cannot load", async () => {
    mock.tasks = [];
    const first = render(<OrgTasks orgId="o1" slug="acme" />);
    expect(await screen.findByText("No tasks match.")).toBeInTheDocument();
    first.unmount();

    mock.failTasks = true;
    render(<OrgTasks orgId="o1" slug="acme" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load tasks.");
  });

  it("still lists tasks when the people and engagements cannot be loaded", async () => {
    const { api } = await import("../../../lib/api");
    const original = vi.mocked(api).getMockImplementation();
    vi.mocked(api).mockImplementation((path: string) => {
      if (path.startsWith("/orgs/o1/tasks?")) return Promise.resolve({ items: [task()], total: 1 });
      return Promise.reject(new Error("down"));
    });
    try {
      render(<OrgTasks orgId="o1" slug="acme" />);
      expect(await screen.findByText("Review Rechnung März 電気.pdf")).toBeInTheDocument();
    } finally {
      if (original) vi.mocked(api).mockImplementation(original);
    }
  });

  it("shows every notification with who got it and whether the email went", async () => {
    mock.notifications = [
      { id: "n1", kind: "task_assigned", task_id: "t1", title: "Ann assigned you: Review", link: "/?view=dashboard", read_at: null, email_status: "failed", created_at: "2026-11-02T10:00:00Z", user_id: "u-debo", user_name: "Debo Okafor" },
      { id: "n2", kind: "task_completed", task_id: "t1", title: "Debo completed: Review", link: null, read_at: "2026-11-03T10:00:00Z", email_status: "sent", created_at: "2026-11-03T09:00:00Z", user_id: "u-ann", user_name: "Ann Admin" },
    ];
    render(<OrgTasks orgId="o1" slug="acme" />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    const failed = (await screen.findByText("Ann assigned you: Review")).closest("tr") as HTMLElement;
    expect(within(failed).getByText("Debo Okafor")).toBeInTheDocument();
    expect(within(failed).getByText("Email failed")).toBeInTheDocument();
    expect(within(failed).getByText("Unread")).toBeInTheDocument();
    const sent = screen.getByText("Debo completed: Review").closest("tr") as HTMLElement;
    expect(within(sent).getByText("Email sent")).toBeInTheDocument();
    expect(within(sent).getByText("Read")).toBeInTheDocument();
    // The task-only filters are not offered here, the person filter is.
    expect(screen.queryByLabelText("Status")).toBeNull();
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "u-debo" } });
    await waitFor(() => expect(mock.calls.at(-1)).toContain("user_id=u-debo"));
  });

  it("links back to the org home", async () => {
    render(<OrgTasks orgId="o1" slug="acme" />);
    expect(await screen.findByRole("link", { name: /Back/ })).toHaveAttribute("href", "/org/acme");
  });
});
