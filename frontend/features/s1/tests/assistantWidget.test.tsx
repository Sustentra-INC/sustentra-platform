/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";

import { AssistantWidget, respond } from "../components/AssistantWidget";
import type { NavKey } from "../components/S1Chrome";

const PAGES: NavKey[] = ["dashboard", "setup", "upload", "evidence", "requests", "coverage", "results", "output"];
const QUESTIONS = [
  "Explain materiality", "What emission factor is used?", "What does coverage mean?", "scope 2 market-based",
  "scope 1 diesel", "refrigerant R-22", "what does held mean", "how do I accept a value", "something else",
];
// Names and figures that belong to the fixture demo engagement only.
const DEMO_ONLY = /cascade|tualatin|kent cannery|modesto|13,540|677|3,910|4,205|182,400|148|34 \/ 46/i;

beforeAll(() => {
  Element.prototype.scrollTo = () => {}; // jsdom has no layout
});

describe("assistant on live data", () => {
  it("explains methods and never quotes the demo engagement's figures", () => {
    for (const page of PAGES) {
      for (const question of QUESTIONS) {
        expect(respond(question, page, true)).not.toMatch(DEMO_ONLY);
      }
    }
    expect(respond("refrigerant", "results", true)).toContain("(P_N − C_N) + P_S + (C_D − R_D)");
  });

  it("briefs the live page without demo figures", () => {
    render(<AssistantWidget page="results" live />);
    fireEvent.click(screen.getByRole("button", { name: "Open Sustentra assistant" }));
    const panel = screen.getByRole("dialog", { name: "Sustentra assistant" });
    expect(panel.textContent).toContain("compares each reported data point with its recalculated value");
    expect(panel.textContent).not.toMatch(DEMO_ONLY);
  });

  it("keeps the demo briefing in fixture mode", () => {
    render(<AssistantWidget page="results" />);
    fireEvent.click(screen.getByRole("button", { name: "Open Sustentra assistant" }));
    expect(screen.getByRole("dialog", { name: "Sustentra assistant" }).textContent).toContain("13,540");
  });
});
