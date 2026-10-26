/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";

import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { useRequestsStore, type RequestsStore } from "../requests/requestsStore";
import type { ReviewValue } from "../types/review";

/**
 * A value card added to requests says where the request stands. "Requested" and
 * "requested from client" tell an auditor the client was asked, so they wait until the
 * request is sent; before that the card says the request is not sent.
 */
function renderReview(documentId: string, valueId?: string) {
  const live: { store: RequestsStore | null; values: ReviewValue[] } = { store: null, values: manufacturerValues };
  function Harness() {
    const [values, setValues] = useState(manufacturerValues);
    const store = useRequestsStore([]);
    live.store = store;
    live.values = values;
    return (
      <ExtractionReview
        engagement={engagementConfig}
        values={values}
        onValuesChange={setValues}
        initialDocumentId={documentId}
        initialValueId={valueId}
        onSaveAsk={store.saveAsk}
        asks={store.asks}
        onBack={vi.fn()}
        reviewerName="Thanishque"
      />
    );
  }
  const { container } = render(<Harness />);
  const card = () => container.querySelector<HTMLElement>(".s1-xr-card.is-sel")!;
  const chip = () => card().querySelector(".s1-xr-badge")?.textContent;
  const lines = () => Array.from(card().querySelectorAll(".s1-xr-rec__act")).map((n) => n.textContent);
  const filters = () =>
    within(container.querySelector(".s1-xr-filters") as HTMLElement)
      .getAllByRole("button")
      .map((b) => b.textContent);
  const addToRequests = () => {
    fireEvent.click(within(card()).getByRole("button", { name: "Request" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
  };
  return { live, card, chip, lines, filters, addToRequests };
}

describe("extraction review: a value added to requests", () => {
  it("says the request is not sent until it is, then that the client was asked", () => {
    const view = renderReview("DOC-tualatin-elec-jan");
    view.addToRequests();

    // Only the label changes: the value is in the "requested" state, its ask not yet sent.
    const ask = view.live.store!.asks[0];
    expect(ask.state).toBe("not_yet_sent");
    const reading = view.live.values.filter((v) => v.documentId === "DOC-tualatin-elec-jan");
    expect(reading.map((v) => v.reviewState)).toEqual(["requested", "requested"]);
    expect(reading[0].record.at(-1)).toMatchObject({ actor: "Thanishque", action: "added to requests", askId: ask.id });

    expect(screen.getByText("Added to requests · not yet sent")).toBeInTheDocument();
    expect(view.chip()).toBe("Request not sent");
    expect(view.lines()).toContain("Thanishque · added to requests");
    expect(view.card().textContent).not.toMatch(/requested from client|Requested/);
    expect(view.filters().at(-1)).toMatch(/^1Requests$/);

    act(() => {
      view.live.store!.sendAsks([ask.id]);
    });
    expect(view.chip()).toBe("Requested");
    expect(view.lines()).toContain("Thanishque · requested from client");
    expect(view.lines()).not.toContain("Thanishque · added to requests");

    act(() => {
      view.live.store!.resolveAsk(ask.id);
    });
    expect(view.chip()).toBe("Request resolved");
    expect(view.lines()).toContain("Thanishque · requested from client");
  });

  it("says a request withdrawn before it was sent never reached the client", () => {
    const view = renderReview("DOC-tualatin-elec-jan");
    view.addToRequests();
    const ask = view.live.store!.asks[0];

    act(() => {
      view.live.store!.withdrawAsk(ask.id, "found on the next bill");
    });
    expect(view.chip()).toBe("Request withdrawn");
    expect(view.lines()).toContain("Thanishque · added to requests");
    expect(view.card().textContent).not.toContain("requested from client");
  });

  it("follows the latest request raised from the card", () => {
    const view = renderReview("DOC-tualatin-elec-jan");
    view.addToRequests();
    const first = view.live.store!.asks[0];
    act(() => {
      view.live.store!.sendAsks([first.id]);
    });
    act(() => {
      view.live.store!.resolveAsk(first.id);
    });
    // A follow-up keeps the field it came from: the card now waits on it.
    act(() => {
      view.live.store!.saveAsk({
        origin: first.source.origin,
        documentId: first.source.documentId,
        fieldKey: first.source.fieldKey,
        itemLabel: first.source.itemLabel,
        facilityName: first.source.facilityName,
        period: first.source.period,
        type: first.type,
        whatIsNeeded: first.whatIsNeeded,
        raisedByName: first.raisedByName,
        raisedByLogin: first.raisedByLogin,
        linkedFromAskId: first.id,
      });
    });
    expect(view.chip()).toBe("Request not sent");
    // The first request did reach the client, and its line still says so.
    expect(view.lines()).toContain("Thanishque · requested from client");
  });

  it("keeps a value requested before requests were tracked as requested", () => {
    // The demo's refrigerant log was requested from the client with no ask on file.
    const seeded = manufacturerValues.find((v) => v.filename === "modesto_refrigerant_service.pdf" && v.reviewState === "requested")!;
    const view = renderReview(seeded.documentId, seeded.id);
    expect(view.chip()).toBe("Requested");
    expect(view.lines()).toContain("M. Osei · requested from client");
  });
});
