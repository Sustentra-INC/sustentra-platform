/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import type { EvidenceItem } from "../types";

afterEach(cleanup);

const base = manufacturerEvidence[0];

function open(over: Partial<EvidenceItem>, extra: Partial<React.ComponentProps<typeof ExtractionReview>> = {}) {
  const item: EvidenceItem = { ...base, documentId: "DOC-SUM", filename: "ghg_statement.pdf", ...over };
  const onOpenMethodology = vi.fn();
  render(
    <ExtractionReview
      engagement={engagementConfig}
      values={[]}
      onValuesChange={vi.fn()}
      initialDocumentId="DOC-SUM"
      initialDocumentName={item.filename}
      typeItem={item}
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
      onOpenMethodology={onOpenMethodology}
      renderPage={(id) => <div data-testid="viewer">file {id}</div>}
      {...extra}
    />
  );
  return { onOpenMethodology };
}

describe("a document with no values", () => {
  it("a summary document shows the viewer, a note and a link to Methodology review", () => {
    const { onOpenMethodology } = open({ detectedType: "Inventory methodology statement", processingState: "extracted" });
    expect(screen.getByTestId("viewer")).toHaveTextContent("file DOC-SUM");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Company-prepared summary document. Its facts are read in Methodology review, not here."
    );
    expect(screen.queryByText("No values to review yet.")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Methodology review" }));
    expect(onOpenMethodology).toHaveBeenCalled();
  });

  it("a non-summary document says no values were read, and still shows the document", () => {
    open({ detectedType: "Electricity bill", processingState: "extracted" });
    expect(screen.getByRole("status")).toHaveTextContent("No values were read from this document.");
    expect(screen.queryByRole("button", { name: "Open Methodology review" })).toBeNull();
    expect(screen.getByTestId("viewer")).toBeInTheDocument();
  });

  it("a document still being read shows a loading state, not an empty page", () => {
    open({ detectedType: "Inventory workbook", processingState: "ingested", reading: "in_progress" });
    expect(screen.getByRole("status")).toHaveTextContent("still being read");
    expect(screen.getByText("Loading document…")).toBeInTheDocument();
    expect(screen.queryByTestId("viewer")).toBeNull();
  });
});
