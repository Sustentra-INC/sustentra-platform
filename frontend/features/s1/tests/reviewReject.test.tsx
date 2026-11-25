/* @vitest-environment jsdom */
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { mapBackendCandidateToExtractedField, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { fieldsFromExtraction, type BackendReviewDecision } from "../api/s1Backend";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem } from "../types";
import type { ReviewValue } from "../types/review";
import { markName, markState } from "../utils/markState";
import { dashboardFigures, firstValueToReview } from "../utils/engagementActivity";

afterEach(cleanup);

const DOC = {
  documentId: "DOC-1",
  filename: "bill.pdf",
  format: "pdf",
  uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill",
} as unknown as EvidenceItem;

const candidate = (name: string, value: string | null, flags: string[] = [], id = name): BackendExtractionCandidateLike => ({
  candidate_id: id,
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: name,
  display_label: name,
  normalized_value: value,
  unit: null,
  validation_flags: flags,
  source_reference: { text_snippet: `${name} ${value}`, page_number: 1 },
});

const valuesOf = (candidates: BackendExtractionCandidateLike[]) =>
  reviewValuesFromFields(candidates.map((c) => mapBackendCandidateToExtractedField(c, "CT-S2-ELEC")), [DOC]);

type Persist = (value: ReviewValue, reason: string) => Promise<void>;

function Harness(props: {
  initial: ReviewValue[];
  onPersistReject?: Persist;
  onPersistAccept?: (v: ReviewValue) => Promise<void>;
  onPersistCorrect?: (v: ReviewValue, next: { value: string; unit: string }) => Promise<void>;
  onState?: (values: ReviewValue[]) => void;
}) {
  const [values, setValues] = useState(props.initial);
  props.onState?.(values);
  return (
    <ExtractionReview
      engagement={engagementConfig}
      values={values}
      onValuesChange={(update) => setValues(update)}
      initialDocumentId="DOC-1"
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
      reviewerName="Rae Reviewer"
      onPersistReject={props.onPersistReject}
      onPersistAccept={props.onPersistAccept}
      onPersistCorrect={props.onPersistCorrect}
    />
  );
}

const ok = () => vi.fn<Persist>(() => Promise.resolve());

function openReject(reason?: string) {
  fireEvent.click(screen.getByRole("button", { name: "Reject" }));
  const box = screen.getByRole("textbox", { name: "Why is this value not used?" });
  if (reason !== undefined) fireEvent.change(box, { target: { value: reason } });
  return box;
}

