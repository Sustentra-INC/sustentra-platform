/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityDrawer } from "../components/ActivityDrawer";
import { CoveragePanel } from "../components/CoveragePanel";
import { cardProvenance } from "../components/ExtractionReview";
import { ProvenanceLabel, provenanceText } from "../components/ProvenanceLabel";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { ReviewValue } from "../types/review";

afterEach(cleanup);

const AT = "2026-10-21T15:57:00Z";

describe("ProvenanceLabel", () => {
  it("reads Read by AI, Checked by system, and a person's action with their name", () => {
    expect(provenanceText({ source: "ai" })).toBe("Read by AI");
    expect(provenanceText({ source: "system" })).toBe("Checked by system");
    expect(provenanceText({ source: "human", action: "accepted", by: "M. Osei" })).toBe("Accepted by M. Osei");
    expect(provenanceText({ source: "human", action: "corrected", by: "M. Osei", detail: "was 42.31" })).toBe("Corrected by M. Osei · was 42.31");
  });

  it("never shows an id: a missing or id-shaped name reads a reviewer", () => {
    expect(provenanceText({ source: "human", action: "accepted" })).toBe("Accepted by a reviewer");
    expect(provenanceText({ source: "human", action: "accepted", by: "  " })).toBe("Accepted by a reviewer");
    expect(provenanceText({ source: "human", action: "examined", by: "3f2b8c1e-aaaa-bbbb-cccc-1234567890ab" })).toBe("Examined by a reviewer");
  });

  it("ignores a stray action on a machine source and a bad time", () => {
    expect(provenanceText({ source: "ai", action: "accepted", by: "M. Osei" })).toBe("Read by AI");
    expect(provenanceText({ source: "human", action: "accepted", by: "M. Osei", at: "not a date" })).toBe("Accepted by M. Osei");
  });

  it("draws an icon beside the words", () => {
    const { container } = render(<ProvenanceLabel source="system" />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Checked by system")).toBeInTheDocument();
  });

  it("handles huge unicode names without breaking", () => {
    const name = "Ægir Østergaard ".repeat(100);
    render(<ProvenanceLabel source="human" action="accepted" by={name} />);
    expect(screen.getByText(/^Accepted by Ægir/)).toBeInTheDocument();
  });
});

const value = (over: Partial<ReviewValue>): ReviewValue =>
  ({
    id: "v1",
    documentId: "D1",
    filename: "bill.pdf",
    documentType: "Electricity bill",
    period: "2025-11",
    whatItIs: "Electricity consumed",
    value: "42.31",
    unit: "kWh",
    reviewState: "to_review",
    page: 3,
    record: [{ kind: "machine", actor: "system", at: AT, action: "read" }],
    ...over,
  }) as ReviewValue;

const human = (action: string) => ({ kind: "human" as const, actor: "M. Osei", at: AT, action });

describe("Extraction review value cards", () => {
  it("an unreviewed AI value reads Read by AI and never Accepted", () => {
    render(<div>{cardProvenance(value({}), null)}</div>);
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
    expect(screen.queryByText(/Accepted/)).toBeNull();
  });

  it("a value still to review never reads Accepted, whatever its record holds", () => {
    render(<div>{cardProvenance(value({ record: [human("accepted")] }), null)}</div>);
    expect(screen.queryByText(/Accepted/)).toBeNull();
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
  });

  it("accepted, corrected and keyed values say who", () => {
    const { rerender } = render(<div>{cardProvenance(value({ reviewState: "accepted", record: [human("accepted")] }), null)}</div>);
    expect(screen.getByText(/^Accepted by M\. Osei/)).toBeInTheDocument();
    rerender(<div>{cardProvenance(value({ reviewState: "corrected", originalValue: "42.31", record: [human("corrected")] }), null)}</div>);
    expect(screen.getByText(/^Corrected by M\. Osei .*was 42\.31/)).toBeInTheDocument();
    rerender(<div>{cardProvenance(value({ reviewState: "corrected", originalValue: null, record: [human("added")] }), null)}</div>);
    expect(screen.getByText(/^Keyed by M\. Osei .*highlighted on page 3/)).toBeInTheDocument();
  });
});

describe("Coverage & requests", () => {
  it("check rows read Checked by system, and a requested row reads Requested by", () => {
    const rules = coverageRules.slice(0, 2);
    render(<CoveragePanel coverage={{ rules }} isRequested={() => false} onRequest={vi.fn()} />);
    expect(screen.getAllByText("Checked by system").length).toBeGreaterThan(0);
    cleanup();
    render(
      <CoveragePanel
        coverage={{ rules: [{ ...rules[0], status: "inputs_missing" }] }}
        isRequested={() => true}
        requestOf={() => ({ by: "M. Osei", at: AT })}
        onRequest={vi.fn()}
      />,
    );
    expect(screen.getByText(/^Requested by M\. Osei/)).toBeInTheDocument();
  });
});

describe("Activity drawer", () => {
  it("labels a person's decision with the same words", () => {
    render(
      <ActivityDrawer
        onClose={vi.fn()}
        entries={[
          { at: AT, who: "M. Osei", what: "accepted: Electricity (bill.pdf)", kind: "review" },
          { at: AT, who: "M. Osei", what: "Request 3 sent", kind: "request" },
          { at: AT, who: "A. Lee", what: "uploaded bill.pdf", kind: "upload" },
        ]}
      />,
    );
    expect(screen.getByText(/^Accepted by M\. Osei/)).toBeInTheDocument();
    expect(screen.getByText(/^Requested by M\. Osei/)).toBeInTheDocument();
    expect(document.querySelectorAll("[data-provenance]")).toHaveLength(2);
  });
});
