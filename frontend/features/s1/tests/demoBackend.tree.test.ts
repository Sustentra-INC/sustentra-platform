/* @vitest-environment jsdom */
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import type { EvidenceTree, LineSchedule, TreeDocRow } from "../api/evidenceTree";
import type { Recalculation, RecalculationReference } from "../api/recalculation";
import { demoApi } from "../demo-backend";
import { demoDecisions } from "../demo-backend/state";
import { BackendVerificationResults } from "../components/BackendVerificationResults";
import { SupportingSchedule } from "../components/SupportingSchedule";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { useVerificationStore } from "../verification/verificationStore";

const ID = engagementConfig.engagementId;
const KENT_GAS = "s1:stationary:natural-gas:facility-kent";
const enc = (key: string) => encodeURIComponent(key);

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const treeRows = (tree: EvidenceTree): TreeDocRow[] => [
  ...tree.blocks.summary,
  ...tree.blocks.unassigned,
  ...tree.blocks.supporting.unassigned,
  ...tree.blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines.flatMap((n) => n.documents)))),
];

describe("demo backend: evidence tree, schedule and recalculation", () => {
  it("lists only real fixture documents, under real lines", async () => {
    const tree = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
    const real = new Set(manufacturerEvidence.map((d) => d.documentId));
    const rows = treeRows(tree);
    expect(rows.length).toBeGreaterThan(100);
    for (const row of rows) expect(real.has(row.document_id)).toBe(true);
    const lineKeys = new Set(tree.lines.map((l) => l.key));
    expect(lineKeys.has(KENT_GAS)).toBe(true);
    expect(tree.facilities.map((f) => f.name)).toEqual(["Tualatin Plant", "Kent Cannery", "Modesto Bottling"]);
    expect(tree.set_aside.map((s) => s.document_id)).toEqual(expect.arrayContaining(["DOC-DUPE-B", "DOC-OLD"]));
    // Fresh objects per call.
    const again = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
    expect(again).toEqual(tree);
    expect(again).not.toBe(tree);
  });

  it("recounts for one facility", async () => {
    const tree = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree?facility_id=facility-kent`);
    expect(tree.lines.length).toBeGreaterThan(0);
    expect(tree.lines.every((l) => l.facility_id === "facility-kent")).toBe(true);
    expect(treeRows(tree).every((r) => r.facility_id === "facility-kent" || r.facility_id === null)).toBe(true);
  });

  it("builds Kent Cannery natural gas as Claire designed it", async () => {
    const s = await demoApi<LineSchedule>(`/engagements/${ID}/calculation-lines/${enc(KENT_GAS)}/schedule`);
    expect(s.line.label).toBe("Kent Cannery");
    expect(s.coverage).toHaveLength(12);
    const status = Object.fromEntries(s.coverage.map((m) => [m.month.slice(5), m.status]));
    expect(status["01"]).toBe("counted_in_part");
    expect(status["12"]).toBe("counted_in_part");
    expect(Object.values(status).filter((v) => v === "not_reviewed")).toHaveLength(1);
    expect(Object.values(status).filter((v) => v === "no_document")).toHaveLength(1);
    const meter = s.identifier_groups.find((g) => g.label === "Meter number")!;
    expect(meter.documents_with).toBe(10);
    expect(meter.documents_total).toBe(11);
    expect(s.identifier_groups.map((g) => g.label)).toEqual(["Facility", "Service address", "Account number", "Meter number"]);
    expect(s.rows.filter((r) => r.accepted && r.saved_by?.name && r.saved_by.at)).toHaveLength(10);
    expect(s.history.length).toBeGreaterThan(5);
    expect(s.activity_quantity_note).toBe("Activity quantity: fuel quantity combusted");
  });

  it("keeps line keys and quantities the same across tree, schedule and recalculation", async () => {
    const tree = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
    const recalc = await demoApi<Recalculation>(`/engagements/${ID}/recalculation`);
    const treeKeys = new Set(tree.lines.map((l) => l.key));
    const lines = recalc.calculation_lines ?? [];
    expect(lines.length).toBeGreaterThanOrEqual(8);
    for (const line of lines) {
      expect(treeKeys.has(line.key)).toBe(true);
      const sched = await demoApi<LineSchedule>(`/engagements/${ID}/calculation-lines/${enc(line.key)}/schedule`);
      expect(sched.line.key).toBe(line.key);
      expect(sched.calculated).toBe(true);
      // Every document of the line's activity is on the schedule, as an accepted row.
      const accepted = new Map(sched.rows.filter((r) => r.accepted).map((r) => [r.document_id, r]));
      for (const row of line.step1.rows) {
        expect(accepted.has(row.document_id)).toBe(true);
        expect(accepted.get(row.document_id)!.activity_quantity.value).toBe(row.quantity);
        expect(row.candidate_id).toBe(accepted.get(row.document_id)!.candidate_id);
      }
      // The schedule's accepted values feed the activity: their prorated sum is Step 1's total.
      const counted = line.step1.rows.reduce((s, r) => s + r.counted_quantity, 0);
      expect(counted).toBeCloseTo(line.step1.total.quantity, 3);
      // Records sit on the line in the tree.
      const treeLine = tree.blocks.supporting.scopes.flatMap((sc) => sc.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines))).find((n) => n.line.key === line.key)!;
      const onTree = new Set(treeLine.documents.map((d) => d.document_id));
      for (const row of line.step1.rows) expect(onTree.has(row.document_id)).toBe(true);
      // The line's gases sum to its total, and the facility result is the sum of its gases.
      expect(line.results.sum_co2e_t).toBeCloseTo(line.step3.gases.reduce((s, g) => s + g.co2e_t, 0), 6);
    }
    // Quality checks and awaiting-review items point at real documents.
    const real = new Set(manufacturerEvidence.map((d) => d.documentId));
    for (const q of recalc.quality_checks ?? []) for (const d of q.documents) expect(real.has(d)).toBe(true);
    for (const a of recalc.awaiting_review) expect(real.has(a.document_id)).toBe(true);
    expect(recalc.awaiting_review.length).toBeGreaterThan(0);
    const severities = (recalc.quality_checks ?? []).map((q) => q.severity);
    expect(severities).toEqual([...severities].sort((a, b) => ["warning", "review", "info"].indexOf(a) - ["warning", "review", "info"].indexOf(b)));
  });

  it("recomputed totals equal the sum of the calculation lines", async () => {
    const recalc = await demoApi<Recalculation>(`/engagements/${ID}/recalculation`);
    const lines = recalc.calculation_lines ?? [];
    const toward = (c: string) => lines.filter((l) => l.counts_toward === c).reduce((s, l) => s + l.results.total_co2e_t, 0);
    expect(recalc.categories.stationary_combustion!.total_co2e).toBeCloseTo(toward("stationary"), 4);
    expect(recalc.categories.mobile_combustion!.total_co2e).toBeCloseTo(toward("mobile"), 4);
    expect(recalc.categories.purchased_electricity_location_based!.total_co2e).toBeCloseTo(toward("purchased_energy"), 3);
    const node = (k: string) => recalc.rollup!.nodes[k].co2e_t!;
    expect(node("stationary_combustion_total")).toBeCloseTo(toward("stationary"), 4);
    expect(node("scope1_total")).toBeCloseTo(toward("stationary") + toward("mobile") + node("fugitive_total"), 4);
    expect(node("inventory_location_total")).toBeCloseTo(node("scope1_total") + node("scope2_location_total"), 6);
    expect(recalc.rollup!.checks.every((c) => c.ok)).toBe(true);
    expect(recalc.scope_totals.scope1!.total_co2e).toBeCloseTo(node("scope1_total"), 6);
    // The old demo's order of magnitude: Scope 1 in the tens of thousands of tonnes, reported about 17,589.
    const scope1 = recalc.comparisons.find((c) => c.key === "scope1_total")!;
    expect(scope1.reported).toBeGreaterThan(17_500);
    expect(scope1.reported).toBeLessThan(17_700);
    expect(scope1.recalculated).toBeGreaterThan(10_000);
    // At least one line is material and one matches.
    expect(lines.some((l) => l.status === "above")).toBe(true);
    expect(lines.some((l) => l.status === "within" && Math.abs(l.difference_t ?? 1) < 1)).toBe(true);
  });

  it("answers the reference routes", async () => {
    const ref = await demoApi<RecalculationReference>("/reference/recalculation");
    expect(ref.default_gwp_set).toBe("AR5");
    expect(ref.rollup_layout!.final_outputs.length).toBe(34);
    expect(ref.egrid_subregions.some((r) => r.egrid_subregion === "NWPP")).toBe(true);
    expect(await demoApi<{ subregions: string[] }>("/reference/egrid-zip/98032")).toEqual({ zip: "98032", subregions: ["NWPP"] });
  });

  it("moves a placement and saves the decision", async () => {
    const before = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
    const row = treeRows(before).find((r) => r.document_id === "DOC-kent-gas-feb")!;
    expect(row.placement_from).toBe(KENT_GAS);
    const saved = await demoApi<{ kind: string; payload: { placements: { from: string; to: string }[] } }>(`/engagements/${ID}/workpaper-items/document/DOC-kent-gas-feb`, {
      method: "PUT",
      body: { payload: { documentId: "DOC-kent-gas-feb", placements: [{ from: KENT_GAS, to: "supporting:unassigned" }] } },
    });
    expect(saved.kind).toBe("document");
    expect(demoDecisions().get("DOC-kent-gas-feb")?.placements).toHaveLength(1);
    const after = await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
    expect(after.blocks.supporting.unassigned.some((r) => r.document_id === "DOC-kent-gas-feb")).toBe(true);
    const sched = await demoApi<LineSchedule>(`/engagements/${ID}/calculation-lines/${enc(KENT_GAS)}/schedule`);
    expect(sched.rows.some((r) => r.document_id === "DOC-kent-gas-feb")).toBe(false);
    (demoDecisions() as Map<string, unknown>).delete("DOC-kent-gas-feb");
  });
});

describe("the staging screens over the demo backend", () => {
  it("renders Kent Cannery natural gas on the supporting schedule", async () => {
    render(createElement(SupportingSchedule, { engagementId: ID, lineKey: KENT_GAS, onBack: () => {}, onOpenDocument: () => {}, onOpenCalculationLine: () => {} }));
    expect(await screen.findByRole("heading", { level: 1, name: /Kent Cannery · Natural gas/ })).toBeTruthy();
    await waitFor(() => expect(document.querySelectorAll(".s1-sch-month--active").length).toBe(2));
    expect(screen.getAllByText(/Not reviewed/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/No document/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/M-4471/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/10 of 11|10\/11/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Activity quantity: fuel quantity combusted/).length).toBeGreaterThan(0);
  });

  it("renders the calculation panels, inputs and data quality checks", async () => {
    const store = renderHook(() => useVerificationStore()).result;
    render(createElement(BackendVerificationResults, { engagement: engagementConfig, store: store.current, onSaveInputs: async () => {}, onError: () => false }));
    expect(await screen.findByRole("region", { name: "Calculation by line" })).toBeTruthy();
    expect(screen.getByText(/Scope 1 › Stationary combustion/)).toBeTruthy();
    expect(screen.getByText(/Scope 1 › Mobile combustion/)).toBeTruthy();
    expect(screen.getByText(/Scope 2 › Purchased electricity/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Data quality checks" })).toBeTruthy();
    expect(screen.getAllByText(/Kent Cannery/).length).toBeGreaterThan(0);
  });
});
