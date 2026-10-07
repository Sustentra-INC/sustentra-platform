/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { S1Chrome, type WorkpaperUser } from "../components/S1Chrome";
import type { EngagementConfig } from "../types";

const ENGAGEMENT: EngagementConfig = {
  clientName: "Acme Foods",
  engagementId: "0f8b8c4e-0000-4000-8000-000000000001",
  engagementName: "FY2024 GHG verification",
  reportingPeriod: { start: "2024-01-01", end: "2024-12-31" },
  facilities: [],
  regulation: "",
  conclusionType: "",
  assuranceLevel: "",
  boundaryApproach: "",
  scopeBoundaryStatement: "",
};

function renderChrome(user?: WorkpaperUser, onSignOut = vi.fn()) {
  render(
    <S1Chrome engagement={ENGAGEMENT} user={user} onSignOut={user ? onSignOut : undefined}>
      <p>content</p>
    </S1Chrome>
  );
  return onSignOut;
}

const member: WorkpaperUser = { email: "mia@acme.test", firstName: "Mia", role: "org_member", orgSlug: "acme" };

describe("workpaper chrome: signed-in user (FE-006)", () => {
  it("shows the user, role and sign-out", () => {
    const onSignOut = renderChrome(member);
    const area = screen.getByLabelText("Signed in");
    expect(within(area).getByText("Mia")).toHaveAttribute("title", "mia@acme.test");
    expect(within(area).getByText("Member")).toBeInTheDocument();
    expect(within(area).queryByRole("link", { name: "Admin" })).toBeNull();
    fireEvent.click(within(area).getByRole("button", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  it("links org admins to their org's admin pages", () => {
    renderChrome({ ...member, role: "org_admin" });
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/org/acme");
  });

  it("links provider admins to the org list", () => {
    renderChrome({ email: "ops@sustentra.test", firstName: null, role: "provider_admin", orgSlug: null });
    expect(screen.getByText("ops@sustentra.test")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Organizations" })).toHaveAttribute("href", "/provider-admin/orgs");
  });

  it("shows the engagement's name instead of its id", () => {
    renderChrome(member);
    expect(screen.getByText("FY2024 GHG verification")).toBeInTheDocument();
    expect(screen.queryByText(ENGAGEMENT.engagementId)).toBeNull();
  });

  it("has no user area in the fixture demo", () => {
    renderChrome(undefined);
    expect(screen.queryByLabelText("Signed in")).toBeNull();
  });
});
