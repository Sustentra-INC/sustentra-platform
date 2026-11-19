/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardScreen } from "../components/DashboardScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { dashboardFigures } from "../utils/engagementActivity";

afterEach(cleanup);

const figures = () => dashboardFigures({ evidence: manufacturerEvidence, values: manufacturerValues, asks: [], findings: [], coverage: null });

describe('the dashboard item "N values waiting for review"', () => {
  it("opens the review, not Evidence", () => {
    const onNavigate = vi.fn();
    const onOpenReview = vi.fn();
    render(<DashboardScreen engagement={engagementConfig} figures={figures()} onNavigate={onNavigate} onOpenReview={onOpenReview} />);
    fireEvent.click(screen.getByRole("button", { name: /values? waiting for review/ }));
    expect(onOpenReview).toHaveBeenCalledTimes(1);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("falls back to Evidence when the page has no review to open", () => {
    const onNavigate = vi.fn();
    render(<DashboardScreen engagement={engagementConfig} figures={figures()} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("button", { name: /values? waiting for review/ }));
    expect(onNavigate).toHaveBeenCalledWith("evidence");
  });

  it("leaves the other attention items where they were", () => {
    const onNavigate = vi.fn();
    const onOpenReview = vi.fn();
    render(
      <DashboardScreen
        engagement={engagementConfig}
        figures={{ ...figures(), blockedDocuments: 2 }}
        onNavigate={onNavigate}
        onOpenReview={onOpenReview}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /can.t be read/ }));
    expect(onNavigate).toHaveBeenCalledWith("evidence");
    expect(onOpenReview).not.toHaveBeenCalled();
  });
});
