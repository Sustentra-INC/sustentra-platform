/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { DashboardScreen } from "../components/DashboardScreen";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { dashboardFigures, engagementActivity, type DashboardFigures } from "../utils/engagementActivity";

const FIGURES: DashboardFigures = {
  documents: 152,
  documentsReadable: 141,
  blockedDocuments: 1,
  documentsNeedingYou: 2,
  valuesReviewed: 41,
  valuesToReview: 67,
  requestsNotSent: 1,
  requestsAwaitingClient: 1,
  requestsResolved: 0,
  requestsRaised: 2,
  coverage: { present: 9, missing: 3, notApplicable: 1, outOfScope: 1 },
  dataPointsCalculated: 0,
  dataPointsExamined: 0,
  findings: 0,
};

describe("dashboard: progress only", () => {
  it("shows the timeline, the two meters and what needs attention, most urgent first", () => {
    const onNavigate = vi.fn();
    render(<DashboardScreen engagement={engagementConfig} figures={FIGURES} onNavigate={onNavigate} />);

    const timeline = screen.getByRole("list", { name: "Engagement timeline" });
    expect(within(timeline).getAllByRole("button").map((b) => b.textContent)).toEqual([
      expect.stringContaining("Setup"),
      expect.stringContaining("Evidence intake152 documents in"),
      expect.stringContaining("67 values to review"),
      expect.stringContaining("Assessment"),
      expect.stringContaining("Statement not issued"),
    ]);
    expect(screen.getByText("9 of 12 in-scope data points have their evidence")).toBeInTheDocument();
    expect(screen.getByText("41 of 108 values accepted or corrected")).toBeInTheDocument();

    const attention = screen.getAllByRole("button").filter((b) => b.className.includes("s1-attention__item"));
    expect(attention[0]).toHaveTextContent("1document can't be read");
    expect(attention.map((b) => b.textContent)).toContain("67values waiting for reviewReview");
    fireEvent.click(screen.getByText("data points missing evidence"));
    expect(onNavigate).toHaveBeenCalledWith("requests");
  });

  it("says so when nothing needs anyone", () => {
    render(
      <DashboardScreen
        engagement={engagementConfig}
        figures={{ ...FIGURES, blockedDocuments: 0, documentsNeedingYou: 0, valuesToReview: 0, requestsNotSent: 0, requestsAwaitingClient: 0, coverage: null }}
      />
    );
    expect(screen.getByText("Nothing needs you right now.")).toBeInTheDocument();
  });
});

describe("evidence: bird's-eye first", () => {
  function renderEvidence() {
    render(
      <EvidenceWorkspace
        engagement={engagementConfig}
        evidence={manufacturerEvidence}
        asks={[]}
        onSaveAsk={vi.fn()}
        onEvidenceChange={vi.fn()}
        onOpenExtraction={vi.fn()}
        onOpenUpload={vi.fn()}
      />
    );
  }

  it("opens on one summary bar per type, and a type opens to five columns", () => {
    renderEvidence();
    expect(screen.queryByRole("table")).toBeNull();
    const heads = screen.getAllByRole("button", { expanded: false });
    expect(heads.length).toBeGreaterThan(3);

    fireEvent.click(heads.find((b) => b.textContent?.startsWith("Electricity bill"))!);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Document",
      "Facility",
      "Type",
      "Status",
      "",
    ]);
    // Who uploaded a document, and when, is in its history, not on the row.
    expect(within(table).queryByText(/^Uploaded ·/)).toBeNull();
  });

  it("puts the upload behind one button", () => {
    renderEvidence();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });
});

describe("activity log", () => {
  it("lists uploads newest first, with who uploaded each file", () => {
    const log = engagementActivity({ evidence: manufacturerEvidence, values: [], asks: [], findings: [] });
    expect(log).toHaveLength(manufacturerEvidence.length);
    expect(log[0].at >= log[log.length - 1].at).toBe(true);
    expect(log[0].what).toMatch(/^uploaded /);
  });

  it("counts the figures the dashboard shows", () => {
    const figures = dashboardFigures({ evidence: manufacturerEvidence, values: [], asks: [], findings: [], coverage: null });
    expect(figures.documents).toBe(manufacturerEvidence.filter((e) => e.disposition !== "withdrawn").length);
    expect(figures.coverage).toBeNull();
  });
});

describe("coverage & requests: one page", () => {
  it("leads with the values waiting for review, filters checks, and turns a missing check into a request", async () => {
    const { EvidenceRequests } = await import("../components/EvidenceRequests");
    const { coverageRules } = await import("../fixtures/verification/coverageRules");
    const onReview = vi.fn();
    const onSaveAsk = vi.fn();
    render(
      <EvidenceRequests
        engagement={{ ...engagementConfig, engagementTeam: [{ name: "M. Osei", login: "mosei" }], signedInLogin: "mosei" }}
        asks={[]}
        coverage={{ rules: coverageRules }}
        valuesToReview={14}
        onReview={onReview}
        onSaveAsk={onSaveAsk}
        onSend={vi.fn(() => 1)}
        onResolve={vi.fn()}
        onWithdraw={vi.fn()}
        onEdit={vi.fn()}
        onRaiseFollowUp={vi.fn()}
        onOpenSource={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /14 values waiting for review/ }));
    expect(onReview).toHaveBeenCalled();

    // Opens on the checks missing their inputs; a filter shows another state.
    const missing = coverageRules.filter((r) => r.status === "inputs_missing");
    expect(screen.getAllByRole("button", { name: /^Request$/ })).toHaveLength(missing.length);
    fireEvent.click(screen.getByRole("button", { name: /Inputs present/ }));
    expect(screen.queryAllByRole("button", { name: /^Request$/ })).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /Inputs present/ })); // off again: every check

    fireEvent.click(screen.getAllByRole("button", { name: /^Request$/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
    expect(onSaveAsk).toHaveBeenCalledWith(
      expect.objectContaining({ origin: "data_point", fieldKey: missing[0].ruleId, type: "missing_document" })
    );
    expect(screen.queryByRole("button", { name: /Request by email/ })).toBeNull();
  });
});
