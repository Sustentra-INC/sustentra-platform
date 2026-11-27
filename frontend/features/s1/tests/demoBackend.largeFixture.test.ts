import { afterEach, describe, expect, it, vi } from "vitest";

import "../demo-backend"; // loads the routes first (the route modules import each other)
import { buildTree } from "../demo-backend/evidenceTree";
import { largeFixtureSize } from "../demo-backend/largeFixture";

afterEach(() => vi.unstubAllEnvs());

const allDocuments = (tree: ReturnType<typeof buildTree>): string[] => [
  ...tree.blocks.summary.map((d) => d.document_id),
  ...tree.blocks.unassigned.map((d) => d.document_id),
  ...tree.blocks.supporting.unassigned.map((d) => d.document_id),
  ...tree.blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l2) => l2.lines.flatMap((n) => n.documents.map((d) => d.document_id))))),
];

describe("the demo's large engagement (dev only)", () => {
  it("is off in the normal demo", () => {
    expect(largeFixtureSize()).toBeNull();
    const normal = allDocuments(buildTree(null));
    expect(normal.some((id) => id.startsWith("DEMO-LARGE"))).toBe(false);
  });

  it("is never on in a production build, unless that run says so", () => {
    vi.stubEnv("NEXT_PUBLIC_S1_DEMO_DOCS", "500");
    vi.stubEnv("NODE_ENV", "production");
    expect(largeFixtureSize()).toBeNull();
    vi.stubEnv("NEXT_PUBLIC_S1_DEMO_DOCS_ALLOW_PRODUCTION", "1");
    expect(largeFixtureSize()).toBe(500);
  });

  it("ignores values that are not a sensible count", () => {
    for (const bad of ["abc", "0", "-5", "999999", ""]) {
      vi.stubEnv("NEXT_PUBLIC_S1_DEMO_DOCS", bad);
      expect(largeFixtureSize()).toBeNull();
    }
  });

  it("pads the tree to the asked size with consistent counts, Block 1 and unassigned documents", () => {
    const before = allDocuments(buildTree(null)).length;
    vi.stubEnv("NEXT_PUBLIC_S1_DEMO_DOCS", "500");
    const tree = buildTree(null);
    const ids = allDocuments(tree);
    expect(new Set(ids).size).toBe(ids.length); // no id twice
    expect(ids.length).toBeGreaterThanOrEqual(Math.max(500, before));
    expect(tree.blocks.summary.filter((d) => d.document_id.startsWith("DEMO-LARGE")).length).toBe(30);
    expect(tree.blocks.unassigned.filter((d) => d.document_id.startsWith("DEMO-LARGE")).length).toBe(10);
    for (const scope of tree.blocks.supporting.scopes) {
      for (const category of scope.categories) {
        for (const level2 of category.level2s) {
          for (const node of level2.lines) expect(node.counts.documents).toBe(node.documents.length);
          expect(level2.counts.documents).toBe(level2.lines.reduce((n, l) => n + l.counts.documents, 0));
        }
      }
    }
    expect(tree.blocks.summary_counts?.documents).toBe(tree.blocks.summary.length);
  });
});
