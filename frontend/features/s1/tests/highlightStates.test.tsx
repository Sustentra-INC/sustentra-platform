/* @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import postcss from "postcss";
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({
  api: vi.fn().mockResolvedValue({ pages: 1 }),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { BackendPageView } from "../components/BackendPageView";
import type { PageMark } from "../types/review";

/**
 * A figure on a client's document is highlighted by its review state, the same way in the
 * demo's drawn documents (.s1-dd-hl) and on staging's uploaded pages (.s1-pv__box) and files
 * (.s1-cv__mark): a highlighter stroke from the shared --hl-* tokens. The selected figure gets
 * the accent ring, never the amber of "to review".
 */
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {}; // jsdom has no layout
});

const span = (y: number) => ({ page: 1, x: 0.1, y, w: 0.3, h: 0.02 });
const MARKS: PageMark[] = [
  { id: "kwh", span: span(0.4), label: "Electricity consumed: 182.4 MWh", reviewState: "to_review" },
  { id: "account", span: span(0.2), label: "Account number: ACC-77", reviewState: "accepted" },
  { id: "start", span: span(0.3), label: "Service period start: 2025-02-01", reviewState: "corrected" },
  { id: "supplier", span: span(0.1), label: "Utility: Puget Sound Energy", reviewState: "requested" },
];

describe("an uploaded page's highlights", () => {
  it("are drawn by review state, the selected one ringed, with no separate amber box", async () => {
    const { container } = render(<BackendPageView documentId="DOC" span={MARKS[3].span} marks={MARKS} onPickMark={vi.fn()} />);
    await screen.findAllByRole("button", { name: /^Select / });
    const boxes = Array.from(container.querySelectorAll(".s1-pv__box"));
    expect(boxes.map((b) => b.className)).toEqual([
      "s1-pv__box s1-pv__box--to_review",
      "s1-pv__box s1-pv__box--accepted",
      "s1-pv__box s1-pv__box--corrected",
      "s1-pv__box s1-pv__box--requested is-sel",
    ]);
    expect(screen.getByRole("button", { current: true })).toHaveProperty("title", "Utility: Puget Sound Energy");
    expect(container.querySelector(".s1-pv__mark")).toBeNull();
  });

  it("still shows where the selected value is when its page cannot be picked from", async () => {
    const { container } = render(<BackendPageView documentId="DOC" span={MARKS[0].span} marks={MARKS} />);
    await screen.findByRole("img");
    expect(Array.from(container.querySelectorAll(".s1-pv__box")).map((b) => b.className)).toEqual(["s1-pv__box s1-pv__box--alone is-sel"]);
  });
});

describe("the highlight colours", () => {
  const sheet = (name: string) => postcss.parse(readFileSync(join(process.cwd(), "features", "s1", "styles", name), "utf8"));
  const decl = (root: postcss.Root, selector: string, prop: string) => {
    let value: string | undefined;
    root.walkRules((rule) => {
      if (rule.parent?.type === "atrule") return;
      if (rule.selectors.includes(selector)) rule.walkDecls(prop, (d) => void (value = d.value));
    });
    return value;
  };
  const demo = sheet("s1-demo-documents.css");
  const workpaper = sheet("s1-workpaper.css");

  it("are one set for the demo's documents and for uploaded pages and files", () => {
    const states = [
      ["to_review", ".s1-dd-hl", ".s1-pv__box", ".s1-cv__mark"],
      ["accepted", ".s1-dd-hl--accepted", ".s1-pv__box--accepted", ".s1-cv__mark--accepted"],
      ["corrected", ".s1-dd-hl--corrected", ".s1-pv__box--corrected", ".s1-cv__mark--corrected"],
      ["requested", ".s1-dd-hl--requested", ".s1-pv__box--requested", ".s1-cv__mark--requested"],
    ];
    for (const [state, demoRule, pageRule, contentRule] of states) {
      const token = `var(--hl-${state.replace("_", "-")})`;
      expect(decl(demo, demoRule, "background"), demoRule).toBe(token);
      expect(decl(workpaper, pageRule, "background"), pageRule).toBe(token);
      expect(decl(workpaper, contentRule, "background"), contentRule).toBe(token);
    }
    // Four states, four colours: requested and corrected can be told apart.
    const tokens = readFileSync(join(process.cwd(), "features", "s1", "styles", "sustentra-tokens.css"), "utf8");
    const fills = ["to-review", "accepted", "corrected", "requested"].map((s) => new RegExp(`--hl-${s}:\\s*([^;]+);`).exec(tokens)?.[1]);
    expect(new Set(fills).size).toBe(4);
  });

  it("ring the selected figure in the accent, never the amber of an open state", () => {
    for (const selector of [".s1-pv__box.is-sel", ".s1-cv__mark.s1-cv__mark--selected"]) {
      expect(decl(workpaper, selector, "box-shadow"), selector).toContain("var(--accent-solid)");
    }
    const css = workpaper.toString();
    expect(css).not.toContain(".s1-pv__mark");
    let reduced = "";
    workpaper.walkAtRules("media", (at) => {
      if (at.params.includes("prefers-reduced-motion")) reduced += at.toString();
    });
    expect(reduced).toContain(".s1-pv__box.is-sel");
  });
});
