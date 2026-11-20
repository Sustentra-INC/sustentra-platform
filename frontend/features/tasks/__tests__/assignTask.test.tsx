/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  assignees: [] as unknown[],
  failAssignees: false,
  createError: null as unknown,
  calls: [] as { path: string; method: string; body?: unknown }[],
}));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string; body?: unknown }) => {
    mock.calls.push({ path, method: options?.method ?? "GET", body: options?.body });
    if (path.endsWith("/tasks/assignees")) {
      return mock.failAssignees ? Promise.reject(new Error("x")) : Promise.resolve({ items: mock.assignees });
    }
    if (path.endsWith("/tasks") && options?.method === "POST") {
      return mock.createError ? Promise.reject(mock.createError) : Promise.resolve({ assignee_name: "Vivian Reyes" });
    }
    return Promise.resolve({});
  }),
}));

import { ApiError } from "../../../lib/api";
import { AssignTaskProvider, useAssignTask } from "../AssignTaskContext";

const PEOPLE = [
  { id: "u-debo", name: "Debo Okafor", email: "debo@acme.test", role: "org_member" },
  { id: "u-viv", name: "Vivian Reyes", email: "vivian@acme.test", role: "org_member" },
];

function Opener() {
  const assign = useAssignTask();
  if (!assign) return <p>no assign</p>;
  return (
    <button
      type="button"
      onClick={() =>
        assign({ kind: "Document", label: "Rechnung März 電気.pdf", link: "/?view=review&doc=D1&e=E1", title: "Review Rechnung März 電気.pdf" })
      }
    >
      open
    </button>
  );
}

beforeEach(() => {
  mock.assignees = PEOPLE;
  mock.failAssignees = false;
  mock.createError = null;
  mock.calls = [];
});
afterEach(cleanup);

async function openDialog() {
  render(
    <AssignTaskProvider orgId="o1" engagementId="E1">
      <Opener />
    </AssignTaskProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "open" }));
  return screen.findByRole("dialog", { name: "Assign to…" });
}

describe("Assign to… window", () => {
  it("offers nothing where there is no organisation (the demo site)", () => {
    render(
      <AssignTaskProvider orgId={null} engagementId={null}>
        <Opener />
      </AssignTaskProvider>,
    );
    expect(screen.getByText("no assign")).toBeInTheDocument();
    expect(mock.calls).toHaveLength(0);
  });

  it("names what the task is about and pre-fills the title", async () => {
    const dialog = await openDialog();
    expect(dialog).toHaveTextContent("Rechnung März 電気.pdf");
    expect(screen.getByLabelText("Task")).toHaveValue("Review Rechnung März 電気.pdf");
    expect(await screen.findByRole("option", { name: /Vivian Reyes/ })).toBeInTheDocument();
  });

  it("cannot be submitted without choosing a person", async () => {
    await openDialog();
    await screen.findByRole("option", { name: /Vivian Reyes/ });
    expect(screen.getByRole("button", { name: "Assign" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Assign to"), { target: { value: "u-viv" } });
    expect(screen.getByRole("button", { name: "Assign" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Task"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Assign" })).toBeDisabled();
  });

  it("sends the person, note, due date, link and engagement, then confirms", async () => {
    await openDialog();
    await screen.findByRole("option", { name: /Vivian Reyes/ });
    fireEvent.change(screen.getByLabelText("Assign to"), { target: { value: "u-viv" } });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "  Check the totals  " } });
    fireEvent.change(screen.getByLabelText("Due date (optional)"), { target: { value: "2999-12-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Assigned to Vivian Reyes");
    const post = mock.calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/orgs/o1/tasks");
    expect(post?.body).toEqual({
      title: "Review Rechnung März 電気.pdf",
      assignee_user_id: "u-viv",
      note: "Check the totals",
      link: "/?view=review&doc=D1&e=E1",
      engagement_id: "E1",
      due_date: "2999-12-01",
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("sends no note or due date when they are left empty", async () => {
    await openDialog();
    await screen.findByRole("option", { name: /Debo Okafor/ });
    fireEvent.change(screen.getByLabelText("Assign to"), { target: { value: "u-debo" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await screen.findByRole("status");
    const body = mock.calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
    expect(body.note).toBeNull();
    expect(body.due_date).toBeNull();
  });

  it("says what to do when the rate limit or the server refuses, and keeps the window open", async () => {
    await openDialog();
    await screen.findByRole("option", { name: /Vivian Reyes/ });
    fireEvent.change(screen.getByLabelText("Assign to"), { target: { value: "u-viv" } });

    mock.createError = new ApiError(429, "Too many", null, null);
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/a lot of tasks/);

    mock.createError = new ApiError(422, "no", null, null);
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/cannot be assigned/));

    mock.createError = new Error("down");
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Nothing was sent/));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("says when the people could not be loaded", async () => {
    mock.failAssignees = true;
    await openDialog();
    expect(await screen.findByRole("option", { name: "Could not load people" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign" })).toBeDisabled();
  });

  it("closes with Cancel, the cross and Escape", async () => {
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "open" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("never promises the note goes out by email", async () => {
    const dialog = await openDialog();
    expect(dialog).toHaveTextContent(/never includes your note or document contents/);
  });
});
