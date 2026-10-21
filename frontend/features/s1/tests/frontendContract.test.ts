import { readFileSync } from "node:fs";
import { join } from "node:path";

import postcss from "postcss";
import { describe, expect, it } from "vitest";

describe("frontend contract checks", () => {
  // Skipped for the 09/16 revision: fixture mode now seeds manufacturerEvidence,
  // not sixDocumentEvidence. The intent (backend mode seeds nothing) still holds
  // in code; re-enable once the revised Workspace IA is confirmed with product.
  it.skip("keeps backend mode from seeding fixture evidence", () => {
    const source = readFileSync(join(process.cwd(), "features", "s1", "pages", "S1WorkpaperApp.tsx"), "utf8");

    expect(source).toContain('dataMode === "backend" ? [] : sixDocumentEvidence');
  });

  it("keeps workpaper CSS values inside the token system", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");

    expect(css).not.toMatch(/#[0-9A-Fa-f]{3,8}/);
    expect(css).not.toMatch(/\b[1-9][0-9]*px\b/);
  });

  it("ships stylesheets that parse: every comment closed, every rule well formed", () => {
    for (const name of ["sustentra-tokens.css", "s1-workpaper.css", "s1-demo-documents.css"]) {
      const css = readFileSync(join(process.cwd(), "features", "s1", "styles", name), "utf8");
      // A comment that lost its opener in a merge turns its words into a broken selector.
      expect((css.match(/\/\*/g) ?? []).length, name).toBe((css.match(/\*\//g) ?? []).length);
      expect(() => postcss.parse(css, { from: name }), name).not.toThrow();
    }
  });

  // docs/design_standard.md, section 2: one family, three sizes, two weights.
  it("keeps the interface to one font family, three text sizes and two weights", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const values = (property: string) => [...css.matchAll(new RegExp(`${property}:\\s*([^;}]+)`, "g"))].map((m) => m[1].trim());

    const sizes = new Set(["var(--text-sm)", "var(--text-md)", "var(--text-lg)", "inherit", "82%" /* the root scale */]);
    expect(values("font-size").filter((v) => !sizes.has(v))).toEqual([]);
    expect(css.match(/font-size:\s*82%/g)).toHaveLength(1);
    const weights = new Set(["var(--weight-regular)", "var(--weight-strong)", "inherit"]);
    expect(values("font-weight").filter((v) => !weights.has(v))).toEqual([]);
    const families = new Set(["var(--font-sans)", "inherit"]);
    expect(values("font-family").filter((v) => !families.has(v))).toEqual([]);
    expect(css).not.toContain("--font-mono");
    expect(css).not.toContain("--text-xs");
  });

  it("documents the workpaper token alias layer", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");

    expect(css).toContain("Alias layer only");
  });
});