describe("Reject on a value card", () => {
  it("asks why, saves the reason, and shows the value as rejected and not used", async () => {
    const onPersistReject = ok();
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={onPersistReject} />);
    expect(screen.getByRole("button", { name: "Accept" })).toBeInTheDocument();
    openReject();
    const confirm = screen.getByRole("button", { name: "Reject value" });
    expect(confirm).toBeDisabled(); // a reason is required
    fireEvent.change(screen.getByRole("textbox", { name: "Why is this value not used?" }), { target: { value: "  Wrong supplier  " } });
    fireEvent.click(confirm);

    await waitFor(() => expect(onPersistReject).toHaveBeenCalledTimes(1));
    expect(onPersistReject.mock.calls[0][1]).toBe("Wrong supplier");
    expect(screen.getAllByText("Rejected").length).toBeGreaterThan(0);
    expect(screen.getByText("Not used in the calculation.")).toBeInTheDocument();
    // the record says who and why
    expect(screen.getByText(/Rae Reviewer · rejected/)).toBeInTheDocument();
    expect(screen.getByText(/Wrong supplier/)).toBeInTheDocument();
  });

  it("counts it beside the other states, and not as still to review", () => {
    render(
      <Harness initial={valuesOf([candidate("supplier_name", "Meridian"), candidate("meter_number", "M-1")])} onPersistReject={ok()} />
    );
    expect(screen.getByRole("button", { name: /^2\s*To review/ })).toBeInTheDocument();
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    expect(screen.getByRole("button", { name: /^1\s*To review/ })).toBeInTheDocument();
    const rejected = screen.getByRole("button", { name: /^1\s*Rejected/ });
    expect(screen.getByRole("button", { name: /^0\s*Accepted/ })).toBeInTheDocument();
    fireEvent.click(rejected);
    expect(rejected).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Not used in the calculation.")).toBeInTheDocument();
    expect(screen.queryByText("M-1")).toBeNull();
  });

  it("goes back to how it was, and says so, when the save fails", async () => {
    const onPersistReject = vi.fn<Persist>(() => Promise.reject(new Error("Server said no")));
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={onPersistReject} />);
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    await screen.findByText("Reject not saved, back to review. Server said no");
    expect(screen.getByRole("button", { name: /^1\s*To review/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^0\s*Rejected/ })).toBeInTheDocument();
    expect(screen.queryByText("Not used in the calculation.")).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("holds Accept, Correct and Reject on a rejected value while its save is pending", async () => {
    let settle: () => void = () => undefined;
    const onPersistReject = vi.fn<Persist>(() => new Promise<void>((resolve) => (settle = resolve)));
    const onPersistAccept = vi.fn(() => Promise.resolve());
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={onPersistReject} onPersistAccept={onPersistAccept} />);
    openReject("Not ours");
    const confirm = screen.getByRole("button", { name: "Reject value" });
    fireEvent.click(confirm);
    fireEvent.click(confirm); // a double click
    expect(onPersistReject).toHaveBeenCalledTimes(1);
    const accept = screen.getByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();
    fireEvent.click(accept);
    expect(onPersistAccept).not.toHaveBeenCalled();
    await act(async () => settle());
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
  });

  it("can be put back: accepted or corrected later", async () => {
    const onPersistAccept = vi.fn(() => Promise.resolve());
    const onPersistCorrect = vi.fn(() => Promise.resolve());
    render(
      <Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={ok()} onPersistAccept={onPersistAccept} onPersistCorrect={onPersistCorrect} />
    );
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(onPersistAccept).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /^1\s*Accepted/ })).toBeInTheDocument();
    expect(screen.queryByText("Not used in the calculation.")).toBeNull();
  });

  it("can be corrected after it was rejected", async () => {
    const onPersistCorrect = vi.fn(() => Promise.resolve());
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={ok()} onPersistCorrect={onPersistCorrect} />);
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Correct" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "Meridian Energy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(onPersistCorrect).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /^1\s*Corrected/ })).toBeInTheDocument();
  });

  it("rejects every data point of one reading", async () => {
    const [one] = valuesOf([candidate("activity_quantity", "12400")]);
    const twin = { ...one, id: `${one.id}#2` };
    const onPersistReject = ok();
    let latest: ReviewValue[] = [];
    render(<Harness initial={[one, twin]} onPersistReject={onPersistReject} onState={(v) => (latest = v)} />);
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    await waitFor(() => expect(onPersistReject).toHaveBeenCalledTimes(2));
    expect(latest.map((v) => v.reviewState)).toEqual(["rejected", "rejected"]);
  });

  it("closes the reason box with Escape and gives focus back to Reject", () => {
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={ok()} />);
    const box = openReject("half a reas");
    expect(box).toHaveFocus();
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Why is this value not used?" })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" })).toHaveFocus();
    // Cancel does the same
    openReject();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Reject" })).toHaveFocus();
  });

  it("caps a very long reason at 500 characters", async () => {
    const onPersistReject = ok();
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={onPersistReject} />);
    const box = openReject("y".repeat(900));
    expect(box).toHaveAttribute("maxlength", "500");
    expect((box as HTMLInputElement).value).toHaveLength(500);
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    await waitFor(() => expect(onPersistReject).toHaveBeenCalled());
    expect(onPersistReject.mock.calls[0][1]).toHaveLength(500);
  });

  it("shows markup in a reason as plain text", async () => {
    const hostile = `<img src=x onerror="window.__pwned=1"> & <b>bold</b>`;
    const { container } = render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} onPersistReject={ok()} />);
    openReject(hostile);
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".s1-xr-record b")).toBeNull();
    expect(within(container.querySelector(".s1-xr-record") as HTMLElement).getByText(/<img src=x/)).toBeInTheDocument();
  });

  it("does not offer Reject on a value not found on the document, or on a withdrawn document's value", () => {
    const missing = valuesOf([candidate("fuel_type", null)]);
    const { unmount } = render(<Harness initial={missing} onPersistReject={ok()} />);
    expect(screen.getByRole("button", { name: "Enter value" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    unmount();
    const withdrawn = valuesOf([candidate("supplier_name", "Meridian")]).map((v) => ({ ...v, withdrawn: true }));
    render(<Harness initial={withdrawn} onPersistReject={ok()} />);
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Accept" })).toBeNull();
  });

  it("works in the demo (no backend): the card is rejected in the session", () => {
    render(<Harness initial={valuesOf([candidate("supplier_name", "Meridian")])} />);
    openReject("Not ours");
    fireEvent.click(screen.getByRole("button", { name: "Reject value" }));
    expect(screen.getByText("Not used in the calculation.")).toBeInTheDocument();
  });
});

describe("Accept all and values with a warning", () => {
  function render3(candidates: BackendExtractionCandidateLike[]) {
    const onPersistAccept = vi.fn(() => Promise.resolve());
    render(<Harness initial={valuesOf(candidates)} onPersistAccept={onPersistAccept} />);
    return onPersistAccept;
  }

  it("leaves out a value with a warning, counts the rest, and says why", async () => {
    const onPersistAccept = render3([
      candidate("account_number", "5521-8890"),
      candidate("supplier_name", "Meridian"),
      candidate("meter_number", "M-1", ["unit_ambiguous"]),
      candidate("statement_date", "2025-02-01", ["estimated_read"]),
    ]);
    expect(screen.getByRole("button", { name: "Accept all 2" })).toBeInTheDocument();
    expect(screen.getByText("2 with a warning need individual review: unit unclear, estimated reading")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept all 2" }));
    await waitFor(() => expect(onPersistAccept).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: /^2\s*To review/ })).toBeInTheDocument();
  });

  it("does not hold back a flag that only informs, but holds back one it does not know", () => {
    render3([
      candidate("account_number", "5521-8890", ["unit_converted"]),
      candidate("supplier_name", "Meridian", ["biofuel_blend"]),
      candidate("meter_number", "M-1", ["a_flag_added_later"]),
    ]);
    expect(screen.getByRole("button", { name: "Accept all 2" })).toBeInTheDocument();
    expect(screen.getByText("1 with a warning need individual review: flagged by the reading")).toBeInTheDocument();
  });

  it("names Sustentra's AI readings and warnings separately, and offers nothing when all are held back", () => {
    render3([
      candidate("account_number", "5521-8890", ["ai_suggested"]),
      candidate("meter_number", "M-1", ["unit_missing"]),
    ]);
    expect(screen.queryByRole("button", { name: /Accept all/ })).toBeNull();
    expect(screen.getByText("1 suggested by Sustentra's AI need individual review")).toBeInTheDocument();
    expect(screen.getByText("1 with a warning need individual review: unit missing")).toBeInTheDocument();
  });

  it("never sweeps up a rejected value", () => {
    const rejected = valuesOf([candidate("supplier_name", "Meridian"), candidate("meter_number", "M-1"), candidate("account_number", "A-1")]);
    rejected[0] = { ...rejected[0], reviewState: "rejected" };
    const onPersistAccept = vi.fn(() => Promise.resolve());
    render(<Harness initial={rejected} onPersistAccept={onPersistAccept} />);
    fireEvent.click(screen.getByRole("button", { name: "Accept all 2" }));
    expect(onPersistAccept).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /^1\s*Rejected/ })).toBeInTheDocument();
  });
});

