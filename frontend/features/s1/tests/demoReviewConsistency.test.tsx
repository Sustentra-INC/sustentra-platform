/* @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { DemoDocument } from "../components/demo/DemoDocument";
import { buildRecords, engagementNow } from "../demo-backend/linesModel";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { documentReview } from "../fixtures/extraction/reviewDecisions";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { dashboardFigures } from "../utils/engagementActivity";

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const valuesOf = (documentId: string) => manufacturerValues.filter((v) => v.documentId === documentId);

describe("one review decision per document, in the fixtures", () => {
  const { records, setAside } = buildRecords(engagementNow().facilities);
  const calculable = records.filter((r) => r.kind !== "other" && r.quantity !== null && r.processingStatus !== "blocked");

  it("counts a document as accepted in the schedule exactly when its fixture values are accepted", () => {
    expect(calculable.length).toBeGreaterThan(80);
    for (const r of calculable) {
      const review = documentReview(valuesOf(r.documentId));
      expect(r.accepted, r.fileName).toBe(review.done && review.open.length === 0);
      if (r.accepted) {
        // "Saved by X · date" in the schedule is "Accepted by X" in Extraction review.
        expect(r.reviewer, r.fileName).toBe(review.reviewer);
        expect(r.reviewedAt, r.fileName).toBe(review.at);
      }
    }
    expect(calculable.some((r) => !r.accepted)).toBe(true);
  });

  it("names the same reviewer on every accepted value of an accepted document", () => {
    for (const r of calculable.filter((x) => x.accepted)) {
      const names = valuesOf(r.documentId).flatMap((v) => v.record.filter((e) => e.kind === "human").map((e) => e.actor));
      expect(new Set(names), r.fileName).toEqual(new Set([r.reviewer]));
    }
  });

  it("leaves some tens of values to review on the Dashboard", () => {
    const { valuesToReview } = dashboardFigures({ evidence: manufacturerEvidence, values: manufacturerValues, asks: [], findings: [], coverage: null });
    expect(valuesToReview).toBeGreaterThanOrEqual(20);
    expect(valuesToReview).toBeLessThan(100);
  });

  it("sets the withdrawn June bill aside on Evidence, in the fixtures and in the tree alike", () => {
    const june = manufacturerEvidence.find((d) => d.filename === "kent_gas_jun_2025.pdf")!;
    expect(june.disposition).toBe("withdrawn");
    expect(setAside.find((s) => s.document_id === june.documentId)?.reason).toContain(june.note!);
    expect(records.some((r) => r.documentId === june.documentId)).toBe(false);
    expect(valuesOf(june.documentId).every((v) => v.withdrawn)).toBe(true);
    expect(manufacturerValues.filter((v) => v.ai).every((v) => v.filename !== june.filename)).toBe(true);
  });

  it("puts Claude's heat content and meter number on the September bill, and the meter is the schedule's", () => {
    const sep = valuesOf("DOC-PARTIAL").filter((v) => v.ai);
    expect(sep.map((v) => v.whatItIs).sort()).toEqual(["Heat content", "Meter number"]);
    expect(sep.find((v) => v.whatItIs === "Meter number")!.value).toBe(records.find((r) => r.documentId === "DOC-kent-gas-jan")!.meter);
    const strip = (t: string) => t.replace(/\s/g, "");
    const { container } = render(<DemoDocument values={valuesOf("DOC-PARTIAL")} engagement={engagementConfig} selectedId={null} onPick={() => undefined} />);
    const text = strip(container.textContent ?? "");
    for (const v of sep) expect(text).toContain(strip(v.snippet!));
  });
});
