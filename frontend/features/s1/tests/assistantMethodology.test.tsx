/* @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({ calls: [] as string[], reply: null as unknown, fail: false }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(async (path: string, options?: { method?: string }) => {
    if (path.includes("/methodology-assistant/")) {
      mock.calls.push(`${options?.method ?? "GET"} ${path}`);
      if (mock.fail) throw new Error("404");
      return mock.reply;
    }
    return (await import("../demo-backend")).demoApi(path, options as never);
  }),
}));

import { demoApi } from "../demo-backend";
import { resetDemoMethodology } from "../demo-backend/methodology";
import { runAssistantToolAsync } from "../assistant/methodologyTools";
import { ASSISTANT_TOOLS, TOOL_ACTIVITY, systemPrompt } from "../assistant/spec";
import type { AssistantData } from "../assistant/tools";

const data = { engagement: { engagementId: "ENG-1" } } as unknown as AssistantData;

beforeEach(() => {
  mock.calls = [];
  mock.fail = false;
});

describe("the assistant's Methodology tools", () => {
  it("are declared, labelled, and the prompt grounds the answer in them and keeps the model's name out", () => {
    const names = ASSISTANT_TOOLS.map((t) => t.name);
    expect(names).toEqual(expect.arrayContaining(["explain_methodology_suggestion", "get_methodology_summary"]));
    for (const name of names) expect(TOOL_ACTIVITY[name]).toBeTruthy();
    const prompt = systemPrompt("methodology");
    expect(prompt).toContain("explain_methodology_suggestion");
    expect(prompt).toMatch(/never write a rationale yourself/);
    expect(prompt).toMatch(/never the model's name or id/);
  });

  it("read the engagement's own endpoints with GET only and hand back the server's answer", async () => {
    mock.reply = { matches: [{ field_id: "consolidation_approach", explanation: { reason: "R.", items: [{ quote: "q", page: 4 }] } }] };
    const out = JSON.parse(await runAssistantToolAsync("explain_methodology_suggestion", { question: "consolidation approach" }, data));
    expect(out.matches[0].explanation.items[0]).toMatchObject({ quote: "q", page: 4 });
    expect(mock.calls).toEqual(["GET /engagements/ENG-1/methodology-assistant/explain?q=consolidation+approach"]);
    mock.reply = { suggestions: [], count: 0 };
    await runAssistantToolAsync("get_methodology_summary", { document: "GHG statement" }, data);
    expect(mock.calls[1]).toBe("GET /engagements/ENG-1/methodology-assistant/summary?document=GHG+statement");
  });

  it("tell the model plainly when the server refuses (another organization's engagement), without guessing", async () => {
    mock.fail = true;
    const out = JSON.parse(await runAssistantToolAsync("explain_methodology_suggestion", { question: "x" }, data));
    expect(out.error).toMatch(/could not be read/);
    expect(out.matches).toBeUndefined();
  });

  it("work in the demo too: the stored quote and page, and an honest 'reason not recorded'", async () => {
    resetDemoMethodology();
    const base = "/engagements/ENG-CASCADE-2025";
    await demoApi(`${base}/methodology-review/prefill`, { method: "POST", body: {} });
    const out = await demoApi<{ matches: { field_id: string; explanation: { reason: string | null; reason_note: string | null; items: { quote: string; location: string }[] } }[] }>(
      `${base}/methodology-assistant/explain?q=${encodeURIComponent("why was operational control suggested for the consolidation approach")}`
    );
    expect(out.matches[0].field_id).toBe("consolidation_approach");
    expect(out.matches[0].explanation.reason).toBeNull();
    expect(out.matches[0].explanation.reason_note).toMatch(/Reason not recorded/);
    expect(out.matches[0].explanation.items[0].quote).toMatch(/operational control approach/);
    expect(out.matches[0].explanation.items[0].location).toBe("page 1");
    const none = await demoApi<{ matches: unknown[]; note: string }>(`${base}/methodology-assistant/explain?q=zzzz`);
    expect(none.matches).toEqual([]);
    const summary = await demoApi<{ count: number }>(`${base}/methodology-assistant/summary`);
    expect(summary.count).toBeGreaterThan(5);
  });
});
