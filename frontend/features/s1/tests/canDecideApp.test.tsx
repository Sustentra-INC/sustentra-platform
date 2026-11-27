/* @vitest-environment jsdom */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/BackendVerificationResults", async (importActual) => {
  const actual = await importActual<typeof import("../components/BackendVerificationResults")>();
  return { ...actual, BackendVerificationResults: (props: { canDecide?: boolean }) => <div data-testid="results" data-can-decide={String(props.canDecide)} /> };
});

import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

/** Who may decide on a calculation line's working: org roles and the demo, never provider_admin. */

const ENGAGEMENT_ROW = {
  id: "ENG-1", org_id: "ORG-1", name: "FY2025 inventory", client_name: "Acme", reporting_period_start: "2025-01-01", reporting_period_end: "2025-12-31",
  status: "active", settings: {}, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  if (path === "/auth/me") return json(200, { email: "m@example.com", role: "org_member" });
  if (path === "/engagements/ENG-1") return json(200, ENGAGEMENT_ROW);
  if (path === "/engagements") return json(200, { items: [ENGAGEMENT_ROW] });
  if (path === "/engagements/ENG-1/documents") return json(200, { items: [] });
  if (path.startsWith("/engagements/ENG-1/evidence-tree")) return json(200, { blocks: { summary: [], unassigned: [], supporting: { scopes: [], unassigned: [] } }, facilities: [], lines: [], set_aside: [] });
  if (path === "/engagements/ENG-1/workpaper-items") return json(200, { items: [] });
  return json(404, { detail: "Not found." });
});

async function settle() {
  for (let i = 0; i < 10; i += 1) {
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

const userOf = (role: "provider_admin" | "org_admin" | "org_member") => ({ email: "m@example.com", firstName: "Mary", role, orgSlug: "acme", orgId: "ORG-1" });

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.localStorage.clear();
});

describe("canDecide at the app level", () => {
  it.each([
    ["provider_admin", "false"],
    ["org_member", "true"],
    ["org_admin", "true"],
  ] as const)("backend mode, %s gives %s", async (role, expected) => {
    window.history.replaceState(null, "", "/?view=results&e=ENG-1");
    render(<S1WorkpaperApp user={userOf(role)} />);
    await settle();
    expect((await screen.findByTestId("results")).getAttribute("data-can-decide")).toBe(expected);
  });

  it("fixture mode (the demo) gives true", async () => {
    vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
    window.localStorage.setItem("sustentra-demo-signedin", "1");
    window.history.replaceState(null, "", "/?view=results&e=ENG-CASCADE-2025");
    render(<S1WorkpaperApp />);
    await settle();
    expect((await screen.findByTestId("results")).getAttribute("data-can-decide")).toBe("true");
  });
});
