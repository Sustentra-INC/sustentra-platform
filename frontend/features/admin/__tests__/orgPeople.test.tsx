/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

import { ApiError } from "../../../lib/api";

vi.mock("../orgApi", async () => {
  const actual = await vi.importActual<typeof import("../orgApi")>("../orgApi");
  return { ...actual, listOrgUsers: vi.fn(), inviteUser: vi.fn(), resendInvite: vi.fn(), deleteUser: vi.fn() };
});

import { inviteUser, listOrgUsers, resendInvite } from "../orgApi";
import { OrgPeople } from "../OrgPeople";

const listMock = listOrgUsers as unknown as ReturnType<typeof vi.fn>;
const inviteMock = inviteUser as unknown as ReturnType<typeof vi.fn>;
const resendMock = resendInvite as unknown as ReturnType<typeof vi.fn>;

const user = (over: Record<string, unknown>) => ({
  id: "u",
  email: "x@acme.com",
  first_name: "",
  last_name: "",
  role: "org_member",
  status: "active",
  created_at: "2026-11-12T10:00:00Z",
  ...over,
});
const PEOPLE = [
  user({ id: "1", email: "zed@acme.com", first_name: "Zed", last_name: "Zane", role: "org_member" }),
  user({ id: "2", email: "ann@acme.com", first_name: "Ann", last_name: "Lee", role: "org_member", status: "invited" }),
  user({ id: "3", email: "boss@acme.com", first_name: "Bo", last_name: "Ss", role: "org_admin", status: "suspended" }),
];
const result = (items: unknown[]) => ({ items, total: items.length, max_users: 10, seats_used: items.length });

beforeEach(() => vi.clearAllMocks());

describe("OrgPeople", () => {
  it("lists names, roles and statuses, admins first", async () => {
    listMock.mockResolvedValue(result(PEOPLE));
    render(<OrgPeople orgId="o1" />);
    await screen.findByText("Bo Ss");
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["Bo Ss", "Ann Lee", "Zed Zane"]);
    expect(within(rows[0]).getByText("Org admin")).toBeInTheDocument();
    expect(within(rows[0]).getByText("suspended")).toBeInTheDocument();
    expect(within(rows[1]).getByText("invited")).toBeInTheDocument();
    expect(within(rows[1]).getByText(/invited 12 Nov 2026/)).toBeInTheDocument();
    expect(within(rows[2]).getByText("Member")).toBeInTheDocument();
  });

  it("says so when there is nobody, and when the list cannot load", async () => {
    listMock.mockResolvedValueOnce(result([]));
    const { unmount } = render(<OrgPeople orgId="o1" />);
    await screen.findByText(/no one has been added/i);
    unmount();
    listMock.mockRejectedValueOnce(new Error("boom"));
    render(<OrgPeople orgId="o1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load people.");
  });

  it("invites, then refreshes the list and tells the page", async () => {
    listMock.mockResolvedValueOnce(result([])).mockResolvedValue(result(PEOPLE));
    inviteMock.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<OrgPeople orgId="o1" onChanged={onChanged} />);
    await screen.findByText(/no one has been added/i);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ann@acme.com" } });
    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Ann" } });
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: "Lee" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "org_admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
    await waitFor(() =>
      expect(inviteMock).toHaveBeenCalledWith("o1", {
        email: "ann@acme.com",
        role: "org_admin",
        first_name: "Ann",
        last_name: "Lee",
      }),
    );
    expect(await screen.findByText("Invite sent to ann@acme.com")).toBeInTheDocument();
    await screen.findByText("Ann Lee");
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows the API's error text, including the seat limit", async () => {
    listMock.mockResolvedValue(result([]));
    inviteMock.mockRejectedValueOnce(new ApiError(422, "Seat limit reached (10 of 10).", null, null));
    render(<OrgPeople orgId="o1" />);
    await screen.findByText(/no one has been added/i);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@acme.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Seat limit reached (10 of 10).");
  });

  it("resends an invite from an invited row", async () => {
    listMock.mockResolvedValue(result(PEOPLE));
    resendMock.mockResolvedValue(undefined);
    render(<OrgPeople orgId="o1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Resend invite to ann@acme.com" }));
    await waitFor(() => expect(resendMock).toHaveBeenCalledWith("o1", "2"));
    expect(await screen.findByText("Invite sent again to ann@acme.com.")).toBeInTheDocument();
  });
});
