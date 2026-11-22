/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { ApiError } from "../../../lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../providerApi", async () => {
  const actual = await vi.importActual<typeof import("../providerApi")>("../providerApi");
  return { ...actual, getOrg: vi.fn(), suspendOrg: vi.fn(), activateOrg: vi.fn(), updateOrg: vi.fn(), createOrg: vi.fn() };
});
vi.mock("../orgApi", async () => {
  const actual = await vi.importActual<typeof import("../orgApi")>("../orgApi");
  return { ...actual, resendInvite: vi.fn(), listOrgUsers: vi.fn() };
});

import { listOrgUsers, resendInvite } from "../orgApi";
import { OrgDetail } from "../OrgDetail";
import { getOrg, type InitialAdminStatus } from "../providerApi";

const getOrgMock = getOrg as unknown as ReturnType<typeof vi.fn>;
const resendMock = resendInvite as unknown as ReturnType<typeof vi.fn>;

const ORG = { id: "o1", name: "Käserei Zürich", slug: "kaserei", status: "active" as const, max_users: 10, user_count: 1 };

const admin = (over: Partial<InitialAdminStatus> = {}): InitialAdminStatus => ({
  user_id: "u1",
  email: "zoe@kaserei.test",
  first_name: "Zoë",
  last_name: "Müller 山田",
  status: "invited",
  invited_at: "2026-11-12T09:30:00Z",
  last_invite_sent_at: "2026-11-12T09:30:00Z",
  invite_expired: false,
  ...over,
});

async function show(detail: Record<string, unknown>) {
  getOrgMock.mockResolvedValue({ ...ORG, ...detail });
  render(<OrgDetail orgId="o1" />);
  await waitFor(() => expect(screen.getByRole("heading", { name: "Käserei Zürich" })).toBeInTheDocument());
}

beforeEach(() => {
  vi.clearAllMocks();
  (listOrgUsers as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [], total: 0, max_users: 10, seats_used: 0 });
});

describe("provider org detail: the first admin", () => {
  it("says an invited admin is waiting, with the invite date, and offers Resend invite", async () => {
    await show({ initial_admin: admin(), user_counts: { active: 0, invited: 1, suspended: 0 } });
    expect(screen.getByTestId("first-admin-state")).toHaveTextContent("Invited · waiting");
    expect(screen.getByText(/Zoë Müller 山田/)).toBeInTheDocument();
    expect(screen.getByText(/zoe@kaserei\.test/)).toBeInTheDocument();
    expect(screen.getByText(/invited 12 Nov 2026/)).toBeInTheDocument();
    expect(screen.getByText("0 active · 1 invited · 0 suspended")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend invite" })).toBeInTheDocument();
  });

  it("says when the link has expired, and when it was last sent", async () => {
    await show({
      initial_admin: admin({ invite_expired: true, last_invite_sent_at: "2026-11-14T10:00:00Z" }),
      user_counts: { active: 0, invited: 1, suspended: 0 },
    });
    expect(screen.getByTestId("first-admin-state")).toHaveTextContent("Invited · link expired");
    expect(screen.getByText(/last sent 14 Nov 2026/)).toBeInTheDocument();
  });

  it("resends the invite to that user and shows the answer", async () => {
    resendMock.mockResolvedValue(undefined);
    await show({ initial_admin: admin(), user_counts: { active: 0, invited: 1, suspended: 0 } });
    fireEvent.click(screen.getByRole("button", { name: "Resend invite" }));
    await waitFor(() => expect(resendMock).toHaveBeenCalledWith("o1", "u1"));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Invite sent again."));
  });

  it("says why a resend failed", async () => {
    resendMock.mockRejectedValue(new ApiError(409, "This user is not waiting for an invite", null, null));
    await show({ initial_admin: admin() });
    fireEvent.click(screen.getByRole("button", { name: "Resend invite" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This user is not waiting for an invite"));
  });

  it("shows an active admin with no resend", async () => {
    await show({ initial_admin: admin({ status: "active" }), user_counts: { active: 2, invited: 0, suspended: 0 } });
    expect(screen.getByTestId("first-admin-state")).toHaveTextContent("Active");
    expect(screen.queryByRole("button", { name: "Resend invite" })).toBeNull();
    expect(screen.getByText("2 active · 0 invited · 0 suspended")).toBeInTheDocument();
  });

  it("shows a suspended admin with no resend", async () => {
    await show({ initial_admin: admin({ status: "suspended" }), user_counts: { active: 0, invited: 0, suspended: 1 } });
    expect(screen.getByTestId("first-admin-state")).toHaveTextContent("Suspended");
    expect(screen.queryByRole("button", { name: "Resend invite" })).toBeNull();
  });

  it("says so when no admin was invited, and falls back to the email when the name is empty", async () => {
    await show({ initial_admin: null, user_counts: { active: 0, invited: 0, suspended: 0 } });
    expect(screen.getByText("No admin has been invited yet.")).toBeInTheDocument();
    expect(screen.queryByTestId("first-admin-state")).toBeNull();
  });

  it("shows the email when the admin has no name", async () => {
    await show({ initial_admin: admin({ first_name: "", last_name: "", status: "active" }) });
    expect(screen.getAllByText(/zoe@kaserei\.test/).length).toBeGreaterThan(0);
  });

  it("still loads from an older server that sends neither field", async () => {
    await show({});
    expect(screen.getByText("No admin has been invited yet.")).toBeInTheDocument();
  });
});
