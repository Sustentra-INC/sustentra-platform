/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AuditLog } from "../AuditLog";

const fetchMock = vi.fn();

function page(items: object[], next_cursor: string | null) {
  return new Response(JSON.stringify({ items, next_cursor }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const EVENT = {
  id: "e1",
  event_type: "user_role_changed",
  created_at: "2026-10-01T12:00:00Z",
  actor: "Ann Admin",
  target: "Meg Member",
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("AuditLog (COMP-002 contract)", () => {
  it("shows labelled events and loads the next page with the cursor", async () => {
    fetchMock
      .mockResolvedValueOnce(page([EVENT], "CURSOR1"))
      .mockResolvedValueOnce(page([{ ...EVENT, id: "e2", event_type: "user_invited", target: "Ivy" }], null));
    render(<AuditLog orgId="o1" />);

    await waitFor(() => expect(screen.getByText("Role changed")).toBeInTheDocument());
    expect(screen.getByText("Ann Admin")).toBeInTheDocument();
    expect(screen.getByText("Meg Member")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/v1/orgs/o1/audit-logs");

    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(screen.getByText("User invited")).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[1][0])).toContain("cursor=CURSOR1");
    expect(screen.queryByRole("button", { name: /load more/i })).not.toBeInTheDocument();
  });

  it("filters by the backend's event names", async () => {
    fetchMock.mockResolvedValue(page([], null));
    render(<AuditLog orgId="o1" />);
    await waitFor(() => expect(screen.getByText(/no events yet/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/filter by event type/i), { target: { value: "user_deleted" } });
    await waitFor(() =>
      expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("event_type=user_deleted"),
    );
  });
});
