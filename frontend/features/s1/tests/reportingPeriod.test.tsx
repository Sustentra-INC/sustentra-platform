/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { engagementFromBackend, type BackendEngagement } from "../api/engagements";
import { DashboardScreen } from "../components/DashboardScreen";
import { S1Chrome } from "../components/S1Chrome";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig } from "../types";
import type { DashboardFigures } from "../utils/engagementActivity";
import { formatReportingPeriod } from "../utils/formatPeriod";

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
    expect(formatReportingPeriod("2026-10-08", "")).toBe("From Oct 8, 2026 · end date not set");
    expect(formatReportingPeriod("2026-10-08", null)).toBe("From Oct 8, 2026 · end date not set");
    expect(formatReportingPeriod("", "2026-12-31")).toBe("Until Dec 31, 2026 · start date not set");
    expect(formatReportingPeriod(undefined, undefined)).toBe("Reporting period not set");
  });

  it("shows a date it cannot read as it was given", () => {
    expect(formatReportingPeriod("2026-13-40", "soon")).toBe("2026-13-40 – soon");
  });
});

describe("reporting period with no end date", () => {
  const engagement: EngagementConfig = engagementFromBackend(ROW);

  it("shows on the dashboard as a start date with the end not set", () => {
    render(<DashboardScreen engagement={engagement} figures={NO_FIGURES} />);
    expect(screen.getByText("From Oct 8, 2026 · end date not set")).toBeInTheDocument();
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
    expect(screen.getByText("From Oct 8, 2026 · end date not set")).toBeInTheDocument();
    expect(screen.queryByText(/ to $/)).toBeNull();
  });
});