describe("a rejected decision loaded from the API", () => {
  const extraction = {
    created_at: "2026-11-01T10:00:00Z",
    items: [candidate("supplier_name", "Meridian", [], "C1"), candidate("meter_number", "M-1", [], "C2")],
  };
  const rejection: BackendReviewDecision = {
    candidate_id: "C1",
    field_name: "supplier_name",
    decision: "rejected",
    reviewed_value: null,
    reviewer_id: "claire@sustentra.com",
    reviewed_at: "2026-11-02T11:30:00Z",
    reviewer_note: "Wrong supplier",
  };
  const load = (reviews: BackendReviewDecision[]) =>
    reviewValuesFromFields(fieldsFromExtraction(extraction, reviews, "CT-S2-ELEC"), [DOC]);

  it("loads as rejected, with the reason, who and when, in the value's record", () => {
    const [rejected, other] = load([rejection]);
    expect(rejected.reviewState).toBe("rejected");
    expect(other.reviewState).toBe("to_review");
    expect(rejected.record.at(-1)).toMatchObject({
      kind: "human",
      actor: "claire@sustentra.com",
      at: "2026-11-02T11:30:00Z",
      action: "rejected, not used in the calculation",
      reason: "Wrong supplier",
    });
  });

  it("stays rejected when the latest decision is the rejection, and follows a later accept", () => {
    const accept: BackendReviewDecision = { ...rejection, decision: "accepted", reviewer_note: null };
    expect(load([accept, rejection])[0].reviewState).toBe("rejected");
    expect(load([rejection, accept])[0].reviewState).toBe("accepted");
  });

  it("carries over a re-read to the value it now applies to, and is to review when it applies to none", () => {
    expect(load([{ ...rejection, candidate_id: "OLD", applies_to_candidate_id: "C2" }]).map((v) => v.reviewState)).toEqual(["to_review", "rejected"]);
    expect(load([{ ...rejection, applies_to_candidate_id: null }]).map((v) => v.reviewState)).toEqual(["to_review", "to_review"]);
  });

  it("still blocks the value from placing the bill", () => {
    expect(fieldsFromExtraction(extraction, [rejection], null)[0].placementBlocked).toBe(true);
  });

  it("opens on the page as a rejected card", () => {
    render(<Harness initial={load([rejection])} />);
    expect(screen.getByRole("button", { name: /^1\s*Rejected/ })).toBeInTheDocument();
    expect(screen.getByText("Not used in the calculation.")).toBeInTheDocument();
  });
});

describe("other places that switch on the review state", () => {
  const rejectedValue = (): ReviewValue => ({ ...valuesOf([candidate("supplier_name", "Meridian")])[0], reviewState: "rejected" });

  it("a highlight with only rejected values reads rejected, and a to-review one keeps the mark urgent", () => {
    expect(markState([{ reviewState: "rejected" }])).toBe("rejected");
    expect(markState([{ reviewState: "rejected" }, { reviewState: "to_review" }])).toBe("to_review");
    expect(markName([{ label: "Supplier: Meridian", reviewState: "rejected" }])).toBe("Supplier: Meridian, rejected");
  });

  it("is neither still to review nor reviewed for the dashboard, and is not where Review opens", () => {
    const values = [rejectedValue()];
    expect(firstValueToReview(values)).toBeNull();
    const figures = dashboardFigures({ evidence: [], values, asks: [], findings: [], coverage: null });
    expect(figures.valuesToReview).toBe(0);
    expect(figures.valuesReviewed).toBe(0);
  });
});
