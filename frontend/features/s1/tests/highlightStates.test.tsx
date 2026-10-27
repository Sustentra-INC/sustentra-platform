/* @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import postcss from "postcss";
import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", () => ({
  // A one-page PDF, or a text file of one line for the content view.
  api: vi.fn((path: string) =>
    Promise.resolve(path.endsWith("/content") ? { kind: "lines", truncated: false, lines: ["Total kWh Used: 182,400 kWh"] } : { pages: 1 })
  ),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { BackendPageView } from "../components/BackendPageView";
import { DocumentContentView } from "../components/DocumentContentView";
import type { PageMark } from "../types/review";
import { markState } from "../utils/markState";

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
    expect(screen.getByRole("button", { current: true })).toHaveProperty("title", "Utility: Puget Sound Energy, requested");
    expect(container.querySelector(".s1-pv__mark")).toBeNull();
  });

  it("still shows where the selected value is when its page cannot be picked from", async () => {
    const { container } = render(<BackendPageView documentId="DOC" span={MARKS[0].span} marks={MARKS} />);
    await screen.findByRole("img");
    expect(Array.from(container.querySelectorAll(".s1-pv__box")).map((b) => b.className)).toEqual(["s1-pv__box s1-pv__box--alone is-sel"]);
  });
});

describe("a highlight shared by several values", () => {
  // An amount and its unit read from one line: the amount accepted, the unit still to review.
  const line = span(0.4);
  const SHARED: PageMark[] = [
    { id: "kwh", span: line, anchor: { kind: "line", line: 1 }, rawText: "182,400", label: "Electricity consumed: 182.4 MWh", reviewState: "accepted" },
    { id: "unit", span: line, anchor: { kind: "line", line: 1 }, rawText: "182,400", label: "Electricity unit: MWh", reviewState: "to_review" },
  ];
  const NAME = "Select Electricity consumed: 182.4 MWh, accepted · Electricity unit: MWh, to review";

  it("takes the most urgent state of its values, as the demo's documents do", () => {
    const of = (...states: PageMark["reviewState"][]) => markState(states.map((reviewState) => ({ reviewState })));
    expect(of("accepted", "to_review")).toBe("to_review");
    expect(of("accepted", "corrected", "requested")).toBe("requested");
    expect(of("accepted", "corrected")).toBe("corrected");
    expect(of("accepted")).toBe("accepted");
  });

  it("reads 'to review' on a page, and names each value with its state", async () => {
    const { container } = render(<BackendPageView documentId="DOC" span={null} marks={SHARED} onPickMark={vi.fn()} />);
    const box = await screen.findByRole("button", { name: NAME });
    expect(box.className).toBe("s1-pv__box s1-pv__box--to_review");
    expect(box.getAttribute("title")).toBe(NAME.replace("Select ", ""));
    expect(container.querySelectorAll(".s1-pv__box")).toHaveLength(1);
  });

  it("reads 'to review' in a file's line too, with the same name", async () => {
    render(<DocumentContentView documentId="DOC" marks={SHARED} selectedId={null} />);
    const mark = await screen.findByRole("button", { name: NAME });
    expect(mark.className).toBe("s1-cv__mark s1-cv__mark--to_review");
    expect(mark.textContent).toBe("182,400");
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
