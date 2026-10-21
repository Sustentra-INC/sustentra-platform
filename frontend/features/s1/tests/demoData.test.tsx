/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import type { SourceRef } from "../types/verificationResults";

/** What Verification results recomputes each document from: file name -> quantity. */
function verificationReads(): Map<string, number> {
  const reads = new Map<string, number>();
  const take = (source?: SourceRef) => {
    if (source?.kind === "records") source.items.forEach((d) => reads.set(d.filename, d.quantity));
    else if (source?.kind === "document") reads.set(source.filename, source.quantity);
  };
  for (const line of verificationLines)
    for (const facility of line.facilities ?? []) for (const step of facility.steps) [...step.how, step.reported, step.recomputed].forEach((c) => take(c?.source));
  return reads;
}

describe("the demo's documents are one set across Evidence, review and Verification results", () => {
  it("lists each file once on Evidence", () => {
    const seen = new Map<string, number>();
    for (const doc of manufacturerEvidence) seen.set(doc.filename, (seen.get(doc.filename) ?? 0) + 1);
    expect([...seen].filter(([, n]) => n > 1)).toEqual([]);
  });

  it("keys every value to a document on Evidence", () => {
    const ids = new Set(manufacturerEvidence.map((d) => d.documentId));
    expect([...new Set(manufacturerValues.filter((v) => !ids.has(v.documentId)).map((v) => v.filename))]).toEqual([]);
  });

  it("reads every monthly electricity and gas bill, with the figure Verification results recomputes from", () => {
    const reads = verificationReads();
    const valued = new Set(manufacturerValues.map((v) => v.documentId));
    const bills = manufacturerEvidence.filter((d) => /_(electric|gas)_[a-z]{3}_2025\.pdf$/.test(d.filename) && d.disposition !== "withdrawn");
    expect(bills.length).toBeGreaterThan(60);
    expect(bills.filter((b) => !valued.has(b.documentId)).map((b) => b.filename)).toEqual([]);

    const mismatched = manufacturerValues
      .filter((v) => /consumed$/.test(v.whatItIs) && reads.has(v.filename))
      .filter((v) => {
        const read = reads.get(v.filename)!;
        return Number(v.value.replace(/,/g, "")) !== (v.unit === "kWh" ? Math.round(read * 1000) : Math.round(read));
      })
      .map((v) => `${v.filename}: ${v.value} ${v.unit}`);
    expect(mismatched).toEqual([]);
  });
});

describe("a document opened with no values", () => {
  it("says so, rather than opening another document's value", () => {
    const meter = manufacturerEvidence.find((d) => d.filename === "kent_meter_mar.jpg")!;
    expect(manufacturerValues.some((v) => v.documentId === meter.documentId)).toBe(false);
    const { container } = render(
      <ExtractionReview
        engagement={engagementConfig}
        values={manufacturerValues}
        onValuesChange={vi.fn()}
        initialDocumentId={meter.documentId}
        initialDocumentName={meter.filename}
        initialNodeKey={`F:${meter.facilityId}|T:${meter.detectedType}`}
        onSaveAsk={vi.fn()}
        onBack={vi.fn()}
      />
    );
    expect(screen.getByRole("status").textContent).toContain("No values were read from kent_meter_mar.jpg");
    expect(container.querySelector(".s1-xr-card.is-sel")).toBeNull();
  });
});
