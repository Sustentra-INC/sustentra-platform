/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({
  unread: 2,
  list: [] as unknown[],
  failCount: false,
  failList: false,
  calls: [] as string[],
}));
vi.mock("../../../lib/api", () => ({
  api: vi.fn((path: string, options?: { method?: string }) => {
    const key = `${options?.method ?? "GET"} ${path}`;
    mock.calls.push(key);
    if (path.endsWith("/unread-count")) {
      return mock.failCount ? Promise.reject(new Error("offline")) : Promise.resolve({ unread_count: mock.unread });
    }
    if (path.includes("/notifications?")) {
      return mock.failList ? Promise.reject(new Error("boom")) : Promise.resolve({ items: mock.list, unread_count: mock.unread });
    }
    if (path.endsWith("/read-all")) return Promise.resolve({ updated: 2 });
    return Promise.resolve({});
  }),
}));

import { NotificationBell, POLL_MS } from "../NotificationBell";

const N1 = {
  id: "n1",
  kind: "task_assigned",
  task_id: "t1",
  title: "Debo Okafor assigned you: Review Rechnung März 電気.pdf",
  link: "/?view=review&doc=D1&e=E1",
  read_at: null,
  email_status: "sent",
  created_at: new Date().toISOString(),
};
const N2 = { ...N1, id: "n2", title: "Vivian completed: Chase supplier", link: null, read_at: "2026-11-20T10:00:00Z" };

beforeEach(() => {
  mock.unread = 2;
  mock.list = [N1, N2];
  mock.failCount = false;
  mock.failList = false;
  mock.calls = [];
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("notification bell", () => {
  it("shows the unread count on the bell", async () => {
    render(<NotificationBell orgId="o1" tasksHref="/org/acme/tasks" />);
    expect(await screen.findByRole("button", { name: "Notifications, 2 unread" })).toBeInTheDocument();
    expect(mock.calls[0]).toBe("GET /orgs/o1/notifications/unread-count");
  });

  it("shows no badge when everything is read", async () => {
    mock.unread = 0;
    render(<NotificationBell orgId="o1" tasksHref="/org/acme/tasks" />);
    const bell = await screen.findByRole("button", { name: "Notifications" });
    await waitFor(() => expect(mock.calls).toHaveLength(1));
    expect(bell.querySelector(".s1-bell__count")).toBeNull();
  });

  it("asks for the count again every minute, not more often", async () => {
    vi.useFakeTimers();
    render(<NotificationBell orgId="o1" tasksHref="/t" />);
    await act(async () => {});
    expect(mock.calls).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS - 1);
    });
    expect(mock.calls).toHaveLength(1);
    mock.unread = 5;
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(mock.calls).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Notifications, 5 unread" })).toBeInTheDocument();
    expect(POLL_MS).toBe(60_000);
  });

  it("stops polling when it goes away", async () => {
    vi.useFakeTimers();
    const { unmount } = render(<NotificationBell orgId="o1" tasksHref="/t" />);
    await act(async () => {});
    unmount();
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS * 3);
    });
    expect(mock.calls).toHaveLength(1);
  });

  it("keeps working when a poll fails", async () => {
    mock.failCount = true;
    render(<NotificationBell orgId="o1" tasksHref="/t" />);
    await waitFor(() => expect(mock.calls).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("lists the latest notifications, unread first marked", async () => {
    render(<NotificationBell orgId="o1" tasksHref="/org/acme/tasks" />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    const panel = await screen.findByRole("region", { name: "Notifications" });
    expect(await within(panel).findByText(N1.title)).toBeInTheDocument();
    expect(within(panel).getByText(N2.title)).toBeInTheDocument();
    expect(within(panel).getByText(/Unread/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "My tasks" })).toHaveAttribute("href", "/org/acme/tasks");
  });

  it("opens the link and marks it read when a notification is clicked", async () => {
    const onNavigate = vi.fn();
    render(<NotificationBell orgId="o1" tasksHref="/org/acme/tasks" onNavigate={onNavigate} />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    fireEvent.click(await screen.findByRole("button", { name: new RegExp("Review Rechnung") }));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("/?view=review&doc=D1&e=E1"));
    expect(mock.calls).toContain("POST /orgs/o1/notifications/n1/read");
  });

  it("sends a notification without a link to My tasks", async () => {
    const onNavigate = vi.fn();
    render(<NotificationBell orgId="o1" tasksHref="/org/acme/tasks" onNavigate={onNavigate} />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Chase supplier/ }));
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("/org/acme/tasks"));
  });

  it("still opens the link when marking it read fails", async () => {
    const { api } = await import("../../../lib/api");
    const onNavigate = vi.fn();
    render(<NotificationBell orgId="o1" tasksHref="/t" onNavigate={onNavigate} />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    const button = await screen.findByRole("button", { name: /Review Rechnung/ });
    vi.mocked(api).mockImplementationOnce(() => Promise.reject(new Error("nope")));
    fireEvent.click(button);
    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith(N1.link));
  });

  it("marks everything read", async () => {
    render(<NotificationBell orgId="o1" tasksHref="/t" />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument());
    expect(mock.calls).toContain("POST /orgs/o1/notifications/read-all");
    expect(screen.queryByText(/Unread/)).toBeNull();
  });

  it("says so when there is nothing, and when the list cannot be loaded", async () => {
    mock.list = [];
    mock.unread = 0;
    const first = render(<NotificationBell orgId="o1" tasksHref="/t" />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
    first.unmount();

    mock.failList = true;
    render(<NotificationBell orgId="o1" tasksHref="/t" />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load notifications/);
  });

  it("closes on Escape", async () => {
    render(<NotificationBell orgId="o1" tasksHref="/t" />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    await screen.findByRole("region", { name: "Notifications" });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
  });
});
