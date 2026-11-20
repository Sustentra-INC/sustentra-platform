/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { explanationOf } from "../api/methodologyReview";
import { AiExplainPopover } from "../components/AiExplainPopover";
import { AiFacilityNote } from "../components/AiFacilityNote";

afterEach(cleanup);

const EXPLANATION: AiExplanation = {
  reason: "The report states it uses the operational control approach under 'Organizational boundary'.",
  reason_note: null,
  read_at: "2026-11-11T09:00:00Z",
  model: "model-x",
  items: [
    {
      label: null,
      reason: "The report states it uses the operational control approach under 'Organizational boundary'.",
      quote: "operational control approach",
      document_id: "d1",
      file_name: "GHG report.pdf",
      page: 4,
      location: "page 4",
      checks: ["The quote was found on the document (GHG report.pdf, page 4) when it was read.", "The wording matched: 'operational control' → Operational Control."],
      implied: ["Start date implied: the quote states a year ended 2024-12-31."],
    },
  ],
};

describe("the AI explanation popover", () => {
  it("is a button that opens Why, Evidence and Checks passed, and the document link opens the document at its page", () => {
    const onOpen = vi.fn();
    render(<AiExplainPopover label="Suggested by Sustentra's AI" explanation={EXPLANATION} onOpenDocument={onOpen} />);
    const button = screen.getByRole("button", { name: "Suggested by Sustentra's AI" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("heading").map((h) => h.textContent)).toEqual(["Why", "Evidence", "Checks passed"]);
    expect(within(dialog).getByText(EXPLANATION.reason!)).toBeInTheDocument();
    expect(within(dialog).getByText("operational control approach")).toBeInTheDocument();
    expect(within(dialog).getByText("The wording matched: 'operational control' → Operational Control.")).toBeInTheDocument();
    expect(within(dialog).getByText(/Start date implied/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Read by Sustentra's AI · Nov 11, 2026/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "GHG report.pdf, page 4" }));
    expect(onOpen).toHaveBeenCalledWith("d1", { entry: null, page: 4 });
    expect(document.body.textContent).not.toMatch(/Claude|model-x/);
  });

  it("opens with Enter, closes with Escape and gives focus back to the button", () => {
    render(<AiExplainPopover label="Suggested by Sustentra's AI" explanation={EXPLANATION} />);
    const button = screen.getByRole("button", { name: "Suggested by Sustentra's AI" });
    button.focus();
    fireEvent.click(button); // Enter and Space on a button are clicks
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("closes on a click elsewhere", () => {
    render(<AiExplainPopover label="Suggested by Sustentra's AI" explanation={EXPLANATION} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says no reason was recorded for an older suggestion, and still shows the evidence and the checks", () => {
    const old: AiExplanation = { ...EXPLANATION, reason: null, reason_note: NO_REASON, items: [{ ...EXPLANATION.items[0], reason: null }] };
    render(<AiExplainPopover label="Suggested by Sustentra's AI" explanation={old} />);
    fireEvent.click(screen.getByRole("button"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Reason not recorded for this suggestion. Re-read the reports to get one.")).toBeInTheDocument();
    expect(within(dialog).getByText("operational control approach")).toBeInTheDocument();
    expect(within(dialog).getByText(/The wording matched/)).toBeInTheDocument();
  });

  it("labels each entry of a list suggestion", () => {
    const list: AiExplanation = {
      ...EXPLANATION,
      items: [
        { ...EXPLANATION.items[0], label: "PPA or VPPA", reason: "It names a PPA." },
        { ...EXPLANATION.items[0], label: "Residual mix", reason: "It names the residual mix." },
      ],
    };
    render(<AiExplainPopover label="Suggested by Sustentra's AI" explanation={list} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("It names a PPA.").parentElement).toHaveTextContent("PPA or VPPA: It names a PPA.");
  });
});

describe("a suggestion with no server explanation", () => {
  it("is explained from the stored suggestion alone: its reason when it has one, never invented checks", () => {
    const suggestion = { value: "x", quote: "q quote", document_id: "d", file_name: "f.pdf", source_reference: { page_number: 2 }, origin: "ai", model: "m", request_id: "r", suggested_at: "t" };
    const none = explanationOf({ suggestion, explanation: null })!;
    expect(none.reason).toBeNull();
    expect(none.reason_note).toBe(NO_REASON);
    expect(none.items[0]).toMatchObject({ quote: "q quote", location: "page 2", page: 2, checks: [] });
    expect(explanationOf({ suggestion: { ...suggestion, reason: "Because." }, explanation: null })!.reason).toBe("Because.");
    expect(explanationOf({ suggestion: null, explanation: null })).toBeNull();
  });
});

describe("the facility suggestion", () => {
  it("uses the same popover, with its reason", () => {
    const explanation: AiExplanation = {
      reason: "The file name says Fresno.",
      reason_note: null,
      items: [{ label: null, reason: "The file name says Fresno.", quote: "Fresno", document_id: "d", file_name: "Fresno_log.csv", page: null, location: "", checks: ["Fresno Plant is one of the facilities in Setup."], implied: [] }],
    };
    render(<AiFacilityNote facilityName="Fresno Plant" quote="Fresno" where="the file name" onPlace={() => {}} explanation={explanation} />);
    fireEvent.click(screen.getByRole("button", { name: "Facility suggested by Sustentra's AI" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("The file name says Fresno.")).toBeInTheDocument();
    expect(within(dialog).getByText("Fresno Plant is one of the facilities in Setup.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place on Fresno Plant" })).toBeInTheDocument();
  });
});
