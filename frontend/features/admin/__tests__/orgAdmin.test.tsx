/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

vi.mock("../orgApi", async () => {
  const actual = await vi.importActual<typeof import("../orgApi")>("../orgApi");
  return {
    ...actual,
    inviteUser: vi.fn(),
    getOrgUser: vi.fn(),
    resendInvite: vi.fn(),
    suspendUser: vi.fn(),
    reactivateUser: vi.fn(),
    deleteUser: vi.fn(),
    updateUserRole: vi.fn(),
  };
});

import { deleteUser, inviteUser, getOrgUser, type OrgUser } from "../orgApi";
import { InviteUserForm } from "../InviteUserForm";
import { UserDetail } from "../UserDetail";

const inviteMock = inviteUser as unknown as ReturnType<typeof vi.fn>;
const getUserMock = getOrgUser as unknown as ReturnType<typeof vi.fn>;
const deleteMock = deleteUser as unknown as ReturnType<typeof vi.fn>;

function user(over: Partial<OrgUser> = {}): OrgUser {
  return {
    id: "u1",
    email: "sam@acme.com",
    first_name: "Sam",
    last_name: "Lee",
    role: "org_member",
    status: "active",
    ...over,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("InviteUserForm", () => {
  it("submits and shows a confirmation", async () => {
    inviteMock.mockResolvedValueOnce(user({ status: "invited" }));
    render(<InviteUserForm orgId="o1" slug="acme" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sam@acme.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));
    await waitFor(() =>
      expect(inviteMock).toHaveBeenCalledWith(
        "o1",
        expect.objectContaining({ email: "sam@acme.com", role: "org_member" }),
      ),
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/invite sent to sam@acme.com/i));
  });
});

describe("UserDetail resend invite", () => {
  it("shows Resend invite only for invited users", async () => {
    getUserMock.mockResolvedValueOnce(user({ status: "invited" }));
    const { unmount } = render(<UserDetail orgId="o1" slug="acme" userId="u1" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sam Lee" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /resend invite/i })).toBeInTheDocument();
    unmount();

    getUserMock.mockResolvedValueOnce(user({ status: "active" }));
    render(<UserDetail orgId="o1" slug="acme" userId="u1" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sam Lee" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /resend invite/i })).not.toBeInTheDocument();
  });
});

describe("UserDetail delete", () => {
  it("confirms by typing the email, then goes back to the users list", async () => {
    getUserMock.mockResolvedValueOnce(user());
    deleteMock.mockResolvedValueOnce(undefined);
    const onDeleted = vi.fn();
    render(<UserDetail orgId="o1" slug="acme" userId="u1" onDeleted={onDeleted} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sam Lee" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: /^delete$/i });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/type/i), { target: { value: "sam@acme.com" } });
    fireEvent.click(confirm);

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("o1", "u1"));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("/org/acme/admin/users?deleted=1"));
    expect(getUserMock).toHaveBeenCalledTimes(1); // no refetch of a user that no longer exists
  });
});
