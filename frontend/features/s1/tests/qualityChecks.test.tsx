/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { QualityCheck } from "../api/recalculation";
import { QualityChecksPanel, qualityIssueLines } from "../components/QualityChecksPanel";

const check = (over: Partial<QualityCheck>): QualityCheck => ({
  check: "Q-004", trigger: "overlap_same_source_different_document_id", severity: "warning",
  category: "purchased_electricity", facility: "Facility B", documents: ["ANNUAL", "Q1"],
  records: ["annual.pdf", "q1.docx"], message: "annual.pdf and q1.docx both cover 2025-01-01 to 2025-03-31.",
  detail: { overlap_days: 90 }, ...over,
});

const CHECKS: QualityCheck[] = [
  check({}),
  check({ check: "Q-001", trigger: "missing_month", severity: "warning", documents: ["ANNUAL"],
    message: "Facility A electricity: no bill covers Mar 2025.", detail: { missing_months: ["Mar 2025"] } }),
  check({ check: "Q-005", trigger: "cross_year_without_allocation_support", severity: "info", documents: ["DEC"],
    message: "dec.pdf runs 2024-12-15 to 2025-01-14.", detail: { share_percent: 45.2 } }),
];

describe("data quality checks", () => {
  it("lists what to look at, opened when something needs a look", () => {
    render(<QualityChecksPanel checks={CHECKS} />);
    expect(screen.getByText("2 to look at, 1 noted")).toBeTruthy();
    expect(screen.getByText(/no bill covers Mar 2025/)).toBeTruthy();
    expect(screen.getAllByText("Look at")).toHaveLength(2);
    expect(screen.getByText("Note")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Data quality checks/ }));
    expect(screen.queryByText(/no bill covers Mar 2025/)).toBeNull();
  });

  it("says when nothing was found", () => {
    render(<QualityChecksPanel checks={[]} />);
    expect(screen.getByText(/Nothing found/)).toBeTruthy();
  });

  it("gives each document a short line for the Evidence screen", () => {
    const name = (id: string) => ({ ANNUAL: "annual.pdf", Q1: "q1.docx", DEC: "dec.pdf" })[id] ?? id;
    expect(qualityIssueLines(CHECKS, "Q1", name)).toEqual(["Overlaps annual.pdf (90 days)"]);
    expect(qualityIssueLines(CHECKS, "DEC", name)).toEqual(["Crosses the reporting period (45.2% counted)"]);
    // A missing month is about bills that are not there: it shows on the results screen, not on a document.
    expect(qualityIssueLines(CHECKS, "ANNUAL", name)).toEqual(["Overlaps q1.docx (90 days)"]);
    expect(qualityIssueLines(undefined, "Q1", name)).toEqual([]);
  });
});
