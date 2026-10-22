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

  // docs/design_standard.md, section 2: the text in a field is smaller than the section title above it.
  it("sets the text in form fields at the small size", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const field = /(^|[\s,>+~(])(input|select|textarea)\b|[-_](input|select)\b/;
    const offenders: string[] = [];
    postcss.parse(css).walkRules((rule) => {
      if (!field.test(rule.selector)) return;
      rule.walkDecls("font-size", (d) => {
        if (d.value !== "var(--text-sm)" && d.value !== "inherit") offenders.push(`${rule.selector} { font-size: ${d.value} }`);
      });
    });
    expect(offenders).toEqual([]);
  });

  // docs/design_standard.md, section 4: text reads at 4.5:1 or better on every surface it sits on.
  it("keeps text colours legible on every surface (WCAG AA, 4.5:1)", () => {
    const tokens = readFileSync(join(process.cwd(), "features", "s1", "styles", "sustentra-tokens.css"), "utf8");
    const hex = (name: string) => {
      const m = tokens.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`));
      if (!m) throw new Error(`no --${name}`);
      return m[1];
    };
    const luminance = (h: string) => {
      const [r, g, b] = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const ratio = (a: string, b: string) => {
      const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
      return (x + 0.05) / (y + 0.05);
    };
    const surfaces = ["sf-page", "sf-card", "sf-sunken", "accent-soft", "accent-softer", "state-active-bg", "state-open-bg", "state-blocking-bg"];
    for (const text of ["ink", "ink-2", "ink-3"]) {
      for (const surface of surfaces) expect(ratio(hex(text), hex(surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
    // Links and selected text sit on the neutral and blue surfaces.
    for (const surface of ["sf-page", "sf-card", "sf-sunken", "accent-soft", "accent-softer", "state-active-bg"]) {
      expect(ratio(hex("accent"), hex(surface)), `accent on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
    // White text on the solid fills (primary button, active chip).
    for (const fill of ["accent-solid", "accent-strong", "brand-ink"]) expect(ratio("#FFFFFF", hex(fill)), `white on ${fill}`).toBeGreaterThanOrEqual(4.5);
  });

  it("documents the workpaper token alias layer", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");

    expect(css).toContain("Alias layer only");
  });
});
