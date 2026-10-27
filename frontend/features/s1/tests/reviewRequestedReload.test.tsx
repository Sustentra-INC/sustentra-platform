/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { reviewValuesFromFields, withRequestsFromAsks } from "../adapters/reviewValueAdapter";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { useRequestsStore, type RequestsStore } from "../requests/requestsStore";
import type { EvidenceItem, ExtractedField } from "../types";
import type { Ask } from "../types/requests";
import type { ReviewValue } from "../types/review";

/**
 * Staging (backend mode): the review API records accepts and corrections, and a value added to
 * requests is saved as an ask, not as a review decision. After a reload the values come back
 * from the extraction as "to review"; the saved asks put the requested ones back.
 */
function field(name: string, value: string | null, extra: Partial<ExtractedField> = {}): ExtractedField {
  return {
    documentId: "DOC-1",
    canonicalTypeId: "CT-S2-ELEC",
    fieldKey: `candidate:${name}`,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: name, evidence_id: "EV-1", document_id: "DOC-1", field_name: name, display_label: name,
      normalized_value: value, unit: null,
    }),
    fieldLabel: name,
    value,
    unit: null,
    valueProperties: [],
    fieldState: value === null ? "missing_requestable" : "populated",
    snippet: null,
    snippetContext: null,
    location: null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
    ...extra,
  };
}

const DOC = { documentId: "DOC-1", filename: "kent_electric_feb.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill" } as unknown as EvidenceItem;

/** What listWorkspaceEvidence gives on every load: nothing reviewed yet, then one accepted value. */
const loaded = () =>
  reviewValuesFromFields(
    [
      field("activity_quantity", "182.4", { unit: "MWh" }),
      field("account_number", "ACC-77"),
      field("supplier_name", "Puget Power", { reviewStatus: "accepted", reviewedBy: "claire@sustentra.com", reviewedAt: "2026-10-21T10:00:00Z" }),
    ],
    [DOC]
  );

function ask(id: string, fieldKey: string, extra: Partial<Ask> = {}): Ask {
  return {
    id,
    type: "clarify",
    whatIsNeeded: "Please confirm the reading.",
    source: { origin: "review_value", documentId: "DOC-1", fieldKey, itemLabel: "x", facilityName: null, period: null },
    raisedByName: "Thanishque",
    raisedByLogin: "thanishque@sustentra.com",
    raisedAt: "2026-10-22T08:00:00.000Z",
    state: "not_yet_sent",
    requestNumber: null,
    lineNumber: null,
    history: [],
    ...extra,
  };
}

describe("asks laid over the backend's values", () => {
  it("puts a value added to requests back in the requested state, with the line that added it", () => {
    const [quantity, account] = withRequestsFromAsks(loaded(), [ask("ASK-1", "candidate:activity_quantity")]);
    expect(quantity.reviewState).toBe("requested");
    expect(quantity.record.at(-1)).toEqual({
      kind: "human", actor: "Thanishque", at: "2026-10-22T08:00:00.000Z", action: "added to requests", askId: "ASK-1",
    });
    expect(account.reviewState).toBe("to_review");
  });

  it("keeps a value accepted after it was requested accepted, the request first in its record", () => {
    const supplier = withRequestsFromAsks(loaded(), [ask("ASK-1", "candidate:supplier_name", { raisedAt: "2026-10-20T12:00:00.000Z" })])[2];
    expect(supplier.reviewState).toBe("accepted");
    expect(supplier.record.map((r) => [r.kind, r.action])).toEqual([
      ["machine", "extracted"],
      ["human", "added to requests"],
      ["human", "accepted as read"],
    ]);
  });

  it("adds nothing the session already recorded, nor a line for a follow-up", () => {
    const first = ask("ASK-1", "candidate:activity_quantity");
    const followUp = ask("ASK-2", "candidate:activity_quantity", { linkedFromAskId: "ASK-1", raisedAt: "2026-10-23T08:00:00.000Z" });
    const [once] = withRequestsFromAsks(loaded(), [first, followUp]);
    expect(once.record.filter((r) => r.action === "added to requests")).toHaveLength(1);
    const [again] = withRequestsFromAsks([once], [first, followUp]);
    expect(again.record).toEqual(once.record);
  });

  it("ignores asks raised anywhere but a value card", () => {
    const values = loaded();
    const fromDocument = { ...ask("ASK-1", "candidate:activity_quantity"), source: { ...ask("x", "y").source, origin: "workspace_document" as const, fieldKey: "candidate:activity_quantity" } };
    expect(withRequestsFromAsks(values, [fromDocument])).toBe(values);
    expect(withRequestsFromAsks(values, [])).toBe(values);
  });
});

/** The signed-in reviewer, as the app names them on staging. */
const STAGING = { ...engagementConfig, signedInLogin: "thanishque@sustentra.com", signedInName: "Thanishque" };

/** The review screen as the app wires it on staging: the asks are laid over what was loaded. */
function renderStaging(saved: Ask[]) {
  const live: { store: RequestsStore | null } = { store: null };
  function Harness() {
    const [values, setValues] = useState<ReviewValue[]>(loaded);
    const store = useRequestsStore(saved);
    live.store = store;
    return (
      <ExtractionReview
        engagement={STAGING}
        values={withRequestsFromAsks(values, store.asks)}
        onValuesChange={setValues}
        initialDocumentId="DOC-1"
        initialValueId="candidate:activity_quantity"
        onSaveAsk={store.saveAsk}
        asks={store.asks}
        onBack={vi.fn()}
        reviewerName="Thanishque"
        onPersistAccept={() => Promise.resolve()}
      />
    );
  }
  const { container } = render(<Harness />);
  const card = () => container.querySelector<HTMLElement>(".s1-xr-card.is-sel")!;
  const seen = () => ({
    chip: card().querySelector(".s1-xr-badge")?.textContent,
    lines: Array.from(card().querySelectorAll(".s1-xr-rec__act")).map((n) => n.textContent),
    filters: within(container.querySelector(".s1-xr-filters") as HTMLElement).getAllByRole("button").map((b) => b.textContent),
    buttons: within(card()).queryAllByRole("button").map((b) => b.textContent),
  });
  return { live, card, seen };
}

describe("extraction review on staging: a requested value after a reload", () => {
  it("reads exactly as it did before the reload: requested, its record line, and counted", () => {
    const session = renderStaging([]);
    fireEvent.click(within(session.card()).getByRole("button", { name: "Request" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
    const before = session.seen();
    expect(before.chip).toBe("Request not sent");
    expect(before.lines).toContain("Thanishque · added to requests");
    expect(before.filters).toEqual(["1To review", "1Accepted", "0Corrected", "1Requests"]);
    const saved = session.live.store!.asks;
    cleanup();

    // Reload: the values come back as read, the asks come back from the workpaper.
    const reloaded = renderStaging(saved);
    expect(reloaded.seen()).toEqual(before);
    // A requested value cannot be requested twice.
    expect(reloaded.seen().buttons).not.toContain("Request");

    act(() => {
      reloaded.live.store!.sendAsks([saved[0].id]);
    });
    expect(reloaded.seen().chip).toBe("Requested");
    expect(reloaded.seen().lines).toContain("Thanishque · requested from client");
  });
});
