import { beforeEach, describe, expect, it } from "vitest";

import type { LineTraceResponse } from "../api/calcTrace";
import type { Recalculation } from "../api/recalculation";
import { demoApi } from "../demo-backend";
import { resetDemoDecisions } from "../demo-backend/calcTrace/decisions";

const E = "ENG-CASCADE-2025";
let lineKey = "";
const base = () => `/engagements/${E}/calculation-lines/${encodeURIComponent(lineKey)}`;
const post = (path: string, body: unknown) => demoApi<Record<string, unknown>>(`${base()}${path}`, { method: "POST", body });
const trace = async () => (await demoApi<LineTraceResponse>(`/engagements/${E}/recalculation/lines/${encodeURIComponent(lineKey)}/trace`)).trace!;
const failure = async (p: Promise<unknown>) => p.then(() => null, (e: { status: number; detail: string }) => e);

beforeEach(async () => {
  resetDemoDecisions();
  lineKey = (await demoApi<Recalculation>(`/engagements/${E}/recalculation`)).calculation_lines![0].key;
});

describe("demo calculation decisions", () => {
  it("shows an edit on the trace, keeps the unit, and reverts it", async () => {
    await post("/inputs/ef.CO2/recomputed", { action: "edit", value: "54.5", unit: "kg CO₂/MMBtu", reason: "Supplier certificate" });
    const side = (await trace()).inputs["ef.CO2"].recomputed!;
    expect(side.decision).toMatchObject({ status: "edited", value: 54.5, unit: "kg CO₂/MMBtu", reason: "Supplier certificate", kind: "reviewer_entered" });
    await post("/inputs/ef.CO2/recomputed", { action: "revert" });
    expect((await trace()).inputs["ef.CO2"].recomputed!.decision).toBeUndefined();
  });

  it("refuses an edit without a reason (422), a wrong unit (422) and text for a number (422)", async () => {
    expect((await failure(post("/inputs/ef.CO2/recomputed", { action: "edit", value: 54 })))?.status).toBe(422);
    expect((await failure(post("/inputs/ef.CO2/recomputed", { action: "edit", value: 54, unit: "lb/MMBtu", reason: "x" })))?.status).toBe(422);
    expect((await failure(post("/inputs/ef.CO2/recomputed", { action: "edit", value: "abc", reason: "x" })))?.status).toBe(422);
  });

  it("rejects with a reason (422 without), then refuses a second decision and a revert of nothing (409)", async () => {
    expect((await failure(post("/inputs/ef.CH4/recomputed", { action: "reject" })))?.status).toBe(422);
    expect((await failure(post("/inputs/ef.CH4/recomputed", { action: "revert" })))?.status).toBe(409);
    await post("/inputs/ef.CH4/recomputed", { action: "reject", reason: "Wrong fuel" });
    expect((await trace()).inputs["ef.CH4"].recomputed!.decision).toMatchObject({ status: "rejected", reason: "Wrong fuel" });
    expect((await failure(post("/inputs/ef.CH4/recomputed", { action: "reject", reason: "again" })))?.status).toBe(409);
  });

  it("decides on a row of a summed input", async () => {
    const row = (await trace()).inputs["activity.total"].rows![0];
    await post(`/inputs/activity.total/${encodeURIComponent(row.id)}/recomputed`.replace(/%2F/g, "/"), { action: "edit", value: 1000, reason: "Corrected" });
    const decided = (await trace()).inputs["activity.total"].rows![0].recomputed!;
    expect(decided.decision).toMatchObject({ status: "edited", value: 1000 });
    expect((await failure(post("/inputs/activity.total/no-such-row/recomputed", { action: "reject", reason: "x" })))?.status).toBe(404);
  });

  it("chooses an option: a reason is needed off the automatic one, an unavailable option is 409, an unknown one 422", async () => {
    const choice = (await trace()).choices.find((c) => c.id.startsWith("equation:"))!;
    const path = `/choices/${encodeURIComponent(choice.id)}`;
    expect((await failure(post(path, { action: "choose", option_id: "eq2", reason: "x" })))?.status).toBe(409);
    expect((await failure(post(path, { action: "choose", option_id: "nope" })))?.status).toBe(422);
    // the automatic option needs no reason
    await post(path, { action: "choose", option_id: choice.chosen });
    expect((await trace()).choices.find((c) => c.id === choice.id)!.decision).toMatchObject({ status: "edited", value: choice.chosen });
    expect((await failure(post(path, { action: "accept" })))?.status).toBe(409); // no suggestion, and already decided
  });

  it("answers 404 for a line or a choice the engagement does not have", async () => {
    expect((await failure(demoApi(`/engagements/${E}/calculation-lines/nope/choices/method`, { method: "POST", body: { action: "revert" } })))?.status).toBe(404);
    expect((await failure(post("/choices/nope", { action: "revert" })))?.status).toBe(404);
  });

  it("marks decidable like the backend and refuses an edit on a GWP with a coded 409, but never a reject", async () => {
    const t = await trace();
    expect(t.inputs["activity.total"].decidable).toBe(true);
    expect(t.inputs["ef.CO2"].decidable).toBe(true);
    for (const id of ["gwp.CO2", "unit_conversion", "share"]) {
      expect(t.inputs[id].decidable).toBe(false);
      expect(t.inputs[id].why_not).toBeTruthy();
    }
    expect(t.inputs["ef.CO2"].why_not).toBeUndefined();
    const refused = (await failure(post("/inputs/gwp.CO2/recomputed", { action: "edit", value: 30, reason: "x" }))) as unknown as { status: number; body: { code: string } };
    expect(refused.status).toBe(409);
    expect(refused.body.code).toBe("not_decidable");
    await post("/inputs/gwp.CO2/recomputed", { action: "reject", reason: "x" });
    await post("/inputs/gwp.CO2/recomputed", { action: "revert" });
  });

  it("forgets every decision on reset", async () => {
    await post("/inputs/ef.CO2/recomputed", { action: "reject", reason: "Wrong" });
    resetDemoDecisions();
    expect((await trace()).inputs["ef.CO2"].recomputed!.decision).toBeUndefined();
  });
});
