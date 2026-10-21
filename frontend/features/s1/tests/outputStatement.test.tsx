/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OutputScreen } from "../components/OutputScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import { materialityFraction, statementFigures } from "../utils/outputStatement";
import { buildResultBoxes, formatTonnes } from "../utils/verificationTable";

describe("the statement on Output", () => {
  it("reports the same totals as Verification results", () => {
    const boxes = Object.fromEntries(buildResultBoxes(verificationLines).map((b) => [b.key, b.totals]));
    const s = statementFigures(verificationLines, "5%");
    expect(s.location.reported).toBeCloseTo(boxes.scope1.reported + boxes.scope2_location.reported);
    expect(s.location.verified).toBeCloseTo(boxes.scope1.recomputed + boxes.scope2_location.recomputed);
    expect(s.market.verified).toBeCloseTo(boxes.scope1.recomputed + boxes.scope2_market.recomputed);
    // Rows add up to the totals, box by box.
    const sum = (basis: string | null) => s.rows.filter((r) => (basis ? r.basis === basis : r.label.startsWith("Scope 1"))).reduce((t, r) => t + r.reported, 0);
    expect(sum(null)).toBeCloseTo(boxes.scope1.reported);
    expect(sum("Location-based")).toBeCloseTo(boxes.scope2_location.reported);
  });

  it("marks the conclusion as a draft while a difference is above materiality", () => {
    const s = statementFigures(verificationLines, engagementConfig.materialityThreshold);
    expect(s.materialBoxes.map((b) => b.title)).toEqual(["Scope 2, market-based"]);
    render(<OutputScreen engagement={engagementConfig} lines={verificationLines} />);
    expect(screen.getByRole("note").textContent).toMatch(/^Draft: Scope 2, market-based differs from the evidence by \+8\.2%/);
    expect(screen.getByText(formatTonnes(s.location.verified), { selector: ".s1-out-total td" })).toBeTruthy();
    // With a threshold above every difference, nothing is flagged.
    expect(statementFigures(verificationLines, "10%").materialBoxes).toEqual([]);
  });

  it("reads the threshold as Setup writes it", () => {
    expect(materialityFraction("5%")).toBe(0.05);
    expect(materialityFraction("2.5% of total")).toBe(0.025);
    expect(materialityFraction(undefined)).toBe(0.05);
  });
});
