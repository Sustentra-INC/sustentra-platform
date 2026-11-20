/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { parseEmails } from "../emails";
import { PeopleList } from "../PeopleList";

const fetchMock = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const LIST = {
  items: [
    { id: "u1", email: "ann@acme.test", first_name: "Ann", last_name: "Admin", role: "org_admin", status: "active" },
    { id: "u2", email: "ivy@acme.test", first_name: "Ivy", last_name: "I", role: "org_member", status: "invited" },
  ],
  total: 2, page: 1, page_size: 100, max_users: 10, seats_used: 2,
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const calls = () => fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url)}`);

describe("parseEmails", () => {
  it("splits a pasted list, lower-cases, de-duplicates and keeps the bad ones apart", () => {
    expect(parseEmails("A@x.co, b@x.co;\nA@X.co  nope <c@x.co>")).toEqual({
      valid: ["a@x.co", "b@x.co", "c@x.co"],
      invalid: ["nope"],
    });
  });
});

describe("People page", () => {
  it("lists name, email, role and status, with per-row actions by status", async () => {
    fetchMock.mockResolvedValue(json(LIST));
    render(<PeopleList orgId="o1" />);
    expect(await screen.findByText("ivy@acme.test")).toBeInTheDocument();
    expect(screen.getByText("2 / 10 seats used")).toBeInTheDocument();
    expect(screen.getByText("invited")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-send invite to ivy@acme.test" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove access for ann@acme.test" })).toBeInTheDocument();
  });

  it("sends a pasted list as one bulk invite and shows each result", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).endsWith("/invites/bulk")) {
        return json({
          invited: 1,
          results: [
            { email: "new@acme.test", status: "invited" },
            { email: "ann@acme.test", status: "already_member" },
          ],
        }, 201);
      }
      return json(LIST);
    });
    render(<PeopleList orgId="o1" />);
    await screen.findByText("ivy@acme.test");
    fireEvent.click(screen.getByRole("button", { name: "Add people" }));
    fireEvent.change(screen.getByLabelText("Email addresses"), {
      target: { value: "New@acme.test, ann@acme.test\nbad-address" },
    });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "org_admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Send 2 invitations" }));
    expect(await screen.findByText(/ann@acme.test: Already in your organization/)).toBeInTheDocument();
    expect(screen.getByText(/bad-address: Not a valid email address/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/invites/bulk"));
    expect(JSON.parse(post![1].body)).toEqual({ emails: ["new@acme.test", "ann@acme.test"], role: "org_admin" });
    expect(await screen.findByText("1 invitation sent.")).toBeInTheDocument();
  });

  it("refuses more than 50 addresses before calling the API", async () => {
    fetchMock.mockResolvedValue(json(LIST));
    render(<PeopleList orgId="o1" startAdding />);
    await screen.findByText("ivy@acme.test");
    const many = Array.from({ length: 51 }, (_, i) => `p${i}@acme.test`).join(" ");
    fireEvent.change(screen.getByLabelText("Email addresses"), { target: { value: many } });
    fireEvent.click(screen.getByRole("button", { name: /Send 51 invitations/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at most 50");
    expect(calls().some((c) => c.includes("/invites/bulk"))).toBe(false);
  });

  it("re-sends an invite and removes access after confirming", async () => {
    fetchMock.mockImplementation(async () => json(LIST));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<PeopleList orgId="o1" />);
    await screen.findByText("ivy@acme.test");
    fireEvent.click(screen.getByRole("button", { name: "Re-send invite to ivy@acme.test" }));
    await waitFor(() => expect(calls()).toContain("POST /api/v1/orgs/o1/invites/u2/resend"));
    expect(await screen.findByText("Invitation re-sent to ivy@acme.test.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove access for ann@acme.test" }));
    await waitFor(() => expect(calls()).toContain("POST /api/v1/orgs/o1/users/u1/suspend"));
  });

  it("does nothing when removal is not confirmed", async () => {
    fetchMock.mockResolvedValue(json(LIST));
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<PeopleList orgId="o1" />);
    await screen.findByText("ivy@acme.test");
    fireEvent.click(screen.getByRole("button", { name: "Remove access for ann@acme.test" }));
    expect(calls().some((c) => c.includes("/suspend"))).toBe(false);
  });
});
