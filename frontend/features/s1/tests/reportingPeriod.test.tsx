/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("../api/recalculation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/recalculation")>()),
  getRecalculation: vi.fn(),
}));

import { engagementFromBackend, type BackendEngagement } from "../api/engagements";
import { getRecalculation, type Recalculation } from "../api/recalculation";
import { BackendOutputScreen } from "../components/BackendOutputScreen";
import { DashboardScreen } from "../components/DashboardScreen";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { S1Chrome } from "../components/S1Chrome";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { EngagementConfig, EvidenceItem } from "../types";
import type { DashboardFigures } from "../utils/engagementActivity";
import { formatReportingPeriod } from "../utils/formatPeriod";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

const NO_FIGURES: DashboardFigures = {
  documents: 0,
  documentsReadable: 0,
  blockedDocuments: 0,
  documentsNeedingYou: 0,
  valuesReviewed: 0,
  valuesToReview: 0,
  requestsNotSent: 0,
  requestsAwaitingClient: 0,
  requestsResolved: 0,
  requestsRaised: 0,
  coverage: null,
  dataPointsCalculated: 0,
  dataPointsExamined: 0,
  findings: 0,
};

/** An engagement as the backend returns it after Setup saved a start date and no end date. */
const ROW: BackendEngagement = {
  id: "0f8b8c4e-0000-4000-8000-000000000002",
  org_id: "aaaaaaaa-0000-4000-8000-00000000000a",
  name: "FY2026 GHG verification",
  client_name: "Acme Foods",
  reporting_period_start: "2026-10-08",
  reporting_period_end: null,
  status: "active",
  settings: {},
  created_at: "2026-10-07T00:00:00Z",
  updated_at: "2026-10-07T00:00:00Z",
};

describe("formatReportingPeriod", () => {
  it("reads a whole period as two dates", () => {
    expect(formatReportingPeriod("2025-01-01", "2025-12-31")).toBe("Jan 1, 2025 – Dec 31, 2025");
  });

  it("says which date is not set yet, instead of Invalid Date", () => {
    expect(formatReportingPeriod("2026-10-08", "")).toBe("Oct 8, 2026 – end date not set");
    expect(formatReportingPeriod("2026-10-08", null)).toBe("Oct 8, 2026 – end date not set");
    expect(formatReportingPeriod("", "2026-12-31")).toBe("start date not set – Dec 31, 2026");
    expect(formatReportingPeriod(undefined, undefined)).toBe("Reporting period not set");
  });

  it("never uses the middle dot the dashboard joins it to the regulation with", () => {
    for (const [start, end] of [["2026-10-08", ""], ["", "2026-12-31"], ["", ""], ["2025-01-01", "2025-12-31"]]) {
      expect(formatReportingPeriod(start, end)).not.toContain("·");
    }
  });

  it("shows a date it cannot read as it was given", () => {
    expect(formatReportingPeriod("2026-13-40", "soon")).toBe("2026-13-40 – soon");
  });
});

describe("reporting period with no end date", () => {
  const engagement: EngagementConfig = engagementFromBackend(ROW);

  it("shows on the dashboard as a start date with the end not set", () => {
    const withRegulation = { ...engagement, regulation: "SB 253: Climate Corporate Data Accountability Act" };
    render(<DashboardScreen engagement={withRegulation} figures={NO_FIGURES} />);
    // The regulation and the period are the line's only two items.
    expect(screen.getByText("SB 253 · Oct 8, 2026 – end date not set")).toBeInTheDocument();
    expect(screen.queryByText(/Invalid Date/)).toBeNull();
  });

  it("still shows a whole period on the dashboard as before", () => {
    render(<DashboardScreen engagement={engagementConfig} figures={NO_FIGURES} />);
    expect(screen.getByText(/Jan 1, 2025 – Dec 31, 2025/)).toBeInTheDocument();
  });

  it("says the period is not set when neither date is", () => {
    const blank = engagementFromBackend({ ...ROW, reporting_period_start: null });
    render(<DashboardScreen engagement={blank} figures={NO_FIGURES} />);
    expect(screen.getByText("Reporting period not set")).toBeInTheDocument();
  });

  it("shows the same words in the engagement bar's details", () => {
    render(
      <S1Chrome engagement={engagement}>
        <p>content</p>
      </S1Chrome>
    );
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByText("Oct 8, 2026 – end date not set")).toBeInTheDocument();
    expect(screen.queryByText(/ to $/)).toBeNull();
  });

  it("shows the same words on the Output, the page the workpaper downloads from", async () => {
    vi.mocked(getRecalculation).mockResolvedValue({
      ...(workbookExample as unknown as Recalculation),
      engagement_id: engagement.engagementId,
    });
    render(
      <BackendOutputScreen engagement={engagement} evidence={[]} values={[]} asks={[]} findings={[]} onError={() => false} />
    );
    expect(await screen.findByText("Oct 8, 2026 – end date not set")).toBeInTheDocument();
    expect(screen.queryByText(/ to \?|Invalid Date/)).toBeNull();
  });
});

describe("an engagement with only one date set", () => {
  it("does not flag evidence as outside the reporting year against an end date not set yet", () => {
    const noEnd: EngagementConfig = { ...engagementConfig, reportingPeriod: { start: "2025-01-01", end: "" } };
    const wrongYear = manufacturerEvidence.find((d) => d.documentId === "DOC-WRONGYEAR")!;
    const inYear: EvidenceItem = {
      ...wrongYear,
      documentId: "DOC-INYEAR",
      filename: "kent_electric_mar_2025.pdf",
      periodStart: "2025-03-01",
      periodEnd: "2025-03-31",
    };
    render(
      <EvidenceWorkspace
        engagement={noEnd}
        evidence={[wrongYear, inYear]}
        asks={[]}
        onSaveAsk={vi.fn()}
        onEvidenceChange={vi.fn()}
        onOpenExtraction={vi.fn()}
        onOpenUpload={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /^Electricity bill/ }));
    const row = (filename: string) => screen.getByRole("button", { name: filename }).closest("tr") as HTMLElement;
    expect(within(row("kent_electric_mar_2025.pdf")).queryByText("Period outside reporting year")).toBeNull();
    // The start date still bounds the period: a bill from before it is flagged.
    expect(within(row("kent_electric_dec_2024.pdf")).getByText("Period outside reporting year")).toBeInTheDocument();
  });

  it("writes the request without a year while the start date is not set", () => {
    render(
      <EvidenceRequests
        engagement={{ ...engagementConfig, reportingPeriod: { start: "", end: "2025-12-31" } }}
        asks={seedAsks}
        coverage={{ rules: coverageRules }}
        valuesToReview={0}
        onReview={vi.fn()}
        onSaveAsk={vi.fn()}
        onSend={vi.fn(() => 1)}
        onResolve={vi.fn()}
        onWithdraw={vi.fn()}
        onEdit={vi.fn()}
        onRaiseFollowUp={vi.fn()}
        onOpenSource={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all not yet sent" }));
    fireEvent.click(screen.getByRole("button", { name: /^Send \(/ }));
    const panel = screen.getByRole("dialog", { name: "Send requests" });
    expect(within(panel).getByRole("textbox", { name: "Subject" })).toHaveValue(
      "Cascade Provisions Co.: emissions verification"
    );
    const message = (within(panel).getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value;
    expect(message).toContain("To finish verifying Cascade Provisions Co.'s emissions, could you help");
    expect(message).not.toContain("  ");
  });
});
