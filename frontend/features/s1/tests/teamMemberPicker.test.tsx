/* @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TeamMemberPicker, type TeamDirectory } from "../components/TeamMemberPicker";

afterEach(cleanup);

function directory(over: Partial<TeamDirectory> = {}): TeamDirectory {
  return {
    orgName: "Acme Foods",
    canInvite: true,
    invite: vi.fn().mockResolvedValue(undefined),
    members: [
      { id: "1", email: "meg@acme.test", name: "Meg Member", status: "active" },
      { id: "2", email: "ivy@acme.test", name: "Ivy Invited", status: "invited" },
    ],
    ...over,
  };
}

const type = (value: string) => fireEvent.change(screen.getByLabelText("Add a team member"), { target: { value } });

describe("Setup team picker", () => {
  it("searches members by name or email and adds the pick", () => {
    const onPick = vi.fn();
    render(<TeamMemberPicker directory={directory()} taken={[]} onPick={onPick} />);
    type("meg");
    fireEvent.click(screen.getByRole("button", { name: /Meg Member/ }));
    expect(onPick).toHaveBeenCalledWith({ name: "Meg Member", login: "meg@acme.test" });
  });

  it("leaves out people already on the team", () => {
    render(<TeamMemberPicker directory={directory()} taken={["MEG@acme.test"]} onPick={vi.fn()} />);
    type("meg");
    expect(screen.queryByRole("button", { name: /Meg Member/ })).toBeNull();
  });

  it("offers an invite for an unknown address, sends it, then adds them to the team", async () => {
    const dir = directory();
    const onPick = vi.fn();
    render(<TeamMemberPicker directory={dir} taken={[]} onPick={onPick} />);
    type("New.Hire@acme.test");
    fireEvent.click(screen.getByRole("button", { name: "Invite new.hire@acme.test to Acme Foods" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith({ name: "new.hire@acme.test", login: "new.hire@acme.test" }));
    expect(dir.invite).toHaveBeenCalledWith("new.hire@acme.test");
  });

  it("does not invite for an existing member's address, nor for half an address", () => {
    render(<TeamMemberPicker directory={directory()} taken={[]} onPick={vi.fn()} />);
    type("meg@acme.test");
    expect(screen.queryByRole("button", { name: /^Invite/ })).toBeNull();
    type("new.hire@");
    expect(screen.queryByRole("button", { name: /^Invite/ })).toBeNull();
  });

  it("tells a non-admin to ask an admin instead of inviting", () => {
    render(<TeamMemberPicker directory={directory({ canInvite: false })} taken={[]} onPick={vi.fn()} />);
    type("new.hire@acme.test");
    expect(screen.queryByRole("button", { name: /^Invite/ })).toBeNull();
    expect(screen.getByText(/Ask an org admin/)).toBeInTheDocument();
  });

  it("shows the reason and adds no one when the invite fails", async () => {
    const onPick = vi.fn();
    const dir = directory({ invite: vi.fn().mockRejectedValue(new Error("No seats left.")) });
    render(<TeamMemberPicker directory={dir} taken={[]} onPick={onPick} />);
    type("new.hire@acme.test");
    fireEvent.click(screen.getByRole("button", { name: /^Invite/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No seats left.");
    expect(onPick).not.toHaveBeenCalled();
  });
});
