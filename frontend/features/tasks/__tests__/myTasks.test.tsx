/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  tasks: {} as Record<string, unknown[]>,
  fail: false,
  failAction: false,
  calls: [] as string[],
}));
vi.mock("../../../lib/api", () => ({
  api: vi.fn((path: string, options?: { method?: string }) => {
    const key = `${options?.method ?? "GET"} ${path}`;
    mock.calls.push(key);
    if (path.includes("/tasks/mine")) {
      if (mock.fail) return Promise.reject(new Error("x"));
      const relation = new URLSearchParams(path.split("?")[1]).get("relation") ?? "assigned";
      const status = new URLSearchParams(path.split("?")[1]).get("status");
      return Promise.resolve({ items: (mock.tasks[relation] ?? []).filter((t) => !status || (t as { status: string }).status === status) });
    }
    if (options?.method === "POST") {
      return mock.failAction ? Promise.reject(new Error("no")) : Promise.resolve({});
    }
    return Promise.resolve({});
  }),
}));

import { MyTasks } from "../MyTasks";
import type { Task } from "../tasksApi";

const task = (over: Partial<Task> = {}): Task => ({
  id: "t1",
  org_id: "o1",
  engagement_id: "E1",
  engagement_name: "FY25 Footprint",
  title: "Review Rechnung März 電気.pdf",
  note: "Check the totals",
  link: "/?view=review&doc=D1&e=E1",
  assignee_user_id: "me",
  assignee_name: "Me Myself",
  requested_by_user_id: "u2",
  requested_by_name: "Debo Okafor",
  status: "open",
  due_date: null,
  created_at: "2026-11-01T10:00:00Z",
  completed_at: null,
  completed_by: null,
  completed_by_name: null,
  ...over,
});

beforeEach(() => {
  mock.tasks = {
    assigned: [task(), task({ id: "t2", title: "Already finished", status: "done", completed_at: "2026-11-02T10:00:00Z" })],
    requested: [task({ id: "t3", title: "Chase the supplier", assignee_name: "Vivian Reyes", requested_by_name: "Me Myself", link: null, note: null })],
  };
  mock.fail = false;
  mock.failAction = false;
  mock.calls = [];
});
afterEach(cleanup);

describe("My tasks", () => {
  it("lists open tasks assigned to me, with who asked, the engagement and a link", async () => {
    render(<MyTasks orgId="o1" slug="acme" />);
    const link = await screen.findByRole("link", { name: "Review Rechnung März 電気.pdf" });
    expect(link).toHaveAttribute("href", "/?view=review&doc=D1&e=E1");
    expect(screen.getByText("Debo Okafor")).toBeInTheDocument();
    expect(screen.getByText("FY25 Footprint")).toBeInTheDocument();
    expect(screen.getByText("Check the totals")).toBeInTheDocument();
    expect(screen.queryByText("Already finished")).toBeNull(); // open only by default
    expect(mock.calls[0]).toBe("GET /orgs/o1/tasks/mine?relation=assigned&status=open");
  });

  it("marks a task complete, then refreshes the list", async () => {
    render(<MyTasks orgId="o1" slug="acme" />);
    await screen.findByText("Review Rechnung März 電気.pdf");
    mock.tasks.assigned = [];
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Marked complete: Review Rechnung");
    expect(mock.calls).toContain("POST /orgs/o1/tasks/t1/done");
    expect(await screen.findByText("Nothing is assigned to you.")).toBeInTheDocument();
  });

  it("shows done tasks without an action when the filter says so", async () => {
    render(<MyTasks orgId="o1" slug="acme" />);
    await screen.findByText("Review Rechnung März 電気.pdf");
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "done" } });
    const row = (await screen.findByText("Already finished")).closest("tr") as HTMLElement;
    expect(within(row).queryByRole("button")).toBeNull();
    expect(within(row).getByText("Done")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "" } });
    await waitFor(() => expect(screen.getAllByRole("row").length).toBeGreaterThan(2));
  });

  it("switches to the tasks I asked others to do, which can be cancelled", async () => {
    render(<MyTasks orgId="o1" slug="acme" />);
    await screen.findByText("Review Rechnung März 電気.pdf");
    fireEvent.click(screen.getByRole("button", { name: "Requested by me" }));
    expect(await screen.findByText("Chase the supplier")).toBeInTheDocument();
    expect(screen.getByText("Vivian Reyes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark complete" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(mock.calls).toContain("POST /orgs/o1/tasks/t3/cancel"));
  });

  it("highlights an overdue open task with a word, not only a colour", async () => {
    mock.tasks.assigned = [task({ due_date: "2020-01-01" }), task({ id: "t9", title: "Future", due_date: "2999-01-01" })];
    render(<MyTasks orgId="o1" slug="acme" />);
    const row = (await screen.findByText("Review Rechnung März 電気.pdf")).closest("tr") as HTMLElement;
    expect(within(row).getByText(/Overdue/)).toBeInTheDocument();
    expect(within(row).getByText(/1 Jan 2020/)).toBeInTheDocument();
    const future = screen.getByText("Future").closest("tr") as HTMLElement;
    expect(within(future).queryByText(/Overdue/)).toBeNull();
  });

  it("says plainly when it cannot load or an action fails", async () => {
    mock.fail = true;
    const first = render(<MyTasks orgId="o1" slug="acme" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load your tasks/);
    first.unmount();

    mock.fail = false;
    mock.failAction = true;
    render(<MyTasks orgId="o1" slug="acme" />);
    fireEvent.click(await screen.findByRole("button", { name: "Mark complete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/did not go through/);
  });

  it("links back to the org home", async () => {
    render(<MyTasks orgId="o1" slug="acme" />);
    expect(await screen.findByRole("link", { name: /Back/ })).toHaveAttribute("href", "/org/acme");
  });
});
