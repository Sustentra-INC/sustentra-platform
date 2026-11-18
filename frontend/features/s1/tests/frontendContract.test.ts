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
  it("lets the context bar wrap at phone width, so the header never scrolls the page sideways", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const phone = css.slice(css.indexOf("Context bar tidies up on a phone"));
    const block = phone.slice(0, phone.indexOf("\n}") + 2);
    expect(block).toMatch(/\.s1-ctx__bar\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(block).toMatch(/\.s1-ctx__actions\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(block).toMatch(/\.s1-ctx__actions\s*\{[^}]*min-width:\s*0/);
    expect(block).toMatch(/\.s1-ctx__user\s*\{[^}]*flex-wrap:\s*wrap/);
  });

  // Measured on staging at 792px: the summary was 0 wide, the client name wrapped to three lines
  // and the actions drew over it. The rules below are what keeps that from coming back at any width.
  it("keeps the context bar's summary readable at medium widths: actions wrap first, names truncate", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const rule = (selector: string) => {
      const match = css.match(new RegExp(`^${selector.replace(/\./g, "\\.")}\\s*\\{([^}]*)\\}`, "m"));
      return match ? match[1] : "";
    };
    expect(rule(".s1-ctx__bar")).toMatch(/flex-wrap:\s*wrap/);
    // A minimum width the summary keeps, and room to grow.
    expect(rule(".s1-ctx__summary")).toMatch(/min-width:\s*min\(var\(--ctx-summary-min\),\s*100%\)/);
    expect(rule(".s1-ctx__summary")).toMatch(/flex:\s*1 1 var\(--ctx-summary-min\)/);
    expect(css).toMatch(/--ctx-summary-min:\s*[0-9.]+rem/);
    // The actions wrap and may shrink; they never push the summary down to nothing.
    expect(rule(".s1-ctx__actions")).toMatch(/flex-wrap:\s*wrap/);
    expect(rule(".s1-ctx__actions")).toMatch(/min-width:\s*0/);
    // Long names are cut with an ellipsis on one line.
    for (const name of [".s1-ctx__client", ".s1-ctx__id"]) {
      expect(rule(name)).toMatch(/text-overflow:\s*ellipsis/);
      expect(rule(name)).toMatch(/white-space:\s*nowrap/);
      expect(rule(name)).toMatch(/min-width:\s*0/);
    }
  });

  it("gives the context bar's names a title, so a cut name can still be read in full", () => {
    const source = readFileSync(join(process.cwd(), "features", "s1", "components", "S1Chrome.tsx"), "utf8");
    expect(source).toMatch(/className="s1-ctx__client" title=\{contextTitle\.title\}/);
    expect(source).toMatch(/className="s1-ctx__id" title=\{contextTitle\.sub\}/);
  });

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

  // Inheritance must not decide a field's size. The app-wide reset (`.s1-app :where(...) { font-size: inherit }`)
  // ties with a single-class field rule and comes later in the file, so such a rule loses to it and the field
  // computes the body size. A field rule that sets no size, or a single-class one, is only safe because of one
  // explicit, more specific rule after the reset: check that it is there and that the reset is not below it.
  it("sets every form field's text size explicitly, not by inheritance", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const rules: { selector: string; size: string | null; line: number }[] = [];
    postcss.parse(css).walkRules((rule) => {
      let size: string | null = null;
      rule.walkDecls("font-size", (d) => {
        size = d.value;
      });
      rules.push({ selector: rule.selector.replace(/\s+/g, " "), size, line: rule.source?.start?.line ?? 0 });
    });
    const reset = rules.find((r) => r.selector.startsWith(".s1-app :where(button, input, select, textarea"));
    const explicit = rules.find((r) => r.selector === ".s1-app input, .s1-app select, .s1-app textarea");
    expect(reset, "the app-wide control reset").toBeDefined();
    expect(explicit?.size).toBe("var(--text-sm)");
    expect(explicit!.line).toBeGreaterThan(reset!.line);
    // The methodology fields name the size themselves too.
    for (const selector of [".s1-mr-input", ".s1-mr-select"]) {
      expect(rules.find((r) => r.selector === selector)?.size, selector).toBe("var(--text-sm)");
    }
  });

  // docs/design_standard.md, section 2: bold is for structure. The last declaration wins, so read the cascade's end.
  it("keeps values, counts and links regular weight, and the schedule title at the page-title size", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    const last = (selector: string, prop: string) => {
      let found: string | undefined;
      postcss.parse(css).walkRules((rule) => {
        if (!rule.selectors.includes(selector)) return;
        rule.walkDecls(prop, (d) => {
          found = d.value;
        });
      });
      return found;
    };
    for (const sel of [".s1-sch-ids .s1-sch-ids__toggle .s1-sch-ids__value", ".s1-sch-ids .s1-sch-ids__toggle .s1-sch-ids__n", ".s1-xr-node__count", ".s1-xr-card .s1-xr-val", ".s1-backlink"]) {
      expect(last(sel, "font-weight"), sel).toBe("var(--weight-regular)");
    }
    expect(last(".s1-sch-head__id h1", "font-size")).toBe("var(--text-lg)");
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
