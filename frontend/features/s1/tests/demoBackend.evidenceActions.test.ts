/* @vitest-environment jsdom */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import type { EvidenceActivityItem, EvidenceTree, LineAnswer } from "../api/evidenceTree";
import { demoApi } from "../demo-backend";
import { compactMoves } from "../demo-backend/evidenceActions";
import { demoDecisions, setDemoEngagement } from "../demo-backend/state";
import { engagementConfig } from "../fixtures/engagementConfig";
import { ApiError } from "../../../lib/api";

const ID = engagementConfig.engagementId;
const KENT_GAS = "s1:stationary:natural-gas:facility-kent";
const PROPANE = { category: "stationary", level2_label: "Kerosene", anchor_kind: "facility", anchor_id: "facility-kent", label: "Kerosene at Kent" };
const PROPANE_KEY = "s1:stationary:kerosene:facility-kent";
const lines = `/engagements/${ID}/evidence-lines`;

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
  setDemoEngagement({ ...engagementConfig, evidenceLines: [] });
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const refused = async (promise: Promise<unknown>): Promise<ApiError> => {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("expected the request to be refused");
};

const tree = () => demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
const docsOn = (t: EvidenceTree, key: string) =>
  t.blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines))).find((n) => n.line.key === key)?.documents.map((d) => d.document_id) ?? [];

describe("demo backend: Evidence actions", () => {
  it("compacts a chain of moves the way the server does", () => {
    expect(compactMoves([{ from: "a", to: "b" }, { from: "b", to: "a" }])).toEqual([{ from: "b", to: "a" }]);
    expect(compactMoves([{ from: "a", to: "b" }, { from: "b", to: "c" }])).toEqual([{ from: "a", to: "c" }, { from: "b", to: "c" }]);
    expect(compactMoves([{ from: "x", to: "x" }])).toEqual([]);
    const pingPong = Array.from({ length: 1000 }, (_, i) => (i % 2 ? { from: "b", to: "a" } : { from: "a", to: "b" }));
    expect((compactMoves(pingPong) ?? pingPong).length).toBeLessThanOrEqual(2);
  });

  it("adds a line stamped with the signed-in person, and refuses a duplicate or a bad anchor", async () => {
    const created = await demoApi<LineAnswer>(lines, { method: "POST", body: PROPANE });
    expect(created.line).toMatchObject({ created_by: engagementConfig.signedInLogin });
    expect(created.evidenceLines).toHaveLength(1);
    expect((await refused(demoApi(lines, { method: "POST", body: PROPANE }))).status).toBe(409);
    expect((await refused(demoApi(lines, { method: "POST", body: { ...PROPANE, anchor_id: "facility-gone" } }))).status).toBe(422);
    expect((await refused(demoApi(lines, { method: "POST", body: { ...PROPANE, level2_label: "燃料" } }))).status).toBe(422);
    expect(docsOn(await tree(), PROPANE_KEY)).toEqual([]);
  });

  it("moves a document, refuses a stale move, and deletes a line by moving its documents to Unassigned", async () => {
    const t = await tree();
    const doc = docsOn(t, KENT_GAS)[0];
    const move = (from: string, to: string) =>
      demoApi<{ payload: { placements: { from: string; to: string }[] } }>(`/engagements/${ID}/documents/${doc}/placements`, { method: "POST", body: { from, to } });
    await move(KENT_GAS, PROPANE_KEY);
    expect(docsOn(await tree(), PROPANE_KEY)).toEqual([doc]);
    expect((await refused(move(KENT_GAS, "supporting:unassigned"))).status).toBe(409);
    expect((await refused(move(PROPANE_KEY, "s1:stationary:gone:facility-kent"))).status).toBe(422);

    const deleted = await demoApi<LineAnswer>(`${lines}/${encodeURIComponent(PROPANE_KEY)}`, { method: "DELETE" });
    expect(deleted.documents_moved).toBe(1);
    const after = await tree();
    expect(after.blocks.supporting.unassigned.map((d) => d.document_id)).toContain(doc);
    expect(demoDecisions().get(doc)?.placements?.length).toBeLessThanOrEqual(2);

    await demoApi(lines, { method: "POST", body: PROPANE }); // the same key again: the document stays in Unassigned
    const again = await tree();
    expect(again.blocks.supporting.unassigned.map((d) => d.document_id)).toContain(doc);
    expect(docsOn(again, PROPANE_KEY)).toEqual([]);
  });

  it("renames a line and logs every change with who made it, newest first", async () => {
    const renamed = await demoApi<LineAnswer>(`${lines}/${encodeURIComponent(PROPANE_KEY)}`, { method: "PATCH", body: { label: "燃料 tank" } });
    expect(renamed.line?.label).toBe("燃料 tank");
    expect((await refused(demoApi(`${lines}/${encodeURIComponent(KENT_GAS)}`, { method: "PATCH", body: { label: "x" } }))).status).toBe(404);
    expect((await refused(demoApi(`${lines}/${encodeURIComponent(PROPANE_KEY)}`, { method: "PATCH", body: { label: "  " } }))).status).toBe(422);
    const { items } = await demoApi<{ items: EvidenceActivityItem[] }>(`/engagements/${ID}/evidence-activity`);
    expect(items[0]).toMatchObject({ event_type: "evidence_line_renamed", old_label: "Kerosene at Kent", new_label: "燃料 tank" });
    expect(items.map((i) => i.event_type)).toEqual(expect.arrayContaining(["evidence_line_created", "evidence_document_moved", "evidence_line_deleted"]));
    expect(items.every((i) => i.actor_name && i.actor_name !== "C. Yang")).toBe(true);
    expect(JSON.stringify(items)).not.toMatch(/\.pdf/);
  });
});
