/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadWorkpaper, saveWorkpaperItem, workpaperKey } from "../api/workpaper";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));

describe("saved workpaper (requests, findings, examinations)", () => {
  it("loads each kind back into the shape the screens use", async () => {
    fetchMock.mockImplementation(() =>
      json({
        items: [
          { kind: "ask", item_key: "ASK-1", payload: { id: "ASK-1", whatIsNeeded: "Resend p.2" } },
          { kind: "finding", item_key: "FND-1", payload: { id: "FND-1", sentence: "Factor too low" } },
          { kind: "examination", item_key: "RECALC-scope1_total",
            payload: { dataPointId: "RECALC-scope1_total", examinationState: "finding_raised", nextActionWith: "me" } },
        ],
      })
    );
    const saved = await loadWorkpaper("ENG-1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/engagements/ENG-1/workpaper-items");
    expect(saved.asks.map((a) => a.id)).toEqual(["ASK-1"]);
    expect(saved.findings.map((f) => f.id)).toEqual(["FND-1"]);
    expect(saved.examinations).toEqual({ "RECALC-scope1_total": { examinationState: "finding_raised", nextActionWith: "me" } });
  });

  it("saves one item with PUT, keyed by a URL-safe id", async () => {
    fetchMock.mockImplementation(() => json({}));
    await saveWorkpaperItem("ENG-1", "ask", "ASK 1/x", { id: "ASK 1/x" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/engagements/ENG-1/workpaper-items/ask/ASK_1_x");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ payload: { id: "ASK 1/x" } });
    expect(workpaperKey("")).toBe("item");
  });
});
