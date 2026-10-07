/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { UsersList } from "../UsersList";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("UsersList (ORG-002 contract)", () => {
  it("asks for the whole list and shows seats for the whole org, not the filtered total", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              id: "u1",
              email: "ivy@acme.test",
              first_name: "Ivy",
              last_name: "Invited",
              role: "org_member",
              status: "invited",
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
          max_users: 10,
          seats_used: 4,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<UsersList orgId="o1" slug="acme" />);
    await waitFor(() => expect(screen.getByText("4 / 10 seats used")).toBeInTheDocument());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/v1/orgs/o1/users");
    expect(url).toContain("page_size=100");
  });
});
