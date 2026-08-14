import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("frontend contract checks", () => {
  it("keeps backend mode from seeding fixture evidence", () => {
    const source = readFileSync(join(process.cwd(), "features", "s1", "pages", "S1WorkpaperApp.tsx"), "utf8");

    expect(source).toContain('dataMode === "backend" ? [] : sixDocumentEvidence');
  });

  it("keeps workpaper CSS values inside the token system", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");

    expect(css).not.toMatch(/#[0-9A-Fa-f]{3,8}/);
    expect(css).not.toMatch(/\b[1-9][0-9]*px\b/);
  });

  it("documents the workpaper token alias layer", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");

    expect(css).toContain("Alias layer only");
  });
});
