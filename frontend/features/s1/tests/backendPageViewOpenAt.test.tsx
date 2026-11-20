/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(() => Promise.resolve({ pages: 8 })),
}));

import { BackendPageView } from "../components/BackendPageView";

afterEach(cleanup);

describe("BackendPageView opened at a cited page", () => {
  it("opens at that page and outlines every box of the selected quote", () => {
    const marks = [
      { id: "f#1", span: { page: 5, x: 0.1, y: 0.2, w: 0.3, h: 0.02 }, label: "Gas: CO2", reviewState: "to_review" as const },
      { id: "f#2", span: { page: 5, x: 0.1, y: 0.23, w: 0.2, h: 0.02 }, label: "Gas: CO2", reviewState: "to_review" as const },
      { id: "g#1", span: { page: 5, x: 0.1, y: 0.5, w: 0.2, h: 0.02 }, label: "Gas: CH4", reviewState: "to_review" as const },
    ];
    render(<BackendPageView documentId="d1" span={marks[0].span} openPage={5} marks={marks} selectedMarkIds={["f#1", "f#2"]} onPickMark={vi.fn()} />);
    expect(screen.getByText(/page 5 of/)).toBeInTheDocument();
    expect(screen.getByAltText("Page 5 of the uploaded document")).toBeInTheDocument();
    const selected = screen.getAllByRole("button", { name: /Select Gas/ }).filter((b) => b.getAttribute("aria-current") === "true");
    expect(selected).toHaveLength(2);
  });

  it("with no box (quote not located) it still opens the cited page and shows the note", () => {
    render(<BackendPageView documentId="d1" span={null} openPage={5} pageNote="Quote not located on this page" onPickMark={vi.fn()} />);
    expect(screen.getByText(/page 5 of/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Quote not located on this page");
    expect(screen.queryByText(/position was not recorded/)).toBeNull();
  });
});
