import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: { path: string; options: { method?: string; body?: unknown } }[] = [];
vi.mock("../../../lib/api", () => ({
  api: vi.fn(async (path: string, options: { method?: string; body?: unknown }) => {
    calls.push({ path, options });
    return { kind: "document", item_key: "D1", payload: {} };
  }),
}));

import { saveWorkpaperItem } from "../api/workpaper";

describe("saving a document's workpaper item", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("never sends the placements: they change only through the Evidence actions", async () => {
    await saveWorkpaperItem("e1", "document", "D1", {
      documentId: "D1",
      facilityId: "F1",
      note: "check",
      placements: [{ from: "a", to: "b" }],
    });
    expect(calls[0].options.method).toBe("PUT");
    expect(calls[0].options.body).toEqual({ payload: { documentId: "D1", facilityId: "F1", note: "check" } });
  });

  it("leaves every other kind as it is", async () => {
    await saveWorkpaperItem("e1", "finding", "F-1", { placements: [1], text: "x" });
    expect(calls[0].options.body).toEqual({ payload: { placements: [1], text: "x" } });
  });
});
