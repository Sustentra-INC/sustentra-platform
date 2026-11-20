/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mapBackendCandidateToExtractedField, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { ExtractionReview, type SourcePick } from "../components/ExtractionReview";
import type { MethodologyFacts } from "../components/SummaryDocumentReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem } from "../types";
import type { PageMark, ReviewSpan, ReviewValue } from "../types/review";

afterEach(cleanup);

const DOC = { documentId: "DOC-1", filename: "2023-Statement.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z", detectedType: "Inventory workbook" } as unknown as EvidenceItem;

const candidate = (name: string, value: number): BackendExtractionCandidateLike => ({
  candidate_id: name,
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: name,
  display_label: name,
  normalized_value: value,
  unit: "tCO2e",
  validation_flags: [],
  source_reference: { text_snippet: `${name} ${value}`, page_number: 3, bounding_box: { x: 0.4, y: 0.32, width: 0.07, height: 0.012 } },
});

function reported(accepted = false): ReviewValue[] {
  const values = reviewValuesFromFields(
    [candidate("scope1_total", 38922), candidate("scope1_co2", 34128)].map((c) => mapBackendCandidateToExtractedField(c, "CT-GHG-WORKBOOK")),
    [DOC]
  );
  return accepted ? values.map((v) => ({ ...v, reviewState: "accepted" as const })) : values;
}

const factMark: PageMark = { id: "gas:co2#1#0", span: { page: 5, x: 0.1, y: 0.2, w: 0.3, h: 0.02 }, label: "Gas: CO2", reviewState: "to_review" };

function makeFacts(over: Partial<MethodologyFacts> = {}): MethodologyFacts {
  return {
    ready: true,
    loadError: null,
    count: 2,
    marks: [factMark],
    selectedMarkIds: [],
    span: null,
    page: null,
    pageNote: null,
    hasSelection: false,
    viewerKey: "",
    pick: vi.fn(),
    panel: <div data-testid="facts-panel">Gas: CO2</div>,
    ...over,
  };
}

interface Seen {
  span: ReviewSpan | null;
  marks: PageMark[];
  pick?: SourcePick;
  pickBox?: (box: { x: number; y: number; w: number; h: number }, id?: string) => void;
}

function open(values: ReviewValue[], facts: MethodologyFacts | undefined, deep = false) {
  const seen: Seen = { span: null, marks: [] };
  render(
    <ExtractionReview
      engagement={engagementConfig}
      values={values}
      onValuesChange={vi.fn()}
      initialDocumentId="DOC-1"
      typeItem={DOC}
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
      facts={facts}
      factsDeepLinked={deep}
      renderPage={(_id, span, onPickBox, marks, pick): ReactNode => {
        Object.assign(seen, { span, marks: marks ?? [], pick, pickBox: onPickBox });
        return <div data-testid="viewer" />;
      }}
    />
  );
  return seen;
}

const tab = (name: string) => screen.getByRole("tab", { name: new RegExp(name) });

describe("a summary document with reported figures and Methodology facts", () => {
  it("has two tabs in the values slot, and no tabs when there are no facts to show", () => {
    open(reported(), makeFacts());
    expect(tab("Reported figures")).toBeInTheDocument();
    expect(tab("Methodology facts")).toBeInTheDocument();
    cleanup();
    open(reported(), undefined);
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("opens on Reported figures while some are still to review", () => {
    open(reported(), makeFacts());
    expect(tab("Reported figures")).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("facts-panel")).toBeNull();
    fireEvent.click(tab("Methodology facts"));
    expect(screen.getByTestId("facts-panel")).toBeInTheDocument();
    expect(tab("Methodology facts")).toHaveAttribute("aria-selected", "true");
    fireEvent.click(tab("Reported figures"));
    expect(screen.queryByTestId("facts-panel")).toBeNull();
  });

  it("opens on Methodology facts when every reported figure has been reviewed", () => {
    open(reported(true), makeFacts());
    expect(tab("Methodology facts")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("facts-panel")).toBeInTheDocument();
  });

  it("a Methodology source link opens the facts tab even with figures to review, and the page follows the selected fact", () => {
    const seen = open(reported(), makeFacts({ page: 5, span: factMark.span as ReviewSpan, selectedMarkIds: [factMark.id], viewerKey: "gas:co2|1|5" }), true);
    expect(tab("Methodology facts")).toHaveAttribute("aria-selected", "true");
    expect(seen.span).toEqual(factMark.span);
    expect(seen.pick).toMatchObject({ openPage: 5, selectedMarkIds: [factMark.id], viewerKey: "gas:co2|1|5" });
  });

  it("a deep link whose quote was not located still opens its page and carries the note", () => {
    const seen = open(reported(), makeFacts({ marks: [], page: 5, pageNote: "Quote not located on this page" }), true);
    expect(seen.pick).toMatchObject({ openPage: 5, pageNote: "Quote not located on this page" });
    expect(seen.span).toBeNull();
  });

  it("draws both sets of highlights on the page", () => {
    const seen = open(reported(), makeFacts());
    const ids = seen.marks.map((m) => m.id);
    expect(ids).toContain(factMark.id);
    expect(ids.some((id) => id !== factMark.id)).toBe(true); // the reported figures' own
  });

  it("clicking a Methodology highlight selects that fact and its tab; clicking a reported one goes back", () => {
    const facts = makeFacts();
    const seen = open(reported(), facts);
    expect(tab("Reported figures")).toHaveAttribute("aria-selected", "true");
    act(() => seen.pickBox?.(factMark.span as ReviewSpan, factMark.id));
    expect(facts.pick).toHaveBeenCalledWith(factMark);
    expect(tab("Methodology facts")).toHaveAttribute("aria-selected", "true");
    const own = seen.marks.find((m) => m.id !== factMark.id) as PageMark;
    act(() => seen.pickBox?.(own.span as ReviewSpan, own.id));
    expect(tab("Reported figures")).toHaveAttribute("aria-selected", "true");
  });
});
