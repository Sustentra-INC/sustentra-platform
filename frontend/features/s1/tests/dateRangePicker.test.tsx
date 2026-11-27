/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { DateRangePicker } from "../components/DateRangePicker";

function Setup({
  start = "2025-01-01",
  end = "2025-12-31",
  onChange = vi.fn(),
}: {
  start?: string;
  end?: string;
  onChange?: (s: string, e: string) => void;
}) {
  return (
    <div>
      <span id="rp-label">Reporting period</span>
      <DateRangePicker
        start={start}
        end={end}
        onChange={onChange}
        labelId="rp-label"
      />
    </div>
  );
}

describe("DateRangePicker", () => {
  it("renders trigger with formatted dates and day count", () => {
    render(<Setup />);
    // Trigger should show formatted start date
    expect(screen.getByText("Jan 1, 2025")).toBeInTheDocument();
    // Trigger should show formatted end date
    expect(screen.getByText("Dec 31, 2025")).toBeInTheDocument();
    // Day count: Jan 1 to Dec 31 inclusive = 365 days
    expect(screen.getByText("365 days")).toBeInTheDocument();
  });

  it("shows placeholder text when no dates supplied", () => {
    render(<Setup start="" end="" />);
    expect(screen.getByText("Start date")).toBeInTheDocument();
    expect(screen.getByText("End date")).toBeInTheDocument();
  });

  it("opens the dialog panel on trigger click", () => {
    render(<Setup />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));
    expect(screen.getByRole("dialog", { name: "Choose reporting period" })).toBeInTheDocument();
  });

  it("closes the panel on Cancel click without calling onChange", () => {
    const onChange = vi.fn();
    render(<Setup onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("closes the panel on Escape without calling onChange", () => {
    const onChange = vi.fn();
    render(<Setup onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));
    const panel = screen.getByRole("dialog");
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("picks two dates and calls onChange with YYYY-MM-DD strings on Apply", () => {
    const onChange = vi.fn();
    render(<Setup start="2025-01-01" end="2025-12-31" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));

    // Pick start: click day 5 in Jan 2025 (the grid is opened to January 2025)
    const day5 = screen.getAllByRole("gridcell", { name: "Jan 5, 2025" })[0];
    fireEvent.click(day5);

    // Pick end: click day 10 in January 2025
    const day10 = screen.getAllByRole("gridcell", { name: "Jan 10, 2025" })[0];
    fireEvent.click(day10);

    // Apply should now be enabled
    const applyBtn = screen.getByRole("button", { name: "Apply" });
    expect(applyBtn).not.toBeDisabled();
    fireEvent.click(applyBtn);

    // onChange called with YYYY-MM-DD strings
    expect(onChange).toHaveBeenCalledWith("2025-01-05", "2025-01-10");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("swaps start and end when second pick is before first", () => {
    const onChange = vi.fn();
    render(<Setup start="2025-01-01" end="2025-12-31" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));

    // Pick day 15 first
    const day15 = screen.getAllByRole("gridcell", { name: "Jan 15, 2025" })[0];
    fireEvent.click(day15);

    // Pick day 5 second (before 15)
    const day5 = screen.getAllByRole("gridcell", { name: "Jan 5, 2025" })[0];
    fireEvent.click(day5);

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    // Apply should correctly order them: start=5, end=15
    expect(onChange).toHaveBeenCalledWith("2025-01-05", "2025-01-15");
  });

  it("Apply button is disabled until two dates are selected", () => {
    render(<Setup start="" end="" />);
    fireEvent.click(screen.getByRole("button", { name: /reporting period/i }));
    const applyBtn = screen.getByRole("button", { name: "Apply" });
    expect(applyBtn).toBeDisabled();

    // Pick just the first date
    const day1 = screen.getAllByRole("gridcell")[7]; // first real day cell after empty cells
    fireEvent.click(day1);
    expect(applyBtn).toBeDisabled();
  });

  it("day count calculation is inclusive (Jan 1 to Dec 31 = 365 days)", () => {
    render(<Setup start="2025-01-01" end="2025-12-31" />);
    expect(screen.getByText("365 days")).toBeInTheDocument();
  });
});
