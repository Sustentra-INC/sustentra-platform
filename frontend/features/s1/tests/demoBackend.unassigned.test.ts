/* @vitest-environment jsdom */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import type { EvidenceTree } from "../api/evidenceTree";
import { uncountedGroups, uncountedMessage, type Recalculation } from "../api/recalculation";
import { demoApi } from "../demo-backend";
import { setDemoEngagement } from "../demo-backend/state";
import { engagementConfig } from "../fixtures/engagementConfig";

// Claire, Evidence Screen tab I8: values count only when their document is on a calculation line.
const ID = engagementConfig.engagementId;
const KENT_GAS = "s1:stationary:natural-gas:facility-kent";

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
  setDemoEngagement({ ...engagementConfig, evidenceLines: [] });
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const recalculation = () => demoApi<Recalculation>(`/engagements/${ID}/recalculation`);
const tree = () => demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);

describe("demo backend: values off a calculation line are not counted", () => {
  it("leaves a document out while it is Unassigned, counts it again once it is back on its line", async () => {
    const before = await recalculation();
    expect(before.uncounted_values?.accepted_records ?? 0).toBe(0);
    const line = (await tree()).blocks.supporting.scopes
      .flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines)))
      .find((n) => n.line.key === KENT_GAS)!;
    const doc = line.documents[0].document_id;
    const move = (from: string, to: string) =>
      demoApi(`/engagements/${ID}/documents/${doc}/placements`, { method: "POST", body: { from, to } });

    await move(KENT_GAS, "supporting:unassigned");
    const off = await recalculation();
    expect(off.uncounted_values?.accepted_records).toBeGreaterThan(0);
    expect(off.uncounted_values?.documents.map((d) => d.document_id)).toContain(doc);
    expect(off.scope_totals.scope1!.total_co2e).toBeLessThan(before.scope_totals.scope1!.total_co2e);

    await move("supporting:unassigned", KENT_GAS);
    const back = await recalculation();
    expect(back.uncounted_values?.accepted_records ?? 0).toBe(0);
    expect(back.scope_totals.scope1!.total_co2e).toBeCloseTo(before.scope_totals.scope1!.total_co2e, 6);
  });

  it("words the notice by records and by documents, and says nothing for none", () => {
    const doc = (id: string, n: number) => ({ document_id: id, file_name: `${id}.pdf`, reason: "no_vehicle_group" as const, accepted_records: n });
    expect(uncountedMessage(undefined)).toBeNull();
    expect(uncountedMessage({ accepted_records: 0, documents: [] })).toBeNull();
    expect(uncountedMessage({ accepted_records: 1, documents: [doc("A", 1)] })).toBe("1 accepted record in 1 document not counted in the totals.");
    expect(uncountedMessage({ accepted_records: 12, documents: [doc("A", 5), doc("B", 7)] })).toBe(
      "12 accepted records in 2 documents not counted in the totals.",
    );
    const groups = uncountedGroups({ accepted_records: 12, documents: [doc("A", 5), doc("B", 7)] });
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ reason: "no_vehicle_group", records: 12 });
  });
});
