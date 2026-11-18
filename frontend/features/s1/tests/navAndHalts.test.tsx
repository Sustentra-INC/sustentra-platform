/* @vitest-environment jsdom */
import { describe, it, expect } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";

import { navForView } from "../utils/navForView";
import { plainBatchHalt } from "../adapters/evidenceAdapter";
import { BatchProgress, batchStatusFor } from "../components/BatchProgress";
import type { BatchView } from "../api/documentBatches";

describe("sidebar highlight (N16)", () => {
  it("keeps the view the glossary was opened from lit", () => {
    expect(navForView({ name: "glossary", previous: { name: "setup" } })).toBe("setup");
    expect(navForView({ name: "glossary", previous: { name: "results" } })).toBe("results");
    expect(navForView({ name: "glossary", previous: { name: "coverage" } })).toBe("requests");
  });
  it("falls back to Evidence only for extraction and unknown views", () => {
    expect(navForView({ name: "extraction" })).toBe("evidence");
    expect(navForView({ name: "glossary" })).toBe("evidence");
    expect(navForView({ name: "dashboard" })).toBe("dashboard");
  });
});

describe("unsupported-document wording (N22, N23)", () => {
  const raw =
    "Unsupported document type: the closest match was CT-S1-REFRSVC with confidence 0.48, below the 0.55 needed to extract automatically. Set the document type manually if it is a supported type.";
  it("never shows the classifier's code or score", () => {
    const plain = plainBatchHalt(raw);
    expect(plain).toBe("We couldn't tell what kind of document this is. Choose its type in Evidence.");
    expect(plain).not.toMatch(/CT-S1|0\.48/);
  });
  it("calls a partial read with no values 'Not read'", () => {
    expect(batchStatusFor({ status: "partial", records_found: 0 }).label).toBe("Not read");
    expect(batchStatusFor({ status: "partial", records_found: 3 }).label).toBe("Partly read");
  });
  it("renders the plain sentence and chip in the batch table", () => {
    const batch: BatchView = {
      batch_id: "b",
      engagement_id: "e",
      label: null,
      complete: true,
      totals: { queued: 0, reading: 0, done: 0, partial: 1, failed: 0, not_started: 0 },
      items: [
        {
          document_id: "d1",
          file_name: "STG_Riverside_Propane.pdf",
          status: "partial",
          chunks: null,
          canonical_type_id: null,
          halt_reason: raw,
          records_found: 0,
        },
      ],
    };
    render(<BatchProgress batch={batch} onOpenDocument={() => {}} />);
    expect(screen.getAllByText("Not read").length).toBeGreaterThan(0);
    expect(screen.getByText(/couldn't tell what kind of document/)).toBeInTheDocument();
    expect(screen.queryByText(/closest match/)).toBeNull();
  });
});
