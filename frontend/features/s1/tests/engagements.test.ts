/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createEngagement,
  engagementFromBackend,
  engagementSaveProblem,
  engagementToBackend,
  listEngagements,
  pickEngagement,
  rememberEngagement,
  saveEngagement,
  type BackendEngagement,
} from "../api/engagements";

const ROW: BackendEngagement = {
  id: "0f8b8c4e-0000-4000-8000-000000000001",
  org_id: "aaaaaaaa-0000-4000-8000-00000000000a",
  name: "FY2024 GHG verification",
  client_name: "Acme Foods",
  reporting_period_start: "2024-01-01",
  reporting_period_end: "2024-12-31",
  status: "active",
  settings: {
    facilities: [{ facilityId: "F1", name: "Kent Cannery" }],
    assuranceLevel: "Limited",
    dataScope: "Scope 1 & 2",
    clientContact: { name: "Cat", email: "cat@acme.test", company: "Acme Foods" },
  },
  created_at: "2026-10-07T00:00:00Z",
  updated_at: "2026-10-07T00:00:00Z",
};

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("engagement mapping (S1-BE-002)", () => {
  it("maps an API engagement to the Setup config", () => {
    const config = engagementFromBackend(ROW);
    expect(config.engagementId).toBe(ROW.id);
    expect(config.engagementName).toBe("FY2024 GHG verification");
    expect(config.clientName).toBe("Acme Foods");
    expect(config.reportingPeriod).toEqual({ start: "2024-01-01", end: "2024-12-31" });
    expect(config.facilities).toEqual([{ facilityId: "F1", name: "Kent Cannery" }]);
    expect(config.assuranceLevel).toBe("Limited");
    expect(config.dataScope).toBe("Scope 1 & 2");
    expect(config.clientContact?.email).toBe("cat@acme.test");
    expect(config.regulation).toBe("");
  });

  it("round-trips through the API payload", () => {
    const payload = engagementToBackend(engagementFromBackend(ROW));
    expect(payload).toEqual({
      name: ROW.name,
      client_name: "Acme Foods",
      reporting_period_start: "2024-01-01",
      reporting_period_end: "2024-12-31",
      settings: expect.objectContaining(ROW.settings),
    });
    expect(Object.keys(payload.settings)).not.toContain("engagementId");
    expect(Object.keys(payload.settings)).not.toContain("signedInLogin");
  });

  it("handles a brand-new engagement with empty fields", () => {
    const config = engagementFromBackend({ ...ROW, client_name: null, reporting_period_start: null,
      reporting_period_end: null, settings: {} });
    expect(config.facilities).toEqual([]);
    const payload = engagementToBackend({ ...config, engagementName: "  " });
    expect(payload.name).toBe("Untitled engagement");
    expect(payload.client_name).toBeNull();
    expect(payload.reporting_period_start).toBeNull();
  });

  it("refuses to save a period that ends before it starts", () => {
    const config = engagementFromBackend(ROW);
    expect(engagementSaveProblem(config)).toBeNull();
    expect(engagementSaveProblem({ ...config, reportingPeriod: { start: "2024-12-31", end: "2024-01-01" } }))
      .toMatch(/ends before it starts/);
  });
});

describe("engagement API calls", () => {
  function respond(body: unknown, status = 200) {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  }

  it("lists, creates and saves through /api/v1/engagements with the session cookie", async () => {
    respond({ items: [ROW] });
    expect(await listEngagements()).toEqual([ROW]);
    respond(ROW, 201);
    await createEngagement("  New one ");
    respond(ROW);
    await saveEngagement(engagementFromBackend(ROW));

    const calls = fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method ?? "GET",
      (init as RequestInit).credentials, (init as RequestInit).body]);
    expect(calls[0].slice(0, 3)).toEqual(["/api/v1/engagements", "GET", "same-origin"]);
    expect(calls[1].slice(0, 3)).toEqual(["/api/v1/engagements", "POST", "same-origin"]);
    expect(JSON.parse(String(calls[1][3]))).toEqual({ name: "New one" });
    expect(calls[2].slice(0, 3)).toEqual([`/api/v1/engagements/${ROW.id}`, "PATCH", "same-origin"]);
  });
});

describe("pickEngagement", () => {
  const other = { ...ROW, id: "0f8b8c4e-0000-4000-8000-000000000002", name: "Other" };

  it("reopens the remembered engagement", () => {
    rememberEngagement(other.id);
    expect(pickEngagement([ROW, other])?.id).toBe(other.id);
  });

  it("falls back to the most recently updated", () => {
    rememberEngagement("gone");
    expect(pickEngagement([ROW, other])?.id).toBe(ROW.id);
    expect(pickEngagement([])).toBeNull();
  });
});
