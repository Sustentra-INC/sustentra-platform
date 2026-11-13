/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  // Imported when called, not while the mock is built: the demo backend itself imports lib/api.
  return { ...actual, api: vi.fn(async (path: string, options?: never) => (await import("../demo-backend")).demoApi(path, options)) };
});

import { demoApi } from "../demo-backend";
import { resetDemoMethodology } from "../demo-backend/methodology";
import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import type { MethodologyRecord } from "../api/methodologyReview";

const BASE = "/engagements/ENG-CASCADE-2025/methodology-review";
const row = (label: string) => screen.getByText(label).closest("li") as HTMLElement;

type Wire = { fields: (MethodologyRecord & { field_id: string })[]; ai: { enabled: boolean } };
const get = () => demoApi<Wire>(BASE);

async function open(onOpenDocument = vi.fn()) {
  render(<BackendMethodologyReview engagementId="ENG-CASCADE-2025" onOpenDocument={onOpenDocument} />);
  await screen.findByText("Consolidation approach", {}, { timeout: 3000 });
  return onOpenDocument;
}

async function prefillViaUi() {
  fireEvent.click(screen.getByRole("button", { name: "Read the client's reports with Claude" }));
  fireEvent.click(screen.getByRole("button", { name: "Read the reports" }));
  await waitFor(() => expect(within(row("Consolidation approach")).getByText("Suggested by Claude")).toBeTruthy(), { timeout: 3000 });
}

beforeEach(() => resetDemoMethodology());
afterEach(cleanup);

describe("the demo backend's methodology review", () => {
  it("loads with Claude available and company statements already in", async () => {
    await open();
    expect(within(row("Reporting period")).getByText("Accepted")).toBeTruthy();
    expect(within(row("Consolidation approach")).getByText("Pending")).toBeTruthy();
    expect((await get()).ai.enabled).toBe(true);
    expect((await get()).fields.every((f) => !f.suggestion)).toBe(true);
  });

  it("prefill adds Claude suggestions with quotes and real documents, never pre-accepted, and twice adds no rows", async () => {
    const onOpenDocument = await open();
    await prefillViaUi();
    const ids = new Set(manufacturerEvidence.map((d) => d.documentId));
    const suggested = (await get()).fields.filter((f) => f.suggestion);
    expect(suggested.length).toBeGreaterThan(10);
    for (const f of suggested) {
      const s = f.suggestion!;
      expect(s.quote.length).toBeGreaterThanOrEqual(8);
      expect(ids.has(s.document_id)).toBe(true);
      expect(s.source_reference).toBeTruthy();
      expect(s.origin).toBe("ai");
      expect(f.decision?.status ?? "pending").toBe("pending");
      if (typeof s.value === "string" && ["Operational Control", "Equity Share", "Financial Control"].includes(s.value)) {
        expect(s.quote.toLowerCase()).toContain(s.value.toLowerCase());
      }
    }
    // Disagrees with the company's stated eGRID2023.
    expect(suggested.some((f) => JSON.stringify(f.suggestion!.value).includes("eGRID2021"))).toBe(true);

    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: /^Cascade_|cascade_org_boundary_statement/ }));
    expect(onOpenDocument).toHaveBeenCalled();

    const before = (await get()).fields.length;
    await demoApi(`${BASE}/prefill`, { method: "POST", body: {} });
    expect((await get()).fields.length).toBe(before);
  });

  it("an accept sticks, with who and when, and revert restores pending with the suggestion", async () => {
    await open();
    await prefillViaUi();
    fireEvent.click(within(row("Consolidation approach")).getByRole("button", { name: "Accept: Consolidation approach" }));
    await waitFor(() => expect(within(row("Consolidation approach")).getByText("Accepted")).toBeTruthy(), { timeout: 3000 });

    const record = (await get()).fields.find((f) => f.field_id === "consolidation_approach")!;
    expect(record.decision).toMatchObject({ status: "accepted", value: "Operational Control", by: { name: "M. Osei" } });
    expect(record.decision!.at).toMatch(/^2026-11-12T/);

    await demoApi(`${BASE}/consolidation_approach/revert`, { method: "POST", body: {} });
    const reverted = (await get()).fields.find((f) => f.field_id === "consolidation_approach")!;
    expect(reverted.decision?.status).toBe("pending");
    expect(reverted.suggestion).not.toBeNull();
    expect(reverted.history.map((h) => h.action)).toEqual(["accept", "revert"]);
  });
});
